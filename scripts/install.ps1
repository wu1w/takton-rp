# 念匣 · 源码一键安装（Windows）
# 用法（PowerShell 一行）：
#   irm https://raw.githubusercontent.com/wu1w/takton-rp/main/scripts/install.ps1 | iex
#
# 做什么：克隆源码 → core 虚拟环境 → 前端构建 → 起本地服务 →
#         下载 llama.cpp CPU 后端 + Qwen3.5-2B 模型（断点续传，中断可重跑）→ 打开浏览器
# 不需要 Rust；装完是纯本地网页版（http://127.0.0.1:7420），数据在 文档/念匣。

$ErrorActionPreference = "Stop"
$Repo = "https://github.com/wu1w/takton-rp.git"
$Dir  = Join-Path $env:USERPROFILE "takton-rp"
$Api  = "http://127.0.0.1:7420"

function Need($cmd, $hint) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        throw "缺少 $cmd —— 请先安装：$hint"
    }
}

Write-Host "== 念匣源码安装 ==" -ForegroundColor Cyan
Need git    "https://git-scm.com/download/win"
Need python "https://www.python.org/downloads/ （3.11+，安装时勾选 Add python.exe to PATH）"
Need npm    "https://nodejs.org/ （LTS 版）"

# 1. 源码
if (Test-Path $Dir) {
    Write-Host "[1/6] 已有目录，拉取最新…"
    git -C $Dir pull --ff-only
} else {
    Write-Host "[1/6] 克隆源码…"
    git clone $Repo $Dir
}

# 2. core 依赖
Write-Host "[2/6] 准备 Python 环境…"
$VenvPy = Join-Path $Dir "core/.venv/Scripts/python.exe"
if (-not (Test-Path $VenvPy)) { python -m venv (Join-Path $Dir "core/.venv") }
& $VenvPy -m pip install -q --upgrade pip
& $VenvPy -m pip install -q -e (Join-Path $Dir "core")

# 3. 前端
Write-Host "[3/6] 构建前端…"
Push-Location (Join-Path $Dir "shells/desktop")
npm ci --silent | Out-Null
npm run build
Pop-Location

# 4. 起 core（已在跑就复用）
Write-Host "[4/6] 启动本地核心…"
$up = $false
try { $null = Invoke-RestMethod "$Api/v1/health" -TimeoutSec 2; $up = $true } catch {}
if (-not $up) {
    $env:PYTHONPATH = "src"
    Start-Process -WindowStyle Hidden $VenvPy -ArgumentList "-m","nianxia_core" -WorkingDirectory (Join-Path $Dir "core")
    for ($i = 0; $i -lt 30 -and -not $up; $i++) {
        Start-Sleep 1
        try { $null = Invoke-RestMethod "$Api/v1/health" -TimeoutSec 2; $up = $true } catch {}
    }
}
if (-not $up) { throw "core 启动失败，请手动运行：cd $Dir/core; `$env:PYTHONPATH='src'; .venv/Scripts/python -m nianxia_core" }

# 5. 下载后端与模型（断点续传，重复执行安全）
Write-Host "[5/6] 下载 llama.cpp CPU 后端（约 100MB）…"
$bs = Invoke-RestMethod "$Api/v1/engine/l0/backend/status"
if ($bs.installed -notcontains "cpu") {
    $null = Invoke-RestMethod -Method Post "$Api/v1/engine/l0/backend/cpu"
    do { Start-Sleep 3; $bs = Invoke-RestMethod "$Api/v1/engine/l0/backend/status" } while ($bs.installed -notcontains "cpu" -and $bs.status -ne "error")
    if ($bs.status -eq "error") { throw "后端下载失败：$($bs.error)" }
}

Write-Host "[6/6] 下载本地模型 Qwen3.5-2B（约 1.6GB + 视觉组件 0.7GB，最久的一步）…"
$ModelFiles = @(
    "https://huggingface.co/bartowski/Qwen_Qwen3.5-2B-GGUF/resolve/main/Qwen_Qwen3.5-2B-Q5_K_M.gguf",
    "https://huggingface.co/bartowski/Qwen_Qwen3.5-2B-GGUF/resolve/main/mmproj-Qwen_Qwen3.5-2B-f16.gguf"
)
foreach ($url in $ModelFiles) {
    $st = Invoke-RestMethod "$Api/v1/engine/l0/download/status"
    $null = Invoke-RestMethod -Method Post "$Api/v1/engine/l0/download" -ContentType "application/json" -Body (@{ url = $url } | ConvertTo-Json)
    do {
        Start-Sleep 5
        $st = Invoke-RestMethod "$Api/v1/engine/l0/download/status"
        if ($st.total_bytes -gt 0) {
            $pct = [math]::Floor(100.0 * $st.done_bytes / $st.total_bytes)
            Write-Progress -Activity "下载模型 $($st.filename)" -Status "$pct%" -PercentComplete $pct
        }
    } while ($st.status -eq "downloading")
    Write-Progress -Activity "下载模型" -Completed
    if ($st.status -ne "done") { throw "模型下载失败：$($st.error)（网络问题可重跑本脚本，支持续传）" }
}

Write-Host ""
Write-Host "装好啦！念匣已在本地运行：" -ForegroundColor Green
Write-Host "  打开 http://127.0.0.1:7420 开始聊天"
Write-Host "  数据目录：文档/念匣"
Write-Host "  停止：关闭核心进程；下次用：cd $Dir/core; `$env:PYTHONPATH='src'; .venv/Scripts/python -m nianxia_core"
Start-Process $Api
