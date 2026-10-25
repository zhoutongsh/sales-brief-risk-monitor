"""Acceptance regressions for the two P2 fixes in the current batch.

1. At four desktop viewports, the first screen of today's brief must show all
   three conclusions, all six KPI cards and all three risk Top3 rows.  We use
   real viewport screenshots plus getBoundingClientRect(), not a full-page image.
2. A missing source CSV must fail the batch with a specific file/path/metrics
   message, must roll back business tables, and the same message must be visible
   in the shell banner and the data-quality page.
"""
from __future__ import annotations

import base64
import os
import shutil
import sqlite3
import struct
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest

from ui_support import _login, _wait_content, free_port, open_edge, wait_http

PROJECT = Path(__file__).resolve().parents[2]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from app.batch import run_batch  # noqa: E402
from app.config import DEMO_DATE  # noqa: E402

BUSINESS_TABLES = (
    "metric_snapshots", "risks", "risk_evidence", "risk_events",
    "daily_briefs", "weekly_reports", "notifications",
)
EXPECTED_METRICS = ["新增线索数", "有效线索数", "线索有效率", "线索转化率", "线索异常风险"]


def _copy_db(source: Path, target: Path) -> None:
    src = sqlite3.connect(str(source))
    dst = sqlite3.connect(str(target))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def _counts(db_path: Path) -> dict[str, int]:
    conn = sqlite3.connect(str(db_path))
    try:
        tables = BUSINESS_TABLES + ("quality_reports", "batch_runs")
        return {t: int(conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]) for t in tables}
    finally:
        conn.close()


@contextmanager
def _serve(db_path: Path):
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    env = os.environ.copy()
    env["MVP_DB_PATH"] = str(db_path)
    env["PYTHONPATH"] = str(PROJECT)
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
         "--port", str(port), "--log-level", "warning"],
        cwd=str(PROJECT), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        wait_http(base + "/api/health")
        yield base
    finally:
        process.terminate()
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()


@pytest.fixture()
def p2_ui_server(tmp_path: Path, template_db: Path):
    db_path = tmp_path / "p2_ui.db"
    _copy_db(template_db, db_path)
    with _serve(db_path) as base:
        yield base


@dataclass
class FailedSourceEnv:
    base: str
    db_path: Path
    broken_source: Path
    failed: dict
    before: dict[str, int]
    after: dict[str, int]


@pytest.fixture()
def p2_failed_source(tmp_path: Path, template_db: Path, source_dir: Path):
    db_path = tmp_path / "p2_missing.db"
    _copy_db(template_db, db_path)
    broken = tmp_path / "source_missing"
    shutil.copytree(source_dir, broken)
    (broken / "leads.csv").unlink()
    before = _counts(db_path)
    failed = run_batch(
        DEMO_DATE, trigger_type="p2_probe", triggered_by="independent_test",
        db_path=db_path, source_dir=broken,
    )
    after = _counts(db_path)
    with _serve(db_path) as base:
        yield FailedSourceEnv(base, db_path, broken, failed, before, after)


def _layout_probe(base: str, profile: Path) -> dict:
    session = open_edge(profile, width=1280, height=720)
    cdp = session.cdp
    try:
        cdp.command("Page.navigate", {"url": base + "/"})
        time.sleep(1.2)
        assert _login(cdp, base) == 200
        assert cdp.eval("fetch('/api/me',{credentials:'same-origin'}).then(r=>r.status)") == 200
        # A query change forces a full document load after the fetch login.
        cdp.command("Page.navigate", {"url": base + "/?probe=layout#/brief"})

        deadline = time.time() + 15
        counts = {}
        while time.time() < deadline:
            counts = cdp.eval(
                "({c:document.querySelectorAll('.conclusion').length,"
                "k:document.querySelectorAll('.kpi-card').length,"
                "r:document.querySelectorAll('.rm-item').length})"
            )
            if counts and counts.get("c") == 3 and counts.get("k") == 6 and counts.get("r") == 3:
                break
            time.sleep(0.25)
        assert counts == {"c": 3, "k": 6, "r": 3}, counts

        measure = """(()=>{
          const box=e=>{const r=e.getBoundingClientRect();const s=getComputedStyle(e);
            return {top:+r.top.toFixed(1),bottom:+r.bottom.toFixed(1),
                    left:+r.left.toFixed(1),right:+r.right.toFixed(1),
                    h:+r.height.toFixed(1),w:+r.width.toFixed(1),
                    visibility:s.visibility,display:s.display};};
          const q=s=>[...document.querySelectorAll(s)];
          const riskCard=q('#content .brief-grid .card').find(e=>e.innerText.includes('风险 Top3'));
          return {
            iw:innerWidth, ih:innerHeight, sw:document.documentElement.scrollWidth,
            conclusions:q('.conclusion').map(box),
            kpis:q('.kpi-card').map(box),
            risks:q('.rm-item').map(box),
            riskCard:riskCard?box(riskCard):null,
            riskHead:riskCard?(()=>{const e=[...riskCard.querySelectorAll('*')]
              .find(x=>x.textContent.trim()==='风险 Top3');return e?box(e):null;})():null,
            riskFoot:riskCard&&riskCard.querySelector('.risk-mini-foot')
              ? box(riskCard.querySelector('.risk-mini-foot')):null
          };
        })()"""

        result = {"viewports": {}, "screenshots": {}}
        for width, height in [(1280, 720), (1280, 800), (1440, 900), (1600, 900)]:
            cdp.command("Emulation.setDeviceMetricsOverride", {
                "width": width, "height": height, "deviceScaleFactor": 1, "mobile": False,
            })
            time.sleep(0.7)
            info = cdp.eval(measure)
            shot = cdp.command(
                "Page.captureScreenshot",
                {"format": "png", "fromSurface": True, "captureBeyondViewport": False},
                timeout=15,
            )
            image = base64.b64decode(shot["data"])
            png_size = struct.unpack(">II", image[16:24])
            path = profile.parent / f"brief_{width}x{height}.png"
            path.write_bytes(image)
            label = f"{width}x{height}"
            result["viewports"][label] = info
            result["screenshots"][label] = {
                "path": str(path), "bytes": len(image), "png_size": png_size,
            }
        return result
    finally:
        session.close()


