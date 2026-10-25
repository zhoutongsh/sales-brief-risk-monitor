"""站内通知。

渠道字段保留为 in_app，未来可扩展短信/企业微信；本 MVP 只落站内消息。
所有写入用 dedupe_key 保证同日重跑不重复推送。
"""
from __future__ import annotations

import sqlite3

from .config import now_iso
from .scope import get_user


def _manager_of(conn: sqlite3.Connection, user: dict | None) -> dict | None:
    if not user:
        return None
    if user.get("manager_id"):
        manager = get_user(conn, user["manager_id"])
        if manager:
            return manager
    row = conn.execute(
        """SELECT u.* FROM orgs o JOIN users u ON o.manager_user_id = u.user_id
           WHERE o.org_id = ? AND u.active = 1""",
        (user.get("org_id"),),
    ).fetchone()
    return dict(row) if row else None


def _by_role(conn: sqlite3.Connection, role: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM users WHERE role = ? AND active = 1 ORDER BY CASE WHEN is_demo=1 THEN 0 ELSE 1 END, user_id LIMIT 1",
        (role,),
    ).fetchone()
    return dict(row) if row else None


def risk_recipients(conn: sqlite3.Connection, risk: dict) -> list[dict]:
    owner = get_user(conn, risk.get("owner_user_id"))
    recipients: list[dict] = []
    seen: set[str] = set()

    def add(user: dict | None) -> None:
        if user and user.get("active", 1) and user["user_id"] not in seen:
            seen.add(user["user_id"])
            recipients.append(user)

    add(owner)
    manager = _manager_of(conn, owner)
    if risk["level"] in {"red", "orange"}:
        add(manager)
    if risk["level"] == "red":
        add(_by_role(conn, "sd"))
        if float(risk.get("amount") or 0) >= 1_000_000:
            add(_by_role(conn, "gm"))
    return recipients


def create_notification(
    conn: sqlite3.Connection, user_id: str, kind: str, title: str, body: str,
    link: str | None, related_risk_id: str | None, batch_id: str | None, dedupe_key: str,
    created_at: str | None = None,
) -> bool:
    """写入一条站内消息；dedupe_key 冲突时忽略。返回是否新写入。"""
    before = conn.total_changes
    conn.execute(
        """INSERT OR IGNORE INTO notifications
           (user_id, kind, title, body, channel, link, related_risk_id, batch_id,
            dedupe_key, is_read, created_at)
           VALUES (?, ?, ?, ?, 'in_app', ?, ?, ?, ?, 0, ?)""",
        (user_id, kind, title, body, link, related_risk_id, batch_id, dedupe_key, created_at or now_iso()),
    )
    return conn.total_changes > before


def notify_risk_created(conn: sqlite3.Connection, risk: dict, batch_id: str | None) -> int:
    recipients = risk_recipients(conn, risk)
    level_text = {"red": "红色", "orange": "橙色", "yellow": "黄色"}.get(risk["level"], risk["level"])
    sla_text = {"red": "4 小时", "orange": "8 小时", "yellow": "1 个工作日"}.get(risk["level"], "")
    count = 0
    for user in recipients:
        body = f"{level_text}风险已生成：{risk['title']}。请在 {sla_text}内认领并跟进。"
        count += int(create_notification(
            conn, user["user_id"], "risk", f"新风险 · {risk['id']}", body,
            f"#/risks/{risk['id']}", risk["id"], batch_id,
            f"risk_created:{risk['id']}:{user['user_id']}",
            created_at=risk.get("created_at"),
        ))
    return count


def notify_escalation(
    conn: sqlite3.Connection, risk: dict, to_user: dict, level: int, reason: str,
    batch_id: str | None, automatic: bool = True,
) -> int:
    count = 0
    prefix = "超过认领时限，已自动升级" if automatic else "已手动升级"
    body = (
        f"风险 {risk['id']} {prefix}第 {level} 级。"
        f"当前责任人：{risk.get('owner_user_id') or '—'}。原因：{reason}"
    )
    count += int(create_notification(
        conn, to_user["user_id"], "escalation", f"风险升级 · {risk['id']}", body,
        f"#/risks/{risk['id']}", risk["id"], batch_id,
        f"risk_escalated:{risk['id']}:{level}:{to_user['user_id']}",
    ))
    owner = get_user(conn, risk.get("owner_user_id"))
    if owner and owner["user_id"] != to_user["user_id"]:
        count += int(create_notification(
            conn, owner["user_id"], "escalation", f"风险已升级 · {risk['id']}",
            f"你负责的风险 {risk['id']} 已升级至 {to_user['name']}（第 {level} 级）。",
            f"#/risks/{risk['id']}", risk["id"], batch_id,
            f"risk_escalated_owner:{risk['id']}:{level}:{owner['user_id']}",
        ))
    return count
