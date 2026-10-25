"""批处理：抽取 → 指标 → 数据质量 → 风险 → 日报/周报 → 发布 → 通知 → 升级检查。

事务策略：
- batch_runs 运行记录先在主事务外创建；
- 业务数据全部在同一事务内写入，任一步失败整体回滚，保留上一次可用快照；
- 失败状态与步骤耗时在主事务外回写到 batch_runs，便于追溯；
- 同日重跑指标快照 upsert、风险按对象+规则复用、通知按 dedupe_key 去重。
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from datetime import date, datetime
from pathlib import Path

from .brief import (
    patch_brief_batch_info,
    planned_daily_published_at,
    publish_daily_briefs,
    save_daily_briefs,
    save_weekly_reports,
)
from .config import DB_PATH, DEMO_DATE, now_bj, now_iso
from .db import connect, init_db, transaction
from .ingest import IngestError, extract_all
from .metrics import store_metric_snapshots
from .notifications import create_notification, notify_risk_created
from .quality import (
    build_extract_failure_report,
    build_quality_report,
    finalize_quality_report,
    save_quality_report,
)
from .risk_service import check_overdue_escalations
from .rules import evaluate_rules
from .scope import demo_users


def _new_batch_id(as_of: date) -> str:
    return f"B-{as_of.strftime('%Y%m%d')}-{now_bj().strftime('%H%M%S')}-{uuid.uuid4().hex[:4].upper()}"


class BatchRunner:
    def __init__(self, as_of: date, batch_id: str, started_at: str, conn: sqlite3.Connection):
        self.as_of = as_of
        self.batch_id = batch_id
        self.started_at = started_at
        self.conn = conn
        self.steps: list[dict] = []
        self.stats: dict = {}

    def step(self, key: str, label: str, func):
        started = now_bj()
        t0 = time.perf_counter()
        entry = {
            "step": key, "label": label, "status": "running",
            "started_at": started.isoformat(timespec="seconds"),
            "finished_at": None, "duration_ms": None, "stats": {},
        }
        try:
            result = func()
            entry["status"] = "success"
            entry["stats"] = result if isinstance(result, (dict, list, int, float, str)) else {}
            return result
        except Exception as exc:
            entry["status"] = "failed"
            entry["error"] = str(exc)
            raise
        finally:
            finished = now_bj()
            entry["finished_at"] = finished.isoformat(timespec="seconds")
            entry["duration_ms"] = int((time.perf_counter() - t0) * 1000)
            self.steps.append(entry)


def _publish_weekly(conn: sqlite3.Connection, batch_id: str) -> int:
    """发布周报：published_at 保持周报自身计划时间，不被实际批处理时间覆盖。"""
    rows = conn.execute(
        "SELECT id, payload_json, published_at FROM weekly_reports WHERE batch_id=?", (batch_id,)
    ).fetchall()
    for row in rows:
        payload = json.loads(row["payload_json"])
        published = payload.get("published_at") or row["published_at"]
        if not published:
            continue
        payload["published_at"] = published
        conn.execute(
            "UPDATE weekly_reports SET published_at=?, payload_json=? WHERE id=?",
            (published, json.dumps(payload, ensure_ascii=False), row["id"]),
        )
    return len(rows)


def _notify_after_publish(conn: sqlite3.Connection, as_of: date, batch_id: str) -> dict:
    count = 0
    # 只通知本次批次“新建”的风险。同日重跑时旧风险沿用原 batch_id，不会
    # 因为负责人变化而给新责任人补发“新风险”通知，保证通知幂等。
    risks = conn.execute(
        "SELECT * FROM risks WHERE as_of=? AND batch_id=?", (as_of.isoformat(), batch_id)
    ).fetchall()
    for row in risks:
        count += notify_risk_created(conn, dict(row), batch_id)
    brief_count = 0
    for user in demo_users(conn):
        inserted = create_notification(
            conn, user["user_id"], "brief", "今日简报已发布",
            f"{as_of.month} 月 {as_of.day} 日经营简报已更新，点击查看 3 条结论、6 张指标卡与风险 Top3。",
            "#/brief", None, batch_id, f"daily_brief:{as_of.isoformat()}:{user['user_id']}",
        )
        brief_count += int(inserted)
    return {"risk_notifications": count, "brief_notifications": brief_count,
            "total": count + brief_count}


def run_batch(
    as_of: date = DEMO_DATE, trigger_type: str = "manual", triggered_by: str | None = None,
    db_path: Path | str | None = None, source_dir: Path | str | None = None,
) -> dict:
    db_path = Path(db_path) if db_path else DB_PATH
    init_db(db_path)
    source_path = Path(source_dir) if source_dir else None
    batch_id = _new_batch_id(as_of)
    started = now_bj()
    started_iso = started.isoformat(timespec="seconds")
    conn = connect(db_path)
    conn.execute(
        """INSERT INTO batch_runs
           (batch_id, as_of, status, trigger_type, triggered_by, started_at, finished_at,
            steps_json, stats_json, error)
           VALUES (?, ?, 'running', ?, ?, ?, NULL, '[]', '{}', NULL)""",
        (batch_id, as_of.isoformat(), trigger_type, triggered_by, started_iso),
    )
    runner = BatchRunner(as_of, batch_id, started_iso, conn)
    stats: dict = {"as_of": as_of.isoformat(), "batch_id": batch_id}
    try:
        with transaction(conn):
            ingest_stats = runner.step(
                "extract", "抽取与校验",
                lambda: extract_all(conn, as_of, source_path),
            )
            stats["ingest"] = ingest_stats
            metric_count = runner.step(
                "metrics", "指标快照",
                lambda: {"snapshots": store_metric_snapshots(conn, batch_id, as_of)},
            )
            stats["metrics"] = metric_count

            def quality_step():
                report = build_quality_report(conn, as_of, batch_id, started_iso, ingest_stats)
                save_quality_report(conn, report)
                if report["status"] == "fail":
                    raise RuntimeError("数据质量检查未通过，批次停止发布")
                return {"status": report["status"], "score": report["score"],
                        "warnings": report["summary"]["warnings"],
                        "affected_metrics": len(report["affected_metrics"])}
            quality_stats = runner.step("quality", "数据质量", quality_step)
            stats["quality"] = quality_stats

            risk_stats = runner.step(
                "risks", "风险识别",
                lambda: evaluate_rules(conn, as_of, batch_id),
            )
            stats["risks"] = risk_stats

            daily_count = runner.step(
                "daily", "生成日报",
                lambda: {"briefs": save_daily_briefs(conn, as_of, batch_id)},
            )
            stats["daily"] = daily_count
            weekly_count = runner.step(
                "weekly", "生成周报",
                lambda: {"reports": save_weekly_reports(conn, as_of, batch_id)},
            )
            stats["weekly"] = weekly_count

            def publish_step():
                # 对外展示“计划发布时间”；实际生成时间保存在 generated_at/批次记录中。
                published_at = planned_daily_published_at(as_of)
                daily = publish_daily_briefs(conn, as_of, published_at)
                weekly = _publish_weekly(conn, batch_id)
                return {
                    "published_at": published_at,
                    "daily_briefs": daily,
                    "weekly_reports": weekly,
                }
            publish_stats = runner.step("publish", "发布", publish_step)
            stats["publish"] = publish_stats

            notify_stats = runner.step(
                "notify", "站内通知",
                lambda: _notify_after_publish(conn, as_of, batch_id),
            )
            stats["notifications"] = notify_stats

            escalation_count = runner.step(
                "escalation", "超时升级检查",
                lambda: {"escalated": check_overdue_escalations(conn, batch_id=batch_id)},
            )
            stats["escalation"] = escalation_count

            finished = now_bj()
            finished_iso = finished.isoformat(timespec="seconds")
            duration_seconds = (finished - started).total_seconds()
            finalize_quality_report(conn, as_of, finished_iso, duration_seconds, runner.steps)
            patch_brief_batch_info(conn, as_of, finished_iso, duration_seconds, runner.steps)
            stats["duration_seconds"] = round(duration_seconds, 2)
            stats["finished_at"] = finished_iso

        conn.execute(
            "UPDATE batch_runs SET status='success', finished_at=?, steps_json=?, stats_json=?, error=NULL WHERE batch_id=?",
            (finished_iso, json.dumps(runner.steps, ensure_ascii=False),
             json.dumps(stats, ensure_ascii=False), batch_id),
        )
        return {
            "batch_id": batch_id, "as_of": as_of.isoformat(), "status": "success",
            "started_at": started_iso, "finished_at": finished_iso,
            "duration_seconds": round(duration_seconds, 2),
            "steps": runner.steps, "stats": stats, "error": None,
        }
    except Exception as exc:
        # 主事务已回滚，保留上一次可用快照；运行记录标记 failed
        failed_at = now_iso()
        duration_seconds = round((now_bj() - started).total_seconds(), 2)
        error_text = str(exc)
        failure_report = None
        if isinstance(exc, IngestError):
            missing = [
                {"file": item.get("source"), "path": item.get("path")}
                for item in exc.errors
                if item.get("code") == "missing_source"
            ]
            if missing:
                failure_report = build_extract_failure_report(
                    as_of, batch_id, started_iso, failed_at, duration_seconds,
                    runner.steps, missing, (exc.stats or {}).get("source_dir"),
                )
                error_text = "源数据校验失败：" + failure_report["failure"]["message"]
                # 让“批次步骤”接口也显示同一个包含文件名和影响指标的错误。
                for step in runner.steps:
                    if step.get("status") == "failed":
                        step["error"] = error_text
                stats["failure"] = failure_report["failure"]
        try:
            conn.execute(
                """UPDATE batch_runs SET status='failed', finished_at=?, steps_json=?,
                   stats_json=?, error=? WHERE batch_id=?""",
                (failed_at, json.dumps(runner.steps, ensure_ascii=False),
                 json.dumps(stats, ensure_ascii=False), error_text[:4000], batch_id),
            )
        except Exception:
            pass
        if failure_report is not None:
            # 质量报告在主事务外单独落库，供数据质量页与顶部横幅读取；
            # 业务表仍保持回滚，不产生当日指标、风险、日报或周报。
            try:
                with transaction(conn):
                    save_quality_report(conn, failure_report)
            except Exception:
                pass
        return {
            "batch_id": batch_id, "as_of": as_of.isoformat(), "status": "failed",
            "started_at": started_iso, "finished_at": failed_at,
            "duration_seconds": duration_seconds, "steps": runner.steps, "stats": stats,
            "error": error_text,
            "failure": failure_report["failure"] if failure_report else None,
        }
    finally:
        conn.close()
