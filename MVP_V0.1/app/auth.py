"""演示登录与会话。

这不是生产认证：仅允许四个预置演示账号，使用 itsdangerous 签名 Cookie。
所有业务 API 都通过 FastAPI 依赖再次读取数据库中的用户，停用账号立即失效。
"""
from __future__ import annotations

import sqlite3

from fastapi import HTTPException, Request, Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from .config import SECRET_KEY, SESSION_COOKIE, SESSION_MAX_AGE, now_iso
from .db import connect
from .privacy import mask_email, mask_phone
from .scope import demo_users, get_org, get_user, role_label, scope_label, user_scope_org_ids


class AuthError(HTTPException):
    def __init__(self, status_code: int, detail: str):
        super().__init__(status_code=status_code, detail=detail)


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(SECRET_KEY, salt="mvp-demo-session-v1")


def issue_session(response: Response, user_id: str) -> str:
    token = _serializer().dumps({"user_id": user_id})
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=False,
        path="/",
    )
    return token


def clear_session(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


def read_session(request: Request) -> str | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    try:
        data = _serializer().loads(token, max_age=SESSION_MAX_AGE)
    except SignatureExpired as exc:
        raise AuthError(401, "登录已过期，请重新登录") from exc
    except BadSignature as exc:
        raise AuthError(401, "登录凭证无效，请重新登录") from exc
    user_id = data.get("user_id") if isinstance(data, dict) else None
    return user_id or None


def get_db(request: Request) -> sqlite3.Connection:
    """每个请求一个 SQLite 连接，请求结束自动关闭。"""
    db_path = getattr(request.app.state, "db_path", None)
    if db_path is None:
        raise AuthError(500, "数据库未初始化")
    conn = connect(db_path)
    try:
        yield conn
    finally:
        conn.close()


def current_user(request: Request, conn: sqlite3.Connection) -> dict:
    user_id = read_session(request)
    if not user_id:
        raise AuthError(401, "未登录，请先登录演示账号")
    user = get_user(conn, user_id)
    if not user:
        raise AuthError(401, "账号不存在或已停用，请重新登录")
    return user


def require_roles(user: dict, *roles: str) -> None:
    if user["role"] not in set(roles):
        raise AuthError(403, "当前角色无权执行该操作")


def request_meta(request: Request) -> dict:
    return {
        "ip": request.client.host if request.client else None,
        "user_agent": request.headers.get("user-agent"),
    }


def user_profile(conn: sqlite3.Connection, user: dict, include_scope: bool = True) -> dict:
    org = get_org(conn, user["org_id"])
    data = {
        "user_id": user["user_id"],
        "name": user["name"],
        "role": user["role"],
        "role_label": role_label(user),
        "title": user["title"],
        "org_id": user["org_id"],
        "org_name": org["name"] if org else user["org_id"],
        "phone": mask_phone(user.get("phone")),
        "email": mask_email(user.get("email")),
        "is_demo": bool(user.get("is_demo")),
        "demo_notice": "演示环境：本登录仅用于本地演示，不是生产认证。",
        "server_time": now_iso(),
    }
    if include_scope:
        data["scope"] = {
            "label": scope_label(conn, user),
            "permission": "本事业部及下级" if user["role"] == "bu" else (
                "本部门及本人" if user["role"] == "sm" else "全公司"
            ),
            "org_ids": user_scope_org_ids(conn, user),
        }
    return data


def demo_login_options(conn: sqlite3.Connection) -> list[dict]:
    items = []
    for user in demo_users(conn):
        org = get_org(conn, user["org_id"])
        items.append({
            "user_id": user["user_id"],
            "name": user["name"],
            "role": user["role"],
            "role_label": role_label(user),
            "title": user["title"],
            "org_name": org["name"] if org else user["org_id"],
            "phone": mask_phone(user.get("phone")),
            "email": mask_email(user.get("email")),
            "scope_label": scope_label(conn, user),
        })
    return items


def authenticate_demo_user(conn: sqlite3.Connection, user_id: str) -> dict:
    user_id = (user_id or "").strip()
    if not user_id:
        raise AuthError(400, "请选择演示账号")
    user = get_user(conn, user_id)
    if not user or not user.get("is_demo"):
        raise AuthError(403, "只允许登录预置演示账号")
    return user
