<#
.SYNOPSIS
    构建 DocBabel 离线 Docker Compose 安装包（镜像 + 源码 + BabelDOC 离线资产 + 脚本/文档）。
.DESCRIPTION
    流程：生成经 SHA3 校验的离线资产 zip -> 构建内置资产的后端离线镜像
          -> 导出 4 个镜像 tar.gz -> git archive 源码 -> 组装包目录 -> SHA256 -> zip。
    必须在 Windows + Docker Desktop 环境运行；依赖 Git for Windows 自带的 gzip/sed。
    产物：dist/DocBabel-offline-<短commit>.zip
.PARAMETER RepoRoot
    仓库根目录，默认取 git rev-parse --show-toplevel。
.PARAMETER Profile
    离线资产预检档位 full/core/minimal，默认 full（资产包始终按 full 生成）。
.PARAMETER SkipZip
    只组装目录、不生成最终 zip（调试用）。
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\.trae\skills\docbabel-offline-package\scripts\build-offline-package.ps1
#>
param(
    [string]$RepoRoot,
    [ValidateSet("full", "core", "minimal")]
    [string]$Profile = "full",
    [switch]$SkipZip
)

$ErrorActionPreference = "Stop"

function Assert-LastExit([string]$Message) {
    if ($LASTEXITCODE -ne 0) { throw $Message }
}

function Write-Step([string]$Text) { Write-Host "`n==== $Text ====" -ForegroundColor Cyan }

# ── 1. 定位仓库与技能目录 ────────────────────────────────────────────
if (-not $RepoRoot) {
    $RepoRoot = (git rev-parse --show-toplevel 2>$null)
    Assert-LastExit "当前目录不在 git 仓库内，请用 -RepoRoot 指定仓库根目录"
    $RepoRoot = $RepoRoot.Trim()
}
$RepoRoot = (Resolve-Path $RepoRoot).Path
$SkillDir = Split-Path -Parent $PSScriptRoot
$AssetsDir = Join-Path $SkillDir "assets"

# ── 2. 前置检查 ──────────────────────────────────────────────────────
docker info | Out-Null
Assert-LastExit "Docker 不可用，请先启动 Docker Desktop"

$gzip = "C:\Program Files\Git\usr\bin\gzip.exe"
if (-not (Test-Path $gzip)) { throw "未找到 $gzip，请安装 Git for Windows（导出镜像需要 gzip）" }

$backendPy = Join-Path $RepoRoot "backend\.venv\Scripts\python.exe"
$Python = if (Test-Path $backendPy) { $backendPy } else { "python" }

# ── 3. 版本与目录 ────────────────────────────────────────────────────
$Commit = (git -C $RepoRoot rev-parse --short HEAD).Trim()
$BuildDate = Get-Date -Format "yyyy-MM-dd"
$Dist = Join-Path $RepoRoot "dist"
$Stage = Join-Path $Dist "offline-build"
$PkgName = "DocBabel-offline-$Commit"
$Pkg = Join-Path $Dist $PkgName
$AssetZip = Join-Path $Stage "offline_assets.zip"

Write-Host "仓库:     $RepoRoot"
Write-Host "版本:     $Commit ($BuildDate), 资产档位: $Profile"
Write-Host "Python:   $Python"

foreach ($d in @($Stage, "$Pkg\images", "$Pkg\src", "$Pkg\config")) {
    New-Item -ItemType Directory -Force $d | Out-Null
}

# ── 4. 生成经 SHA3 校验的离线资产包 ──────────────────────────────────
Write-Step "1/7 生成 BabelDOC 离线资产（逐个 SHA3 校验，约 1-3 分钟）"
Push-Location (Join-Path $RepoRoot "backend")
$env:PYTHONUTF8 = "1"
$assetOut = & $Python -X utf8 -c @"
from pathlib import Path
from babeldoc.assets.assets import generate_all_assets_file_list, get_offline_assets_tag
from app.services.babeldoc_assets import _write_offline_assets_package
tag = get_offline_assets_tag(generate_all_assets_file_list())
_write_offline_assets_package(Path(r'$AssetZip'))
print('ASSET_TAG=' + tag)
print('ASSET_ZIP_BYTES=' + str(Path(r'$AssetZip').stat().st_size))
"@
Pop-Location
Assert-LastExit "离线资产生成失败（确认 $Python 已安装后端依赖且资产缓存完整，可先在联网环境预热）"
$assetOut | ForEach-Object { Write-Host $_ }
$AssetTag = ([regex]::Match(($assetOut -join "`n"), 'ASSET_TAG=([0-9a-f]+)')).Groups[1].Value
if (-not $AssetTag) { throw "未能解析资产标签" }

