#!/usr/bin/env bash
# DocBabel 离线安装脚本（Linux / macOS）
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "=========================================="
echo "  DocBabel 离线安装程序"
echo "=========================================="

# ── Pre-flight checks ────────────────────────────────────────────────
if ! command -v docker >/dev/null 2>&1; then
    echo "[ERROR] 未检测到 Docker，请先安装 Docker Engine >= 20.10（或 Docker Desktop）"
    exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
    echo "[ERROR] 未检测到 Docker Compose V2，请安装 docker-compose-plugin"
    exit 1
fi

echo "[INFO] $(docker --version)"
echo "[INFO] $(docker compose version)"

# ── Prepare .env ─────────────────────────────────────────────────────
if [ ! -f .env ]; then
    cp config/.env.example .env
    echo "[INFO] 已从 config/.env.example 生成 .env，建议修改 SECRET_KEY 后重新执行"
fi

# ── Load images ──────────────────────────────────────────────────────
echo ""
echo "[STEP 1/2] 加载离线 Docker 镜像（后端镜像已内置完整 BabelDOC 资产）..."
for img in images/*.tar.gz; do
    echo "  -> 加载 $(basename "$img")"
    docker load -i "$img"
done

# ── Start stack ──────────────────────────────────────────────────────
echo ""
echo "[STEP 2/2] 启动服务..."
docker compose up -d

echo ""
echo "=========================================="
echo "  安装完成"
echo "=========================================="
echo "  访问地址: http://localhost  (如在 .env 修改 WEB_PORT 则用对应端口)"
echo "  健康检查: http://localhost/api/health"
echo ""
echo "  首次使用: 打开页面注册第一个账号（自动成为管理员），"
echo "            然后在「模型」页配置内网可达的 OpenAI 兼容翻译接口"
echo ""
echo "  常用命令:"
echo "    状态: docker compose ps"
echo "    日志: docker compose logs -f backend"
echo "    停止: docker compose down"
