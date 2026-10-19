$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$env:PYTHONUTF8 = "1"

$python = $null
$commands = @(
    @("py", "-3"),
    @("python", ""),
    @("$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe", "")
)

foreach ($candidate in $commands) {
    $exe = $candidate[0]
    $prefix = @()
    if ($candidate[1]) { $prefix = @($candidate[1]) }
    try {
        & $exe @prefix -c "import openpyxl" 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) {
            $python = $exe
            $pythonPrefix = $prefix
            break
        }
    } catch {
        continue
    }
}

if (-not $python) {
    Write-Host ""
    Write-Host "未找到可用的 Python 环境。" -ForegroundColor Yellow
    Write-Host "请先安装 Python 3.10+，然后执行：pip install -r requirements.txt"
    exit 1
}

Write-Host ""
Write-Host "正在启动果知 · 水果店智能运营助手..." -ForegroundColor Green
Write-Host "浏览器会自动打开；按 Ctrl+C 停止服务。"
Write-Host ""
& $python @pythonPrefix app.py
