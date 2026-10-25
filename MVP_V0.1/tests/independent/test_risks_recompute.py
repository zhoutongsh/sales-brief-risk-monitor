"""Six risk classes recomputed independently, plus evidence and merge checks."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import pytest

from recompute import DEMO_DATE, compute_risks, expected_risks_for_role

TZ = timezone(timedelta(hours=8))
RISK_ID = re.compile(r"^R-\d{8}-\d{3}$")


def _gm_risks(env) -> list[dict]:
    env.login("gm")
    response = env.get("/api/risks?page_size=100")
    assert response.status_code == 200, response.text
    return response.json()["items"]


def test_all_six_risk_classes_match_independent_recompute(env):
    expected = compute_risks(env.source_dir)
    assert len(expected) == 10
    actual = _gm_risks(env)
    assert len(actual) == 10
    by_key = {(r["rule_id"], r["object"]["type"], r["object"]["id"]): r for r in actual}
    assert set(by_key) == {r.key for r in expected}

    for want in expected:
        got = by_key[want.key]
        assert got["level"] == want.level, want
        assert got["owner"]["user_id"] == want.owner_user_id, want
        assert got["org"]["org_id"] == want.org_id, want
        assert got["amount"] == pytest.approx(want.amount_yuan / 10000.0, abs=1e-9)
        assert RISK_ID.match(got["id"]), got["id"]

    # Risk numbers are sequential and unique; list order itself is priority-sorted.
    db_ids = [r["id"] for r in env.rows("SELECT id FROM risks ORDER BY id")]
    assert db_ids == [f"R-20261024-{i:03d}" for i in range(1, 11)]

    # Database raw amounts stay in yuan and match the source exactly.
    db_rows = {
        (row["rule_id"], row["object_type"], row["object_id"]): row
        for row in env.rows("SELECT * FROM risks")
    }
    for want in expected:
        assert abs(float(db_rows[want.key]["amount"]) - want.amount_yuan) <= 1.0


def test_every_risk_has_three_complete_evidence_rows(env):
    expected = compute_risks(env.source_dir)
    env.login("gm")
    for want in expected:
        detail = env.get(f"/api/risks/{_risk_id(env, want.key)}")
        assert detail.status_code == 200
        data = detail.json()
        assert len(data["evidence"]) >= 3, want
        assert data["evidence_count"] >= 3
        for item in data["evidence"]:
            for field in ("current_value", "threshold", "baseline", "source", "triggered_at"):
                assert item.get(field), f"{want.key} evidence missing {field}: {item}"
            assert item["label"]
        assert len(data["timeline"]) >= 1
        assert data["timeline"][0]["event_type"] == "created"


def _risk_id(env, key: tuple[str, str, str]) -> str:
    row = env.one(
        "SELECT id FROM risks WHERE rule_id=? AND object_type=? AND object_id=?",
        key,
    )
    assert row, key
    return row["id"]


@pytest.mark.parametrize(
    "role,expected_count,expected_keys",
    [
        ("gm", 10, None),
        ("sd", 10, None),
        ("bu", 6, None),
        ("sm", 1, ("churn", "opportunity", "OPP-2026-0001")),
    ],
)
def test_risk_list_is_scoped_by_role(env, role, expected_count, expected_keys):
    expected = expected_risks_for_role(env.source_dir, role)
    assert len(expected) == expected_count
    env.login(role)
    response = env.get("/api/risks?page_size=100")
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == expected_count
    assert {(r["rule_id"], r["object"]["type"], r["object"]["id"]) for r in items} == {
        r.key for r in expected
    }
    if expected_keys:
        assert {(items[0]["rule_id"], items[0]["object"]["type"], items[0]["object"]["id"])} == {
            expected_keys
        }


def test_out_of_scope_risk_detail_returns_403(env):
    expected = {(r.rule_id, r.object_type, r.object_id): r for r in compute_risks(env.source_dir)}
    bu_403 = _risk_id(env, ("target_gap", "org", "W400"))
    sm_403 = _risk_id(env, ("target_gap", "org", "E140"))
    env.login("bu")
    assert env.get(f"/api/risks/{bu_403}").status_code == 403
    assert env.get(f"/api/risks/{_risk_id(env, ('payment', 'order', 'SO-2026-0054'))}").status_code == 403
    env.login("sm")
    assert env.get(f"/api/risks/{sm_403}").status_code == 403
    own = _risk_id(env, ("churn", "opportunity", "OPP-2026-0001"))
    assert env.get(f"/api/risks/{own}").status_code == 200


def test_24h_same_object_rule_merges_and_appends_evidence(env):
    # Make the first run unambiguously inside the 24h merge window.
    now = datetime.now(TZ).isoformat(timespec="seconds")
    env.execute("UPDATE risks SET last_seen_at=?", (now,))
    result = env.run_batch("2026-10-25")
    assert result["status"] == "success", result.get("error")
    stats = result["stats"]["risks"]
    assert stats["merged"] == 9, stats
    assert stats["created"] == 3, stats
    assert stats["skipped"] == 0, stats
    assert env.one("SELECT COUNT(*) AS c FROM risks")["c"] == 13

    merged = env.one("SELECT * FROM risks WHERE id='R-20261024-002'")
    assert merged["merged_count"] == 1
    assert merged["trigger_count"] == 2
    assert env.one(
        "SELECT COUNT(*) AS c FROM risk_evidence WHERE risk_id='R-20261024-002'"
    )["c"] == 6
    event_types = {
        row["event_type"] for row in env.rows(
            "SELECT event_type FROM risk_events WHERE risk_id='R-20261024-002'"
        )
    }
    assert "merged" in event_types


def test_defect_merged_evidence_history_is_hidden_by_detail_api(env):
    """P3: 24h merge appends evidence, but detail returns only the latest per key."""
    now = datetime.now(TZ).isoformat(timespec="seconds")
    env.execute("UPDATE risks SET last_seen_at=?", (now,))
    assert env.run_batch("2026-10-25")["status"] == "success"
    env.login("gm")
    detail = env.get("/api/risks/R-20261024-002").json()
    assert detail["evidence_count"] == 6
    assert len(detail["evidence"]) == 6, (
        "合并后 evidence_count=6，但详情只返回 %d 条证据，历史证据不可见"
        % len(detail["evidence"])
    )
    assert len(detail["latest_evidence"]) == 3, "最新证据视图应保留每个证据键各 1 条"