# ── 5. 构建内置资产的后端离线镜像 ────────────────────────────────────
# 固定 :base 标签为“不含资产的普通后端镜像”：离线镜像始终 FROM :base，
# 避免 latest 已指向离线镜像时重复烤入资产造成层叠加（体积膨胀）。
# 从源码构建，层全部命中缓存时仅需数十秒，不会移动/依赖 latest 标签。
Write-Step "2/7 确认基础镜像 :base（命中缓存时秒级完成）"
docker build -t ghcr.io/ccsert/babeldoc-backend:base (Join-Path $RepoRoot "backend")
Assert-LastExit "基础后端镜像构建失败（首次需联网拉取依赖，可先执行 docker compose build）"

Write-Host "  -> 叠加离线资产层"
$offlineDockerfile = @'
FROM ghcr.io/ccsert/babeldoc-backend:base
COPY offline_assets.zip /tmp/offline_assets.zip
RUN python3 -c "import zipfile,os; os.makedirs('/root/.cache/babeldoc', exist_ok=True); zipfile.ZipFile('/tmp/offline_assets.zip').extractall('/root/.cache/babeldoc')" \
    && rm /tmp/offline_assets.zip
ENV BABELDOC_OFFLINE_MODE=true
ENV BABELDOC_OFFLINE_ASSET_PROFILE=__PROFILE__
ENV BABELDOC_PRECHECK_ASSETS_ON_STARTUP=true
'@ -replace "__PROFILE__", $Profile
[IO.File]::WriteAllText((Join-Path $Stage "Dockerfile"), $offlineDockerfile.Replace("`r`n", "`n"), (New-Object System.Text.UTF8Encoding($false)))
docker build -t "ghcr.io/ccsert/babeldoc-backend:$Commit-offline" -t "ghcr.io/ccsert/babeldoc-backend:latest" $Stage
Assert-LastExit "离线后端镜像构建失败"

# ── 6. 导出 4 个镜像（PowerShell save + Git gzip；禁止 bash 管道）────
Write-Step "3/7 导出镜像 tar.gz（后端约 1GB，耗时数分钟）"
function Save-Image([string]$Name, [string[]]$Refs) {
    $tar = Join-Path $Pkg "images\$Name.tar"
    $gz = "$tar.gz"
    if (Test-Path $gz) { Remove-Item $gz -Force }
    Write-Host "  -> $Name"
    docker save -o $tar @Refs
    Assert-LastExit "docker save 失败: $Name"
    & $gzip -1 $tar
    Assert-LastExit "gzip 压缩失败: $Name"
}
Save-Image "babeldoc-backend" @("ghcr.io/ccsert/babeldoc-backend:latest", "ghcr.io/ccsert/babeldoc-backend:$Commit-offline")
Save-Image "babeldoc-frontend" @("ghcr.io/ccsert/babeldoc-frontend:latest")
Save-Image "postgres" @("postgres:16-alpine")
Save-Image "redis" @("redis:7-alpine")

# ── 7. 导出干净源码快照 ──────────────────────────────────────────────
Write-Step "4/7 git archive 源码"
$SrcZip = Join-Path $Stage "src.zip"
git -C $RepoRoot archive --format=zip -o $SrcZip HEAD
Assert-LastExit "git archive 失败（确认工作区已提交）"
if (Test-Path "$Pkg\src") { Remove-Item "$Pkg\src" -Recurse -Force }
Expand-Archive -Path $SrcZip -DestinationPath "$Pkg\src" -Force

