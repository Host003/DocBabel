---
name: docbabel-offline-package
description: Build DocBabel offline Docker Compose installer with bundled images, source and BabelDOC assets. Use for 离线安装包/离线部署包/镜像导出 to air-gapped hosts. Not for normal online deployment.
---

# DocBabel 离线安装包制作

把当前仓库构建为**完全离线可用**的 Docker Compose 安装包：4 个镜像 tar、
内置 full 离线资产的后端镜像、完整源码、离线 compose、双平台安装脚本、
配置样例、校验文件和说明文档。

## 何时使用 / 不使用

- 使用：用户要求"离线安装包/离线部署包/导出镜像到内网/气隙环境部署"。
- 不使用：普通 `docker compose up` 联网部署；只构建单个镜像。

## 一键执行

```powershell
# 在仓库根目录或任意目录执行（脚本自动定位 git 仓库根）
powershell -ExecutionPolicy Bypass -File `.trae/skills/docbabel-offline-package/scripts/build-offline-package.ps1`
```

产物：`dist/DocBabel-offline-<短commit>.zip` 与同名解压目录（`dist/` 已被 .gitignore 忽略）。
脚本幂等，可重复执行；参数见脚本顶部注释（`-SkipZip`、`-Profile core|minimal` 等）。

## 前置条件（缺什么补什么，不要绕过）

1. Docker Desktop 正在运行；`backend/.venv` 存在且已安装当前 pyproject 的依赖
   （脚本默认用它生成资产；没有 venv 时退回 `python`）。
2. 本地已有后端/前端基础镜像：`ghcr.io/ccsert/babeldoc-backend:latest`、
   `ghcr.io/ccsert/babeldoc-frontend:latest`。缺失时先 `docker compose build`。
   注意 docker.io 在本机网络常被重置，基础镜像需经镜像源预拉取并打回标准 tag，例如：
   `docker pull docker.m.daocloud.io/library/python:3.11-slim` 后
   `docker tag ... python:3.11-slim`（postgres/redis/nginx/node 同理）。
3. `backend/Dockerfile` 的 entrypoint 必须含 CRLF 规范化
   （`sed -i 's/\r$//' /entrypoint.sh`），否则目标机会重现
   `env: 'bash\r'`、exit 127。

## 流程要点（脚本已固化，改动前必读）

1. **生成资产包必须走应用自身的校验导出**，不要手工 zip 缓存目录：
   ```python
   from babeldoc.assets.assets import generate_all_assets_file_list, get_offline_assets_tag
   from app.services.babeldoc_assets import _write_offline_assets_package
   ```
   `_write_offline_assets_package` 会对每个文件做 SHA3 校验。full 档约 213MB，
   182 个文件（models 1、fonts 34、cmap 146、tiktoken 1）。
2. **离线镜像 = 基础后端镜像 + 烤入资产**，与 .github/workflows/release.yml 同法。
   关键：先从源码构建并固定普通镜像标签 `ghcr.io/ccsert/babeldoc-backend:base`，
   离线 Dockerfile 始终 `FROM ...:base`（**不要 FROM latest**——重复执行脚本时
   latest 已是离线镜像，会再次烤入资产导致每层 +336MB 的体积膨胀）。
   烤入方式：解压资产到 `/root/.cache/babeldoc` → 设置三个 ENV：
   `BABELDOC_OFFLINE_MODE=true`、`BABELDOC_OFFLINE_ASSET_PROFILE=full`、
   `BABELDOC_PRECHECK_ASSETS_ON_STARTUP=true`。打两个 tag：`latest` 和
   `<短commit>-offline`。
3. **导出镜像用 PowerShell 原生命令**：`docker save -o x.tar <tags>` 后用
   `C:\Program Files\Git\usr\bin\gzip.exe -1` 压缩。禁止在 Git Bash 里
   `docker save | gzip`——本机会静默产出空文件。导出顺序：backend（两个 tag
   一起 save）、frontend、postgres:16-alpine、redis:7-alpine。
4. **源码用 git 快照**：`git archive --format=zip HEAD` 解包到 `src/`，
   保证与镜像内程序版本一致，不含 .venv/.env/本地 override。
