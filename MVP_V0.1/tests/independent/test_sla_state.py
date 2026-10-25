"""SLA, state machine, transfer, timeout escalation."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from recompute import add_workdays

TZ = timezone(timedelta(hours=8))
CLAIM_HOURS = {"red": 4, "orange": 8}
CLOSE_WORKDAYS = {"red": 3, "orange": 5, "yellow": 10}


def _risk(env, rule_id: str, object_id: str) -> dict:
    row = env.one(
        "SELECT * FROM risks WHERE rule_id=? AND object_id=?", (rule_id, object_id)
    )
    assert row, (rule_id, object_id)
    return row


def _detail(env, risk_id: str) -> dict:
    response = env.get(f"/api/risks/{risk_id}")
    assert response.status_code == 200, response.text
    return response.json()


def test_sla_deadlines_for_all_risk_levels(env):
    env.login("gm")
    for risk in env.rows("SELECT * FROM risks"):
        created = datetime.fromisoformat(risk["created_at"])
        claim_due = datetime.fromisoformat(risk["claim_due_at"])
        close_due = datetime.fromisoformat(risk["close_due_at"])
        level = risk["level"]
        if level in CLAIM_HOURS:
            assert claim_due - created == timedelta(hours=CLAIM_HOURS[level]), risk["id"]
        else:
            assert claim_due == add_workdays(created, 1), risk["id"]
        assert close_due == add_workdays(created, CLOSE_WORKDAYS[level]), risk["id"]
        detail = _detail(env, risk["id"])
        assert detail["sla"]["claim_due_at"] == risk["claim_due_at"]
        assert detail["sla"]["close_due_at"] == risk["close_due_at"]
        assert detail["sla"]["claim_state"] in {"normal", "due_soon"}
        assert detail["sla"]["close_state"] in {"normal", "due_soon"}


def test_claim_moves_pending_to_processing_and_is_not_repeatable(env):
    row = _risk(env, "churn", "OPP-2026-0001")
    env.login("sm")
    response = env.post(
        f"/api/risks/{row['id']}/claim",
        json={"plan": "今天下午回访客户并确认预算", "due": "2026-10-25"},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["status"] == "processing"
    assert data["claimed_by"]["user_id"] == "u_sm"
    assert data["allowed_actions"]["claim"] is False
    assert data["allowed_actions"]["close"] is True
    assert any(event["event_type"] == "claimed" for event in data["timeline"])
    again = env.post(f"/api/risks/{row['id']}/claim", json={})
    assert again.status_code == 409


def test_close_requires_processing_and_all_three_texts(env):
    row = _risk(env, "target_gap", "E130")
    env.login("gm")
    assert env.post(
        f"/api/risks/{row['id']}/close",
        json={"result_status": "closed", "reason": "客户预算调整", "action": "重新排期", "result": "已确认下月"},
    ).status_code == 409
    assert env.post(f"/api/risks/{row['id']}/claim", json={"plan": "拉通商机"}).status_code == 200
    short = env.post(
        f"/api/risks/{row['id']}/close",
        json={"result_status": "closed", "reason": "太短", "action": "跟进", "result": "完成"},
    )
    assert short.status_code == 400
    closed = env.post(
        f"/api/risks/{row['id']}/close",
        json={
            "result_status": "closed",
            "reason": "客户预算调整，目标顺延至下月",
            "action": "重新排期并逐单确认签约日期",
            "result": "已与客户确认 11 月首周签约",
        },
    )
    assert closed.status_code == 200, closed.text
    data = closed.json()
    assert data["status"] == "closed"
    assert data["close"]["reason"].startswith("客户预算调整")
    assert data["allowed_actions"]["close"] is False
    assert any(event["event_type"] == "closed" for event in data["timeline"])
    listing = env.get("/api/risks?page_size=100").json()["items"]
    assert listing[-1]["id"] == row["id"], "已结束风险应置底"


def test_transfer_changes_owner_resets_sla_and_keeps_old_owner_watcher(env):
    row = _risk(env, "target_gap", "E140")
    env.login("bu")
    before = datetime.now(TZ)
    response = env.post(
        f"/api/risks/{row['id']}/transfer",
        json={"to_user_id": "u_ea3", "note": "华东三部更熟悉该客户，转由孙浩跟进"},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["owner"]["user_id"] == "u_ea3"
    assert data["status"] == "pending"
    assert data["claimed_by"] is None
    assert data["escalation"]["level"] == 0
    assert data["is_watcher"] is False
    assert any(w["user_id"] == "u_ea4" for w in data["watchers"])
    assert any(event["event_type"] == "transferred" for event in data["timeline"])
    claim_due = datetime.fromisoformat(data["sla"]["claim_due_at"])
    close_due = datetime.fromisoformat(data["sla"]["close_due_at"])
    assert timedelta(hours=4) - timedelta(seconds=120) <= claim_due - before <= timedelta(hours=4) + timedelta(seconds=120)
    expected_close = add_workdays(before, 3)
    assert abs((close_due - expected_close).total_seconds()) <= 120
    notification = env.one(
        "SELECT COUNT(*) AS c FROM notifications WHERE user_id='u_ea3' AND title LIKE '%转派%'"
    )
    assert notification["c"] >= 1


def test_department_manager_transfer_returns_403(env):
    row = _risk(env, "churn", "OPP-2026-0001")
    env.login("sm")
    response = env.post(
        f"/api/risks/{row['id']}/transfer",
        json={"to_user_id": "u_e101", "note": "转给销售代表跟进"},
    )
    assert response.status_code == 403


def test_timeout_escalation_runs_in_batch(env):
    row = _risk(env, "target_gap", "E130")
    env.execute(
        "UPDATE risks SET claim_due_at=?, escalation_level=0, escalated_to=NULL WHERE id=?",
        ("2026-10-24T00:00:00+08:00", row["id"]),
    )
    result = env.run_batch()
    assert result["status"] == "success"
    assert result["stats"]["escalation"]["escalated"] == 1
    env.login("gm")
    data = _detail(env, row["id"])
    assert data["escalation"]["level"] == 1
    assert data["escalation"]["escalated_to"]["user_id"] == "u_bu"
    assert any(
        event["event_type"] == "escalated" and event["payload"].get("automatic") is True
        for event in data["timeline"]
    )


def test_defect_lazy_escalation_not_triggered_by_risk_api(env):
    """P1: README and plan 4.1 promise lazy escalation when risk detail/list is opened."""
    row = _risk(env, "target_gap", "E130")
    env.execute(
        "UPDATE risks SET claim_due_at=?, escalation_level=0, escalated_to=NULL WHERE id=?",
        ("2026-10-24T00:00:00+08:00", row["id"]),
    )
    env.login("gm")
    env.get("/api/risks?page_size=100")
    data = _detail(env, row["id"])
    assert data["escalation"]["level"] == 1, (
        "认领时限已过，列表/详情应触发 1 级惰性升级，且不能因重复读取连升两级"
    )
    auto_events = [
        event for event in data["timeline"]
        if event["event_type"] == "escalated" and event["payload"].get("automatic") is True
    ]
    assert len(auto_events) == 1, "同一认领时限内自动升级应幂等，只写 1 条事件"


def test_defect_manual_bu_escalation_level2_targets_sd_not_gm(env):
    """P2: final escalation level must enter the general manager pool."""
    row = _risk(env, "target_gap", "E140")
    env.execute(
        "UPDATE risks SET escalation_level=1, escalated_to='u_sd' WHERE id=?", (row["id"],)
    )
    env.login("bu")
    response = env.post(f"/api/risks/{row['id']}/escalate", json={"note": "连续两周未改善"})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["escalation"]["level"] == 2
    assert data["escalation"]["escalated_to"]["user_id"] == "u_gm", (
        "二级升级应进入总经理风险池，实际 escalated_to=%s"
        % data["escalation"]["escalated_to"]["user_id"]
    )
    assert data["escalation"]["in_general_manager_pool"] is True
