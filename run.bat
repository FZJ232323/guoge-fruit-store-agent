@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHON_CMD="

py -3 -c "import openpyxl" >nul 2>nul
if not errorlevel 1 set "PYTHON_CMD=py -3"

if not defined PYTHON_CMD (
  python -c "import openpyxl" >nul 2>nul
  if not errorlevel 1 set "PYTHON_CMD=python"
)

if not defined PYTHON_CMD (
  set "BUNDLED_PYTHON=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
  if exist "%BUNDLED_PYTHON%" set "PYTHON_CMD="%BUNDLED_PYTHON%""
)

if not defined PYTHON_CMD (
  echo.
  echo 未找到可用的 Python 环境。
  echo 请先安装 Python 3.10+，然后执行：pip install -r requirements.txt
  echo.
  pause
  exit /b 1
)

echo.
echo 正在启动果知 · 水果店智能运营助手...
echo 浏览器会自动打开；关闭本窗口或按 Ctrl+C 停止服务。
echo.
%PYTHON_CMD% app.py

if errorlevel 1 pause
