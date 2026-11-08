"""DocBabel 针对 BabelDOC 的运行时补丁：技术文档翻译质量修复。

修复四类问题（不修改 venv 内 BabelDOC 源码，猴子补丁随后端代码进镜像）：

Patch A —— 代码/选项/标识符不送翻译：
  包装 ILTranslator.pre_translate_paragraph（ILTranslatorLLMOnly 与
  ILTranslator 两条翻译路径都会经过它）：
  1. 等宽字体字符占比 >= MONO_SKIP_RATIO 的段落整体跳过
     （代码块、命令行、表格中的选项参数单元格）；
  2. 无空白且只含标识符安全字符并带分隔符/数字的段落跳过
     （文档编号、URL、路径等）；
  3. 其余混合段落中，等宽字体的 pdf_same_style_characters 片段被转换为
     PdfFormula，走公式占位符机制，LLM 只翻译周围的普通文字。

Patch B —— 列表项 / 索引 / 扉页标题拆分：
  包装 ParagraphFinder.process_page：原版分段完成后，把多条语义行被合并成
  一个段落的情况按视觉行重新拆开：
  1. 列表项：标记行占比过半（每行一条），或明确 bullet 字形（私用区
     Wingdings 符号 \uf0a1、■•◦ 等）的标记行虽少但每条都紧跟在已收尾的
     上一条目之后（一条 bullet 折成 3~6 行的常见版式）；标记含
     •/-/*/1./1.1/a./1 等；另有定义列表辅助规则（行首等宽字体且上一行
     以句末标点结尾）。编号/引号/续行符等弱信号仍要求标记行占比过半，
     避免把代码块、终端输出、普通正文切碎。
  2. index/索引词条：>=3 行、多数行以页码结尾（23 / 133–136 / 5, 14, 130）
     时，按“行尾页码”切分成一条词条一个段落；无页码的折行并入前一条。
  3. 大字号多行标题（Part/附录扉页横幅，行高 >= 18pt）：每行独立成段，
     避免中文变长后重排把下一行的文字挤到上一行行末。

Patch C —— 提示词强化：
  在 il_translator / il_translator_llm_only 两个 PROMPT_TEMPLATE 中追加
  “不翻译命令行选项、路径、URL、版本号、文档编号、标识符；整段为代码时
  原样返回”的规则。采用锚点替换，锚点缺失（库升级）时仅告警不中断。

Patch D —— 孤字行修复：
  BabelDOC 的排版只在内容垂直溢出边界框时才缩小字号，从不检查末行字数。
  中文译文比英文原文长，短标题（如 "Part 1" -> "第一部分"）断行后末行常常
  只剩一个字，非常难看。包装 Typesetting.retypeset_with_precomputed_scale：
  排版完成后检测末行非空白字符数，若为 1 则按 2% 步长逐步缩小该段字号，
  取第一个“所有内容放得下且重排后末行 >= 2 字”的字号重新排版。
  缩放下限为 max(ORPHAN_SCALE_FLOOR, base_scale * ORPHAN_RELATIVE_FLOOR)，
  避免为凑行把字号缩得过小。含公式/图形单元的段落也参与修复：重排前先截断
  第一次排版追加到页面的曲线/图形，重排后再重新追加，保证装饰只绘制一次。
"""

import logging
import re
from string import Template

logger = logging.getLogger(__name__)

_APPLIED = False

# 等宽字体判定：mupdf 的 is_monospaced 标志 + 字体名正则兜底
MONO_FONT_NAME_RE = re.compile(
    r"(courier|mono|code|consol|menlo|monaco|andale|inconsolata|dejavu|"
    r"liberation mono|noto sans mono|pt mono|plex mono|roboto mono|"
    r"source code|fira|cascadia|jetbrains|hack|fixedsys|terminal|"
    r"typewriter|teletype|letter gothic|prestige|ocr ?b|ubuntu mono|"
    r"droid sans mono|cutive|share tech|sfmono|sf-mono)",
    re.IGNORECASE,
)
MONO_SKIP_RATIO = 0.6

