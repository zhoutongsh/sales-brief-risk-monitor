"""字段脱敏工具。所有 API、导出和打印输出统一走这里。"""
from __future__ import annotations


def mask_phone(value: str | None) -> str | None:
    if not value:
        return value
    digits = str(value).strip()
    if len(digits) >= 7:
        return f"{digits[:3]}****{digits[-4:]}"
    if len(digits) >= 2:
        return f"{digits[0]}***"
    return "***"


def mask_email(value: str | None) -> str | None:
    if not value:
        return value
    text = str(value).strip()
    if "@" not in text:
        return text[:2] + "***" if text else text
    local, domain = text.split("@", 1)
    if not local:
        return "***@" + domain
    prefix = local[:2] if len(local) >= 2 else local[:1]
    return f"{prefix}***@{domain}"


def safe_user(user: dict | None) -> dict | None:
    """用户摘要，绝不下发密码或完整联系方式。"""
    if not user:
        return None
    return {
        "user_id": user.get("user_id"),
        "name": user.get("name"),
        "role": user.get("role"),
        "title": user.get("title"),
        "org_id": user.get("org_id"),
        "phone": mask_phone(user.get("phone")),
        "email": mask_email(user.get("email")),
    }
