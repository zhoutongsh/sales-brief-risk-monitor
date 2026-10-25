"""审计日志写入。"""
from __future__ import annotations

import sqlite3

from .config import now_iso


def write_audit(
    conn: sqlite3.Connection, user_id: str | None, action: str, resource_type: str,
    resource_id: str | None = None, detail: str = "", ip: str | None = None,
    user_agent: str | None = None,
) -> None:
    conn.execute(
        """INSERT INTO audit_logs
           (user_id, action, resource_type, resource_id, detail, ip, user_agent, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (user_id, action, resource_type, resource_id, detail or "", ip, user_agent, now_iso()),
    )
