"""风险查询、权限、状态机、SLA、转派/关闭/升级。

所有访问都先经过服务端行级权限；越权统一抛 403。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta

from .audit import write_audit
from .config import (
    APPROVED_CLOSE_STATUSES,
    LEVEL_ALIASES,
    LEVEL_LABELS,
    LEVEL_WEIGHTS,
    RISK_TYPES,
    SLA_CLAIM,
    SLA_CLOSE_WORKDAYS,
    STATUS_ALIASES,
    STATUS_LABELS,
    add_workdays,
    money_wan,
    now_bj,
    now_iso,
    parse_dt,
)
from .notifications import create_notification, notify_escalation
from .privacy import mask_email, mask_phone
from .scope import get_user, org_descendants, org_path_name, user_scope_org_ids

TERMINAL = set(APPROVED_CLOSE_STATUSES)

EVENT_LABELS = {
    "created": "自动生成",
    "merged": "再次触发合并",
    "claimed": "认领",
    "transferred": "转派",
    "closed": "关闭",
    "escalated": "升级",
}

OBJECT_TYPE_LABELS = {
    "org": "组织",
    "opportunity": "商机",
    "order": "订单",
    "receivable": "应收",
}

TRANSFER_ROLES = {"gm", "sd", "bu"}
ESCALATE_ROLES = {"gm", "sd", "bu"}


class RiskServiceError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _user_any(conn: sqlite3.Connection, user_id: str | None) -> dict | None:
    if not user_id:
        return None
    row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def _user_summary(conn: sqlite3.Connection, user_id: str | None) -> dict | None:
    user = _user_any(conn, user_id)
    if not user:
        return {"user_id": user_id, "name": "未知用户", "title": "", "org_name": ""}
    org = conn.execute("SELECT name FROM orgs WHERE org_id = ?", (user["org_id"],)).fetchone()
    return {
        "user_id": user["user_id"],
        "name": user["name"],
        "role": user["role"],
        "title": user["title"],
        "org_id": user["org_id"],
        "org_name": org["name"] if org else user["org_id"],
        "phone": mask_phone(user.get("phone")),
        "email": mask_email(user.get("email")),
    }


def _org_summary(conn: sqlite3.Connection, org_id: str) -> dict:
    row = conn.execute("SELECT * FROM orgs WHERE org_id = ?", (org_id,)).fetchone()
    return {
        "org_id": org_id,
        "name": row["name"] if row else org_id,
        "path": org_path_name(conn, org_id),
    }


def _watcher(conn: sqlite3.Connection, risk_id: str, user_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM risk_watchers WHERE risk_id = ? AND user_id = ?", (risk_id, user_id)
    ).fetchone()
    return bool(row)


def can_view_risk(conn: sqlite3.Connection, user: dict, risk: dict) -> bool:
    if user["role"] in {"gm", "sd"}:
        return True
    if risk["owner_user_id"] == user["user_id"]:
        return True
    if _watcher(conn, risk["id"], user["user_id"]):
        return True
    scope = set(user_scope_org_ids(conn, user))
    return risk["org_id"] in scope


def risk_access_clause(conn: sqlite3.Connection, user: dict, alias: str = "r") -> tuple[str, list]:
    if user["role"] in {"gm", "sd"}:
        return "1=1", []
    org_ids = user_scope_org_ids(conn, user)
    if not org_ids:
        return "1=0", []
    ph = ",".join("?" for _ in org_ids)
    clause = (
        f"({alias}.org_id IN ({ph}) OR {alias}.owner_user_id = ? "
        f"OR EXISTS (SELECT 1 FROM risk_watchers w WHERE w.risk_id = {alias}.id AND w.user_id = ?))"
    )
    return clause, list(org_ids) + [user["user_id"], user["user_id"]]


def _fetch_accessible(conn: sqlite3.Connection, user: dict, risk_id: str) -> dict:
    row = conn.execute("SELECT * FROM risks WHERE id = ?", (risk_id,)).fetchone()
    if not row:
        raise RiskServiceError(404, "风险不存在")
    risk = dict(row)
    if not can_view_risk(conn, user, risk):
        raise RiskServiceError(403, "无权访问该风险")
    return risk


def _deadlines(level: str, start: datetime) -> tuple[str, str]:
    claim = SLA_CLAIM[level]
    if claim.get("hours"):
        claim_due = (start + timedelta(hours=claim["hours"])).isoformat(timespec="seconds")
    else:
        claim_due = add_workdays(start, claim["workdays"]).isoformat(timespec="seconds")
    close_due = add_workdays(start, SLA_CLOSE_WORKDAYS[level]).isoformat(timespec="seconds")
    return claim_due, close_due


def _relative_text(seconds: float | None, prefix_due: str = "剩余") -> str:
    if seconds is None:
        return "—"
    if seconds < 0:
        seconds = abs(seconds)
        if seconds < 3600:
            return f"已超时 {int(seconds // 60)} 分钟"
        if seconds < 86400:
            return f"已超时 {seconds / 3600:.1f} 小时"
        return f"已超时 {seconds / 86400:.1f} 天"
    if seconds < 3600:
        return f"{prefix_due} {int(seconds // 60)} 分钟"
    if seconds < 86400:
        return f"{prefix_due} {seconds / 3600:.1f} 小时"
    return f"{prefix_due} {seconds / 86400:.1f} 天"


def sla_view(risk: dict, now: datetime | None = None) -> dict:
    now = now or now_bj()
    status = risk["status"]
    terminal = status in TERMINAL
    claim_due = parse_dt(risk.get("claim_due_at"))
    close_due = parse_dt(risk.get("close_due_at"))
    claim_seconds = (claim_due - now).total_seconds() if claim_due else None
    close_seconds = (close_due - now).total_seconds() if close_due else None
    if status == "pending" and claim_seconds is not None and claim_seconds < 0:
        claim_state = "overdue"
        claim_text = _relative_text(claim_seconds)
    elif status == "pending":
        claim_state = "due_soon" if claim_seconds is not None and claim_seconds <= 3600 else "normal"
        claim_text = _relative_text(claim_seconds)
    elif terminal:
        claim_state = "closed"
        claim_text = "已结束"
    else:
        claim_state = "claimed"
        claim_text = "已认领"

    if terminal:
        close_state = "closed"
        close_text = STATUS_LABELS.get(status, status)
    elif close_seconds is not None and close_seconds < 0:
        close_state = "overdue"
        close_text = _relative_text(close_seconds)
    elif close_seconds is not None and close_seconds <= 8 * 3600:
        close_state = "due_soon"
        close_text = _relative_text(close_seconds)
    else:
        close_state = "normal"
        close_text = _relative_text(close_seconds)
    return {
        "claim_due_at": risk.get("claim_due_at"),
        "close_due_at": risk.get("close_due_at"),
        "claim_state": claim_state,
        "claim_text": claim_text,
        "claim_remaining_seconds": int(claim_seconds) if claim_seconds is not None else None,
        "close_state": close_state,
        "close_text": close_text,
        "close_remaining_seconds": int(close_seconds) if close_seconds is not None else None,
    }


def _allowed_actions(conn: sqlite3.Connection, user: dict, risk: dict) -> dict:
    terminal = risk["status"] in TERMINAL
    return {
        "claim": risk["status"] == "pending",
        "transfer": user["role"] in TRANSFER_ROLES and not terminal,
        "close": risk["status"] == "processing",
        "escalate": user["role"] in ESCALATE_ROLES and not terminal and int(risk.get("escalation_level") or 0) < 2,
    }


def _parse_json(text: str | None, default):
    try:
        return json.loads(text) if text else default
    except (json.JSONDecodeError, TypeError):
        return default


def _risk_base(conn: sqlite3.Connection, user: dict, risk: dict) -> dict:
    owner = _user_summary(conn, risk["owner_user_id"])
    org = _org_summary(conn, risk["org_id"])
    evidence_count = conn.execute(
        "SELECT COUNT(*) FROM risk_evidence WHERE risk_id = ?", (risk["id"],)
    ).fetchone()[0]
    event_count = conn.execute(
        "SELECT COUNT(*) FROM risk_events WHERE risk_id = ?", (risk["id"],)
    ).fetchone()[0]
    escalated_to = _user_summary(conn, risk.get("escalated_to")) if risk.get("escalated_to") else None
    return {
        "id": risk["id"],
        "rule_id": risk["rule_id"],
        "type": risk["type"],
        "type_label": RISK_TYPES.get(risk["type"], risk["type"]),
        "level": risk["level"],
        "level_label": LEVEL_LABELS.get(risk["level"], risk["level"]),
        "level_weight": LEVEL_WEIGHTS.get(risk["level"], 0),
        "title": risk["title"],
        "object": {
            "type": risk["object_type"],
            "type_label": OBJECT_TYPE_LABELS.get(risk["object_type"], risk["object_type"]),
            "id": risk["object_id"],
            "name": risk["object_name"],
        },
        "amount": money_wan(risk["amount"]),
        "amount_unit": "万元",
        "org": org,
        "dept": risk.get("dept") or org["name"],
        "owner": owner,
        "status": risk["status"],
        "status_label": STATUS_LABELS.get(risk["status"], risk["status"]),
        "as_of": risk.get("as_of"),
        "created_at": risk["created_at"],
        "updated_at": risk["updated_at"],
        "last_seen_at": risk["last_seen_at"],
        "claimed_at": risk.get("claimed_at"),
        "claimed_by": _user_summary(conn, risk.get("claimed_by")) if risk.get("claimed_by") else None,
        "closed_at": risk.get("closed_at"),
        "close_result_status": risk.get("close_result_status"),
        "escalation": {
            "level": int(risk.get("escalation_level") or 0),
            "escalated_to": escalated_to,
            "in_general_manager_pool": bool(escalated_to and escalated_to.get("role") == "gm"),
        },
        "sla": sla_view(risk),
        "merged_count": int(risk.get("merged_count") or 0),
        "trigger_count": int(risk.get("trigger_count") or 1),
        "evidence_count": int(evidence_count),
        "event_count": int(event_count),
        "is_owner": risk["owner_user_id"] == user["user_id"],
        "is_watcher": _watcher(conn, risk["id"], user["user_id"]),
        "allowed_actions": _allowed_actions(conn, user, risk),
    }


def _transfer_candidates(conn: sqlite3.Connection, user: dict, risk: dict) -> list[dict]:
    if user["role"] not in TRANSFER_ROLES:
        return []
    params: list = []
    if user["role"] == "bu":
        org_ids = org_descendants(conn, user["org_id"], include_self=True)
        ph = ",".join("?" for _ in org_ids)
        sql = (
            f"SELECT * FROM users WHERE active=1 AND role IN ('sm','rep','bu') "
            f"AND org_id IN ({ph}) ORDER BY CASE role WHEN 'bu' THEN 1 WHEN 'sm' THEN 2 ELSE 3 END, org_id, user_id"
        )
        params = org_ids
    else:
        sql = (
            "SELECT * FROM users WHERE active=1 AND role IN ('gm','sd','bu','sm','rep') "
            "ORDER BY CASE role WHEN 'gm' THEN 1 WHEN 'sd' THEN 2 WHEN 'bu' THEN 3 WHEN 'sm' THEN 4 ELSE 5 END, org_id, user_id"
        )
    rows = conn.execute(sql, params).fetchall()
    result = []
    for row in rows:
        u = dict(row)
        org = conn.execute("SELECT name FROM orgs WHERE org_id = ?", (u["org_id"],)).fetchone()
        result.append({
            "user_id": u["user_id"], "name": u["name"], "role": u["role"],
            "title": u["title"], "org_id": u["org_id"], "org_name": org["name"] if org else u["org_id"],
            "phone": mask_phone(u.get("phone")), "email": mask_email(u.get("email")),
            "is_current_owner": u["user_id"] == risk["owner_user_id"],
        })
    return result


def _related_items(conn: sqlite3.Connection, risk: dict) -> list[dict]:
    items = _parse_json(risk.get("related_json"), [])
    object_type = risk["object_type"]
    object_id = risk["object_id"]
    if object_type == "opportunity":
        row = conn.execute("SELECT * FROM opportunities WHERE opp_id = ?", (object_id,)).fetchone()
        if row:
            items.append({
                "type": "opportunity", "id": row["opp_id"], "label": row["customer"],
                "amount": money_wan(row["amount"]), "stage": row["stage"],
                "last_followup_date": row["last_followup_date"], "status": row["status"],
            })
    elif object_type == "order":
        row = conn.execute("SELECT * FROM orders WHERE order_id = ?", (object_id,)).fetchone()
        if row:
            items.append({
                "type": "order", "id": row["order_id"], "label": row["customer"],
                "amount": money_wan(row["amount"]), "order_date": row["order_date"], "status": row["status"],
            })
    elif object_type == "receivable":
        row = conn.execute("SELECT * FROM receivables WHERE recv_id = ?", (object_id,)).fetchone()
        if row:
            outstanding = float(row["amount"] or 0) - float(row["paid_amount"] or 0)
            items.append({
                "type": "receivable", "id": row["recv_id"], "label": row["customer"],
                "amount": money_wan(outstanding), "due_date": row["due_date"], "status": row["status"],
            })
    return items


def _related_opportunities(conn: sqlite3.Connection, risk: dict) -> list[dict]:
    if risk["object_type"] != "org":
        return []
    org_ids = org_descendants(conn, risk["org_id"], include_self=True)
    ph = ",".join("?" for _ in org_ids)
    rows = conn.execute(
        f"""SELECT opp_id, customer, amount, stage, last_followup_date, status
            FROM opportunities WHERE status='open' AND org_id IN ({ph})
            ORDER BY amount DESC, opp_id LIMIT 5""",
        org_ids,
    ).fetchall()
    return [{
        "id": r["opp_id"], "customer": r["customer"], "amount": money_wan(r["amount"]),
        "stage": r["stage"], "last_followup_date": r["last_followup_date"], "status": r["status"],
    } for r in rows]


def risk_detail_data(conn: sqlite3.Connection, user: dict, risk_id: str) -> dict:
    risk = _fetch_accessible(conn, user, risk_id)
    base = _risk_base(conn, user, risk)
    evidence_rows = conn.execute(
        "SELECT * FROM risk_evidence WHERE risk_id = ? ORDER BY id", (risk_id,)
    ).fetchall()
    all_evidence: list[tuple[int, dict]] = []
    latest_by_key: dict[str, dict] = {}
    for row in evidence_rows:
        item = {k: v for k, v in dict(row).items() if k not in {"id", "risk_id"}}
        all_evidence.append((int(row["id"]), item))
        latest_by_key[item["evidence_key"]] = item
    # 合并后的完整证据链全部返回，保证 len(evidence) 与 evidence_count 一致；
    # latest_evidence 额外提供按判定项去重后的最新一条，方便前端做摘要。
    evidence = [item for _, item in sorted(
        all_evidence, key=lambda pair: (pair[1]["sort_order"], pair[0])
    )]
    latest_evidence = sorted(
        latest_by_key.values(), key=lambda item: (item["sort_order"], item["triggered_at"])
    )

    event_rows = conn.execute(
        "SELECT * FROM risk_events WHERE risk_id = ? ORDER BY created_at, id", (risk_id,)
    ).fetchall()
    timeline = []
    for row in event_rows:
        actor = _user_any(conn, row["actor_user_id"])
        timeline.append({
            "id": row["id"],
            "event_type": row["event_type"],
            "event_label": EVENT_LABELS.get(row["event_type"], row["event_type"]),
            "actor": ({"user_id": actor["user_id"], "name": actor["name"], "title": actor["title"]}
                      if actor else {"user_id": None, "name": "系统", "title": ""}),
            "from_status": row["from_status"],
            "from_status_label": STATUS_LABELS.get(row["from_status"], row["from_status"] or ""),
            "to_status": row["to_status"],
            "to_status_label": STATUS_LABELS.get(row["to_status"], row["to_status"] or ""),
            "note": row["note"],
            "payload": _parse_json(row["payload_json"], {}),
            "created_at": row["created_at"],
        })
    watcher_rows = conn.execute(
        """SELECT w.*, u.name, u.title FROM risk_watchers w
           LEFT JOIN users u ON w.user_id = u.user_id
           WHERE w.risk_id = ? ORDER BY w.created_at, w.user_id""",
        (risk_id,),
    ).fetchall()
    base.update({
        "actions": _parse_json(risk.get("actions_json"), []),
        "close": ({
            "result_status": risk.get("close_result_status"),
            "result_status_label": STATUS_LABELS.get(risk.get("close_result_status"), risk.get("close_result_status")),
            "reason": risk.get("close_reason"),
            "action": risk.get("close_action"),
            "result": risk.get("close_result"),
        } if risk.get("closed_at") else None),
        "evidence": evidence,
        "latest_evidence": latest_evidence,
        "timeline": timeline,
        "watchers": [{
            "user_id": r["user_id"], "name": r["name"], "title": r["title"],
            "reason": r["reason"], "created_at": r["created_at"],
        } for r in watcher_rows],
        "related": _related_items(conn, risk),
        "related_opportunities": _related_opportunities(conn, risk),
        "transfer_candidates": _transfer_candidates(conn, user, risk),
        "transfer_allowed": user["role"] in TRANSFER_ROLES,
    })
    return base


def _overall_stats(conn: sqlite3.Connection, user: dict) -> dict:
    access, params = risk_access_clause(conn, user, "r")
    by_level = {k: 0 for k in ["red", "orange", "yellow"]}
    for row in conn.execute(
        f"SELECT level, COUNT(*) c FROM risks r WHERE {access} GROUP BY level", params
    ).fetchall():
        by_level[row["level"]] = int(row["c"])
    by_status = {k: 0 for k in ["pending", "processing", "closed", "false_positive", "long_term"]}
    for row in conn.execute(
        f"SELECT status, COUNT(*) c FROM risks r WHERE {access} GROUP BY status", params
    ).fetchall():
        by_status[row["status"]] = int(row["c"])
    now = now_iso()
    claim_overdue = conn.execute(
        f"SELECT COUNT(*) FROM risks r WHERE {access} AND r.status='pending' AND r.claim_due_at < ?",
        params + [now],
    ).fetchone()[0]
    close_overdue = conn.execute(
        f"SELECT COUNT(*) FROM risks r WHERE {access} AND r.status IN ('pending','processing') AND r.close_due_at < ?",
        params + [now],
    ).fetchone()[0]
    total = sum(by_status.values())
    return {
        "total": total,
        "by_level": by_level,
        "by_status": by_status,
        "active": by_status["pending"] + by_status["processing"],
        "red_active": sum(
            1 for _ in conn.execute(
                f"SELECT 1 FROM risks r WHERE {access} AND r.level='red' AND r.status IN ('pending','processing')",
                params,
            )
        ),
        "claim_overdue": int(claim_overdue),
        "close_overdue": int(close_overdue),
    }


def _filter_parts(
    conn: sqlite3.Connection, user: dict, level: str | None, status: str | None,
    risk_type: str | None, owner: str | None, q: str | None,
    as_of_start: date | None = None, as_of_end: date | None = None,
) -> tuple[str, list]:
    access, params = risk_access_clause(conn, user, "r")
    where = [access]
    if level:
        parts = [p.strip() for p in level.replace("|", ",").split(",") if p.strip()]
        values = [LEVEL_ALIASES.get(p, p) for p in parts]
        values = [v for v in values if v in LEVEL_LABELS]
        if values:
            where.append(f"r.level IN ({','.join('?' for _ in values)})")
            params.extend(values)
    if status:
        if status not in {"all", ""}:
            if status == "active":
                where.append("r.status IN ('pending','processing')")
            elif status in {"terminal", "ended"}:
                where.append("r.status IN ('closed','false_positive','long_term')")
            else:
                normalized = STATUS_ALIASES.get(status, status)
                if normalized in STATUS_LABELS:
                    where.append("r.status = ?")
                    params.append(normalized)
    if risk_type:
        parts = [p.strip() for p in risk_type.replace("|", ",").split(",") if p.strip()]
        values = []
        reverse = {v: k for k, v in RISK_TYPES.items()}
        for p in parts:
            values.append(reverse.get(p, p))
        values = [v for v in values if v in RISK_TYPES]
        if values:
            where.append(f"r.type IN ({','.join('?' for _ in values)})")
            params.extend(values)
    if owner:
        where.append("r.owner_user_id = ?")
        params.append(owner)
    if q:
        like = f"%{q.strip()}%"
        where.append(
            "(r.title LIKE ? OR r.object_name LIKE ? OR r.object_id LIKE ? "
            "OR r.id LIKE ? OR o.name LIKE ? OR o.user_id LIKE ?)"
        )
        params.extend([like] * 6)
    if as_of_start:
        where.append("r.as_of >= ?")
        params.append(as_of_start.isoformat())
    if as_of_end:
        where.append("r.as_of <= ?")
        params.append(as_of_end.isoformat())
    return " AND ".join(where), params


def query_risks(
    conn: sqlite3.Connection, user: dict, level: str | None = None,
    status: str | None = None, risk_type: str | None = None, owner: str | None = None,
    q: str | None = None, sort: str = "priority", page: int = 1, page_size: int = 20,
    max_page_size: int = 100, as_of_start: date | None = None, as_of_end: date | None = None,
) -> dict:
    page = max(1, int(page or 1))
    page_size = min(max(1, int(page_size or 20)), max_page_size)
    where, params = _filter_parts(
        conn, user, level, status, risk_type, owner, q, as_of_start, as_of_end
    )
    total = conn.execute(
        f"SELECT COUNT(*) FROM risks r LEFT JOIN users o ON r.owner_user_id = o.user_id WHERE {where}",
        params,
    ).fetchone()[0]
    terminal_case = "CASE WHEN r.status IN ('closed','false_positive','long_term') THEN 1 ELSE 0 END ASC"
    status_case = "CASE r.status WHEN 'pending' THEN 0 WHEN 'processing' THEN 1 ELSE 2 END"
    level_case = "CASE r.level WHEN 'red' THEN 3 WHEN 'orange' THEN 2 WHEN 'yellow' THEN 1 ELSE 0 END"
    if sort == "created":
        order = f"{terminal_case}, r.created_at DESC, r.id"
    elif sort == "amount":
        order = f"{terminal_case}, r.amount DESC, {level_case} DESC, r.id"
    elif sort == "due":
        order = f"{terminal_case}, r.claim_due_at ASC, {level_case} DESC, r.id"
    elif sort == "level":
        order = f"{terminal_case}, {level_case} DESC, {status_case}, r.claim_due_at ASC, r.id"
    else:
        order = f"{terminal_case}, {status_case}, {level_case} DESC, r.claim_due_at ASC, r.id"
    rows = conn.execute(
        f"SELECT r.* FROM risks r LEFT JOIN users o ON r.owner_user_id = o.user_id "
        f"WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?",
        params + [page_size, (page - 1) * page_size],
    ).fetchall()
    items = []
    for row in rows:
        risk = dict(row)
        base = _risk_base(conn, user, risk)
        # 列表只保留摘要，不传证据/时间线等大字段
        items.append(base)
    return {
        "items": items,
        "total": int(total),
        "page": page,
        "page_size": page_size,
        "stats": _overall_stats(conn, user),
        "server_time": now_iso(),
    }


def _audit_meta_detail(payload: dict | None) -> str:
    if not payload:
        return ""
    pieces = []
    for key in ("plan", "due", "note", "reason", "action", "result"):
        if payload.get(key):
            pieces.append(f"{key}={payload[key]}")
    return "；".join(pieces)


def claim_risk(
    conn: sqlite3.Connection, user: dict, risk_id: str, payload: dict | None,
    request_meta: dict | None = None,
) -> dict:
    risk = _fetch_accessible(conn, user, risk_id)
    if risk["status"] != "pending":
        raise RiskServiceError(409, f"当前状态为{STATUS_LABELS.get(risk['status'], risk['status'])}，不能认领")
    payload = payload or {}
    now = now_bj()
    now_value = now.isoformat(timespec="seconds")
    plan = str(payload.get("plan") or "").strip()
    conn.execute(
        """UPDATE risks SET status='processing', claimed_at=?, claimed_by=?, updated_at=? WHERE id=?""",
        (now_value, user["user_id"], now_value, risk_id),
    )
    conn.execute(
        """INSERT INTO risk_events
           (risk_id, event_type, actor_user_id, from_status, to_status, note, payload_json, created_at)
           VALUES (?, 'claimed', ?, 'pending', 'processing', ?, ?, ?)""",
        (risk_id, user["user_id"], plan or "已认领风险",
         json.dumps({"plan": plan, "due": payload.get("due"), "sync": bool(payload.get("sync"))},
                    ensure_ascii=False), now_value),
    )
    write_audit(
        conn, user["user_id"], "risk.claim", "risk", risk_id,
        _audit_meta_detail(payload) or "认领风险",
        (request_meta or {}).get("ip"), (request_meta or {}).get("user_agent"),
    )
    return risk_detail_data(conn, user, risk_id)


def transfer_risk(
    conn: sqlite3.Connection, user: dict, risk_id: str, to_user_id: str, note: str,
    request_meta: dict | None = None,
) -> dict:
    if user["role"] not in TRANSFER_ROLES:
        raise RiskServiceError(403, "当前角色无权转派风险")
    risk = _fetch_accessible(conn, user, risk_id)
    if risk["status"] in TERMINAL:
        raise RiskServiceError(409, "已关闭的风险不能转派")
    note = (note or "").strip()
    if not note:
        raise RiskServiceError(400, "转派必须填写说明")
    target = get_user(conn, to_user_id or "")
    if not target:
        raise RiskServiceError(400, "转派对象不存在或已停用")
    if target["role"] not in {"gm", "sd", "bu", "sm", "rep"}:
        raise RiskServiceError(400, "转派对象不是销售角色")
    if to_user_id == risk["owner_user_id"]:
        raise RiskServiceError(400, "转派对象不能与当前责任人相同")
    if user["role"] == "bu":
        allowed_orgs = set(org_descendants(conn, user["org_id"], include_self=True))
        if target["org_id"] not in allowed_orgs:
            raise RiskServiceError(403, "只能转派给本事业部及下级人员")
    now = now_bj()
    now_value = now.isoformat(timespec="seconds")
    claim_due, close_due = _deadlines(risk["level"], now)
    old_owner = risk["owner_user_id"]
    conn.execute(
        """UPDATE risks SET owner_user_id=?, status='pending', claimed_at=NULL, claimed_by=NULL,
             claim_due_at=?, close_due_at=?, updated_at=?, escalation_level=0, escalated_to=NULL
           WHERE id=?""",
        (to_user_id, claim_due, close_due, now_value, risk_id),
    )
    conn.execute(
        "INSERT OR IGNORE INTO risk_watchers (risk_id, user_id, reason, created_at) VALUES (?, ?, ?, ?)",
        (risk_id, old_owner, "原负责人（保留可见权）", now_value),
    )
    conn.execute(
        """INSERT INTO risk_events
           (risk_id, event_type, actor_user_id, from_status, to_status, note, payload_json, created_at)
           VALUES (?, 'transferred', ?, ?, 'pending', ?, ?, ?)""",
        (risk_id, user["user_id"], risk["status"], note,
         json.dumps({"from_user_id": old_owner, "to_user_id": to_user_id,
                     "claim_due_at": claim_due, "close_due_at": close_due}, ensure_ascii=False),
         now_value),
    )
    create_notification(
        conn, to_user_id, "assignment", f"风险转派 · {risk_id}",
        f"{user['name']} 将风险转派给你：{risk['title']}。请及时认领处理。",
        f"#/risks/{risk_id}", risk_id, risk.get("batch_id"),
        f"risk_transferred:{risk_id}:{to_user_id}:{now_value}",
    )
    write_audit(
        conn, user["user_id"], "risk.transfer", "risk", risk_id,
        f"转派给 {target['name']}（{to_user_id}）；说明：{note}",
        (request_meta or {}).get("ip"), (request_meta or {}).get("user_agent"),
    )
    return risk_detail_data(conn, user, risk_id)


def close_risk(
    conn: sqlite3.Connection, user: dict, risk_id: str, payload: dict | None,
    request_meta: dict | None = None,
) -> dict:
    risk = _fetch_accessible(conn, user, risk_id)
    if risk["status"] != "processing":
        raise RiskServiceError(409, "只有处理中的风险才能关闭，请先认领")
    payload = payload or {}
    result_status = str(payload.get("result_status") or "").strip()
    result_status = {"已关闭": "closed", "误报": "false_positive", "长期跟踪": "long_term"}.get(
        result_status, result_status
    )
    if result_status not in TERMINAL:
        raise RiskServiceError(400, "result_status 必须为 closed / false_positive / long_term")
    fields = {}
    for key, label in [("reason", "原因"), ("action", "动作"), ("result", "结果")]:
        value = str(payload.get(key) or "").strip()
        if len(value) < 5:
            raise RiskServiceError(400, f"{label}至少填写 5 个字")
        fields[key] = value
    now_value = now_iso()
    conn.execute(
        """UPDATE risks SET status=?, close_result_status=?, close_reason=?, close_action=?,
             close_result=?, closed_at=?, updated_at=? WHERE id=?""",
        (result_status, result_status, fields["reason"], fields["action"], fields["result"],
         now_value, now_value, risk_id),
    )
    conn.execute(
        """INSERT INTO risk_events
           (risk_id, event_type, actor_user_id, from_status, to_status, note, payload_json, created_at)
           VALUES (?, 'closed', ?, 'processing', ?, ?, ?, ?)""",
        (risk_id, user["user_id"], result_status,
         f"{fields['reason']}；动作：{fields['action']}；结果：{fields['result']}",
         json.dumps({"result_status": result_status, **fields}, ensure_ascii=False), now_value),
    )
    write_audit(
        conn, user["user_id"], "risk.close", "risk", risk_id,
        f"关闭为 {STATUS_LABELS.get(result_status, result_status)}；{_audit_meta_detail(fields)}",
        (request_meta or {}).get("ip"), (request_meta or {}).get("user_agent"),
    )
    return risk_detail_data(conn, user, risk_id)


def _by_role(conn: sqlite3.Connection, role: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM users WHERE role=? AND active=1 ORDER BY CASE WHEN is_demo=1 THEN 0 ELSE 1 END, user_id LIMIT 1",
        (role,),
    ).fetchone()
    return dict(row) if row else None


def _manual_escalation_target(
    conn: sqlite3.Connection, user: dict, new_level: int
) -> dict | None:
    """手动升级对象：最高级（2 级）统一进入总经理池，1 级按汇报关系上送。"""
    if user["role"] == "gm":
        return _by_role(conn, "gm")
    if user["role"] == "sd":
        return _by_role(conn, "gm")
    if user["role"] == "bu":
        return _by_role(conn, "gm") if new_level >= 2 else _by_role(conn, "sd")
    return None


def escalate_risk(
    conn: sqlite3.Connection, user: dict, risk_id: str, note: str | None = None,
    request_meta: dict | None = None,
) -> dict:
    if user["role"] not in ESCALATE_ROLES:
        raise RiskServiceError(403, "当前角色无权手动升级风险")
    risk = _fetch_accessible(conn, user, risk_id)
    if risk["status"] in TERMINAL:
        raise RiskServiceError(409, "已结束的风险不能升级")
    current_level = int(risk.get("escalation_level") or 0)
    if current_level >= 2:
        raise RiskServiceError(409, "已达到最高升级级别（2 级）")
    new_level = min(2, current_level + 1)
    target = _manual_escalation_target(conn, user, new_level)
    if not target:
        raise RiskServiceError(400, "未找到可升级对象")
    now_value = now_iso()
    reason = (note or "").strip() or "管理员/上级手动升级"
    conn.execute(
        "UPDATE risks SET escalation_level=?, escalated_to=?, updated_at=? WHERE id=?",
        (new_level, target["user_id"], now_value, risk_id),
    )
    conn.execute(
        """INSERT INTO risk_events
           (risk_id, event_type, actor_user_id, from_status, to_status, note, payload_json, created_at)
           VALUES (?, 'escalated', ?, ?, ?, ?, ?, ?)""",
        (risk_id, user["user_id"], risk["status"], risk["status"], reason,
         json.dumps({"level": new_level, "to_user_id": target["user_id"], "automatic": False},
                    ensure_ascii=False), now_value),
    )
    refreshed = dict(conn.execute("SELECT * FROM risks WHERE id=?", (risk_id,)).fetchone())
    notify_escalation(conn, refreshed, target, new_level, reason, risk.get("batch_id"), automatic=False)
    write_audit(
        conn, user["user_id"], "risk.escalate", "risk", risk_id,
        f"升级至第 {new_level} 级：{target['name']}；{reason}",
        (request_meta or {}).get("ip"), (request_meta or {}).get("user_agent"),
    )
    return risk_detail_data(conn, user, risk_id)


def _auto_target(conn: sqlite3.Connection, risk: dict) -> dict | None:
    current_level = int(risk.get("escalation_level") or 0)
    if current_level == 0:
        owner = _user_any(conn, risk["owner_user_id"])
        if owner and owner.get("manager_id"):
            manager = get_user(conn, owner["manager_id"])
            if manager:
                return manager
        org = conn.execute("SELECT manager_user_id FROM orgs WHERE org_id=?", (risk["org_id"],)).fetchone()
        if org and org["manager_user_id"]:
            manager = get_user(conn, org["manager_user_id"])
            if manager:
                return manager
        return _by_role(conn, "sd") or _by_role(conn, "gm")
    return _by_role(conn, "gm")


def check_overdue_escalations(
    conn: sqlite3.Connection, limit: int = 50, batch_id: str | None = None
) -> int:
    """惰性检查：超时未认领自动升级一级，最多两级。

    幂等约束：同一段认领时限内只自动升级一次。以 claim_due_at 为界，
    若已存在自动升级事件且事件时间不早于当前时限，则不再重复升级；
    转派后 claim_due_at 会重算，进入新的时限段后才允许再次自动升级。
    """
    now = now_bj()
    now_value = now.isoformat(timespec="seconds")
    rows = conn.execute(
        """SELECT * FROM risks WHERE status='pending' AND claim_due_at < ?
           AND escalation_level < 2
           AND NOT EXISTS (
               SELECT 1 FROM risk_events e
               WHERE e.risk_id = risks.id AND e.event_type='escalated'
                 AND e.actor_user_id IS NULL AND e.created_at >= risks.claim_due_at
           )
           ORDER BY claim_due_at, id LIMIT ?""",
        (now_value, limit),
    ).fetchall()
    count = 0
    for row in rows:
        risk = dict(row)
        target = _auto_target(conn, risk)
        if not target:
            continue
        current_level = int(risk.get("escalation_level") or 0)
        new_level = min(2, current_level + 1)
        conn.execute(
            "UPDATE risks SET escalation_level=?, escalated_to=?, updated_at=? WHERE id=?",
            (new_level, target["user_id"], now_value, risk["id"]),
        )
        conn.execute(
            """INSERT INTO risk_events
               (risk_id, event_type, actor_user_id, from_status, to_status, note, payload_json, created_at)
               VALUES (?, 'escalated', NULL, 'pending', 'pending', ?, ?, ?)""",
            (risk["id"], "超过认领时限，系统自动升级",
             json.dumps({"level": new_level, "to_user_id": target["user_id"], "automatic": True},
                        ensure_ascii=False), now_value),
        )
        refreshed = dict(conn.execute("SELECT * FROM risks WHERE id=?", (risk["id"],)).fetchone())
        notify_escalation(conn, refreshed, target, new_level, "超过认领时限", batch_id or risk.get("batch_id"))
        count += 1
    return count