# 标识符段落：无空白、仅标识符安全 ASCII 字符、且含强分隔符或（数字+分隔符）
_IDENTIFIER_SAFE_RE = re.compile(r"^[A-Za-z0-9_\-./\\:@=+~#%&]+$")
_IDENTIFIER_STRONG_CHARS = set("_@/\\:=~#%&")

# 列表行首标记
_LIST_MARKER_RE = re.compile(
    r"^\s*(?:"
    r"[■•⚫⬤◆◇○●◦‣⁃▪▫∗·†‡¶※⁑⁂⁕⁎⁜❧☙⁋](?=[\s ]|$)"
    r"|[-–—*+](?=[\s ]\S)"
    r"|\d+(?:\.\d+)+\.?[\])]?(?=[\s ]\S)"
    r"|\d{1,4}[.)](?=[\s ]\S)"
    r"|\(\d{1,3}\)(?=[\s ]?\S)"
    r"|[a-zA-Z][.)](?=[\s ]\S)"
    r")"
)
_LIST_SPLIT_MIN_MARKERS = 2
# 紧排列表（每行一条）的标记行占比下限
_LIST_SPLIT_MIN_RATIO = 0.5
# 折行列表（一条 bullet 常占 3~6 行）中，标记行占比通常远低于 50%。
# 此时改用“条目收尾”判据：上一条目以句末标点/冒号收尾，标记紧接其后；
# 最多允许这么多条标记没有可靠的前置收尾（首条可直接接在引导句后）。
_LIST_SPLIT_CONFIRM_TOLERANCE = 1
# PDF 符号字体（Wingdings/Webdings/Symbol）把项目符号映射到私用区
# U+E000–U+F8FF（曼宁书籍的小方块提取为 \uf0a1），肉眼不可见但确实在行首
_PUA_BULLET_RE = re.compile(r"^\s*[\ue000-\uf8ff](?=[\s\w])")
# 明确的 bullet 字形：只有它们才允许走“折行列表”判据。其他行首符号
# （➥ 续行符、ANSI 转义、引号、括号、编号等）可能是正文/代码，必须要求
# 标记行占比过半才拆，避免把普通段落切碎
_STRONG_BULLET_RE = re.compile(
    r"^\s*(?:[■•⚫⬤◆◇○●◦‣⁃▪▫∗]|[\ue000-\uf8ff])(?=[\s\u00a0]|\w)"
)
_ITEM_END_CHARS = (".", "?", "!", ":", "。", "！", "？", "：")
# 曼宁书籍常用 "1 xxx" 这种无点号的编号列表
_NUMBER_LIST_MARKER_RE = re.compile(r"^\s*\d{1,2}(?=[\s\u00a0]\S)")

# index/索引词条段落：多行被合并成一个 PdfParagraph 时按词条拆开。
# 词条行特征是行尾页码：23 / 133–136 / 5, 14, 130, 185, 229
_INDEX_PAGE_TAIL_RE = re.compile(
    r"\d{1,4}(?:(?:\s*[,;–—\-]\s*\d{1,4})+)?\s*$"
)
_INDEX_SPLIT_MIN_LINES = 3
_INDEX_SPLIT_MIN_ENTRIES = 2
_INDEX_SPLIT_MIN_RATIO = 0.6
# 大字号多行标题（Part/附录扉页横幅）：按物理行拆开，避免翻译后把下一行
# 文字挤到上一行行末；正文小标题行高约 13pt，不受影响
_HEADING_SPLIT_MIN_HEIGHT = 18.0
_HEADING_SPLIT_MAX_CHARS = 60
_SENTENCE_FINAL_CHARS = (".", "?", "!")
# 只对这些版面标签做列表拆分；表格单元格(fallback_line)、页眉页脚(abandon)等不动
_LIST_SPLITTABLE_LABELS = {None, "plain text", "text", "paragraph_hybrid", "list"}

