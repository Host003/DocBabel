# 用户管理脚本部署与使用说明

用于在 **忘记管理员密码** 或需要运维用户账号时，在部署 DocBabel 的宿主机上：

1. **列出系统中的全部用户**（ID、用户名、邮箱、角色、状态、创建时间）；
2. **重置指定用户的登录密码**（管理员或普通用户均可）。

脚本提供 Linux 与 Windows 两个版本，功能完全一致，均通过 `docker exec` 操作正在运行的容器，**无需登录 Web、无需重启容器、不影响其他用户和任务数据**。

## 目录

- [1. 文件清单与适用环境](#1-文件清单与适用环境)
- [2. 前置条件](#2-前置条件)
- [3. 部署脚本](#3-部署脚本)
- [4. 使用方法](#4-使用方法)
- [5. 完整参数说明](#5-完整参数说明)
- [6. 工作原理](#6-工作原理)
- [7. 安全注意事项](#7-安全注意事项)
- [8. 常见问题排查](#8-常见问题排查)

---

## 1. 文件清单与适用环境

| 文件 | 适用环境 | 解释器 |
|------|---------|--------|
| `scripts/manage-users.sh` | Linux / macOS（**生产部署常用**） | bash 4+ |
| `scripts/manage-users.ps1` | Windows 10/11、Windows Server | Windows PowerShell 5.1 / PowerShell 7+ |

两个脚本不依赖 Python、psql 等宿主机环境，所有数据库与密码哈希操作都在 DocBabel 已有的 Docker 容器内完成，宿主机只需能运行 `docker` 命令。

---

## 2. 前置条件

1. **Docker 正在运行**，当前用户有执行 `docker` 的权限（Linux 上通常属于 `docker` 用户组，或使用 `sudo`，见 [FAQ](#8-常见问题排查)）。
2. DocBabel 容器处于运行状态，默认容器名（与 `docker-compose.yml` 默认配置一致）：

   | 角色 | 默认容器名 |
   |------|-----------|
   | 后端 | `babeldoc-backend` |
   | 数据库 | `babeldoc-postgres` |

   可用 `docker ps --format '{{.Names}}'` 核对实际名称。
3. 部署时若自定义过 compose 项目名（`COMPOSE_PROJECT_NAME`）或容器名，需通过参数指定实际容器名，见 [第 5 节](#5-完整参数说明)。
4. 数据库名/账号默认均为 `babeldoc`，与 compose 默认值一致；如改过，用参数覆盖。

---

## 3. 部署脚本

脚本不需要"安装"，放到部署 DocBabel 的宿主机上、赋予执行权限即可。建议随项目源码一起放在 `scripts/` 目录。

### 3.1 Linux / macOS

```bash
# 进入项目目录（脚本位于 scripts/ 下）
cd /opt/DocBabel          # 按实际部署路径调整

# 赋予执行权限（仅首次需要）
chmod +x scripts/manage-users.sh

# 验证脚本可正常运行（打印用法/用户列表）
./scripts/manage-users.sh --help
./scripts/manage-users.sh list
```

**行尾要求**：`manage-users.sh` 必须为 **LF 行尾、UTF-8 编码**（仓库内已是该格式）。
若从 Windows 拷贝后出现 `env: 'bash\r'`、`\r': command not found` 等错误，执行一次转换：

```bash
sed -i 's/\r$//' scripts/manage-users.sh   # GNU sed
# 或：dos2unix scripts/manage-users.sh
```

**sudo 场景**：若当前账号不在 `docker` 用户组，可在命令前加 `sudo`，例如 `sudo ./scripts/manage-users.sh list`。

### 3.2 Windows

```powershell
# 进入项目目录
cd D:\Project\DocBabel

# 直接运行即可，无需改执行策略（-ExecutionPolicy Bypass 仅对本次进程生效）
powershell -ExecutionPolicy Bypass -File .\scripts\manage-users.ps1 list
```

`manage-users.ps1` 为 **UTF-8 with BOM** 编码（保证 Windows PowerShell 5.1 正确识别中文提示），用系统自带 PowerShell 或 Windows Terminal 运行。

### 3.3 离线环境

脚本可直接在 [离线部署](DEPLOYMENT.md) 的 DocBabel 上使用：它只调用本地容器，不访问互联网，离线安装包同样适用（脚本也可从源码包 `scripts/` 目录取用）。

---

## 4. 使用方法

### 4.1 列出所有用户

**Linux：**

```bash
./scripts/manage-users.sh list
```

**Windows：**

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\manage-users.ps1 list
```

输出示例：

```
 id | username |      email      | role  | status |          created_at
----+----------+-----------------+-------+--------+-------------------------------
  1 | admin    | admin@qq.com    | admin | active | 2026-09-25 19:51:44.171735+00
  4 | zhangsan | zhangsan@qq.com | user  | active | 2026-10-08 21:08:47.101457+00
```

- `role`：`admin` 为管理员，`user` 为普通用户；
- `status`：`active` 正常，`disabled` 已停用。

### 4.2 重置指定用户的密码（推荐：交互式输入）

不把密码写在命令行里，执行后按提示**输入两次新密码（输入不回显）**：

**Linux：**

```bash
./scripts/manage-users.sh reset -u admin
```

**Windows：**

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\manage-users.ps1 reset -Username admin
```

成功输出示例：

```
密码已重置成功：
  用户: admin  (角色: admin)
  现在可以使用新密码在登录页登录。
  建议登录后在「个人设置」中再次修改为自己记得住的密码。
```

### 4.3 重置密码（直接带密码，便于自动化）

适合脚本/流水线调用；缺点是密码会出现在 shell 历史中，日常运维不推荐。

**Linux：**

```bash
./scripts/manage-users.sh reset -u admin -p 'NewPass123'
```

**Windows：**

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\manage-users.ps1 reset -Username admin -Password NewPass123
```

新密码规则与注册接口一致：**长度 6–128 位**。重置后建议立即登录并在「个人设置」中改密。

### 4.4 查看帮助

```bash
./scripts/manage-users.sh --help
```

---

## 5. 完整参数说明

### 5.1 Linux（`manage-users.sh`）

| 参数 | 说明 | 默认值 |
|------|------|--------|
| 动作（第 1 个位置参数） | `list` 或 `reset` | 无，必填 |
| `-u`, `--username` | reset 时要重置的用户名 | 无，reset 必填 |
| `-p`, `--password` | 直接指定新密码；省略则交互式输入两次 | 空（交互输入） |
| `--backend-container` | 后端容器名 | `babeldoc-backend` |
| `--pg-container` | 数据库容器名 | `babeldoc-postgres` |
| `--pg-user` | 数据库用户名 | `babeldoc` |
| `--pg-db` | 数据库名 | `babeldoc` |
| `-h`, `--help` | 显示帮助 | — |

示例：compose 项目名为 `myproj`、容器名带 `myproj-` 前缀时：

```bash
./scripts/manage-users.sh list \
  --pg-container myproj-postgres

./scripts/manage-users.sh reset -u admin \
  --backend-container myproj-backend \
  --pg-container myproj-postgres
```

### 5.2 Windows（`manage-users.ps1`）

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `list` / `reset`（位置参数） | 动作 | `list` |
| `-Username` | reset 时要重置的用户名 | 无，reset 必填 |
| `-Password` | 直接指定新密码；省略则交互式安全输入两次 | 空（交互输入） |
| `-BackendContainer` | 后端容器名 | `babeldoc-backend` |
| `-PgContainer` | 数据库容器名 | `babeldoc-postgres` |
| `-PgUser` | 数据库用户名 | `babeldoc` |
| `-PgDb` | 数据库名 | `babeldoc` |

---

## 6. 工作原理

- **列出用户**：脚本在 `postgres` 容器内执行只读 `SELECT`（`psql`），不修改任何数据。
- **重置密码**：脚本把一段 Python 通过 `docker exec` 送入 **backend 容器**执行：
  1. 按用户名查询用户，不存在则报错退出；
  2. 使用应用自身的 `app.core.security.get_password_hash`（**bcrypt**）生成哈希，与登录校验算法完全一致；
  3. 通过应用的数据库会话更新该用户的 `hashed_password` 并提交。
- **密码传输**：新密码通过容器 stdin 传入，不出现在命令行参数和容器进程列表中。
- 整个过程只更新目标用户一行记录，无需重启任何服务，重置后可**立即用新密码登录**。

---

## 7. 安全注意事项

1. 该脚本拥有重置任意用户（含管理员）密码的能力，应仅限**服务器管理员**使用，注意文件权限，不要放在普通用户可写的目录。
2. 优先使用**交互式输入**模式，避免密码进入 shell 历史；使用 `-p`/`-Password` 后，必要时清理历史记录（如 `history -c`）。
3. 重置为临时密码后，应尽快通知用户并要求其登录后自行改密。
4. 脚本不会打印、读取或导出任何现有密码（系统只存 bcrypt 哈希，**无法反查明文**，只能重置）。
5. 操作全程在本地宿主机与容器间完成，不经过网络接口、不需要 Web 登录态。

---

## 8. 常见问题排查

**Q1 提示「Docker 不可用」/ `Cannot connect to the Docker daemon`**
- Windows：启动 Docker Desktop 后重试。
- Linux：启动 Docker 服务（`sudo systemctl start docker`）；或将当前用户加入 docker 组（`sudo usermod -aG docker $USER`，重新登录生效），临时使用可加 `sudo`。

**Q2 提示「数据库容器 'babeldoc-postgres' 未运行」**
- 执行 `docker ps --format '{{.Names}}'` 查看真实容器名；若项目名不同，用 `--pg-container`（Windows：`-PgContainer`）指定。
- 若容器已停止，先 `docker compose up -d` 启动完整服务栈。

**Q3 提示「用户 'xxx' 不存在」**
- 先执行 `list` 确认准确用户名（区分大小写），再重置。

**Q4 重置成功但仍无法登录**
- 确认登录页输入的用户名与重置的用户名一致；
- 确认部署使用的是同一套容器/数据库（多套环境并存时，检查容器名参数是否指向目标环境）；
- 检查该用户 `status` 是否为 `active`（被停用用户需先由管理员在 Web 端启用）。

**Q5 连管理员账号本身都不存在了（不是忘记密码，而是账号被删）**
- 系统有兜底机制：**当数据库中不存在任何活跃管理员时，新注册的第一个账号会自动成为管理员**。此时直接在登录页注册即可恢复管理员入口；若仍有活跃管理员，普通注册只会得到普通用户角色。

**Q6 Linux 下运行报 `\r` / `bash\r` / `permission denied`**
- 行尾问题：执行 `sed -i 's/\r$//' scripts/manage-users.sh`；
- 权限问题：执行 `chmod +x scripts/manage-users.sh`。

**Q7 Windows 下提示执行策略相关警告**
- 按文档使用 `powershell -ExecutionPolicy Bypass -File ...` 即可，无需修改系统全局执行策略。
