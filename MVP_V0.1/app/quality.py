"""数据质量检查与报告。

报告落库 quality_reports，页面的数据质量弹窗只读服务端结果。
检查项：字段完整性、主键重复、目标缺失、组织/负责人映射、缺失源、影响指标。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path

from .config import SOURCE_DIR, now_iso
from .scope import all_orgs

# 业务必填字段（不含可空的联系人电话、备注等）
COMPLETENESS_FIELDS = {
    "orgs": ["org_id", "name", "type"],
    "users": ["user_id", "name", "role", "title", "org_id"],
    "targets": ["target_id", "month", "org_id", "sign_target"],
    "leads": ["lead_id", "created_date", "source", "owner_id", "org_id", "customer", "status"],
    "opportunities": ["opp_id", "customer", "owner_id", "org_id", "amount", "created_date", "status"],
    "contracts": ["contract_id", "customer", "owner_id", "org_id", "amount", "sign_date", "status"],
    "orders": ["order_id", "customer", "owner_id", "org_id", "amount", "order_date", "status"],
    "receivables": ["recv_id", "customer", "owner_id", "org_id", "amount", "due_date", "status"],
    "ad_spend": ["spend_key", "date", "channel", "spend"],
    "followups": ["followup_id", "opp_id", "user_id", "date"],
}

KEY_FIELDS = {
    "orgs": "org_id", "users": "user_id", "targets": "target_id", "leads": "lead_id",
    "opportunities": "opp_id", "contracts": "contract_id", "orders": "order_id",
    "receivables": "recv_id", "ad_spend": "spend_key", "followups": "followup_id",
}

SOURCE_FILES = {
    "orgs": "orgs.csv", "users": "users.csv", "targets": "targets.csv",
    "leads": "leads.csv", "opportunities": "opportunities.csv", "contracts": "contracts.csv",
    "orders": "orders.csv", "receivables": "receivables.csv", "ad_spend": "ad_spend.csv",
    "followups": "followups.csv",
}

METRIC_DEPENDENCIES = {
    "orgs": ["全部组织范围指标", "全部风险"],
    "users": ["负责人/组织映射", "风险责任人", "通知对象"],
    "targets": ["目标完成率", "商机覆盖率", "目标缺口风险"],
    "leads": ["新增线索数", "有效线索数", "线索有效率", "线索转化率", "线索异常风险"],
    "opportunities": ["新增商机数", "商机管道金额", "商机覆盖率", "大客户流失风险"],
    "contracts": ["签约额", "签约单数", "目标完成率", "业绩下滑风险", "营销 ROI"],
    "orders": ["订单/回款风险"],
    "receivables": ["回款完成率", "订单/回款风险"],
    "ad_spend": ["营销费用", "营销 ROI", "渠道分析"],
    "followups": ["大客户流失风险", "商机最后跟进时间"],
}


def _table_count(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    return bool(row)


def _completeness(conn: sqlite3.Connection) -> dict:
    by_source = []
    total_fields = 0
    missing_fields = 0
    for table, fields in COMPLETENESS_FIELDS.items():
        if not _table_exists(conn, table):
            by_source.append({"source": table, "rows": 0, "fields": len(fields), "missing": None,
                              "score": None, "available": False})
            continue
        rows = _table_count(conn, table)
        missing = 0
        details = []
        for field in fields:
            count = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {field} IS NULL OR TRIM(CAST({field} AS TEXT)) = ''"
            ).fetchone()[0]
            if count:
                details.append({"field": field, "missing": int(count)})
            missing += int(count)
        cells = rows * len(fields)
        score = round((cells - missing) / cells * 100, 1) if cells else None
        total_fields += cells
        missing_fields += missing
        by_source.append({
            "source": SOURCE_FILES.get(table, table),
            "rows": rows,
            "fields": len(fields),
            "missing": missing,
            "score": score,
            "available": True,
            "missing_detail": details[:5],
        })
    overall = round((total_fields - missing_fields) / total_fields * 100, 1) if total_fields else None
    return {"score": overall, "missing_cells": missing_fields, "checked_cells": total_fields, "by_source": by_source}


def _duplicates(conn: sqlite3.Connection) -> dict:
    by_source = []
    total_rows = 0
    duplicate_rows = 0
    for table, key in KEY_FIELDS.items():
        if not _table_exists(conn, table):
            continue
        rows = _table_count(conn, table)
        dup_groups = conn.execute(
            f"SELECT COUNT(*) FROM (SELECT {key} FROM {table} GROUP BY {key} HAVING COUNT(*) > 1)"
        ).fetchone()[0]
        dup_extra = conn.execute(
            f"SELECT COALESCE(SUM(c - 1),0) FROM (SELECT COUNT(*) c FROM {table} GROUP BY {key} HAVING COUNT(*) > 1)"
        ).fetchone()[0]
        total_rows += rows
        duplicate_rows += int(dup_extra)
        by_source.append({"source": SOURCE_FILES.get(table, table), "rows": rows,
                          "duplicate_groups": int(dup_groups), "duplicate_rows": int(dup_extra)})
    rate = duplicate_rows / total_rows * 100 if total_rows else None
    return {"rate": round(rate, 2) if rate is not None else None, "duplicate_rows": duplicate_rows,
            "rows": total_rows, "by_source": by_source}


def _target_coverage(conn: sqlite3.Connection, as_of: date) -> dict:
    month = f"{as_of.year:04d}-{as_of.month:02d}"
    orgs = all_orgs(conn)
    with_targets = {
        r["org_id"] for r in conn.execute(
            "SELECT DISTINCT org_id FROM targets WHERE month = ? AND COALESCE(user_id,'') = ''", (month,)
        ).fetchall()
    }
    missing_orgs = [{"org_id": o["org_id"], "name": o["name"]} for o in orgs if o["org_id"] not in with_targets]
    # 销售个人目标：只统计有销售职责的 sm/rep；bu/gm/sd/marketing 不要求个人目标
    sales_users = conn.execute(
        "SELECT user_id, name, org_id FROM users WHERE active=1 AND role IN ('sm','rep') ORDER BY org_id, user_id"
    ).fetchall()
    user_targets = {
        r["user_id"] for r in conn.execute(
            "SELECT DISTINCT user_id FROM targets WHERE month = ? AND COALESCE(user_id,'') <> ''", (month,)
        ).fetchall()
    }
    missing_users = [dict(r) for r in sales_users if r["user_id"] not in user_targets]
    return {
        "month": month,
        "orgs_total": len(orgs),
        "orgs_with_target": len(orgs) - len(missing_orgs),
        "orgs_missing": missing_orgs,
        "sales_users_total": len(sales_users),
        "sales_users_with_target": len(sales_users) - len(missing_users),
        "users_missing": missing_users,
        "status": "ok" if not missing_orgs and not missing_users else "warn",
    }


def _mapping_failures(conn: sqlite3.Connection) -> dict:
    failures = []
    checks = [
        ("leads", "org_id", "orgs", "org_id"), ("opportunities", "org_id", "orgs", "org_id"),
        ("contracts", "org_id", "orgs", "org_id"), ("orders", "org_id", "orgs", "org_id"),
        ("receivables", "org_id", "orgs", "org_id"),
        ("leads", "owner_id", "users", "user_id"), ("opportunities", "owner_id", "users", "user_id"),
        ("contracts", "owner_id", "users", "user_id"), ("orders", "owner_id", "users", "user_id"),
        ("receivables", "owner_id", "users", "user_id"), ("followups", "user_id", "users", "user_id"),
        ("targets", "org_id", "orgs", "org_id"),
    ]
    for table, field, ref_table, ref_field in checks:
        count = conn.execute(
            f"""SELECT COUNT(*) FROM {table} t
                LEFT JOIN {ref_table} r ON TRIM(CAST(t.{field} AS TEXT)) = r.{ref_field}
                WHERE t.{field} IS NOT NULL AND TRIM(CAST(t.{field} AS TEXT)) <> '' AND r.{ref_field} IS NULL"""
        ).fetchone()[0]
        if count:
            failures.append({"source": SOURCE_FILES.get(table, table), "field": field, "rows": int(count)})
    followups_orphans = conn.execute(
        """SELECT COUNT(*) FROM followups f LEFT JOIN opportunities o ON f.opp_id = o.opp_id
           WHERE o.opp_id IS NULL"""
    ).fetchone()[0]
    if followups_orphans:
        failures.append({"source": "followups.csv", "field": "opp_id", "rows": int(followups_orphans)})
    return {"failures": failures, "count": sum(x["rows"] for x in failures)}


def _missing_sources() -> list[str]:
    return [filename for filename in SOURCE_FILES.values() if not (SOURCE_DIR / filename).exists()]


def metrics_for_source(filename: str) -> list[str]:
    """按源文件名返回依赖指标，供缺失文件错误和影响范围共用。"""
    table = next((k for k, v in SOURCE_FILES.items() if v == filename or k == filename), None)
    return list(METRIC_DEPENDENCIES.get(table, ["全部指标"])) if table else ["全部指标"]


def _affected_item(reason: str, metrics: list[str], sources: list[str], severity: str) -> dict:
    """统一影响范围结构；label 供前端直接展示，metrics 保留给接口消费方。"""
    unique_metrics = list(dict.fromkeys(metrics))
    return {
        "reason": reason,
        "label": "、".join(unique_metrics) if unique_metrics else "受影响指标",
        "metrics": unique_metrics,
        "sources": sources,
        "severity": severity,
    }


def _affected_metrics(completeness: dict, duplicates: dict, targets: dict, mapping: dict, missing_sources: list[str]) -> list[dict]:
    affected = []
    for filename in missing_sources:
        affected.append(_affected_item(
            f"缺失源文件 {filename}，依赖这些文件的指标无法计算",
            metrics_for_source(filename), [filename], "error",
        ))
    for row in completeness.get("by_source", []):
        if row.get("missing"):
            table = next((k for k, v in SOURCE_FILES.items() if v == row["source"]), row["source"])
            affected.append(_affected_item(
                f"{row['source']} 有 {row['missing']} 个必填单元格缺失",
                METRIC_DEPENDENCIES.get(table, []), [row["source"]], "warning",
            ))
    for row in duplicates.get("by_source", []):
        if row.get("duplicate_rows"):
            table = next((k for k, v in SOURCE_FILES.items() if v == row["source"]), row["source"])
            affected.append(_affected_item(
                f"{row['source']} 存在 {row['duplicate_rows']} 条重复记录",
                METRIC_DEPENDENCIES.get(table, []), [row["source"]], "warning",
            ))
    if targets.get("orgs_missing") or targets.get("users_missing"):
        affected.append(_affected_item(
            "部分组织/销售人员缺少当月目标",
            ["目标完成率", "商机覆盖率", "目标缺口风险"], ["targets.csv"], "warning",
        ))
    if mapping.get("count"):
        affected.append(_affected_item(
            f"存在 {mapping['count']} 条组织或负责人映射失败",
            ["全部按组织汇总的指标"], ["多源"], "error",
        ))
    return affected


def build_extract_failure_report(
    as_of: date, batch_id: str, started_at: str, finished_at: str,
    duration_seconds: float, steps: list[dict], missing_sources: list[dict],
    source_dir: str | None = None,
) -> dict:
    """抽取阶段缺文件时生成可展示的失败质量报告。

    抽取失败时业务事务整体回滚，因此本报告由批处理在回滚后单独落库。
    明确写入文件级影响指标，页面顶部横幅和 /api/quality 都读取同一份文本。
    """
    details = []
    affected = []
    for item in missing_sources:
        filename = item.get("file") or Path(item.get("path") or "").name
        path = item.get("path")
        metrics = metrics_for_source(filename)
        details.append({"file": filename, "path": path, "metrics": metrics})
        affected.append(_affected_item(
            f"缺失源文件 {filename}，依赖这些文件的指标无法计算",
            metrics, [filename], "error",
        ))

    files_text = "、".join(
        f"{item['file']}（{item['path']}）" if item.get("path") else item["file"]
        for item in details
    )
    all_metrics = list(dict.fromkeys(m for item in details for m in item["metrics"]))
    message = (
        f"缺少源文件 {files_text}；影响指标：{'、'.join(all_metrics)}。"
        "批次已停止并回滚，未生成新的日报、周报或风险结论。"
    )
    source_check = {
        "key": "sources", "label": "源文件完整性", "status": "fail",
        "value": f"{len(SOURCE_FILES) - len(details)}/{len(SOURCE_FILES)}",
        "detail": f"缺失：{files_text}",
    }
    skipped = [
        {
            "key": "completeness", "label": "字段完整性", "status": "fail", "value": "未执行",
            "detail": "抽取阶段失败，未对旧快照执行字段完整性检查。",
        },
        {
            "key": "duplicates", "label": "主键重复", "status": "fail", "value": "未执行",
            "detail": "抽取阶段失败，未对旧快照执行主键重复检查。",
        },
        {
            "key": "targets", "label": "目标缺失", "status": "fail", "value": "未执行",
            "detail": "抽取阶段失败，未对旧快照执行目标覆盖检查。",
        },
        {
            "key": "mapping", "label": "组织/负责人映射", "status": "fail", "value": "未执行",
            "detail": "抽取阶段失败，未对旧快照执行映射检查。",
        },
    ]
    return {
        "as_of": as_of.isoformat(),
        "batch_id": batch_id,
        "generated_at": finished_at,
        "status": "fail",
        "score": None,
        "summary": {
            "errors": 1, "warnings": 0,
            "message": "源文件缺失，批次停止发布",
        },
        "checks": skipped + [source_check],
        "completeness": {"score": None, "missing_cells": None, "checked_cells": None, "by_source": []},
        "duplicates": {"rate": None, "duplicate_rows": None, "rows": None, "by_source": []},
        "targets": {
            "orgs_total": None, "orgs_with_target": None, "orgs_missing": [],
            "sales_users_total": None, "sales_users_with_target": None, "users_missing": [],
            "status": "unknown",
        },
        "mapping": {"failures": [], "count": None},
        "missing_sources": [item["file"] for item in details],
        "missing_source_details": details,
        "affected_metrics": affected,
        "source_stats": {"source_dir": source_dir} if source_dir else {},
        "batch": {
            "started_at": started_at,
            "finished_at": finished_at,
            "duration_seconds": round(duration_seconds, 2),
            "steps": steps,
        },
        "failure": {
            "stage": "extract",
            "kind": "missing_source",
            "message": message,
            "missing_files": details,
            "affected_metrics": affected,
        },
    }


def build_quality_report(
    conn: sqlite3.Connection, as_of: date, batch_id: str, started_at: str,
    source_stats: dict | None = None,
) -> dict:
    completeness = _completeness(conn)
    duplicates = _duplicates(conn)
    targets = _target_coverage(conn, as_of)
    mapping = _mapping_failures(conn)
    missing_sources = _missing_sources()
    affected = _affected_metrics(completeness, duplicates, targets, mapping, missing_sources)

    errors = 0
    warnings = 0
    if missing_sources:
        errors += 1
    if mapping.get("count"):
        errors += 1
    if a_complete := completeness.get("missing_cells"):
        warnings += 1
    if duplicates.get("duplicate_rows"):
        warnings += 1
    if targets.get("status") == "warn":
        warnings += 1
    status = "fail" if errors else ("warn" if warnings else "pass")
    score = completeness.get("score")
    if score is not None and (errors or duplicates.get("duplicate_rows")):
        score = round(max(0, score - (10 if errors else 0) - min(5, duplicates["duplicate_rows"])), 1)

    checks = [
        {
            "key": "completeness", "label": "字段完整性",
            "status": "pass" if not completeness.get("missing_cells") else "warn",
            "value": f"{completeness.get('score'):.1f}%" if completeness.get("score") is not None else "—",
            "detail": f"检查 {completeness.get('checked_cells', 0):,} 个必填单元格，缺失 {completeness.get('missing_cells', 0)} 个。",
        },
        {
            "key": "duplicates", "label": "主键重复",
            "status": "pass" if not duplicates.get("duplicate_rows") else "warn",
            "value": f"{duplicates.get('rate'):.2f}%" if duplicates.get("rate") is not None else "—",
            "detail": f"{duplicates.get('duplicate_rows', 0)} 条重复记录。",
        },
        {
            "key": "targets", "label": "目标缺失",
            "status": "pass" if targets.get("status") == "ok" else "warn",
            "value": f"组织 {targets['orgs_with_target']}/{targets['orgs_total']}",
            "detail": (
                f"销售个人目标覆盖 {targets['sales_users_with_target']}/{targets['sales_users_total']}。"
                + (f" 缺目标组织：{'、'.join(o['name'] for o in targets['orgs_missing'])}。" if targets.get("orgs_missing") else "")
            ),
        },
        {
            "key": "mapping", "label": "组织/负责人映射",
            "status": "pass" if not mapping.get("count") else "fail",
            "value": f"失败 {mapping.get('count', 0)} 条",
            "detail": "全部记录可映射" if not mapping.get("count") else "存在无法映射的记录，批次应失败。",
        },
        {
            "key": "sources", "label": "源文件完整性",
            "status": "pass" if not missing_sources else "fail",
            "value": f"{len(SOURCE_FILES) - len(missing_sources)}/{len(SOURCE_FILES)}",
            "detail": "10 个源文件齐全" if not missing_sources else f"缺失：{'、'.join(missing_sources)}",
        },
    ]
    report = {
        "as_of": as_of.isoformat(),
        "batch_id": batch_id,
        "generated_at": now_iso(),
        "status": status,
        "score": score,
        "summary": {
            "errors": errors, "warnings": warnings,
            "message": "全部检查通过" if status == "pass" else ("存在阻断问题" if status == "fail" else "存在需关注的质量提示"),
        },
        "checks": checks,
        "completeness": completeness,
        "duplicates": duplicates,
        "targets": targets,
        "mapping": mapping,
        "missing_sources": missing_sources,
        "affected_metrics": affected,
        "source_stats": source_stats or {},
        "batch": {
            "started_at": started_at,
            "finished_at": None,
            "duration_seconds": None,
            "steps": [],
        },
    }
    return report


def save_quality_report(conn: sqlite3.Connection, report: dict) -> None:
    conn.execute(
        """INSERT INTO quality_reports (as_of, batch_id, status, report_json, created_at)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(as_of) DO UPDATE SET batch_id=excluded.batch_id, status=excluded.status,
             report_json=excluded.report_json, created_at=excluded.created_at""",
        (report["as_of"], report["batch_id"], report["status"], json.dumps(report, ensure_ascii=False),
         report["generated_at"]),
    )


def finalize_quality_report(
    conn: sqlite3.Connection, as_of: date, finished_at: str, duration_seconds: float, steps: list[dict]
) -> None:
    row = conn.execute("SELECT report_json FROM quality_reports WHERE as_of = ?", (as_of.isoformat(),)).fetchone()
    if not row:
        return
    report = json.loads(row["report_json"])
    report["batch"]["finished_at"] = finished_at
    report["batch"]["duration_seconds"] = round(duration_seconds, 2)
    report["batch"]["steps"] = steps
    conn.execute(
        "UPDATE quality_reports SET report_json = ? WHERE as_of = ?",
        (json.dumps(report, ensure_ascii=False), as_of.isoformat()),
    )


def load_quality_report(conn: sqlite3.Connection, as_of: date) -> dict | None:
    row = conn.execute("SELECT * FROM quality_reports WHERE as_of = ?", (as_of.isoformat(),)).fetchone()
    if not row:
        return None
    report = json.loads(row["report_json"])
    report["batch_id"] = row["batch_id"]
    return report
