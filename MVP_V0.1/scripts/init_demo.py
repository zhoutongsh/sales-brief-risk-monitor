"""从零初始化演示环境：删库 → 生成源 CSV → 建表 → 跑批 → 输出摘要。

用法（在 MVP_V0.1 目录）：
    .venv\\Scripts\\python scripts\\init_demo.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.batch import run_batch  # noqa: E402
from app.config import DB_PATH, DEMO_DATE  # noqa: E402
from app.db import connect  # noqa: E402
from app.seed import generate_source_files  # noqa: E402


def main() -> int:
    started = time.perf_counter()
    for suffix in ("", "-wal", "-shm"):
        path = Path(str(DB_PATH) + suffix)
        if path.exists():
            path.unlink()
    t0 = time.perf_counter()
    counts = generate_source_files()
    source_seconds = time.perf_counter() - t0
    t1 = time.perf_counter()
    result = run_batch(DEMO_DATE, trigger_type="init", triggered_by="init_demo")
    batch_seconds = time.perf_counter() - t1
    total = time.perf_counter() - started
    conn = connect(DB_PATH)
    try:
        stats = {
            "orgs": conn.execute("SELECT COUNT(*) FROM orgs").fetchone()[0],
            "users": conn.execute("SELECT COUNT(*) FROM users").fetchone()[0],
            "risks": conn.execute("SELECT COUNT(*) FROM risks").fetchone()[0],
            "daily_briefs": conn.execute("SELECT COUNT(*) FROM daily_briefs").fetchone()[0],
            "weekly_reports": conn.execute("SELECT COUNT(*) FROM weekly_reports").fetchone()[0],
            "metric_snapshots": conn.execute("SELECT COUNT(*) FROM metric_snapshots").fetchone()[0],
            "notifications": conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0],
        }
    finally:
        conn.close()
    report = {
        "status": result["status"],
        "batch_id": result["batch_id"],
        "as_of": result["as_of"],
        "source_generation_seconds": round(source_seconds, 2),
        "batch_seconds": round(batch_seconds, 2),
        "total_seconds": round(total, 2),
        "source_rows": counts,
        "db_counts": stats,
        "database": str(DB_PATH),
        "error": result.get("error"),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
