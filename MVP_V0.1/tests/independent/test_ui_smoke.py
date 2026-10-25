"""PC-only Edge headless UI smoke and responsive checks (1280/1440/1600)."""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from ui_support import EDGE, free_port, rules_threshold_probe, smoke_probe, wait_http

PROJECT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(not EDGE.exists(), reason="Microsoft Edge not installed")


def _copy_db(source: Path, target: Path) -> None:
    src = sqlite3.connect(str(source))
    dst = sqlite3.connect(str(target))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


@pytest.fixture()
def ui_server(tmp_path: Path, template_db: Path):
    db_path = tmp_path / "ui.db"
    _copy_db(template_db, db_path)
    port = free_port()
    env = os.environ.copy()
    env["MVP_DB_PATH"] = str(db_path)
    env["PYTHONPATH"] = str(PROJECT)
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
         "--port", str(port), "--log-level", "warning"],
        cwd=str(PROJECT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        wait_http(base + "/api/health")
        yield base
    finally:
        process.terminate()
        try:
            output, _ = process.communicate(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
            output, _ = process.communicate()
        if process.returncode not in (0, 1, -15):
            print(output)


def test_pc_pages_login_no_console_errors_and_no_horizontal_overflow(ui_server, tmp_path):
    result = smoke_probe(ui_server, tmp_path / "edge_smoke")
    assert result["login_cards"] == 4
    assert result["login_status"] == 200
    for page in ["brief", "risks", "weekly", "rules", "exports"]:
        info = result["pages"][page]
        assert info["length"] > 200, (page, info)
        assert "正在加载" not in info["first"], (page, info)
        assert info["errors"] == 0, (page, result["errors"][page])
    assert result["export_dialog"]["open"] is True
    assert "导出" in result["export_dialog"]["text"] or "确认" in result["export_dialog"]["text"]
    for width in ["1280", "1440", "1600"]:
        info = result["widths"][width]
        assert info["horizontal"] is False, (width, info)
        assert info["scroll_width"] <= info["inner_width"], (width, info)


def test_defect_rules_ui_hardcoded_threshold_badges(ui_server, tmp_path):
    """P3: threshold sentence uses runtime params, the level badges stay hardcoded."""
    text = rules_threshold_probe(ui_server, tmp_path / "edge_rules")
    assert "缺口 ≥ 2pp" in text, text
    assert "≥3pp" not in text, (
        "黄色阈值已改为 2pp，但级别徽标仍显示 ≥3pp：%s" % text
    )
