"""任务记录删除与磁盘文件的孤儿回收。

同一份上传/译文文件可能被多条任务引用（重复翻译复用时输出文件共享，
且去重查询跨用户），因此删除任务记录后必须按全局引用计数决定是否删物理文件。
"""

import os

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.models import TranslationTask


def collect_task_files(tasks: list[TranslationTask]) -> dict[str, str]:
    """返回 {文件名: 所在目录}，同一文件名只保留一个目录。"""
    candidates: dict[str, str] = {}
    for task in tasks:
        if task.stored_filename:
            candidates.setdefault(task.stored_filename, settings.UPLOAD_DIR)
        for name in (task.output_mono_filename, task.output_dual_filename):
            if name:
                candidates.setdefault(name, settings.OUTPUT_DIR)
    return candidates


async def cleanup_orphan_filenames(db: AsyncSession, candidates: dict[str, str]) -> None:
    """任务记录已删除后调用：全局无引用的物理文件才删除。"""
    for filename, base_dir in candidates.items():
        ref_count = (
            await db.execute(
                select(func.count(TranslationTask.id)).where(
                    or_(
                        TranslationTask.stored_filename == filename,
                        TranslationTask.output_mono_filename == filename,
                        TranslationTask.output_dual_filename == filename,
                    )
                )
            )
        ).scalar()
        if ref_count:
            continue
        filepath = os.path.join(base_dir, filename)
        if os.path.isfile(filepath):
            try:
                os.remove(filepath)
            except OSError:
                pass


async def purge_tasks(db: AsyncSession, tasks: list[TranslationTask]) -> int:
    """删除任务记录并回收变为孤儿的文件。调用方须先拦截运行中的任务。"""
    if not tasks:
        return 0
    candidates = collect_task_files(tasks)
    for task in tasks:
        await db.delete(task)
    await db.commit()
    await cleanup_orphan_filenames(db, candidates)
    return len(tasks)
