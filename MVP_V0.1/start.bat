@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"

echo.
echo ============================================================
echo   日常销售数据动态监控 MVP V0.1
echo   演示环境，不是生产系统；登录不是生产认证。
echo ============================================================
echo.

if not exist ".venv\Scripts\python.exe" (
  echo [错误] 未找到 .venv\Scripts\python.exe
  echo 请在本目录创建虚拟环境并安装 requirements.txt 中的依赖。
  pause
  exit /b 1
)

if not exist "data\mvp.db" (
  echo [首次启动] 未发现数据库，正在建库、导入演示数据并跑批……
  ".venv\Scripts\python.exe" "scripts\init_demo.py"
  if errorlevel 1 (
    echo.
    echo [错误] 初始化失败，请查看上方日志。
    pause
    exit /b 1
  )
  echo [首次启动] 初始化完成。
  echo.
)

echo 访问地址: http://127.0.0.1:8000
echo 接口文档: http://127.0.0.1:8000/docs
echo 演示账号: 登录页直接点击，无需密码
echo 停止服务: 按 Ctrl+C
echo.

".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000

if errorlevel 1 (
  echo.
  echo [错误] 服务启动失败。常见原因：8000 端口已被占用。
  pause
)

endlocal
