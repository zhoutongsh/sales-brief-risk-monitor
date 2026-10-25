"""Independent business recomputation from the raw CSV files.

This module intentionally does not import app.metrics or app.rules, so the
expected values are derived from the source data and the written rules only.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

DEMO_DATE = date(2026, 10, 24)
MONTH_START = date(2026, 10, 1)
MONTH_END = date(2026, 10, 31)


def half_up(value: float | int | None, digits: int = 1):
    if value is None:
        return None
    quant = Decimal("1").scaleb(-digits)
    return float(Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP))


def wan(value: float | None) -> float | None:
    if value is None:
        return None
    return half_up(float(value) / 10000.0, 1)


def add_workdays(start: datetime, days: int) -> datetime:
    result = start
    remaining = days
    while remaining > 0:
        result += timedelta(days=1)
        if result.weekday() < 5:
            remaining -= 1
    return result


def read_csv(source_dir: Path, name: str) -> list[dict]:
    with (source_dir / name).open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


class OrgTree:
    def __init__(self, source_dir: Path):
        self.orgs = {row["org_id"]: row for row in read_csv(source_dir, "orgs.csv")}
        self.children: dict[str | None, list[str]] = {}
        for row in self.orgs.values():
            self.children.setdefault(row["parent_id"] or None, []).append(row["org_id"])

    def descendants(self, root: str) -> list[str]:
        result = [root]
        for child in sorted(self.children.get(root, [])):
            result.extend(self.descendants(child))
        return result


def compute_metrics(source_dir: Path, root_org_id: str, as_of: date = DEMO_DATE) -> dict:
    tree = OrgTree(source_dir)
    org_ids = set(tree.descendants(root_org_id))
    d = as_of.isoformat()
    month = d[:7]
    month_start = as_of.replace(day=1).isoformat()

    leads = [r for r in read_csv(source_dir, "leads.csv") if r["org_id"] in org_ids]
    opps = [r for r in read_csv(source_dir, "opportunities.csv") if r["org_id"] in org_ids]
    contracts = [r for r in read_csv(source_dir, "contracts.csv") if r["org_id"] in org_ids]
    receivables = [r for r in read_csv(source_dir, "receivables.csv") if r["org_id"] in org_ids]

    new_leads = [r for r in leads if r["created_date"] == d]
    valid_leads = [r for r in new_leads if r["status"] == "valid"]
    converted = [r for r in valid_leads if r["converted"] == "1"]
    new_opps = [r for r in opps if r["created_date"] == d]
    pipeline = sum(float(r["amount"]) for r in opps if r["status"] == "open" and r["created_date"] <= d)

    day_contracts = [r for r in contracts if r["sign_date"] == d and r["status"] == "active"]
    month_contracts = [
        r for r in contracts
        if month_start <= r["sign_date"] <= d and r["status"] == "active"
    ]
    month_signed = sum(float(r["amount"]) for r in month_contracts)

    target = next(
        (r for r in read_csv(source_dir, "targets.csv")
         if r["org_id"] == root_org_id and r["month"] == month and not r["user_id"]),
        None,
    )
    target_sign = float(target["sign_target"]) if target else None
    target_collection = float(target["collection_target"]) if target else None
    remaining = target_sign - month_signed if target_sign is not None else None

    collection_amount = sum(
        float(r["paid_amount"])
        for r in receivables
        if r["paid_date"] and month_start <= r["paid_date"] <= d
    )
    attributed = sum(
        float(r["amount"]) for r in month_contracts if r["campaign_id"].strip()
    )
    ad_spend = sum(
        float(r["spend"])
        for r in read_csv(source_dir, "ad_spend.csv")
        if month_start <= r["date"] <= d
    )
    week_start = as_of - timedelta(days=as_of.weekday())
    span = (as_of - week_start).days + 1
    prev_start = week_start - timedelta(days=7)
    prev_end = prev_start + timedelta(days=span - 1)
    cur_week_leads = sum(
        1 for r in leads
        if week_start.isoformat() <= r["created_date"] <= d
    )
    prev_week_leads = sum(
        1 for r in leads
        if prev_start.isoformat() <= r["created_date"] <= prev_end.isoformat()
    )
    cur_week_sign = sum(
        float(r["amount"]) for r in contracts
        if r["status"] == "active" and week_start.isoformat() <= r["sign_date"] <= d
    )
    prev_week_sign = sum(
        float(r["amount"]) for r in contracts
        if r["status"] == "active"
        and prev_start.isoformat() <= r["sign_date"] <= prev_end.isoformat()
    )

    return {
        "new_leads": len(new_leads),
        "valid_leads": len(valid_leads),
        "lead_valid_rate": len(valid_leads) / len(new_leads) * 100 if new_leads else None,
        "lead_conversion_rate": len(converted) / len(valid_leads) * 100 if valid_leads else None,
        "new_opportunities": len(new_opps),
        "pipeline_amount": pipeline,
        "opportunity_coverage": pipeline / remaining if remaining and remaining > 0 else None,
        "contract_amount": sum(float(r["amount"]) for r in day_contracts),
        "contract_count": len(day_contracts),
        "target_completion_rate": month_signed / target_sign * 100 if target_sign else None,
        "collection_completion_rate": collection_amount / target_collection * 100 if target_collection else None,
        "marketing_roi": attributed / ad_spend if ad_spend else None,
        # auxiliaries / helpers
        "ad_spend": ad_spend,
        "collection_amount": collection_amount,
        "leads_wow": (cur_week_leads / prev_week_leads * 100 - 100) if prev_week_leads else None,
        "contract_wow": (cur_week_sign / prev_week_sign * 100 - 100) if prev_week_sign else None,
        "month_signed": month_signed,
        "target_sign": target_sign,
        "remaining_target": remaining,
        "time_progress": as_of.day / 31 * 100,
        "attributed_signed": attributed,
    }


@dataclass(frozen=True)
class ExpectedRisk:
    rule_id: str
    object_type: str
    object_id: str
    level: str
    owner_user_id: str
    org_id: str
    amount_yuan: float

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.rule_id, self.object_type, self.object_id)


def compute_risks(source_dir: Path, as_of: date = DEMO_DATE) -> list[ExpectedRisk]:
    tree = OrgTree(source_dir)
    orgs = tree.orgs
    users = {r["user_id"]: r for r in read_csv(source_dir, "users.csv")}
    contracts = read_csv(source_dir, "contracts.csv")
    leads = read_csv(source_dir, "leads.csv")
    opportunities = read_csv(source_dir, "opportunities.csv")
    orders = read_csv(source_dir, "orders.csv")
    receivables = read_csv(source_dir, "receivables.csv")
    targets = read_csv(source_dir, "targets.csv")
    month = as_of.isoformat()[:7]
    month_start = as_of.replace(day=1)
    d = as_of.isoformat()
    time_progress = as_of.day / 31 * 100
    result: list[ExpectedRisk] = []

    # 1. target gap, one per org with an org-level target
    for org_id in sorted(orgs):
        target = next(
            (r for r in targets if r["org_id"] == org_id and r["month"] == month and not r["user_id"]),
            None,
        )
        if not target:
            continue
        ids = set(tree.descendants(org_id))
        signed = sum(
            float(r["amount"]) for r in contracts
            if r["status"] == "active" and month_start.isoformat() <= r["sign_date"] <= d
            and r["org_id"] in ids
        )
        target_amount = float(target["sign_target"])
        completion = signed / target_amount * 100
        gap = time_progress - completion
        if gap >= 15:
            level = "red"
        elif gap >= 8:
            level = "orange"
        elif gap >= 3:
            level = "yellow"
        else:
            continue
        owner = orgs[org_id]["manager_user_id"]
        result.append(ExpectedRisk(
            "target_gap", "org", org_id, level, owner, org_id, max(target_amount - signed, 0)
        ))

    # 2. decline: last three workdays that have contract data
    for org_id in sorted(orgs):
        ids = set(tree.descendants(org_id))
        by_date: dict[str, float] = {}
        for row in contracts:
            if row["status"] != "active" or row["sign_date"] > d or row["org_id"] not in ids:
                continue
            if date.fromisoformat(row["sign_date"]).weekday() > 4:
                continue
            by_date[row["sign_date"]] = by_date.get(row["sign_date"], 0.0) + float(row["amount"])
        dates = sorted(by_date)[-3:]
        if len(dates) < 3:
            continue
        a1, a2, a3 = (by_date[x] for x in dates)
        if a1 <= 0 or a2 <= 0:
            continue
        drop1 = (a2 / a1 - 1) * 100
        drop2 = (a3 / a2 - 1) * 100
        if drop1 > 0 or drop2 > 0:
            continue
        if abs(drop1) >= 30 and abs(drop2) >= 30:
            level = "red"
        elif abs(drop1) >= 20 and abs(drop2) >= 20:
            level = "orange"
        else:
            continue
        owner = orgs[org_id]["manager_user_id"]
        result.append(ExpectedRisk("decline", "org", org_id, level, owner, org_id, a3))

    # 3. leads: current week vs same span last week
    week_start = as_of - timedelta(days=as_of.weekday())
    span = (as_of - week_start).days
    prev_start = week_start - timedelta(days=7)
    prev_end = prev_start + timedelta(days=span)

    def lead_stats(ids: set[str], start: date, end: date):
        rows = [
            r for r in leads
            if r["org_id"] in ids and start.isoformat() <= r["created_date"] <= end.isoformat()
        ]
        return len(rows), sum(1 for r in rows if r["converted"] == "1"), sum(
            1 for r in rows if r["status"] == "valid"
        )

    for org_id in sorted(orgs):
        ids = set(tree.descendants(org_id))
        cur_n, cur_conv, cur_valid = lead_stats(ids, week_start, as_of)
        prev_n, prev_conv, prev_valid = lead_stats(ids, prev_start, prev_end)
        volume_drop = (cur_n / prev_n * 100 - 100) if prev_n else None
        cur_rate = cur_conv / cur_valid * 100 if cur_valid else None
        prev_rate = prev_conv / prev_valid * 100 if prev_valid else None
        conversion_drop = (
            (cur_rate / prev_rate - 1) * 100
            if cur_rate is not None and prev_rate else None
        )
        volume_trigger = volume_drop is not None and volume_drop <= -30
        conversion_trigger = conversion_drop is not None and conversion_drop <= -20
        if not (volume_trigger or conversion_trigger):
            continue
        level = "orange" if volume_trigger else "yellow"
        owner = orgs[org_id]["manager_user_id"]
        result.append(ExpectedRisk("leads", "org", org_id, level, owner, org_id, 0.0))

    # 4. opportunity coverage
    for org_id in sorted(orgs):
        target = next(
            (r for r in targets if r["org_id"] == org_id and r["month"] == month and not r["user_id"]),
            None,
        )
        if not target:
            continue
        ids = set(tree.descendants(org_id))
        pipeline = sum(
            float(r["amount"]) for r in opportunities
            if r["status"] == "open" and r["org_id"] in ids
        )
        signed = sum(
            float(r["amount"]) for r in contracts
            if r["status"] == "active" and month_start.isoformat() <= r["sign_date"] <= d
            and r["org_id"] in ids
        )
        remaining = float(target["sign_target"]) - signed
        if remaining <= 0:
            continue
        coverage = pipeline / remaining
        if coverage >= 2.5:
            continue
        owner = orgs[org_id]["manager_user_id"]
        result.append(ExpectedRisk("coverage", "org", org_id, "orange", owner, org_id, 0.0))

    # 5. churn
    for opp in sorted(opportunities, key=lambda r: r["opp_id"]):
        if opp["status"] != "open" or float(opp["amount"]) < 500000:
            continue
        if opp["created_date"] and opp["created_date"] > d:
            continue
        last = opp["last_followup_date"] or opp["created_date"]
        if not last:
            continue
        days = (as_of - date.fromisoformat(last)).days
        if days < 30:
            continue
        if opp["owner_id"] not in users:
            continue
        result.append(ExpectedRisk(
            "churn", "opportunity", opp["opp_id"], "red", opp["owner_id"],
            opp["org_id"], float(opp["amount"]),
        ))

    # 6. payment: cancelled orders then overdue receivables
    for order in sorted(orders, key=lambda r: (r["order_date"], r["order_id"])):
        if order["status"] != "cancelled" or float(order["amount"]) < 500000:
            continue
        if order["order_date"] > d or order["owner_id"] not in users:
            continue
        result.append(ExpectedRisk(
            "payment", "order", order["order_id"], "red", order["owner_id"],
            order["org_id"], float(order["amount"]),
        ))
    for recv in sorted(receivables, key=lambda r: (r["due_date"], r["recv_id"])):
        if recv["due_date"] > d:
            continue
        if recv["status"] == "paid" and float(recv["paid_amount"]) >= float(recv["amount"]):
            continue
        overdue = (as_of - date.fromisoformat(recv["due_date"])).days
        outstanding = float(recv["amount"]) - float(recv["paid_amount"] or 0)
        if overdue < 30 or outstanding <= 0 or recv["owner_id"] not in users:
            continue
        result.append(ExpectedRisk(
            "payment", "receivable", recv["recv_id"], "red", recv["owner_id"],
            recv["org_id"], outstanding,
        ))
    return result


def expected_risks_for_role(source_dir: Path, role: str, as_of: date = DEMO_DATE) -> list[ExpectedRisk]:
    tree = OrgTree(source_dir)
    risks = compute_risks(source_dir, as_of)
    if role in {"gm", "sd"}:
        return risks
    root = "E100" if role == "bu" else "E110"
    scope = set(tree.descendants(root))
    if role == "bu":
        return [r for r in risks if r.org_id in scope]
    # department manager: own department subtree, or explicitly owned
    return [r for r in risks if r.org_id in scope or r.owner_user_id == "u_sm"]