# 孤字行修复（Patch D）
ORPHAN_SCALE_STEP = 0.02
ORPHAN_SCALE_FLOOR = 0.55  # 绝对下限（原文已经很小的标题可能已缩到 0.65）
ORPHAN_RELATIVE_FLOOR = 0.75  # 相对当前字号最多再缩 25%
ORPHAN_MAX_ATTEMPTS = 16
ORPHAN_MIN_LAST_CHARS = 2
_ORPHAN_Y_TOL = 0.1
# 表格单元格不参与孤字修复；Part/章扉页横幅标题常被标为 abandon，需参与修复
_ORPHAN_SKIP_LABELS = {"fallback_line"}


# ---------------------------------------------------------------------------
# 公共工具
# ---------------------------------------------------------------------------


def _is_mono_font(font) -> bool:
    if font is None:
        return False
    if getattr(font, "monospace", None):
        return True
    name = getattr(font, "name", None)
    return bool(name and MONO_FONT_NAME_RE.search(name))


def _char_font(char, font_map):
    style = getattr(char, "pdf_style", None)
    font_id = getattr(style, "font_id", None) if style else None
    return font_map.get(font_id) if font_id else None


def _iter_paragraph_chars(paragraph):
    for comp in paragraph.pdf_paragraph_composition or []:
        if comp.pdf_line is not None:
            yield from comp.pdf_line.pdf_character
        elif comp.pdf_formula is not None:
            yield from comp.pdf_formula.pdf_character
        elif comp.pdf_character is not None:
            yield comp.pdf_character
        elif comp.pdf_same_style_characters is not None:
            yield from comp.pdf_same_style_characters.pdf_character


def _mono_ratio(paragraph, font_map) -> float:
    total = 0
    mono = 0
    for char in _iter_paragraph_chars(paragraph):
        unicode_text = getattr(char, "char_unicode", "") or ""
        if not unicode_text.strip():
            continue
        total += 1
        if _is_mono_font(_char_font(char, font_map)):
            mono += 1
    return (mono / total) if total else 0.0


def _is_identifier_like(text: str) -> bool:
    text = text.strip()
    if len(text) < 3 or any(c.isspace() for c in text):
        return False
    if not _IDENTIFIER_SAFE_RE.match(text):
        return False
    if any(c in _IDENTIFIER_STRONG_CHARS for c in text):
        return True
    has_digit = any(c.isdigit() for c in text)
    return has_digit and ("-" in text or "." in text or "_" in text)


def _build_effective_font_map(paragraph, page_font_map, xobj_font_map) -> dict:
    font_map = dict(page_font_map or {})
    xobj_map = (xobj_font_map or {}).get(paragraph.xobj_id)
    if xobj_map:
        font_map.update(xobj_map)
    return font_map


# ---------------------------------------------------------------------------
# Patch A：等宽/标识符跳过 + 等宽片段转公式占位符
# ---------------------------------------------------------------------------


def _convert_mono_fragments_to_formulas(paragraph, font_map) -> None:
    """把混合段落中等宽字体的 same-style 片段转成 PdfFormula（占位符保护）。

    幂等：已转换的片段不再是 pdf_same_style_characters，重复调用无副作用。
    """
    from babeldoc.format.pdf.document_il.il_version_1 import PdfFormula
    from babeldoc.format.pdf.document_il.il_version_1 import PdfParagraphComposition
    from babeldoc.format.pdf.document_il.utils.formular_helper import (
        update_formula_data,
    )

    comps = paragraph.pdf_paragraph_composition
    if not comps:
        return
    for idx, comp in enumerate(comps):
        ssc = comp.pdf_same_style_characters
        if ssc is None or not ssc.pdf_character:
            continue
        font = font_map.get(getattr(ssc.pdf_style, "font_id", None))
        if not _is_mono_font(font):
            continue
        formula = PdfFormula(pdf_character=list(ssc.pdf_character))
        update_formula_data(formula)
        comps[idx] = PdfParagraphComposition(pdf_formula=formula)


