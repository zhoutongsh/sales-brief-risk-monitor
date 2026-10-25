# -*- coding: utf-8 -*-
"""「日常销售数据动态监控」一键启动器（自包含 exe）

- 双击运行：首次自动建库并生成 30 天演示数据，然后启动本地服务并打开浏览器
- 若服务已在运行，直接打开浏览器，不重复启动
- 关闭本窗口（或 Ctrl+C）即停止服务
- app/ 代码、web/ 页面、data/ 数据都从 exe 所在目录读取，可随时更新
"""
import importlib
import json
import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

HOST = "127.0.0.1"
PORT = int(os.environ.get("MVP_PORT", "8000"))
URL = f"http://{HOST}:{PORT}"

# exe 所在目录即 MVP 项目根目录（app/、web/、data/ 都在这里）
BASE = os.path.dirname(os.path.abspath(sys.argv[0]))
os.chdir(BASE)
sys.path.insert(0, BASE)

# 单文件 exe 会把代码和网页解压到临时目录；数据库和演示源数据放在 exe 旁边。
BUNDLE = Path(getattr(sys, "_MEIPASS", BASE))
os.environ.setdefault("MVP_WEB_DIR", str(BUNDLE / "web"))
os.environ.setdefault("MVP_DATA_DIR", str(Path(BASE) / "data"))
os.environ.setdefault("MVP_DB_PATH", str(Path(BASE) / "data" / "mvp.db"))


def port_open(host, port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex((host, port)) == 0


def open_browser_later(delay=2.5):
    if os.environ.get("MVP_NO_BROWSER") == "1":
        return

    def _open():
        time.sleep(delay)
        webbrowser.open(URL)
    threading.Thread(target=_open, daemon=True).start()


def init_demo():
    """首次启动：删库 → 生成演示 CSV → 建表 → 跑批。等价于 scripts/init_demo.py。"""
    seed = importlib.import_module("app.seed")
    batch = importlib.import_module("app.batch")
    config = importlib.import_module("app.config")
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(config.DB_PATH) + suffix)
        if p.exists():
            p.unlink()
    counts = seed.generate_source_files()
    result = batch.run_batch(config.DEMO_DATE, trigger_type="init", triggered_by="launcher")
    print(json.dumps({
        "status": result.get("status"),
        "batch_id": result.get("batch_id"),
        "as_of": result.get("as_of"),
        "source_rows": counts,
        "database": str(config.DB_PATH),
        "error": result.get("error"),
    }, ensure_ascii=False, indent=2))
    return result.get("status") == "success"


def main():
    print("=" * 56)
    print("  日常销售数据动态监控 MVP V0.1")
    print("  演示环境，不是生产系统；登录不是生产认证。")
    print("=" * 56)
    print(f"  访问地址：{URL}")
    print(f"  接口文档：http://{HOST}:{PORT}/docs")
    print("  演示账号：登录页直接点击，无需密码")
    print("  关闭本窗口即停止服务（数据保存在 data/ 目录）")
    print("=" * 56)

    if port_open(HOST, PORT):
        print("检测到服务已在运行，直接打开页面…")
        if os.environ.get("MVP_NO_BROWSER") != "1":
            webbrowser.open(URL)
        time.sleep(3)
        return

    db_path = Path(BASE) / "data" / "mvp.db"
    if not db_path.exists():
        print("[首次启动] 未发现数据库，正在建库、生成 30 天演示数据并跑批…")
        try:
            ok = init_demo()
        except Exception as exc:  # noqa: BLE001
            print(f"[错误] 初始化失败：{exc}")
            input("按回车键退出…")
            return
        if not ok:
            print("[错误] 初始化未成功，请查看上方日志。")
            input("按回车键退出…")
            return
        print("[首次启动] 初始化完成。")

    import uvicorn
    open_browser_later()
    uvicorn.run("app.main:app", host=HOST, port=PORT, log_level="info")


if __name__ == "__main__":
    main()
