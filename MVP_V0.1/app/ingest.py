"""CSV 抽取、校验与入库。

批次在同一个数据库事务中调用本模块：
1. 10 个源文件逐个解析并校验；
2. 有任何结构/主键/引用/类型错误则整批失败，事务回滚，保留上次可用数据；
3. 主数据（组织、用户、目标）upsert，事务数据全量重灌。
"""
from __future__ import annotations

import csv
import sqlite3
from datetime import date
from pathlib import Path

from .config import SOURCE_DIR, now_iso


class IngestError(Exception):
    def __init__(self, message: str, errors: list[dict] | None = None, stats: dict | None = None):
        super().__init__(message)
        self.message = message
        self.errors = errors or []
        self.stats = stats or {}


SOURCE_SPECS = {
    "orgs": {
        "file": "orgs.csv", "table": "orgs", "key": "org_id", "kind": "master",
        "required": ["org_id", "name", "type", "sort_order"],
        "dates": [], "numbers": ["sort_order"],
    },
    "users": {
        "file": "users.csv", "table": "users", "key": "user_id", "kind": "master",
        "required": ["user_id", "name", "role", "title", "org_id"],
        "dates": [], "numbers": ["is_demo"],
    },
    "targets": {
        "file": "targets.csv", "table": "targets", "key": "target_id", "kind": "master",
        "required": ["target_id", "month", "org_id", "sign_target", "collection_target"],
        "dates": [], "numbers": ["sign_target", "collection_target"],
    },
    "leads": {
        "file": "leads.csv", "table": "leads", "key": "lead_id", "kind": "txn",
        "required": ["lead_id", "created_date", "source", "owner_id", "org_id", "customer"],
        "dates": ["created_date"], "numbers": ["converted"],
    },
    "opportunities": {
        "file": "opportunities.csv", "table": "opportunities", "key": "opp_id", "kind": "txn",
        "required": ["opp_id", "customer", "owner_id", "org_id", "amount", "created_date", "status"],
        "dates": ["created_date", "last_followup_date", "expected_close_date"], "numbers": ["amount"],
    },
    "contracts": {
        "file": "contracts.csv", "table": "contracts", "key": "contract_id", "kind": "txn",
        "required": ["contract_id", "customer", "owner_id", "org_id", "amount", "sign_date", "status"],
        "dates": ["sign_date"], "numbers": ["amount"],
    },
    "orders": {
        "file": "orders.csv", "table": "orders", "key": "order_id", "kind": "txn",
        "required": ["order_id", "customer", "owner_id", "org_id", "amount", "order_date", "status"],
        "dates": ["order_date"], "numbers": ["amount"],
    },
    "receivables": {
        "file": "receivables.csv", "table": "receivables", "key": "recv_id", "kind": "txn",
        "required": ["recv_id", "customer", "owner_id", "org_id", "amount", "due_date", "status"],
        "dates": ["due_date", "paid_date"], "numbers": ["amount", "paid_amount"],
    },
    "ad_spend": {
        "file": "ad_spend.csv", "table": "ad_spend", "key": "spend_key", "kind": "txn",
        "required": ["spend_key", "date", "channel", "spend"],
        "dates": ["date"], "numbers": ["spend", "impressions", "clicks", "leads_count"],
    },
    "followups": {
        "file": "followups.csv", "table": "followups", "key": "followup_id", "kind": "txn",
        "required": ["followup_id", "opp_id", "user_id", "date"],
        "dates": ["date"], "numbers": [],
    },
}

TX_TABLES = [
    "followups", "ad_spend", "receivables", "orders", "contracts",
    "opportunities", "leads",
]

OWNER_REFS = {
    "leads": "owner_id", "opportunities": "owner_id", "contracts": "owner_id",
    "orders": "owner_id", "receivables": "owner_id",
}

COLUMNS = {
    "orgs": ["org_id", "name", "parent_id", "type", "sort_order", "manager_user_id"],
    "users": ["user_id", "name", "role", "title", "org_id", "phone", "email", "manager_id", "is_demo"],
    "targets": ["target_id", "month", "org_id", "user_id", "sign_target", "collection_target"],
    "leads": ["lead_id", "created_date", "source", "owner_id", "org_id", "customer", "phone",
              "status", "converted", "campaign_id", "batch_as_of", "ingested_at"],
    "opportunities": ["opp_id", "customer", "owner_id", "org_id", "amount", "stage", "created_date",
                      "last_followup_date", "expected_close_date", "status", "batch_as_of", "ingested_at"],
    "contracts": ["contract_id", "customer", "owner_id", "org_id", "amount", "sign_date", "status",
                  "campaign_id", "batch_as_of", "ingested_at"],
    "orders": ["order_id", "customer", "owner_id", "org_id", "amount", "order_date", "status",
               "batch_as_of", "ingested_at"],
    "receivables": ["recv_id", "customer", "owner_id", "org_id", "amount", "due_date",
                    "paid_amount", "paid_date", "status", "batch_as_of", "ingested_at"],
    "ad_spend": ["spend_key", "date", "channel", "spend", "impressions", "clicks", "leads_count",
                 "batch_as_of", "ingested_at"],
    "followups": ["followup_id", "opp_id", "user_id", "date", "type", "note", "batch_as_of", "ingested_at"],
}