def _make_patched_pre_translate_paragraph(orig):
    def patched(self, paragraph, tracker, page_font_map, xobj_font_map):
        try:
            font_map = _build_effective_font_map(
                paragraph, page_font_map, xobj_font_map
            )
            text = (paragraph.unicode or "").strip()
            if text:
                if _is_identifier_like(text):
                    logger.debug(
                        "DocBabel patch: skip identifier-like paragraph %s: %r",
                        paragraph.debug_id,
                        text,
                    )
                    return None, None
                ratio = _mono_ratio(paragraph, font_map)
                if ratio >= MONO_SKIP_RATIO:
                    logger.debug(
                        "DocBabel patch: skip monospace paragraph %s "
                        "(mono ratio %.2f): %r",
                        paragraph.debug_id,
                        ratio,
                        text[:80],
                    )
                    return None, None
                _convert_mono_fragments_to_formulas(paragraph, font_map)
        except Exception:
            logger.exception(
                "DocBabel patch A failed on paragraph %s; "
                "falling back to original behaviour",
                getattr(paragraph, "debug_id", "?"),
            )
        return orig(self, paragraph, tracker, page_font_map, xobj_font_map)

    return patched


# ---------------------------------------------------------------------------
# Patch B：合并列表段落拆分
# ---------------------------------------------------------------------------


def _get_visual_lines(finder, paragraph):
    """段落的视觉行序列；含非 pdf_line 组成时返回 None（不处理）。"""
    lines = []
    for comp in paragraph.pdf_paragraph_composition or []:
        if comp.pdf_line is None:
            return None
        band_lines, _ = finder._split_line_visual_bands(comp.pdf_line)
        lines.extend(band_lines)
    return lines


def _line_starts_monospace(line, font_map) -> bool:
    for char in line.pdf_character:
        unicode_text = getattr(char, "char_unicode", "") or ""
        if not unicode_text.strip():
            continue
        return _is_mono_font(_char_font(char, font_map))
    return False


def _maybe_split_list_paragraph(finder, paragraph, font_map):
    from babeldoc.format.pdf.document_il.utils.layout_helper import (
        get_char_unicode_string,
    )

    if paragraph.layout_label not in _LIST_SPLITTABLE_LABELS:
        return None
    if getattr(paragraph, "vertical", False):
        return None
    lines = _get_visual_lines(finder, paragraph)
    if not lines or len(lines) < 2:
        return None

    texts = [
        (get_char_unicode_string(line.pdf_character) or "").strip()
        for line in lines
    ]
    marker_flags = [
        bool(
            _LIST_MARKER_RE.match(text)
            or _NUMBER_LIST_MARKER_RE.match(text)
            or _PUA_BULLET_RE.match(text)
        )
        if text
        else False
        for text in texts
    ]

    # 兜底：主标记不足时才启用（覆盖未知 bullet glyph）。只取重复次数最多的
    # 首字符，避免把行首引号等其他符号误判成条目边界
    if sum(marker_flags) < _LIST_SPLIT_MIN_MARKERS:
        lead_counts: dict[str, int] = {}
        for text in texts:
            if text and not text[0].isalnum():
                lead_counts[text[0]] = lead_counts.get(text[0], 0) + 1
        candidates = [
            char
            for char, count in lead_counts.items()
            if count >= _LIST_SPLIT_MIN_MARKERS
        ]
        if candidates:
            lead = max(candidates, key=lambda char: lead_counts[char])
            for i, text in enumerate(texts):
                if text.startswith(lead):
                    marker_flags[i] = True

    marker_indices = [i for i, flag in enumerate(marker_flags) if flag]
    marker_count = len(marker_indices)

    boundaries: set[int] = set()
    if marker_count >= _LIST_SPLIT_MIN_MARKERS:
        # 紧排列表：标记行占比过半（每行一条）
        tight = marker_count / len(lines) >= _LIST_SPLIT_MIN_RATIO
        # 折行列表：条目内部会换行，标记行只是少数。仅对明确的 bullet 字形
        # 使用“上一条目已收尾”判据；编号/符号/未知 glyph 仍要求紧排，
        # 否则会把代码块、终端输出、正文引号行切碎
        strong_count = sum(
            1 for text in texts if text and _STRONG_BULLET_RE.match(text)
        )
        unconfirmed = sum(
            1
            for i in marker_indices
            if i > 0 and not texts[i - 1].endswith(_ITEM_END_CHARS)
        )
        if tight or (
            strong_count >= _LIST_SPLIT_MIN_MARKERS
            and unconfirmed <= _LIST_SPLIT_CONFIRM_TOLERANCE
        ):
            boundaries.update(marker_indices)

    # 定义列表辅助规则：行首等宽字体 + 上一行以句末标点结尾
    for i in range(1, len(lines)):
        if (
            texts[i]
            and texts[i - 1].endswith(_SENTENCE_FINAL_CHARS)
            and _line_starts_monospace(lines[i], font_map)
        ):
            boundaries.add(i)

    boundaries.discard(0)
    if not boundaries:
        return None

    groups = [[lines[0]]]
    for i in range(1, len(lines)):
        if i in boundaries:
            groups.append([lines[i]])
        else:
            groups[-1].append(lines[i])
    if len(groups) < 2:
        return None

    return _build_split_paragraphs(finder, paragraph, groups, "list")