5. **包内文件**（模板在本技能 `assets/`，直接拷贝，不要临时重写）：
   - `docker-compose.yml`：删去 build 段；四个服务全部 `pull_policy: never`；
     端口/密钥/口令用 `.env` 变量化；后端环境写死离线三变量且
     `BABELDOC_OFFLINE_ASSETS_PACKAGE: ""`；数据走命名卷。
   - `install.sh`（必须 LF 行尾）、`install.ps1`：load 镜像 → 生成 .env → up。
   - `config/.env.example`、`VERSION`、`SHA256SUMS.txt`（对 images/*.tar.gz）。
   - `README.md`：双平台安装、Windows 5432 保留端口处置、容器访问模型 API
     必须用宿主机内网 IP、日常运维命令。
   - `docs/`：复制仓库文档目录。
6. 最终 zip 用 `Compress-Archive -CompressionLevel NoCompression`
   （tar.gz 已压缩，再压缩只浪费时间）。

## 交付前必做：隔离环境实测（不可跳过）

在**独立项目名 + 备用端口 + 全新数据卷**下验证，避免碰到日常开发栈：

```powershell
$env:COMPOSE_PROJECT_NAME="pkgtest"; $env:WEB_PORT="8081"; $env:BACKEND_PORT="8001"
$env:POSTGRES_PORT="55434"; $env:REDIS_PORT="6380"
cd dist/DocBabel-offline-<commit>
docker load -i images/redis.tar.gz   # 至少实测一个 tar 可加载；全量 load 更稳妥
docker compose config --quiet        # 模板语法
docker compose up -d
# 等待约 45s，检查：
docker compose ps                    # 四容器 Up/healthy
(Invoke-WebRequest http://localhost:8081/api/health -UseBasicParsing).Content
# 必须包含 "babeldoc_offline_mode":true 与 "babeldoc_assets_ready":true
# 在全新库注册第一个账号，验证 Alembic 迁移自动执行且成为 admin
docker compose down -v               # 测完清理卷
```

再对离线镜像本体做一次资产哈希校验：

```powershell
docker run --rm --entrypoint python3 ghcr.io/ccsert/babeldoc-backend:latest -c `
  "from app.services.babeldoc_assets import get_offline_assets_status as g; s=g(); print(s['ready'], s['present_files'], '/', s['total_files'])"
# 期望：True 182 / 182（full 档）
```

## 必须向用户说明的边界

"离线"= 引擎运行资产（模型/字体/CMap/tiktoken）与镜像不依赖互联网；
**翻译仍需一个从后端容器网络可达的 OpenAI 兼容接口**（如内网 Ollama）。
容器内不能用 127.0.0.1 访问宿主机服务，README 需写明用宿主机内网 IP。

## Windows 特定坑位速查

| 现象 | 处置 |
|---|---|
| `docker save \| gzip` 产出空文件 | PowerShell `docker save -o` + Git 自带 gzip.exe |
| 5432 绑定失败（Hyper-V 保留段 5041-5440） | `.env` 设 `POSTGRES_PORT=55433` |
| `env: 'bash\r'` / exit 127 | Dockerfile 构建时 `sed -i 's/\r$//'` entrypoint |
| docker.io connection reset | daocloud 等镜像源预拉取并 retag |
| compose ports 合并追加导致旧端口仍绑定 | 覆盖文件中用 YAML `!override` 标签 |
| 健康检查 assets_ready=false | 通常是空缓存挂载覆盖了镜像内 /root/.cache/babeldoc，去掉该挂载 |
| Trae 沙箱拦截 docker build（拒绝访问 docker-desktop.exe.log） | 运行脚本的 Shell 调用使用非沙箱模式 |
| 中文 .ps1 在 PowerShell 5.1 下报诡异语法错（GBK 误读 UTF-8） | 脚本必须存为 **UTF-8 with BOM**；新建/编辑 .ps1 后用 Parser::ParseFile 校验 |

## 脚本维护注意

- `scripts/build-offline-package.ps1` 与 `assets/install.ps1` 必须是 **UTF-8 with BOM**
  （Windows PowerShell 5.1 无 BOM 时按 GBK 解码，中文注释的字节会被当成行继续符）。
  编辑后执行语法校验：
  ```powershell
  $e=$null; [void][System.Management.Automation.Language.Parser]::ParseFile('<path>',[ref]$null,[ref]$e); $e
  ```
- 改动流程后重新完整执行一遍脚本并跑完隔离实测，再宣告技能更新完成。
