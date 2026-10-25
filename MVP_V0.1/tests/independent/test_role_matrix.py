"""Role-by-action permission matrix for detail, drill, transfer and close."""
from __future__ import annotations

import pytest

IN_SCOPE = [
    ("gm", "target_gap", "E140"),
    ("sd", "target_gap", "E140"),
    ("bu", "target_gap", "E140"),
    ("sm", "churn", "OPP-2026-0001"),
]

DRILL = [
    ("gm", "C001", "org", {"E100", "S200", "N300", "W400"}),
    ("sd", "C001", "org", {"E100", "S200", "N300", "W400"}),
    ("bu", "E100", "org", {"E110", "E120", "E130", "E140"}),
    ("sm", "E110", "user", {"u_sm", "u_e101", "u_e102", "u_e103"}),
]


def _risk_id(env, rule_id: str, object_id: str) -> str:
    row = env.one(
        "SELECT id FROM risks WHERE rule_id=? AND object_id=?", (rule_id, object_id)
    )
    assert row, (rule_id, object_id)
    return row["id"]


@pytest.mark.parametrize("role,rule_id,object_id", IN_SCOPE)
def test_each_role_can_view_in_scope_risk_detail(env, role, rule_id, object_id):
    env.login(role)
    response = env.get(f"/api/risks/{_risk_id(env, rule_id, object_id)}")
    assert response.status_code == 200, response.text
    assert response.json()["object"]["id"] == object_id


@pytest.mark.parametrize("role,root,drill_type,expected_ids", DRILL)
def test_metric_drill_is_scoped_for_each_role(env, role, root, drill_type, expected_ids):
    env.login(role)
    response = env.get("/api/metrics/target_completion_rate/drill")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["scope"]["org_id"] == root
    assert data["drill_type"] == drill_type
    assert {item["id"] for item in data["items"]} == expected_ids
    assert data["total"]["value"] is not None


@pytest.mark.parametrize("role", ["gm", "sd"])
def test_gm_and_sd_can_transfer_in_scope_risk(env, role):
    env.login(role)
    response = env.post(
        f"/api/risks/{_risk_id(env, 'target_gap', 'E140')}/transfer",
        json={"to_user_id": "u_ea3", "note": "由华东三部继续跟进该客户"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["owner"]["user_id"] == "u_ea3"


@pytest.mark.parametrize("role,rule_id,object_id", IN_SCOPE)
def test_each_role_can_close_after_claim(env, role, rule_id, object_id):
    env.login(role)
    risk_id = _risk_id(env, rule_id, object_id)
    assert env.post(f"/api/risks/{risk_id}/claim", json={"plan": "已安排客户沟通"}).status_code == 200
    response = env.post(
        f"/api/risks/{risk_id}/close",
        json={
            "result_status": "closed",
            "reason": "客户确认本月内完成签约",
            "action": "锁定签约日期并逐单跟进",
            "result": "已取得客户书面确认",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "closed"
