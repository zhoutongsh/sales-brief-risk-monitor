"""Permission matrix, field masking, and audit trail."""
from __future__ import annotations

import re

import pytest

PHONE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def test_unauthenticated_requests_return_401(env):
    for path in [
        "/api/me",
        "/api/metrics",
        "/api/metrics/target_completion_rate/drill",
        "/api/brief/daily",
        "/api/brief/weekly",
        "/api/risks",
        "/api/export/brief.xlsx",
        "/api/export/risks.xlsx",
        "/api/print/brief",
        "/api/notifications",
        "/api/audit",
    ]:
        assert env.get(path).status_code == 401, path


@pytest.mark.parametrize("role", ["gm", "sd", "bu", "sm"])
def test_all_roles_can_read_their_own_data(env, role):
    env.login(role)
    for path in ["/api/me", "/api/metrics", "/api/brief/daily", "/api/brief/weekly", "/api/risks", "/api/rules"]:
        response = env.get(path)
        assert response.status_code == 200, (role, path, response.text)
    profile = env.get("/api/me").json()
    assert profile["user_id"] == f"u_{role}"
    assert profile["scope"]["org_ids"]


@pytest.mark.parametrize("role", ["sd", "bu", "sm"])
def test_only_gm_can_read_audit_and_patch_rules_and_run_batch(env, role):
    env.login(role)
    assert env.get("/api/audit").status_code == 403
    assert env.patch("/api/rules/target_gap", json={"params": {"yellow_gap_pp": 2}}).status_code == 403
    assert env.post("/api/admin/batch/run", json={}).status_code == 403
    rules = env.get("/api/rules").json()
    assert rules["can_edit"] is False
    assert all(item["editable"] is False for item in rules["items"])


def test_gm_can_read_audit_patch_rules_and_run_batch(env):
    env.login("gm")
    assert env.get("/api/audit").status_code == 200
    response = env.patch("/api/rules/target_gap", json={"params": {"yellow_gap_pp": 2}})
    assert response.status_code == 200
    assert response.json()["params"]["yellow_gap_pp"] == 2
    assert env.post("/api/admin/batch/run", json={}).status_code == 200


def test_risk_detail_row_level_permissions(env):
    ids = {
        row["object_id"]: row["id"]
        for row in env.rows("SELECT id, object_id FROM risks")
    }
    env.login("bu")
    assert env.get(f"/api/risks/{ids['E140']}").status_code == 200
    assert env.get(f"/api/risks/{ids['W400']}").status_code == 403
    assert env.get(f"/api/risks/{ids['SO-2026-0054']}").status_code == 403
    env.login("sm")
    assert env.get(f"/api/risks/{ids['OPP-2026-0001']}").status_code == 200
    assert env.get(f"/api/risks/{ids['E140']}").status_code == 403
    assert env.get(f"/api/risks/{ids['AR-2026-0061']}").status_code == 403


def test_phone_and_email_are_masked_everywhere(env):
    env.login("gm")
    payloads = [
        env.get("/api/me").text,
        env.get("/api/risks?page_size=100").text,
        env.get("/api/risks/" + env.one("SELECT id FROM risks LIMIT 1")["id"]).text,
        env.get("/api/export/risks.xlsx").content.decode("latin-1", errors="ignore"),
    ]
    for text in payloads:
        assert not PHONE.search(text), "raw 11-digit phone leaked"
        assert not EMAIL.search(text), "raw email leaked"
    profile = env.get("/api/me").json()
    assert profile["phone"] == "138****1001"
    assert profile["email"] == "zh***@corp.com"
    export = env.get("/api/export/risks.xlsx")
    assert export.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


def test_audit_records_all_required_actions(env):
    env.login("gm")
    risk_id = env.one("SELECT id FROM risks WHERE rule_id='target_gap' AND object_id='E130'")["id"]
    env.get("/api/brief/daily")
    env.get(f"/api/risks/{risk_id}")
    env.get("/api/export/brief.xlsx")
    assert env.post(f"/api/risks/{risk_id}/claim", json={"plan": "拉通重点商机"}).status_code == 200
    assert env.post(
        f"/api/risks/{risk_id}/transfer",
        json={"to_user_id": "u_sd", "note": "升级到销售总监协调"},
    ).status_code == 200
    assert env.post(f"/api/risks/{risk_id}/claim", json={"plan": "总监已接手"}).status_code == 200
    assert env.post(
        f"/api/risks/{risk_id}/close",
        json={
            "result_status": "long_term",
            "reason": "客户预算延后，需长期跟踪",
            "action": "每月回访并更新商机阶段",
            "result": "已纳入长期跟踪清单",
        },
    ).status_code == 200
    assert env.patch("/api/rules/target_gap", json={"params": {"yellow_gap_pp": 2}}).status_code == 200
    audit = env.get("/api/audit?limit=200").json()
    actions = {item["action"] for item in audit["items"]}
    for action in [
        "auth.login", "brief.view", "risk.view", "export.xlsx",
        "risk.claim", "risk.transfer", "risk.close", "rule.update",
    ]:
        assert action in actions, f"missing audit action {action}"
    for item in audit["items"]:
        assert item["created_at"]
        assert item["user_id"]


def test_denied_access_is_audited(env):
    env.login("sm")
    assert env.get("/api/audit").status_code == 403
    env.login("gm")
    audit = env.get("/api/audit?action=access.denied&limit=50").json()
    assert audit["total"] >= 1
    assert any("/api/audit" in (item.get("resource_id") or "") for item in audit["items"])