def _build_split_paragraphs(finder, paragraph, groups, reason: str):
    """把按行分组的结果构建成多个 PdfParagraph，并重算它们的几何数据。"""
    from babeldoc.format.pdf.document_il.il_version_1 import Box
    from babeldoc.format.pdf.document_il.il_version_1 import PdfParagraph
    from babeldoc.format.pdf.document_il.il_version_1 import (
        PdfParagraphComposition,
    )
    from babeldoc.format.pdf.document_il.midend.paragraph_finder import (
        generate_base58_id,
    )

    if len(groups) < 2:
        return None

    new_paragraphs = []
    for group_lines in groups:
        comps = [PdfParagraphComposition(pdf_line=line) for line in group_lines]
        new_paragraph = PdfParagraph(
            box=Box(0, 0, 0, 0),  # 临时边界框，update_paragraph_data 重算
            pdf_paragraph_composition=comps,
            unicode="",
            debug_id=generate_base58_id(),
            layout_label=paragraph.layout_label,
            layout_id=paragraph.layout_id,
            xobj_id=paragraph.xobj_id,
        )
        finder.update_paragraph_data(new_paragraph, update_unicode=True)
        new_paragraphs.append(new_paragraph)

    logger.debug(
        "DocBabel patch: split merged %s paragraph %s into %d paragraphs",
        reason,
        paragraph.debug_id,
        len(new_paragraphs),
    )
    return new_paragraphs


def _line_box_height(line) -> float:
    ys = []
    y2s = []
    for char in line.pdf_character:
        box = getattr(char, "box", None)
        if box is None:
            continue
        ys.append(box.y)
        y2s.append(box.y2)
    if not ys:
        return 0.0
    return max(y2s) - min(ys)


def _maybe_split_index_paragraph(finder, paragraph):
    """index/索引页段落：按“行尾页码”把合并的多条词条拆开。

    BabelDOC 会把整栏索引词条合并成一个 PdfParagraph，排版后被当成连续
    文本重排，词条串行、页码混进句子中间。这里按词条边界（行尾页码）分组，
    无页码的折行（如 "AI (artificial intelligence), agents and applica-"
    + "tions"）并入前一词条。
    """
    from babeldoc.format.pdf.document_il.utils.layout_helper import (
        get_char_unicode_string,
    )

    if paragraph.layout_label not in _LIST_SPLITTABLE_LABELS:
        return None
    if getattr(paragraph, "vertical", False):
        return None
    lines = _get_visual_lines(finder, paragraph)
    if not lines or len(lines) < _INDEX_SPLIT_MIN_LINES:
        return None

    texts = [
        (get_char_unicode_string(line.pdf_character) or "").strip()
        for line in lines
    ]
    entry_flags = [bool(text and _INDEX_PAGE_TAIL_RE.search(text)) for text in texts]
    entry_count = sum(entry_flags)
    if entry_count < _INDEX_SPLIT_MIN_ENTRIES:
        return None
    if entry_count / len(lines) < _INDEX_SPLIT_MIN_RATIO:
        return None

    groups = []
    current = []
    for line, text, is_entry in zip(lines, texts, entry_flags):
        current.append(line)
        if is_entry:
            groups.append(current)
            current = []
    if current:
        if groups:
            groups[-1].extend(current)  # 尾部无页码的折行并入最后一条
        else:
            groups.append(current)
    return _build_split_paragraphs(finder, paragraph, groups, "index")