# ── 8. 组装包内文件（模板来自技能 assets/）──────────────────────────
Write-Step "5/7 组装 compose / 安装脚本 / 配置 / 文档"
function Write-Lf([string]$Path, [string]$Text) {
    [IO.File]::WriteAllText($Path, $Text.Replace("`r`n", "`n"), (New-Object System.Text.UTF8Encoding($false)))
}
$compose = [IO.File]::ReadAllText((Join-Path $AssetsDir "docker-compose.yml")).Replace("`r`n", "`n").Replace("BABELDOC_OFFLINE_ASSET_PROFILE: full", "BABELDOC_OFFLINE_ASSET_PROFILE: $Profile")
Write-Lf (Join-Path $Pkg "docker-compose.yml") $compose
Write-Lf (Join-Path $Pkg "install.sh") ([IO.File]::ReadAllText((Join-Path $AssetsDir "install.sh")))
# install.ps1 必须带 UTF-8 BOM，否则 Windows PowerShell 5.1 按 GBK 误读中文
[IO.File]::WriteAllText((Join-Path $Pkg "install.ps1"), ([IO.File]::ReadAllText((Join-Path $AssetsDir "install.ps1")).Replace("`r`n", "`n")), (New-Object System.Text.UTF8Encoding($true)))
Copy-Item (Join-Path $AssetsDir "env.example") (Join-Path $Pkg "config\.env.example") -Force

$readme = [IO.File]::ReadAllText((Join-Path $AssetsDir "README.template.md")).
    Replace("__VERSION__", $Commit).Replace("__BUILD_DATE__", $BuildDate).Replace("__ASSET_TAG__", $AssetTag.Substring(0, 12) + "...")
[IO.File]::WriteAllText((Join-Path $Pkg "README.md"), $readme, (New-Object System.Text.UTF8Encoding($false)))

if (Test-Path "$Pkg\docs") { Remove-Item "$Pkg\docs" -Recurse -Force }
Copy-Item (Join-Path $RepoRoot "docs") $Pkg -Recurse -Force

$versionText = @"
package: DocBabel-offline
build_date: $BuildDate
source_commit: $Commit
engine: Host003/BabelDOC fork (see backend/pyproject.toml for pinned commit)
offline_assets_tag: $AssetTag
offline_asset_profile: $Profile
images:
  - ghcr.io/ccsert/babeldoc-backend:latest (tag $Commit-offline, 内置 $Profile 离线资产)
  - ghcr.io/ccsert/babeldoc-frontend:latest
  - postgres:16-alpine
  - redis:7-alpine
"@
Write-Lf (Join-Path $Pkg "VERSION") $versionText

# ── 9. SHA256SUMS ────────────────────────────────────────────────────
Write-Step "6/7 计算 SHA256 校验"
$sums = Get-ChildItem "$Pkg\images\*.tar.gz" | Sort-Object Name | ForEach-Object {
    "$((Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower())  images/$($_.Name)"
}
Write-Lf (Join-Path $Pkg "SHA256SUMS.txt") ($sums -join "`n")
$sums | ForEach-Object { "  " + $_.Substring(0, 16) + "..." + $_.Substring($_.IndexOf("  ")) }

# ── 10. 最终 zip ─────────────────────────────────────────────────────
if (-not $SkipZip) {
    Write-Step "7/7 压缩最终安装包（NoCompression，tar.gz 已压缩）"
    $ZipPath = "$Pkg.zip"
    if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force }
    Compress-Archive -Path $Pkg -DestinationPath $ZipPath -CompressionLevel NoCompression
    $mb = [math]::Round((Get-Item $ZipPath).Length / 1MB, 1)
    Write-Host "`n完成: $ZipPath ($mb MB)" -ForegroundColor Green
} else {
    Write-Host "`n完成（未压缩）: $Pkg" -ForegroundColor Green
}

Write-Host @"
后续必做验证（见 SKILL.md）：
  1) 容器内资产哈希校验（期望 182/182）
  2) 独立项目名 + 备用端口 docker compose up，检查 /api/health 与注册首个管理员
  3) docker compose down -v 清理
"@ -ForegroundColor Yellow
