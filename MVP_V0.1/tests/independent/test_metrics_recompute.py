"""Twelve core metrics recomputed independently from data/source/*.csv."""
from __future__ import annotations

import math

import pytest

from recompute import DEMO_DATE, compute_metrics, half_up, wan

ROOT_BY_ROLE = {"gm": "C001", "sd": "C001", "bu": "E100", "sm": "E110"}
MONEY_KEYS = {"pipeline_amount", "contract_amount", "ad_spend", "collection_amount"}
COUNT_KEYS = {"new_leads", "valid_leads", "new_opportunities", "contract_count"}
RATE_KEYS = {
    "lead_valid_rate", "lead_conversion_rate", "target_completion_rate",
    "collection_completion_rate", "leads_wow", "contract_wow", "time_progress",
}
MULTIPLE_KEYS = {"opportunity_coverage", "marketing_roi"}


def _api_metrics(env, role: str) -> dict:
    env.login(role)
    response = env.get(f"/api/metrics?date={DEMO_DATE.isoformat()}")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["data_available"] is True
    return {item["key"]: item for item in payload["metrics"] + payload["auxiliary"]}


@pytest.mark.parametrize("role", ["gm", "sd", "bu", "sm"])
def test_twelve_metrics_match_source_within_tolerance(env, role):
    root = ROOT_BY_ROLE[role]
    expected = compute_metrics(env.source_dir, root, DEMO_DATE)
    api = _api_metrics(env, role)
    snapshots = {
        row["metric_key"]: row["value"]
        for row in env.rows(
            "SELECT metric_key, value FROM metric_snapshots "
            "WHERE as_of=? AND scope_type='org' AND scope_id=?",
            (DEMO_DATE.isoformat(), root),
        )
    }
    assert len(snapshots) == 17, f"expected 12 core + 5 auxiliary snapshots, got {len(snapshots)}"

    for key in [
        "new_leads", "valid_leads", "lead_valid_rate", "lead_conversion_rate",
        "new_opportunities", "pipeline_amount", "opportunity_coverage",
        "contract_amount", "contract_count", "target_completion_rate",
        "collection_completion_rate", "marketing_roi",
    ]:
        assert key in api, f"missing core metric {key}"
        want = expected[key]
        got_db = snapshots.get(key)
        if want is None:
            assert got_db is None, f"{role}/{key}: missing must stay null, got {got_db}"
            assert api[key]["value"] is None and api[key]["display"] == "—"
            continue
        if key in MONEY_KEYS:
            assert got_db is not None
            assert abs(float(got_db) - float(want)) <= 1.0, (
                f"{role}/{key}: DB {got_db} vs source {want}, >1 yuan"
            )
            assert api[key]["value"] == pytest.approx(wan(want), abs=1e-9)
        elif key in COUNT_KEYS:
            assert int(got_db) == int(want)
            assert api[key]["value"] == int(want)
        elif key in RATE_KEYS:
            assert abs(float(got_db) - float(want)) <= 0.1, (
                f"{role}/{key}: DB {got_db} vs source {want}, >0.1pp"
            )
            assert api[key]["value"] == pytest.approx(half_up(want), abs=1e-9)
        elif key in MULTIPLE_KEYS:
            assert abs(float(got_db) - float(want)) <= 0.1, (
                f"{role}/{key}: DB {got_db} vs source {want}, >0.1"
            )
            assert api[key]["value"] == pytest.approx(half_up(want), abs=1e-9)
        else:  # pragma: no cover
            raise AssertionError(key)


@pytest.mark.parametrize("role", ["gm", "sd", "bu", "sm"])
def test_auxiliary_metrics_match_source(env, role):
    root = ROOT_BY_ROLE[role]
    expected = compute_metrics(env.source_dir, root, DEMO_DATE)
    api = _api_metrics(env, role)
    for key in ["ad_spend", "collection_amount", "leads_wow", "contract_wow", "time_progress"]:
        assert key in api, f"missing auxiliary metric {key}"
        want = expected[key]
        if want is None:
            assert api[key]["value"] is None
        elif key in {"ad_spend", "collection_amount"}:
            assert api[key]["value"] == pytest.approx(wan(want), abs=1e-9)
        else:
            assert api[key]["value"] == pytest.approx(half_up(want), abs=1e-9)


def test_roi_is_company_level_and_uses_company_ad_spend(env):
    expected_c001 = compute_metrics(env.source_dir, "C001", DEMO_DATE)
    expected_e100 = compute_metrics(env.source_dir, "E100", DEMO_DATE)
    assert expected_c001["ad_spend"] == expected_e100["ad_spend"]
    assert expected_c001["attributed_signed"] != expected_e100["attributed_signed"]
    env.login("bu")
    payload = env.get(f"/api/metrics?date={DEMO_DATE.isoformat()}").json()
    roi = next(item for item in payload["metrics"] if item["key"] == "marketing_roi")
    assert roi["value"] == pytest.approx(half_up(expected_e100["marketing_roi"]), abs=1e-9)
    assert math.isclose(expected_e100["marketing_roi"], 2.774, abs_tol=0.01)


def test_defect_sm_daily_conclusion_rounding_inconsistent(env):
    """P3: KPI card uses half-up 86.3%, conclusion text uses format() 86.2%."""
    env.login("sm")
    brief = env.get("/api/brief/daily").json()
    card = next(k for k in brief["kpis"] if k["key"] == "target_completion_rate")
    assert card["display"] == "86.3%"
    assert "86.3%" in brief["conclusions"][0]["text"], (
        "同一份日报中目标完成率卡片=%s，结论=%s"
        % (card["display"], brief["conclusions"][0]["text"])
    )


def test_metrics_missing_day_returns_null_not_zero(env):
    env.login("gm")
    response = env.get("/api/metrics?date=2026-10-23")
    assert response.status_code == 200
    payload = response.json()
    assert payload["data_available"] is False
    assert payload["message"]
    for item in payload["metrics"]:
        assert item["value"] is None, f"{item['key']} should be null, got {item['value']}"
        assert item["display"] == "—"
        assert item["available"] is False
    assert env.get("/api/brief/daily?date=2026-10-23").status_code == 404
    assert env.get("/api/quality?date=2026-10-23").status_code == 404
