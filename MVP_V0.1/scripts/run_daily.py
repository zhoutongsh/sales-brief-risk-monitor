"""手动触发一次当日批处理（可重复执行，结果幂等）。

用法（在 MVP_V0.1 目录）：
    .venv\\Scripts\\python scripts\\run_daily.py
    .venv\\Scripts\\python scripts\\run_daily.py --date 2026-10-24
    .venv\\Scripts\\python scripts\\run_daily.py --db data\\_daily_test.db

批处理顺序：抽取校验 → 指标快照 → 数据质量 → 风险识别 → 日报 → 周报
→ 发布 → 站内通知 → 超时升级检查。任一步失败会整体回滚，保留上次可用快照。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.batch import run_batch  # noqa: E402
from app.config import DEMO_DATE  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="运行一次销售数据批处理")
    parser.add_argument(
        "--date",
        default=DEMO_DATE.isoformat(),
        help="业务日期，格式 YYYY-MM-DD；默认使用演示数据日 2026-10-24",
    )
    parser.add_argument(
        "--db",
        default=None,
        help="可选：SQLite 数据库路径；默认 data/mvp.db（也可用环境变量 MVP_DB_PATH）",
    )
    parser.add_argument(
        "--source-dir",
        default=None,
        help="可选：CSV 源数据目录；默认 data/source",
    )
    parser.add_argument(
        "--triggered-by",
        default="run_daily",
        help="审计用触发人标识，默认 run_daily",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        as_of = date.fromisoformat(args.date)
    except ValueError:
        print("日期格式不正确，请使用 YYYY-MM-DD，例如 2026-10-24", file=sys.stderr)
        return 2

    result = run_batch(
        as_of,
        trigger_type="manual",
        triggered_by=args.triggered_by,
        db_path=args.db,
        source_dir=args.source_dir,
    )
    summary = {
        "status": result["status"],
        "batch_id": result["batch_id"],
        "as_of": result["as_of"],
        "started_at": result.get("started_at"),
        "finished_at": result.get("finished_at"),
        "duration_seconds": result.get("duration_seconds"),
        "steps": [
            {
                "step": step.get("step"),
                "label": step.get("label"),
                "status": step.get("status"),
                "duration_ms": step.get("duration_ms"),
                "error": step.get("error"),
            }
            for step in result.get("steps", [])
        ],
        "stats": result.get("stats", {}),
        "database": args.db or "data/mvp.db（或环境变量 MVP_DB_PATH）",
        "error": result.get("error"),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