def _read_csv(path: Path, spec: dict) -> tuple[list[dict], list[dict]]:
    errors: list[dict] = []
    if not path.exists():
        return [], [{
            "level": "error", "code": "missing_source", "source": spec["file"],
            "path": str(path), "message": f"缺失源文件：{spec['file']}",
        }]
    rows: list[dict] = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        header = reader.fieldnames or []
        missing_cols = [c for c in spec["required"] if c not in header]
        if missing_cols:
            return [], [{
                "level": "error", "source": spec["file"],
                "message": "缺少必需列：" + "、".join(missing_cols),
            }]
        for lineno, raw in enumerate(reader, start=2):
            row = {k: (v.strip() if isinstance(v, str) else v) for k, v in raw.items()}
            row["_line"] = lineno
            rows.append(row)
    return rows, errors


def _parse_rows(name: str, spec: dict, rows: list[dict]) -> tuple[list[dict], list[dict]]:
    errors: list[dict] = []
    cleaned: list[dict] = []
    seen: dict[str, int] = {}
    key = spec["key"]
    for row in rows:
        line = row.pop("_line")
        for field in spec["required"]:
            if not str(row.get(field, "") or "").strip():
                errors.append({"level": "error", "source": spec["file"], "line": line,
                               "field": field, "message": f"必填字段为空：{field}"})
        key_value = str(row.get(key, "") or "").strip()
        if key_value:
            if key_value in seen:
                errors.append({"level": "error", "source": spec["file"], "line": line,
                               "field": key, "message": f"主键重复：{key_value}（首次出现在第 {seen[key_value]} 行）"})
            else:
                seen[key_value] = line
        for field in spec["dates"]:
            value = str(row.get(field, "") or "").strip()
            if value:
                try:
                    date.fromisoformat(value)
                except ValueError:
                    errors.append({"level": "error", "source": spec["file"], "line": line,
                                   "field": field, "message": f"日期格式非法：{field}={value}"})
        for field in spec["numbers"]:
            value = str(row.get(field, "") or "").strip()
            if value:
                try:
                    float(value)
                except ValueError:
                    errors.append({"level": "error", "source": spec["file"], "line": line,
                                   "field": field, "message": f"数值格式非法：{field}={value}"})
        cleaned.append(row)
    return cleaned, errors


def _insert_row(conn: sqlite3.Connection, table: str, row: dict) -> None:
    cols = COLUMNS[table]
    values = []
    for c in cols:
        value = row.get(c)
        if isinstance(value, str) and value == "":
            value = None
        values.append(value)
    placeholders = ",".join("?" for _ in cols)
    conn.execute(
        f"INSERT INTO {table} ({','.join(cols)}) VALUES ({placeholders})",
        values,
    )


def _check_references(
    conn: sqlite3.Connection, data: dict[str, list[dict]], org_ids: set[str], user_ids: set[str],
    opp_ids: set[str],
) -> list[dict]:
    errors: list[dict] = []
    for name in ["users", "targets", "leads", "opportunities", "contracts", "orders", "receivables"]:
        for row in data.get(name, []):
            org_id = str(row.get("org_id", "") or "").strip()
            if org_id and org_id not in org_ids:
                errors.append({"level": "error", "source": SOURCE_SPECS[name]["file"],
                               "message": f"组织映射失败：{org_id} 不存在"})
            if len(errors) >= 100:
                return errors
    for name, field in OWNER_REFS.items():
        for row in data.get(name, []):
            owner = str(row.get(field, "") or "").strip()
            if owner and owner not in user_ids:
                errors.append({"level": "error", "source": SOURCE_SPECS[name]["file"],
                               "message": f"负责人映射失败：{owner} 不存在"})
            if len(errors) >= 100:
                return errors
    for row in data.get("followups", []):
        opp = str(row.get("opp_id", "") or "").strip()
        if opp and opp not in opp_ids:
            errors.append({"level": "error", "source": "followups.csv",
                           "message": f"商机映射失败：{opp} 不存在"})
    for row in data.get("targets", []):
        user_id = str(row.get("user_id", "") or "").strip()
        if user_id and user_id not in user_ids:
            errors.append({"level": "error", "source": "targets.csv",
                           "message": f"用户目标映射失败：{user_id} 不存在"})
    return errors


