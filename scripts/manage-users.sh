#!/usr/bin/env bash
# DocBabel 用户管理脚本（Linux/macOS）：列出全部用户 / 重置指定用户的登录密码。
#
# 运行在部署 DocBabel 的 Linux 宿主机上，通过 docker exec 操作：
#   - 列表/查询走 postgres 容器内的 psql
#   - 密码重置在 backend 容器内完成：用应用自带 bcrypt 生成哈希并直接更新数据库，
#     与线上登录校验算法完全一致，无需重启容器，不影响其他用户和任务数据。
#
# 用法：
#   ./manage-users.sh list
#   ./manage-users.sh reset -u admin                 # 交互式输入两次新密码（推荐）
#   ./manage-users.sh reset -u admin -p NewPass123   # 直接带密码（会留在 shell 历史）
#
# 可选参数（容器名/库名与 docker-compose.yml 默认值一致）：
#   --backend-container 名   后端容器名（默认 babeldoc-backend）
#   --pg-container 名        数据库容器名（默认 babeldoc-postgres）
#   --pg-user 用户           数据库用户（默认 babeldoc）
#   --pg-db 库名             数据库名（默认 babeldoc）
#
# 密码规则与注册接口一致：长度 6-128。

set -euo pipefail

BACKEND_CONTAINER="babeldoc-backend"
PG_CONTAINER="babeldoc-postgres"
PG_USER="babeldoc"
PG_DB="babeldoc"

c_red=$'\033[31m'; c_green=$'\033[32m'; c_yellow=$'\033[33m'
c_cyan=$'\033[36m'; c_off=$'\033[0m'

fail() {
  echo "${c_red}[错误]${c_off} $*" >&2
  exit 1
}

container_running() {
  [ "$(docker inspect -f '{{.State.Running}}' "$1" 2>/dev/null || true)" = "true" ]
}

usage() {
  sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
}

# ── 参数解析 ──────────────────────────────────────────────────────────
[ $# -ge 1 ] || { usage; exit 1; }
if [ "$1" = "-h" ] || [ "$1" = "--help" ]; then usage; exit 0; fi
ACTION="$1"; shift
USERNAME=""
PASSWORD=""

while [ $# -gt 0 ]; do
  case "$1" in
    -u|--username) USERNAME="${2:-}"; shift 2 ;;
    -p|--password) PASSWORD="${2:-}"; shift 2 ;;
    --backend-container) BACKEND_CONTAINER="${2:-}"; shift 2 ;;
    --pg-container) PG_CONTAINER="${2:-}"; shift 2 ;;
    --pg-user) PG_USER="${2:-}"; shift 2 ;;
    --pg-db) PG_DB="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) fail "未知参数: $1（用 --help 查看用法）" ;;
  esac
done

# ── 前置检查 ──────────────────────────────────────────────────────────
docker info >/dev/null 2>&1 || fail "Docker 不可用，请先确认 Docker 服务已启动。"
container_running "$PG_CONTAINER" || \
  fail "数据库容器 '$PG_CONTAINER' 未运行，可用 --pg-container 指定实际容器名。"

# ── 动作：list ────────────────────────────────────────────────────────
if [ "$ACTION" = "list" ]; then
  echo "${c_cyan}DocBabel 用户列表（数据库 $PG_DB @ $PG_CONTAINER）：${c_off}"
  docker exec -i "$PG_CONTAINER" \
    psql -U "$PG_USER" -d "$PG_DB" -v ON_ERROR_STOP=1 <<'SQL'
SELECT id, username, email, role,
       CASE WHEN is_active THEN 'active' ELSE 'disabled' END AS status,
       created_at
FROM users
ORDER BY id;
SQL
  exit 0
fi

# ── 动作：reset ───────────────────────────────────────────────────────
if [ "$ACTION" != "reset" ]; then
  fail "未知动作 '$ACTION'，支持：list、reset（用 --help 查看用法）。"
fi
[ -n "$USERNAME" ] || fail "reset 必须指定用户名，例如：./manage-users.sh reset -u admin"
container_running "$BACKEND_CONTAINER" || \
  fail "后端容器 '$BACKEND_CONTAINER' 未运行，可用 --backend-container 指定实际容器名。"

# 获取新密码：参数直给 或 交互输入两遍（不回显）
if [ -z "$PASSWORD" ]; then
  read -r -s -p "请输入用户 '$USERNAME' 的新密码（输入不显示）: " PASSWORD; echo
  read -r -s -p "请再次输入新密码确认: " PASSWORD2; echo
  [ "$PASSWORD" = "$PASSWORD2" ] || fail "两次输入的密码不一致，已取消。"
  unset PASSWORD2
fi

if [ "${#PASSWORD}" -lt 6 ] || [ "${#PASSWORD}" -gt 128 ]; then
  fail "新密码长度必须在 6-128 之间。"
fi

# 在后端容器内一步完成：按用户名查用户 -> 用应用自身 bcrypt 生成哈希 -> 更新数据库。
# 密码经 stdin 传入，不出现在命令行参数/进程列表；utf-8-sig 解码可兼容带 BOM 的输入。
read -r -d '' RESET_CODE <<'PY' || true
import os, sys, asyncio
from sqlalchemy import select
from app.core.database import async_session_factory
from app.core.security import get_password_hash
from app.models.models import User

async def main():
    username = os.environ['TARGET_USERNAME']
    pw = sys.stdin.buffer.readline().decode('utf-8-sig').strip()
    async with async_session_factory() as db:
        u = (await db.execute(select(User).where(User.username == username))).scalar_one_or_none()
        if u is None:
            print('NOT_FOUND')
            sys.exit(2)
        u.hashed_password = get_password_hash(pw)
        await db.commit()
        print('OK:' + u.role)

asyncio.run(main())
PY

set +e
reset_output="$(printf '%s\n' "$PASSWORD" | docker exec -i -e TARGET_USERNAME="$USERNAME" \
  "$BACKEND_CONTAINER" python3 -c "$RESET_CODE")"
reset_rc=$?
set -e

marker="$(printf '%s\n' "$reset_output" | grep -E '^(OK:|NOT_FOUND)' | tail -n1 || true)"
if [ "$reset_rc" -eq 2 ] || [ "$marker" = "NOT_FOUND" ]; then
  fail "用户 '$USERNAME' 不存在。可先执行 'list' 查看全部用户名。"
fi
case "$marker" in
  OK:*) role="${marker#OK:}" ;;
  *) echo "$reset_output" >&2; fail "在后端容器中重置密码失败。" ;;
esac

echo
echo "${c_green}密码已重置成功：${c_off}"
echo "  用户: $USERNAME  (角色: $role)"
echo "  现在可以使用新密码在登录页登录。"
echo "${c_yellow}  建议登录后在「个人设置」中再次修改为自己记得住的密码。${c_off}"