def _maybe_split_heading_paragraph(finder, paragraph):
    """大字号多行标题（Part/附录扉页横幅）按物理行拆开。

    这类标题每行都是独立语义行（如 "appendix A" / "Trying out LangChain"）。
    若保持为一段，中文变长后重排会把下一行的文字挤到上一行行末。
    """
    from babeldoc.format.pdf.document_il.utils.layout_helper import (
        get_char_unicode_string,
    )

    if getattr(paragraph, "vertical", False):
        return None
    lines = _get_visual_lines(finder, paragraph)
    if not lines or len(lines) < 2:
        return None

    heights = [_line_box_height(line) for line in lines]
    if min(heights) < _HEADING_SPLIT_MIN_HEIGHT:
        return None

    texts = [
        (get_char_unicode_string(line.pdf_character) or "").strip()
        for line in lines
    ]
    if any(not text for text in texts):
        return None
    if any(text.endswith(_SENTENCE_FINAL_CHARS) for text in texts):
        return None
    if any(len(text) > _HEADING_SPLIT_MAX_CHARS for text in texts):
        return None

    return _build_split_paragraphs(
        finder, paragraph, [[line] for line in lines], "heading"
    )


def _split_list_paragraphs(finder, page) -> None:
    font_map = {font.font_id: font for font in page.pdf_font or []}
    for xobj in page.pdf_xobject or []:
        for font in xobj.pdf_font or []:
            font_map.setdefault(font.font_id, font)

    new_paragraphs = []
    for paragraph in page.pdf_paragraph or []:
        split = _maybe_split_list_paragraph(finder, paragraph, font_map)
        if not split:
            split = _maybe_split_index_paragraph(finder, paragraph)
        if not split:
            split = _maybe_split_heading_paragraph(finder, paragraph)
        if split:
            new_paragraphs.extend(split)
        else:
            new_paragraphs.append(paragraph)
    page.pdf_paragraph[:] = new_paragraphs

    # 新段落必须拥有按字符顺序递增的 render_order，否则 Typesetting 会把
    # 相同 render_order 的多个段落交错排版（文字逐字竖排碎裂）。
    # 同时重跑重叠修复，与 process_page 原生后处理保持一致。
    finder._set_paragraph_render_order(page)
    finder.fix_overlapping_paragraphs(page)


def _make_patched_process_page(orig):
    def patched(self, page):
        orig(self, page)
        try:
            _split_list_paragraphs(self, page)
        except Exception:
            logger.exception(
                "DocBabel patch B failed; keeping original segmentation"
            )

    return patched


# ---------------------------------------------------------------------------
# Patch D：孤字行修复
# ---------------------------------------------------------------------------


def _last_line_non_space_count(entries) -> int:
    """统计最后一行（y 最小的一行）的非空白字符数。

    entries 为 (y, unicode_text) 序列；PDF 坐标向下递减，故最后一行的 y 最小。
    """
    items = [(y, text) for y, text in entries if y is not None and (text or "").strip()]
    if not items:
        return 0
    items.sort(key=lambda item: item[0])
    base_y = items[0][0]
    count = 0
    for y, _text in items:
        if abs(y - base_y) > _ORPHAN_Y_TOL:
            break
        count += 1
    return count


def _composition_line_entries(paragraph):
    """从已排版的 composition 提取 (y, unicode)；含非纯字符组成时返回 None。"""
    entries = []
    for comp in paragraph.pdf_paragraph_composition or []:
        char = comp.pdf_character
        if char is None or char.box is None:
            return None
        entries.append((char.box.y, char.char_unicode))
    return entries


