@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo.
echo ============================================================
echo   重置演示数据
echo ============================================================
echo.
echo 这个操作会删除当前演示数据库，重新生成 30 天演示数据，
echo 并把 10 条风险恢复成“待认领”。只影响演示数据库和演示源数据。
echo.
echo 重要：请先关闭正在运行的服务窗口（按 Ctrl+C），
echo       否则数据库文件被占用，无法重置。
echo.
pause

if not exist ".venv\Scripts\python.exe" (
  echo [错误] 未找到 .venv\Scripts\python.exe
  echo 请确认这个文件放在 MVP_V0.1 目录下。
  pause
  exit /b 1
)

echo.
echo 正在重建演示数据，请稍候……
".venv\Scripts\python.exe" "scripts\init_demo.py"
if errorlevel 1 (
  echo.
  echo [失败] 演示数据没有重置。
  echo 请确认服务窗口已经关闭，再重新双击本文件。
  pause
  exit /b 1
)

echo.
echo [完成] 演示数据已恢复：10 条风险全部“待认领”。
echo 现在可以双击 start.bat 开始演示。
echo.
pause
