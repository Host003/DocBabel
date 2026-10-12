<#
.SYNOPSIS
    DocBabel 用户管理脚本：列出全部用户 / 重置指定用户的登录密码。

.DESCRIPTION
    运行在部署 DocBabel 的 Windows 宿主机上，通过 docker exec 操作：
      - 列表/查询走 postgres 容器内的 psql
      - 密码哈希走 backend 容器内应用自带的 bcrypt（app.core.security），
        与线上登录校验算法完全一致，不直接拼接哈希算法。
    重置密码不会影响其他用户和任务数据，也不需要重启容器。

.EXAMPLE
    # 列出所有用户
    powershell -ExecutionPolicy Bypass -File .\manage-users.ps1 list

.EXAMPLE
    # 重置指定用户密码（推荐：交互式安全输入，密码不落在命令行历史里）
    powershell -ExecutionPolicy Bypass -File .\manage-users.ps1 reset -Username admin

.EXAMPLE
    # 也可直接带密码（方便自动化，但会出现在 shell 历史中，不推荐日常使用）
    powershell -ExecutionPolicy Bypass -File .\manage-users.ps1 reset -Username admin -Password NewPass123

.NOTES
    容器名/库名与 docker-compose.yml 默认值一致；自定义过项目名时用参数覆盖，例如：
      -BackendContainer myproj-backend -PgContainer myproj-postgres
    密码规则与注册接口一致：长度 6-128。
#>
param(
    [Parameter(Position = 0)]
    [ValidateSet('list', 'reset')]
    [string]$Action = 'list',

    # reset 时必填：要重置的用户名
    [string]$Username,

    # 可选：直接给新密码（不给则交互式安全输入两次）
    [string]$Password,

    [string]$BackendContainer = 'babeldoc-backend',
    [string]$PgContainer      = 'babeldoc-postgres',
    [string]$PgUser           = 'babeldoc',
    [string]$PgDb             = 'babeldoc'
)

$ErrorActionPreference = 'Stop'

function Fail([string]$Msg) { Write-Host "[错误] $Msg" -ForegroundColor Red; exit 1 }

function Test-ContainerRunning([string]$Name) {
    $st = docker inspect -f '{{.State.Running}}' $Name 2>$null
    return ($LASTEXITCODE -eq 0 -and $st.Trim() -eq 'true')
}

# ── 前置检查：Docker 可用、容器在运行 ─────────────────────────────────
docker info *> $null
if ($LASTEXITCODE -ne 0) { Fail 'Docker 不可用，请先启动 Docker Desktop。' }

if (-not (Test-ContainerRunning $PgContainer)) {
    Fail "数据库容器 '$PgContainer' 未运行，可用 -PgContainer 指定实际容器名。"
}

# ── 动作：list ────────────────────────────────────────────────────────
if ($Action -eq 'list') {
    Write-Host "DocBabel 用户列表（数据库 $PgDb @ $PgContainer）：" -ForegroundColor Cyan
    $sql = @"
SELECT id, username, email, role, CASE WHEN is_active THEN 'active' ELSE 'disabled' END AS status, created_at
FROM users
ORDER BY id;
"@
    $sql | docker exec -i $PgContainer psql -U $PgUser -d $PgDb -v ON_ERROR_STOP=1
    if ($LASTEXITCODE -ne 0) { Fail '查询用户列表失败。' }
    exit 0
}

# ── 动作：reset ───────────────────────────────────────────────────────
if (-not $Username) { Fail 'reset 必须指定用户名，例如：.\manage-users.ps1 reset -Username admin' }

# 获取新密码：参数直给 或 交互输入两遍
if (-not $Password) {
    $sec1 = Read-Host "请输入用户 '$Username' 的新密码（输入不显示）" -AsSecureString
    $sec2 = Read-Host '请再次输入新密码确认' -AsSecureString
    $b1 = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec1)
    $b2 = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec2)
    try {
        $p1 = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($b1)
        $p2 = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($b2)
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($b1)
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($b2)
    }
    if ($p1 -cne $p2) { Fail '两次输入的密码不一致，已取消。' }
    $Password = $p1
}

if ($Password.Length -lt 6 -or $Password.Length -gt 128) {
    Fail '新密码长度必须在 6-128 之间。'
}

if (-not (Test-ContainerRunning $BackendContainer)) {
    Fail "后端容器 '$BackendContainer' 未运行，可用 -BackendContainer 指定实际容器名。"
}

# 在后端容器内一步完成：按用户名查用户 -> 用应用自身 bcrypt 生成哈希 -> 更新数据库。
# 密码经 stdin 传入，不出现在命令行参数；用 utf-8-sig 解码，自动剥离 PowerShell 5.1
# 管道写入时可能带的 UTF-8 BOM，否则哈希输入会被污染导致登录失败。
$resetCode = @"
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
"@

$prevEnc = $OutputEncoding
$OutputEncoding = New-Object System.Text.UTF8Encoding($false)
try {
    $out = ($Password + "`n") | docker exec -i -e TARGET_USERNAME="$Username" $BackendContainer python3 -c $resetCode
    $dockerExit = $LASTEXITCODE
} finally {
    $OutputEncoding = $prevEnc
}

$marker = ($out | Where-Object { $_ -match '^(OK:|NOT_FOUND)' } | Select-Object -Last 1)
if ($dockerExit -eq 2 -or $marker -eq 'NOT_FOUND') {
    Fail "用户 '$Username' 不存在。可先执行 'list' 查看全部用户名。"
}
if ($dockerExit -ne 0 -or -not $marker) {
    Write-Host ($out -join "`n")
    Fail '在后端容器中重置密码失败。'
}
$role = $marker.Substring(3)

Write-Host ""
Write-Host "密码已重置成功：" -ForegroundColor Green
Write-Host "  用户: $Username  (角色: $role)"
Write-Host "  现在可以使用新密码在登录页登录。"
Write-Host "  建议登录后在「个人设置」中再次修改为自己记得住的密码。" -ForegroundColor Yellow