def _typeset_unit_line_entries(typeset_units):
    """从排版单元提取 (y, unicode)；公式/图形单元按 1 个可见字符计。"""
    entries = []
    for unit in typeset_units:
        if unit.formular is not None:
            box = unit.box
            if box is not None and box.y is not None:
                entries.append((box.y, "\u2588"))
            continue
        if unit.char is not None:
            entries.append((unit.char.box.y, unit.char.char_unicode))
        elif unit.unicode:
            entries.append((unit.y, unit.unicode))
    return entries


def _fix_orphan_last_line(
    typesetting,
    paragraph,
    page,
    typesetting_units,
    use_english_line_break: bool,
    pdf_curve_len: int = 0,
    pdf_form_len: int = 0,
) -> None:
    """末行只剩一个字时缩小该段字号重排，直到末行至少 2 个字。

    缩放下限为 max(ORPHAN_SCALE_FLOOR, base_scale * ORPHAN_RELATIVE_FLOOR)，
    找不到可行字号则保持原排版。重排前把第一次排版追加到页面的曲线/图形
    截断（重排会重新追加），避免同一装饰被绘制两次。
    """
    if getattr(paragraph, "vertical", False):
        return
    if getattr(paragraph, "toc_page_number", None):
        return
    if getattr(paragraph, "layout_label", None) in _ORPHAN_SKIP_LABELS:
        return

    entries = _composition_line_entries(paragraph)
    if entries is None:
        return
    non_space_total = sum(1 for _y, text in entries if (text or "").strip())
    if non_space_total < ORPHAN_MIN_LAST_CHARS:
        return
    if _last_line_non_space_count(entries) != 1:
        return

    base_scale = getattr(paragraph, "scale", None)
    if base_scale is None or base_scale <= ORPHAN_SCALE_FLOOR:
        return

    line_skip = 1.50 if getattr(typesetting, "is_cjk", False) else 1.3
    min_scale = max(ORPHAN_SCALE_FLOOR, base_scale * ORPHAN_RELATIVE_FLOOR)
    scale = round(base_scale - ORPHAN_SCALE_STEP, 4)
    attempts = 0
    while scale >= min_scale and attempts < ORPHAN_MAX_ATTEMPTS:
        attempts += 1
        try:
            layout_units, all_units_fit = typesetting._layout_typesetting_units(
                typesetting_units,
                paragraph.box,
                scale,
                line_skip,
                paragraph,
                use_english_line_break,
            )
        except Exception:
            layout_units, all_units_fit = [], False
        if all_units_fit:
            layout_entries = _typeset_unit_line_entries(layout_units)
            if (
                layout_entries is not None
                and _last_line_non_space_count(layout_entries) >= ORPHAN_MIN_LAST_CHARS
            ):
                if page is not None:
                    if page.pdf_curve is not None:
                        del page.pdf_curve[pdf_curve_len:]
                    if page.pdf_form is not None:
                        del page.pdf_form[pdf_form_len:]
                typesetting._find_optimal_scale_and_layout(
                    paragraph,
                    page,
                    typesetting_units,
                    scale,
                    use_english_line_break,
                    apply_layout=True,
                )
                applied_entries = _composition_line_entries(paragraph)
                if (
                    applied_entries is not None
                    and _last_line_non_space_count(applied_entries)
                    >= ORPHAN_MIN_LAST_CHARS
                ):
                    logger.debug(
                        "DocBabel patch D: fixed orphan last line of paragraph %s "
                        "(scale %.3f -> %.3f)",
                        getattr(paragraph, "debug_id", "?"),
                        base_scale,
                        scale,
                    )
                    return
        scale = round(scale - ORPHAN_SCALE_STEP, 4)


