# DocBabel 离线安装包

基于 **Host003/BabelDOC 0.6.4** 翻译引擎的 DocBabel Web 全栈平台，**完全离线部署**：
所有 Docker 镜像与 BabelDOC 运行资产（版面/OCR 模型、字体、CMap、tiktoken 缓存）
均已内置，目标机器无需访问互联网。

> 构建日期：__BUILD_DATE__ ｜ 源码版本：`__VERSION__` ｜ 资产校验标签：`__ASSET_TAG__`

---

## 一、安装包内容

```
DocBabel-offline-__VERSION__/
├── install.sh                 # Linux / macOS 一键安装脚本
├── install.ps1                # Windows PowerShell 一键安装脚本
├── docker-compose.yml         # 离线专用编排文件（pull_policy: never，禁止联网拉取）
├── VERSION                    # 版本与镜像清单
├── README.md                  # 本说明
├── SHA256SUMS.txt             # 镜像压缩包校验值
├── config/
│   └── .env.example           # 环境变量样例（端口/密钥/数据库口令）
├── images/                    # 离线镜像（docker load 加载）
│   ├── babeldoc-backend.tar.gz    # 后端，已内置完整 BabelDOC 离线资产（约 970 MB）
│   ├── babeldoc-frontend.tar.gz   # 前端 + nginx（约 25 MB）
│   ├── postgres.tar.gz            # PostgreSQL 16（约 110 MB）
│   └── redis.tar.gz               # Redis 7（约 16 MB）
├── src/                       # 完整源码（git __VERSION__ 干净快照，与镜像内程序一致）
└── docs/                      # 架构、部署与用户手册文档
```

**系统要求**

| 项 | 要求 |
|---|---|
| Docker | Engine ≥ 20.10，带 Compose V2（`docker compose version` 可用）；Windows 用 Docker Desktop |
| 磁盘 | 加载后镜像约 4 GB；另需数据库与上传文件空间，建议 ≥ 20 GB |
| 内存 | 建议 ≥ 8 GB（翻译含 ONNX 版面分析；翻译模型在外部 API 端运行，本机不加载 LLM） |
| 网络 | 部署过程**无需互联网**；运行时需能访问你配置的翻译模型 API 地址（见第四节） |

---

## 二、安装（Linux / macOS）

```bash
# 1. 解压
tar xzf DocBabel-offline-__VERSION__.tar.gz   # 或解压 .zip
cd DocBabel-offline-__VERSION__

# 2.（可选）先校验镜像完整性
sha256sum -c SHA256SUMS.txt

# 3. 一键安装：加载镜像 -> 生成 .env -> 启动服务
chmod +x install.sh
./install.sh
```

> 若通过 Windows 拷贝/解压得到 `install.sh`，可能被转成 CRLF 行尾导致
> `env: 'bash\r'` 报错，执行：`sed -i 's/\r$//' install.sh`

## 三、安装（Windows + Docker Desktop）

1. 解压本压缩包，例如 `D:\DocBabel-offline-__VERSION__`
2. 启动 **Docker Desktop**，确认其处于 Running
3. 在该目录打开 PowerShell，执行：

```powershell
.\install.ps1
```

也可以手动执行：

```powershell
# 加载镜像
Get-ChildItem images\*.tar.gz | ForEach-Object { docker load -i $_.FullName }
# 启动
docker compose up -d
```

**端口 5432 绑定失败**（Windows 常见，Hyper-V/WSL 保留 5041–5440 等端口段）：
编辑 `.env`，设置 `POSTGRES_PORT=55433` 后重新 `docker compose up -d`。
80 端口被占用时改 `WEB_PORT`（如 `8080`）。

---

## 四、验证安装与配置翻译模型

```bash
docker compose ps                 # 四个容器应为 Up / healthy
curl http://localhost/api/health  # babeldoc_assets_ready 应为 true
```

浏览器打开 **http://localhost**：

1. 注册**第一个账号 → 自动成为管理员**；
2. 进入「模型」页面，新建模型配置：
   - Base URL：内网可达的 OpenAI 兼容接口，例如 `http://192.168.6.15:11434/v1`（Ollama）
   - 模型名：如 `translategemma:4b`；API Key：Ollama 可任意填（如 `ollama`）
   - 点「测试连接」确认；
3. 进入「翻译」页上传 PDF，选择该模型即可开始。

> 离线指的是**不依赖互联网下载引擎资源**；翻译本身仍需要大模型 API。
> 请确保该 API 地址从**后端容器**可达（容器使用默认 bridge 网络，
> 访问宿主机服务在 Linux 上用宿主机内网 IP，不要用 `127.0.0.1`）。

---

## 五、配置说明

首次运行 `install` 会由 `config/.env.example` 生成 `.env`，常用项：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `SECRET_KEY` | 占位值 | **生产环境务必修改**为长随机串（JWT 签名密钥） |
| `WEB_PORT` | 80 | 浏览器访问端口 |
| `BACKEND_PORT` | 8000 | 后端 API 直连端口（调试用） |
| `POSTGRES_PORT` | 5432 | PostgreSQL 宿主端口（仅调试） |
| `POSTGRES_PASSWORD` | babeldoc | 数据库口令，建议修改 |
| `COMPOSE_PROJECT_NAME` | babeldoc | 容器/卷/网络名前缀 |

数据通过 Docker 命名卷持久化（删除容器不丢数据）：
`babeldoc_postgres_data`、`babeldoc_backend_uploads`、`babeldoc_backend_outputs`。

---

## 六、日常运维

```bash
docker compose ps                    # 查看状态
docker compose logs -f backend       # 跟踪后端日志（翻译进度在此输出）
docker compose restart backend       # 重启后端
docker compose down                  # 停止并删除容器（保留数据卷）
docker compose down -v               # 同时删除数据卷（谨慎：清空数据库与文件）
docker compose pull                  # 无效：离线编排已设置 pull_policy: never
```

升级离线包：加载新版镜像 tar 后 `docker compose up -d`，后端启动时自动执行
Alembic 数据库迁移。

---

## 七、常见问题

**Q: `docker compose up` 报 `ports are not available ... 5432`（Windows）**
A: 5432 落在系统保留端口段。`.env` 中设置 `POSTGRES_PORT=55433`。

**Q: 后端一直 Restarting，日志含 `env: 'bash\r'`**
A: 安装脚本/entrypoint 被转成 CRLF。镜像内已做处理；若自行改脚本，
执行 `sed -i 's/\r$//' install.sh`。

**Q: 健康检查中 `babeldoc_assets_ready:false` 或启动报资产缺失**
A: 后端镜像已内置 full 资产，出现此情况通常是用了自行挂载的空缓存目录覆盖了
`/root/.cache/babeldoc`。请移除该挂载，保持本包 compose 默认配置。

**Q: 翻译任务失败，日志显示连接模型超时**
A: 从后端容器内验证 API 可达性：
`docker exec babeldoc-backend python3 -c "import urllib.request;print(urllib.request.urlopen('http://你的模型地址/models',timeout=5).status)"`。
容器内不能用 `127.0.0.1` 访问宿主机服务，请用宿主机内网 IP。

**Q: 想完全卸载**
A: `docker compose down -v` 删除容器与数据卷，再删除本目录即可；
镜像可用 `docker rmi` 按 VERSION 中清单删除。