def extract_all(conn: sqlite3.Connection, as_of: date, source_dir: Path | None = None) -> dict:
    """读取、校验并重灌数据。调用方负责事务；本函数不提交。"""
    source_dir = source_dir or SOURCE_DIR
    data: dict[str, list[dict]] = {}
    all_errors: list[dict] = []
    raw_counts: dict[str, int] = {}
    for name, spec in SOURCE_SPECS.items():
        rows, read_errors = _read_csv(source_dir / spec["file"], spec)
        raw_counts[name] = len(rows)
        all_errors.extend(read_errors)
        cleaned, parse_errors = _parse_rows(name, spec, rows)
        all_errors.extend(parse_errors)
        data[name] = cleaned
        if len(all_errors) >= 100:
            all_errors = all_errors[:100]
            break

    stats = {"row_counts": raw_counts, "source_dir": str(source_dir)}
    if all_errors:
        raise IngestError("源数据校验失败", all_errors, stats)

    org_ids = {str(r.get("org_id", "") or "").strip() for r in data.get("orgs", [])}
    user_ids = {str(r.get("user_id", "") or "").strip() for r in data.get("users", [])}
    opp_ids = {str(r.get("opp_id", "") or "").strip() for r in data.get("opportunities", [])}
    errors = _check_references(conn, data, org_ids, user_ids, opp_ids)
    if errors:
        raise IngestError("源数据引用校验失败", errors, stats)

    now = now_iso()
    as_of_str = as_of.isoformat()

    # 主数据 upsert，保留历史引用
    for row in data["orgs"]:
        conn.execute(
            """INSERT INTO orgs (org_id, name, parent_id, type, sort_order, manager_user_id)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(org_id) DO UPDATE SET name=excluded.name,
                 parent_id=excluded.parent_id, type=excluded.type,
                 sort_order=excluded.sort_order, manager_user_id=excluded.manager_user_id""",
            (row["org_id"], row["name"], row.get("parent_id") or None, row["type"],
             int(float(row.get("sort_order") or 0)), row.get("manager_user_id") or None),
        )
    for row in data["users"]:
        conn.execute(
            """INSERT INTO users (user_id, name, role, title, org_id, phone, email, manager_id, is_demo, active)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
               ON CONFLICT(user_id) DO UPDATE SET name=excluded.name, role=excluded.role,
                 title=excluded.title, org_id=excluded.org_id, phone=excluded.phone,
                 email=excluded.email, manager_id=excluded.manager_id, is_demo=excluded.is_demo,
                 active=1""",
            (row["user_id"], row["name"], row["role"], row["title"], row["org_id"],
             row.get("phone") or None, row.get("email") or None, row.get("manager_id") or None,
             int(float(row.get("is_demo") or 0))),
        )
    for row in data["targets"]:
        conn.execute(
            """INSERT INTO targets (target_id, month, org_id, user_id, sign_target, collection_target)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(target_id) DO UPDATE SET month=excluded.month, org_id=excluded.org_id,
                 user_id=excluded.user_id, sign_target=excluded.sign_target,
                 collection_target=excluded.collection_target""",
            (row["target_id"], row["month"], row["org_id"], row.get("user_id") or None,
             float(row.get("sign_target") or 0), float(row.get("collection_target") or 0)),
        )

    # 事务类数据全量重灌（同一事务内，失败由批次回滚）
    for table in TX_TABLES:
        conn.execute(f"DELETE FROM {table}")
    for name in ["leads", "opportunities", "contracts", "orders", "receivables", "ad_spend", "followups"]:
        for row in data[name]:
            row["batch_as_of"] = as_of_str
            row["ingested_at"] = now
            # 数值字段统一转 float 以适配 SQLite
            for field in SOURCE_SPECS[name]["numbers"]:
                if str(row.get(field, "") or "") != "":
                    row[field] = float(row[field])
            if name == "leads":
                row["converted"] = int(float(row.get("converted") or 0))
            _insert_row(conn, name, row)

    return {
        "row_counts": raw_counts,
        "ingested_at": now,
        "master_counts": {
            "orgs": len(data["orgs"]), "users": len(data["users"]), "targets": len(data["targets"]),
        },
        "transaction_counts": {
            k: len(data[k]) for k in
            ["leads", "opportunities", "contracts", "orders", "receivables", "ad_spend", "followups"]
        },
    }