def _make_patched_retypeset(orig):
    def patched(
        self,
        paragraph,
        page,
        typesetting_units,
        precomputed_scale,
        use_english_line_break=True,
    ):
        curve_len = len(page.pdf_curve) if page.pdf_curve is not None else 0
        form_len = len(page.pdf_form) if page.pdf_form is not None else 0
        orig(
            self,
            paragraph,
            page,
            typesetting_units,
            precomputed_scale,
            use_english_line_break,
        )
        try:
            _fix_orphan_last_line(
                self,
                paragraph,
                page,
                typesetting_units,
                use_english_line_break,
                curve_len,
                form_len,
            )
        except Exception:
            logger.exception(
                "DocBabel patch D failed on paragraph %s; keeping original layout",
                getattr(paragraph, "debug_id", "?"),
            )

    return patched


# ---------------------------------------------------------------------------
# Patch C：提示词强化
# ---------------------------------------------------------------------------

_IL_RULES_ANCHOR = (
    "4. If the entire input is pure code/identifiers, return it unchanged.\n"
    "5. Translate ALL human-readable content into $lang_out."
)
_IL_RULES_REPLACEMENT = (
    "4. If the entire input is pure code/identifiers, return it unchanged.\n"
    "5. Never translate command-line options or flags (e.g., -C, "
    "--target=..., -mcpu=...), file paths, URLs, version numbers, "
    "document/part numbers, or programming identifiers; keep them exactly "
    "unchanged.\n"
    "6. If the entire input is source code, a shell/command line, or "
    "configuration syntax, return it exactly unchanged.\n"
    "7. Translate ALL human-readable content into $lang_out."
)

_LLM_RULES_ANCHOR = (
    "- Placeholders: `{v1}`, `{name}`, `%s`, `%d`, `[[...]]`, `%%...%%` — "
    "keep exactly unchanged.\n- JSON keys or structure."
)
_LLM_RULES_REPLACEMENT = (
    "- Placeholders: `{v1}`, `{name}`, `%s`, `%d`, `[[...]]`, `%%...%%` — "
    "keep exactly unchanged.\n"
    "- JSON keys or structure.\n"
    "- Command-line options/flags (e.g., -C, --target=..., -mcpu=...), file "
    "paths, URLs, version numbers, document/part numbers, and programming "
    "identifiers: keep exactly unchanged.\n"
    '- If an input paragraph is entirely source code or a shell/command '
    'line, copy it to "output" unchanged.'
)


def _patch_prompt_template(module, anchor: str, replacement: str, name: str) -> None:
    template = module.PROMPT_TEMPLATE
    source = template.template
    if replacement in source:
        return
    if anchor not in source:
        logger.warning(
            "DocBabel patch: %s prompt anchor not found, "
            "prompt hardening skipped (BabelDOC upgraded?)",
            name,
        )
        return
    module.PROMPT_TEMPLATE = Template(source.replace(anchor, replacement))


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def apply_babeldoc_patches() -> None:
    """应用全部补丁，幂等。"""
    global _APPLIED
    if _APPLIED:
        return

    from babeldoc.format.pdf.document_il.midend import il_translator
    from babeldoc.format.pdf.document_il.midend import il_translator_llm_only
    from babeldoc.format.pdf.document_il.midend import paragraph_finder
    from babeldoc.format.pdf.document_il.midend import typesetting

    il_translator.ILTranslator.pre_translate_paragraph = (
        _make_patched_pre_translate_paragraph(
            il_translator.ILTranslator.pre_translate_paragraph
        )
    )
    paragraph_finder.ParagraphFinder.process_page = _make_patched_process_page(
        paragraph_finder.ParagraphFinder.process_page
    )
    typesetting.Typesetting.retypeset_with_precomputed_scale = _make_patched_retypeset(
        typesetting.Typesetting.retypeset_with_precomputed_scale
    )
    _patch_prompt_template(
        il_translator, _IL_RULES_ANCHOR, _IL_RULES_REPLACEMENT, "il_translator"
    )
    _patch_prompt_template(
        il_translator_llm_only,
        _LLM_RULES_ANCHOR,
        _LLM_RULES_REPLACEMENT,
        "il_translator_llm_only",
    )

    _APPLIED = True
    logger.info(
        "DocBabel BabelDOC patches applied "
        "(monospace/identifier skip, list splitting, prompt hardening, "
        "orphan-line fix)"
    )