def _is_fully_visible(box: dict, width: int, height: int) -> bool:
    return (
        box["visibility"] == "visible"
        and box["display"] != "none"
        and box["h"] > 0
        and box["top"] >= 0
        and box["bottom"] <= height
        and box["left"] >= 0
        and box["right"] <= width
    )


def test_brief_first_screen_blocks_visible_at_four_viewports(p2_ui_server, tmp_path):
    result = _layout_probe(p2_ui_server, tmp_path / "edge_layout")
    for label, info in result["viewports"].items():
        width, height = (int(x) for x in label.split("x"))
        assert info["iw"] == width and info["ih"] == height, (label, info)
        assert info["sw"] <= info["iw"], f"{label} 横向溢出：scrollWidth={info['sw']}"
        assert len(info["conclusions"]) == 3, (label, info)
        assert len(info["kpis"]) == 6, (label, info)
        assert len(info["risks"]) == 3, (label, info)
        for box in info["conclusions"] + info["kpis"] + info["risks"]:
            assert _is_fully_visible(box, width, height), (label, box)
        assert info["riskHead"] and _is_fully_visible(info["riskHead"], width, height), (
            label, info["riskHead"]
        )
        assert info["riskFoot"] and _is_fully_visible(info["riskFoot"], width, height), (
            label, info["riskFoot"]
        )
        screenshot = result["screenshots"][label]
        assert screenshot["bytes"] > 1000
        assert screenshot["png_size"] == (width, height), (label, screenshot)
    # 1280x720 is the tightest case: all three risk rows and the footer must be
    # above the fold; the card's own bottom border is allowed to sit a few px lower.
    assert result["viewports"]["1280x720"]["risks"][-1]["bottom"] < 720


def test_missing_source_fails_rolls_back_and_shows_same_message(p2_failed_source, tmp_path):
    env = p2_failed_source
    failed = env.failed
    assert failed["status"] == "failed", failed
    message = failed["failure"]["message"]
    expected_path = str(env.broken_source / "leads.csv")
    assert "leads.csv" in message
    assert expected_path in message
    for metric in EXPECTED_METRICS:
        assert metric in message
    assert "回滚" in message

    for table in BUSINESS_TABLES:
        assert env.after[table] == env.before[table], (table, env.before[table], env.after[table])
    assert env.after["batch_runs"] == env.before["batch_runs"] + 1
    assert env.after["quality_reports"] == env.before["quality_reports"]

    with httpx.Client(base_url=env.base, timeout=10) as client:
        assert client.post("/api/auth/login", json={"user_id": "u_gm"}).status_code == 200
        quality = client.get("/api/quality")
        assert quality.status_code == 200, quality.text
        payload = quality.json()
    assert payload["status"] == "fail"
    assert payload["failure"]["message"] == message
    assert payload["missing_sources"] == ["leads.csv"]
    assert payload["missing_source_details"][0]["path"] == expected_path
    assert payload["missing_source_details"][0]["metrics"] == EXPECTED_METRICS

    session = open_edge(tmp_path / "edge_missing", width=1280, height=800)
    cdp = session.cdp
    try:
        cdp.command("Page.navigate", {"url": env.base + "/"})
        time.sleep(1.2)
        assert _login(cdp, env.base) == 200
        cdp.command("Page.navigate", {"url": env.base + "/?probe=missing#/brief"})
        deadline = time.time() + 15
        banner = ""
        while time.time() < deadline:
            banner = cdp.eval("document.querySelector('#batchAlert')?.innerText || ''") or ""
            hidden = cdp.eval("document.querySelector('#batchAlert')?.hidden")
            if banner and hidden is False:
                break
            time.sleep(0.25)
        assert message in banner, banner
        assert cdp.eval("document.querySelector('#dataPill')?.innerText") == "批次失败"

        cdp.command("Page.navigate", {"url": env.base + "/#/quality"})
        quality_text = ""
        deadline = time.time() + 15
        while time.time() < deadline:
            quality_text = cdp.eval("document.querySelector('#content')?.innerText || ''") or ""
            if "数据质量" in quality_text and "leads.csv" in quality_text and message in quality_text:
                break
            time.sleep(0.25)
        assert message in quality_text, quality_text[:500]
        assert expected_path in quality_text
        for metric in EXPECTED_METRICS:
            assert metric in quality_text
        assert "批次已停止并回滚" in quality_text

        shot = cdp.command(
            "Page.captureScreenshot",
            {"format": "png", "fromSurface": True, "captureBeyondViewport": False},
            timeout=15,
        )
        image = base64.b64decode(shot["data"])
        assert struct.unpack(">II", image[16:24]) == (1280, 800)
        out = tmp_path / "quality_failure_1280x800.png"
        out.write_bytes(image)
        assert out.stat().st_size > 1000
    finally:
        session.close()
