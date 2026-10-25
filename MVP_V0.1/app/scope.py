"""组织树与数据范围。

所有行级权限最终都落到 org_id 集合或 owner_user_id 上，由服务端统一过滤。
"""
from __future__ import annotations

import sqlite3
from datetime import date

from .config import DEMO_ROLE_SCOPES, DEMO_ROLE_TITLES, STATUS_ALIASES


def get_org(conn: sqlite3.Connection, org_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM orgs WHERE org_id = ?", (org_id,)).fetchone()
    return dict(row) if row else None


def all_orgs(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM orgs ORDER BY sort_order, org_id").fetchall()
    return [dict(r) for r in rows]


def org_descendants(conn: sqlite3.Connection, org_id: str, include_self: bool = True) -> list[str]:
    orgs = all_orgs(conn)
    children: dict[str | None, list[str]] = {}
    for o in orgs:
        children.setdefault(o["parent_id"], []).append(o["org_id"])
    result: list[str] = []

    def walk(oid: str) -> None:
        result.append(oid)
        for child in children.get(oid, []):
            walk(child)

    if include_self and org_id not in children:
        # 叶子节点
        result.append(org_id)
    elif include_self:
        walk(org_id)
    else:
        for child in children.get(org_id, []):
            walk(child)
    return result


def org_ancestors(conn: sqlite3.Connection, org_id: str, include_self: bool = False) -> list[str]:
    orgs = {o["org_id"]: o for o in all_orgs(conn)}
    chain: list[str] = []
    cur = org_id if include_self else (orgs.get(org_id) or {}).get("parent_id")
    while cur and cur in orgs:
        chain.append(cur)
        cur = orgs[cur].get("parent_id")
    return chain


def org_path_name(conn: sqlite3.Connection, org_id: str) -> str:
    orgs = {o["org_id"]: o for o in all_orgs(conn)}
    parts: list[str] = []
    cur = org_id
    seen = set()
    while cur and cur in orgs and cur not in seen:
        seen.add(cur)
        parts.append(orgs[cur]["name"])
        cur = orgs[cur].get("parent_id")
    return " / ".join(reversed(parts))


def get_user(conn: sqlite3.Connection, user_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM users WHERE user_id = ? AND active = 1", (user_id,)).fetchone()
    return dict(row) if row else None


def demo_users(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM users WHERE is_demo = 1 AND active = 1 ORDER BY CASE role "
        "WHEN 'gm' THEN 1 WHEN 'sd' THEN 2 WHEN 'bu' THEN 3 WHEN 'sm' THEN 4 ELSE 9 END"
    ).fetchall()
    return [dict(r) for r in rows]


def user_scope_org_ids(conn: sqlite3.Connection, user: dict) -> list[str]:
    """功能/数据范围。公司层角色是全公司；总监也是全公司销售条线。"""
    if user["role"] in {"gm", "sd"}:
        return [o["org_id"] for o in all_orgs(conn)]
    return org_descendants(conn, user["org_id"], include_self=True)


def user_scope_root(conn: sqlite3.Connection, user: dict) -> str:
    if user["role"] in {"gm", "sd"}:
        root = conn.execute("SELECT org_id FROM orgs WHERE parent_id IS NULL ORDER BY sort_order LIMIT 1").fetchone()
        return root["org_id"] if root else user["org_id"]
    return user["org_id"]


def scope_label(conn: sqlite3.Connection, user: dict) -> str:
    if user["role"] in {"gm", "sd"}:
        return "全公司"
    org = get_org(conn, user["org_id"])
    return org["name"] if org else user["org_id"]


def role_label(user: dict) -> str:
    return DEMO_ROLE_TITLES.get(user["role"], user.get("title") or user["role"])


def scope_permission_label(user: dict) -> str:
    return DEMO_ROLE_SCOPES.get(user["role"], "本人")


def can_view_org(conn: sqlite3.Connection, user: dict, org_id: str | None) -> bool:
    if not org_id:
        return False
    if user["role"] in {"gm", "sd"}:
        return True
    return org_id in set(org_descendants(conn, user["org_id"], include_self=True))


def child_scope_orgs(conn: sqlite3.Connection, root_org_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM orgs WHERE parent_id = ? ORDER BY sort_order, org_id",
        (root_org_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def scope_users(conn: sqlite3.Connection, org_ids: list[str]) -> list[dict]:
    if not org_ids:
        return []
    placeholders = ",".join("?" for _ in org_ids)
    rows = conn.execute(
        f"SELECT * FROM users WHERE active = 1 AND org_id IN ({placeholders}) "
        "AND role IN ('sm','rep','bu') ORDER BY CASE role WHEN 'bu' THEN 1 WHEN 'sm' THEN 2 ELSE 3 END, org_id, user_id",
        org_ids,
    ).fetchall()
    return [dict(r) for r in rows]


def target_for_org(conn: sqlite3.Connection, org_id: str, month: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM targets WHERE org_id = ? AND month = ? AND COALESCE(user_id,'') = ''",
        (org_id, month),
    ).fetchone()
    return dict(row) if row else None


def target_for_user(conn: sqlite3.Connection, user_id: str, month: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM targets WHERE user_id = ? AND month = ? "
        "ORDER BY CASE WHEN org_id = (SELECT org_id FROM users WHERE user_id = ?) THEN 0 ELSE 1 END LIMIT 1",
        (user_id, month, user_id),
    ).fetchone()
    return dict(row) if row else None


def normalize_status(value: str | None) -> str | None:
    if not value or value == "all":
        return None
    return STATUS_ALIASES.get(value, value)


def month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"
