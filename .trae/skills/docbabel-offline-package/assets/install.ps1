# DocBabel 离线安装脚本（Windows PowerShell 5+ / Docker Desktop）
# 用法：在本目录打开 PowerShell，执行  .\install.ps1
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

Write-Host "=========================================="
Write-Host "  DocBabel 离线安装程序 (Windows)"
Write-Host "=========================================="

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "[ERROR] 未检测到 docker，请先启动 Docker Desktop" -ForegroundColor Red
    exit 1
}
docker compose version | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] 未检测到 Docker Compose V2，请升级 Docker Desktop" -ForegroundColor Red
    exit 1
}

Write-Host "[INFO] $(docker --version)"

if (-not (Test-Path ".env")) {
    Copy-Item "config\.env.example" ".env"
    Write-Host "[INFO] 已从 config\.env.example 生成 .env，建议修改 SECRET_KEY 后重新执行" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "[STEP 1/2] 加载离线 Docker 镜像..."
Get-ChildItem "images\*.tar.gz" | ForEach-Object {
    Write-Host "  -> 加载 $($_.Name)"
    docker load -i $_.FullName
    if ($LASTEXITCODE -ne 0) { throw "镜像加载失败: $($_.Name)" }
}

Write-Host ""
Write-Host "[STEP 2/2] 启动服务..."
docker compose up -d
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] 启动失败。若提示 5432 端口被系统保留，请在 .env 中设置 POSTGRES_PORT=55433 后重试" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "=========================================="
Write-Host "  安装完成"
Write-Host "=========================================="
Write-Host "  访问地址: http://localhost"
Write-Host "  健康检查: http://localhost/api/health"
Write-Host ""
Write-Host "  首次使用: 注册第一个账号（自动成为管理员），"
Write-Host "            在「模型」页配置内网可达的 OpenAI 兼容翻译接口"
