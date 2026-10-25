"""六类风险规则引擎。

实现严格对应开发规划第四节：
- 目标缺口、业绩下滑、线索异常、商机覆盖、大客户流失、订单/回款；
- 证据链包含当前值、阈值、基期、来源、触发时间；
- 24 小时同对象同规则合并，证据追加；
- 风险编号 R-YYYYMMDD-NNN；
- 每级 SLA 与升级在 risk_service 中执行，本模块负责生成初始风险与通知。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta

from .config import (
    LEVEL_LABELS,
    RISK_TYPES,
    SLA_CLAIM,
    SLA_CLOSE_WORKDAYS,
    add_workdays,
    now_bj,
    now_iso,
    parse_dt,
)
from .scope import all_orgs, get_org, get_user, org_descendants, target_for_org
from .metrics import compute_metrics


def load_rules(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM risk_rules ORDER BY CASE rule_id "
                        "WHEN 'target_gap' THEN 1 WHEN 'decline' THEN 2 WHEN 'leads' THEN 3 "
                        "WHEN 'coverage' THEN 4 WHEN 'churn' THEN 5 WHEN 'payment' THEN 6 ELSE 9 END").fetchall()
    result = []
    for row in rows:
        item = dict(row)
        try:
            item["params"] = json.loads(item.pop("params_json") or "{}")
        except json.JSONDecodeError:
            item["params"] = {}
        item["type_label"] = RISK_TYPES.get(item["rule_id"], item["name"])
        item["enabled"] = bool(item["enabled"])
        result.append(item)
    return result


def get_rule(conn: sqlite3.Connection, rule_id: str) -> dict | None:
    for rule in load_rules(conn):
        if rule["rule_id"] == rule_id:
            return rule
    return None


def _org_manager(conn: sqlite3.Connection, org_id: str) -> str | None:
    org = get_org(conn, org_id)
    if org and org.get("manager_user_id"):
        return org["manager_user_id"]
    row = conn.execute(
        "SELECT user_id FROM users WHERE org_id = ? AND role IN ('sm','bu') AND active=1 "
        "ORDER BY CASE role WHEN 'sm' THEN 0 ELSE 1 END, user_id LIMIT 1",
        (org_id,),
    ).fetchone()
    return row["user_id"] if row else None


def _ph(n: int) -> str:
    return ",".join("?" for _ in range(n))


def _fmt_wan(value: float | int | None) -> str:
    return f"{(float(value or 0) / 10000.0):,.1f} 万元"


def _fmt_pct(value: float | None, digits: int = 1) -> str:
    return "—" if value is None else f"{value:.{digits}f}%"


def _evidence(key: str, label: str, current: str, threshold: str, baseline: str,
              source: str, triggered_at: str, sort_order: int) -> dict:
    return {
        "evidence_key": key, "label": label, "current_value": current,
        "threshold": threshold, "baseline": baseline, "source": source,
        "triggered_at": triggered_at, "sort_order": sort_order,
    }


def _next_risk_id(conn: sqlite3.Connection, as_of: date) -> str:
    prefix = f"R-{as_of.strftime('%Y%m%d')}-"
    row = conn.execute(
        "SELECT id FROM risks WHERE id LIKE ? ORDER BY id DESC LIMIT 1", (prefix + "%",)
    ).fetchone()
    seq = 1
    if row:
        try:
            seq = int(row["id"].rsplit("-", 1)[1]) + 1
        except (ValueError, IndexError):
            seq = 1
    return f"{prefix}{seq:03d}"


def _find_recent_risk(
    conn: sqlite3.Connection, rule_id: str, object_type: str, object_id: str, cutoff: str
) -> dict | None:
    row = conn.execute(
        """SELECT * FROM risks WHERE rule_id = ? AND object_type = ? AND object_id = ?
           AND last_seen_at >= ? ORDER BY created_at DESC LIMIT 1""",
        (rule_id, object_type, object_id, cutoff),
    ).fetchone()
    return dict(row) if row else None


def _insert_risk(
    conn: sqlite3.Connection, batch_id: str, as_of: date, candidate: dict, now_iso_value: str
) -> dict:
    risk_id = _next_risk_id(conn, as_of)
    created = now_iso_value
    claim = SLA_CLAIM[candidate["level"]]
    if claim.get("hours"):
        claim_due = (parse_dt(created) + timedelta(hours=claim["hours"])).isoformat(timespec="seconds")
    else:
        claim_due = add_workdays(parse_dt(created), claim["workdays"]).isoformat(timespec="seconds")
    close_due = add_workdays(parse_dt(created), SLA_CLOSE_WORKDAYS[candidate["level"]]).isoformat(timespec="seconds")
    actions = candidate.get("actions") or []
    related = candidate.get("related") or []
    conn.execute(
        """INSERT INTO risks
           (id, batch_id, as_of, rule_id, dedupe_key, type, level, title, object_type, object_id,
            object_name, amount, org_id, dept, owner_user_id, status, created_at, updated_at,
            last_seen_at, claimed_at, claimed_by, claim_due_at, close_due_at, closed_at,
            close_result_status, close_reason, close_action, close_result, escalation_level,
            escalated_to, actions_json, related_json, merged_count, trigger_count, last_batch_date)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, NULL, NULL,
                   ?, ?, NULL, NULL, NULL, NULL, NULL, 0, NULL, ?, ?, 0, 1, ?)""",
        (
            risk_id, batch_id, as_of.isoformat(), candidate["rule_id"], candidate["dedupe_key"],
            candidate["rule_id"], candidate["level"], candidate["title"], candidate["object_type"],
            candidate["object_id"], candidate["object_name"], candidate["amount"], candidate["org_id"],
            candidate["dept"], candidate["owner_user_id"], created, created, created,
            claim_due, close_due, json.dumps(actions, ensure_ascii=False),
            json.dumps(related, ensure_ascii=False), as_of.isoformat(),
        ),
    )
    for ev in candidate.get("evidence", []):
        conn.execute(
            """INSERT INTO risk_evidence
               (risk_id, evidence_key, label, current_value, threshold, baseline, source, triggered_at, sort_order)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (risk_id, ev["evidence_key"], ev["label"], ev["current_value"], ev["threshold"],
             ev["baseline"], ev["source"], ev["triggered_at"], ev["sort_order"]),
        )
    conn.execute(
        """INSERT INTO risk_events
           (risk_id, event_type, actor_user_id, from_status, to_status, note, payload_json, created_at)
           VALUES (?, 'created', NULL, NULL, 'pending', ?, ?, ?)""",
        (
            risk_id,
            "批处理自动生成风险",
            json.dumps({"rule_id": candidate["rule_id"], "level": candidate["level"],
                        "objective": candidate.get("objective", "")}, ensure_ascii=False),
            created,
        ),
    )
    return dict(conn.execute("SELECT * FROM risks WHERE id = ?", (risk_id,)).fetchone())


def _merge_risk(
    conn: sqlite3.Connection, existing: dict, candidate: dict, as_of: date, now_iso_value: str
) -> None:
    conn.execute(
        """UPDATE risks SET level=?, title=?, amount=?, owner_user_id=?, org_id=?, dept=?,
             last_seen_at=?, updated_at=?, trigger_count=trigger_count+1,
             merged_count=merged_count+1, last_batch_date=?, actions_json=?, related_json=?
           WHERE id=?""",
        (
            candidate["level"], candidate["title"], candidate["amount"], candidate["owner_user_id"],
            candidate["org_id"], candidate["dept"], now_iso_value, now_iso_value,
            as_of.isoformat(), json.dumps(candidate.get("actions") or [], ensure_ascii=False),
            json.dumps(candidate.get("related") or [], ensure_ascii=False), existing["id"],
        ),
    )
    for ev in candidate.get("evidence", []):
        conn.execute(
            """INSERT INTO risk_evidence
               (risk_id, evidence_key, label, current_value, threshold, baseline, source, triggered_at, sort_order)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (existing["id"], ev["evidence_key"], ev["label"], ev["current_value"], ev["threshold"],
             ev["baseline"], ev["source"], ev["triggered_at"], ev["sort_order"]),
        )
    conn.execute(
        """INSERT INTO risk_events
           (risk_id, event_type, actor_user_id, from_status, to_status, note, payload_json, created_at)
           VALUES (?, 'merged', NULL, ?, ?, ?, ?, ?)""",
        (
            existing["id"], existing["status"], existing["status"],
            "24 小时内同对象同规则再次触发，证据已追加",
            json.dumps({"level": candidate["level"], "as_of": as_of.isoformat()}, ensure_ascii=False),
            now_iso_value,
        ),
    )


# ---------------------------------------------------------------------------
# 六类候选风险
# ---------------------------------------------------------------------------

def _candidates_target_gap(
    conn: sqlite3.Connection, as_of: date, params: dict, triggered_at: str
) -> list[dict]:
    month = f"{as_of.year:04d}-{as_of.month:02d}"
    from .config import month_bounds
    month_start, month_end = month_bounds(as_of)
    time_progress = as_of.day / ((month_end - month_start).days + 1) * 100
    yellow = float(params.get("yellow_gap_pp", 3))
    orange = float(params.get("orange_gap_pp", 8))
    red = float(params.get("red_gap_pp", 15))
    out = []
    for org in all_orgs(conn):
        target = target_for_org(conn, org["org_id"], month)
        if not target or not target.get("sign_target"):
            continue
        ids = org_descendants(conn, org["org_id"], include_self=True)
        ph = _ph(len(ids))
        signed = float(conn.execute(
            f"SELECT COALESCE(SUM(amount),0) FROM contracts WHERE status='active' "
            f"AND sign_date >= ? AND sign_date <= ? AND org_id IN ({ph})",
            [month_start.isoformat(), as_of.isoformat()] + ids,
        ).fetchone()[0] or 0)
        target_amount = float(target["sign_target"])
        completion = signed / target_amount * 100 if target_amount else None
        if completion is None:
            continue
        gap = time_progress - completion
        if gap >= red:
            level = "red"
        elif gap >= orange:
            level = "orange"
        elif gap >= yellow:
            level = "yellow"
        else:
            continue
        remaining = target_amount - signed
        owner = _org_manager(conn, org["org_id"])
        if not owner:
            continue
        title = f"{org['name']}目标缺口 {_fmt_wan(max(remaining, 0))}"
        evidence = [
            _evidence("target_gap_pp", "时间进度 − 完成进度",
                      f"{gap:.1f}pp", f"≥{yellow:.0f}/{orange:.0f}/{red:.0f}pp（黄/橙/红）",
                      f"时间进度 {time_progress:.1f}%；完成率 {completion:.1f}%",
                      "targets.csv + contracts.csv", triggered_at, 1),
            _evidence("remaining_target", "剩余签约目标",
                      _fmt_wan(max(remaining, 0)), "大于 0",
                      f"月目标 {_fmt_wan(target_amount)}；月累计已签 {_fmt_wan(signed)}",
                      "targets.csv + contracts.csv", triggered_at, 2),
            _evidence("completion_rate", "目标完成率",
                      f"{completion:.1f}%", f"低于时间进度 {time_progress:.1f}%",
                      f"{month} 月累计签约口径", "contracts.csv", triggered_at, 3),
        ]
        out.append({
            "rule_id": "target_gap", "level": level, "object_type": "org",
            "object_id": org["org_id"], "object_name": org["name"],
            "owner_user_id": owner, "org_id": org["org_id"], "dept": org["name"],
            "amount": max(remaining, 0), "title": title,
            "dedupe_key": f"target_gap:{org['org_id']}:{month}",
            "evidence": evidence,
            "actions": [
                "拉通剩余目标与重点商机清单，按周拆解到人。",
                "对缺口最大的商机制定推进计划，明确下一里程碑。",
                "如目标确实无法完成，提交书面调整申请并说明补救动作。",
            ],
            "related": [
                {"type": "target", "id": target["target_id"],
                 "label": f"{month} 月目标", "amount": money_wan_api(target_amount)},
            ],
            "objective": f"目标缺口 {gap:.1f}pp",
        })
    out.sort(key=lambda x: x["object_id"])
    return out


def _candidates_decline(
    conn: sqlite3.Connection, as_of: date, params: dict, triggered_at: str
) -> list[dict]:
    orange = float(params.get("orange_drop_pct", 20))
    red = float(params.get("red_drop_pct", 30))
    workdays = max(3, int(params.get("workdays", 3)))
    out = []
    for org in all_orgs(conn):
        ids = org_descendants(conn, org["org_id"], include_self=True)
        ph = _ph(len(ids))
        rows = conn.execute(
            f"""SELECT sign_date, COALESCE(SUM(amount),0) AS amount
                FROM contracts
                WHERE status='active' AND sign_date <= ?
                  AND CAST(STRFTIME('%w', sign_date) AS INTEGER) BETWEEN 1 AND 5
                  AND org_id IN ({ph})
                GROUP BY sign_date ORDER BY sign_date DESC LIMIT ?""",
            [as_of.isoformat()] + ids + [workdays],
        ).fetchall()
        rows = list(reversed(rows))
        if len(rows) < 3:
            continue
        # 取最近 3 个有数据工作日，判断连续两段环比
        d1, d2, d3 = rows[-3], rows[-2], rows[-1]
        a1, a2, a3 = float(d1["amount"] or 0), float(d2["amount"] or 0), float(d3["amount"] or 0)
        if a1 <= 0 or a2 <= 0:
            continue
        drop1 = (a2 / a1 - 1) * 100
        drop2 = (a3 / a2 - 1) * 100
        if drop1 > 0 or drop2 > 0:
            continue
        if abs(drop1) >= red and abs(drop2) >= red:
            level = "red"
        elif abs(drop1) >= orange and abs(drop2) >= orange:
            level = "orange"
        else:
            continue
        owner = _org_manager(conn, org["org_id"])
        if not owner:
            continue
        date_text = "、".join(f"{date.fromisoformat(r['sign_date']).month}/{date.fromisoformat(r['sign_date']).day}" for r in (d1, d2, d3))
        amounts = " → ".join(f"{a / 10000:.1f}" for a in (a1, a2, a3))
        title = f"{org['name']}连续两日签约下滑 {min(abs(drop1), abs(drop2)):.1f}%"
        out.append({
            "rule_id": "decline", "level": level, "object_type": "org",
            "object_id": org["org_id"], "object_name": org["name"],
            "owner_user_id": owner, "org_id": org["org_id"], "dept": org["name"],
            "amount": a3, "title": title,
            "dedupe_key": f"decline:{org['org_id']}",
            "evidence": [
                _evidence("recent_3_workdays", "最近 3 个有数据工作日签约额",
                          f"{amounts} 万元", "连续两段环比下降",
                          f"日期：{date_text}", "contracts.csv", triggered_at, 1),
                _evidence("decline_pct", "两段日环比",
                          f"{drop1:.1f}% / {drop2:.1f}%",
                          f"两段均 ≥{orange:.0f}% 橙 / ≥{red:.0f}% 红",
                          f"由 {a1/10000:.1f} 万降至 {a3/10000:.1f} 万",
                          "contracts.csv", triggered_at, 2),
                _evidence("last_day_amount", "最后工作日签约额", _fmt_wan(a3),
                          f"低于前一工作日 {_fmt_wan(a2)}",
                          "金额为当日 active 合同合计", "contracts.csv", triggered_at, 3),
            ],
            "actions": [
                "复盘最近三日签约波动，确认是否为单一大单节奏导致。",
                "排查在途商机与回款节点，补充本周签约计划。",
                "销售经理对重点客户逐单过会，明确签单日期与卡点。",
            ],
            "related": [],
            "objective": f"连续两日下滑 {drop1:.1f}% / {drop2:.1f}%",
        })
    out.sort(key=lambda x: x["object_id"])
    return out


def _week_lead_stats(conn: sqlite3.Connection, org_ids: list[str], start: date, end: date) -> tuple[int, int, int]:
    ph = _ph(len(org_ids))
    row = conn.execute(
        f"""SELECT COUNT(*) AS n,
                   SUM(CASE WHEN status='valid' THEN 1 ELSE 0 END) AS valid,
                   SUM(CASE WHEN converted=1 THEN 1 ELSE 0 END) AS converted
            FROM leads WHERE created_date >= ? AND created_date <= ? AND org_id IN ({ph})""",
        [start.isoformat(), end.isoformat()] + org_ids,
    ).fetchone()
    return int(row["n"] or 0), int(row["valid"] or 0), int(row["converted"] or 0)


def _candidates_leads(
    conn: sqlite3.Connection, as_of: date, params: dict, triggered_at: str
) -> list[dict]:
    volume_threshold = float(params.get("volume_drop_pct", 30))
    conversion_threshold = float(params.get("conversion_drop_pct", 20))
    week_start = as_of - timedelta(days=as_of.weekday())
    span = (as_of - week_start).days
    prev_start = week_start - timedelta(days=7)
    prev_end = prev_start + timedelta(days=span)
    out = []
    for org in all_orgs(conn):
        ids = org_descendants(conn, org["org_id"], include_self=True)
        cur_n, cur_valid, cur_conv = _week_lead_stats(conn, ids, week_start, as_of)
        prev_n, prev_valid, prev_conv = _week_lead_stats(conn, ids, prev_start, prev_end)
        volume_drop = (cur_n / prev_n * 100 - 100) if prev_n else None
        cur_rate = cur_conv / cur_valid * 100 if cur_valid else None
        prev_rate = prev_conv / prev_valid * 100 if prev_valid else None
        conversion_drop = None
        if cur_rate is not None and prev_rate:
            conversion_drop = (cur_rate / prev_rate - 1) * 100
        volume_trigger = volume_drop is not None and volume_drop <= -volume_threshold
        conversion_trigger = conversion_drop is not None and conversion_drop <= -conversion_threshold
        if not (volume_trigger or conversion_trigger):
            continue
        level = "orange" if volume_trigger else "yellow"
        owner = _org_manager(conn, org["org_id"])
        if not owner:
            continue
        if volume_trigger:
            title = f"{org['name']}新增线索周环比下降 {abs(volume_drop):.1f}%"
            reason = f"本周新增线索 {cur_n} 条，较上周同期 {prev_n} 条下降 {abs(volume_drop):.1f}%"
        else:
            title = f"{org['name']}线索转化率相对下降 {abs(conversion_drop):.1f}%"
            reason = (
                f"本周转化率 {cur_rate:.1f}%，较上周同期 {prev_rate:.1f}% "
                f"相对下降 {abs(conversion_drop):.1f}%"
            )
        evidence = [
            _evidence("weekly_leads", "本周新增线索 / 上周同期",
                      f"{cur_n} 条 / {prev_n} 条",
                      f"周环比 ≤−{volume_threshold:.0f}% 触发橙级",
                      f"本周 {week_start.month}/{week_start.day}–{as_of.month}/{as_of.day}；上周同期 {prev_start.month}/{prev_start.day}–{prev_end.month}/{prev_end.day}",
                      "leads.csv", triggered_at, 1),
            _evidence("volume_change", "新增线索周环比",
                      _fmt_pct(volume_drop), f"≤−{volume_threshold:.0f}%",
                      f"上周 {prev_n} 条", "leads.csv", triggered_at, 2),
            _evidence("conversion_change", "线索转化率相对变化",
                      _fmt_pct(conversion_drop), f"≤−{conversion_threshold:.0f}%",
                      f"本周 {_fmt_pct(cur_rate)}；上周 {_fmt_pct(prev_rate)}",
                      "leads.csv", triggered_at, 3),
        ]
        out.append({
            "rule_id": "leads", "level": level, "object_type": "org",
            "object_id": org["org_id"], "object_name": org["name"],
            "owner_user_id": owner, "org_id": org["org_id"], "dept": org["name"],
            "amount": 0, "title": title,
            "dedupe_key": f"leads:{org['org_id']}",
            "evidence": evidence,
            "actions": [
                "检查投放与渠道线索量变化，确认是否存在停投或渠道异常。",
                "抽检低转化线索的跟进记录，安排销售经理陪访。",
                "明确本周线索补量与转化目标，并跟踪到天。",
            ],
            "related": [],
            "objective": reason,
        })
    out.sort(key=lambda x: x["object_id"])
    return out


def _candidates_coverage(
    conn: sqlite3.Connection, as_of: date, params: dict, triggered_at: str
) -> list[dict]:
    threshold = float(params.get("min_coverage", 2.5))
    month = f"{as_of.year:04d}-{as_of.month:02d}"
    from .config import month_bounds
    month_start, _ = month_bounds(as_of)
    out = []
    for org in all_orgs(conn):
        target = target_for_org(conn, org["org_id"], month)
        if not target or not target.get("sign_target"):
            continue
        ids = org_descendants(conn, org["org_id"], include_self=True)
        ph = _ph(len(ids))
        pipeline = float(conn.execute(
            f"SELECT COALESCE(SUM(amount),0) FROM opportunities WHERE status='open' "
            f"AND org_id IN ({ph})", ids,
        ).fetchone()[0] or 0)
        signed = float(conn.execute(
            f"SELECT COALESCE(SUM(amount),0) FROM contracts WHERE status='active' "
            f"AND sign_date >= ? AND sign_date <= ? AND org_id IN ({ph})",
            [month_start.isoformat(), as_of.isoformat()] + ids,
        ).fetchone()[0] or 0)
        remaining = float(target["sign_target"]) - signed
        if remaining <= 0:
            continue
        coverage = pipeline / remaining
        if coverage >= threshold:
            continue
        owner = _org_manager(conn, org["org_id"])
        if not owner:
            continue
        out.append({
            "rule_id": "coverage", "level": "orange", "object_type": "org",
            "object_id": org["org_id"], "object_name": org["name"],
            "owner_user_id": owner, "org_id": org["org_id"], "dept": org["name"],
            "amount": 0, "title": f"{org['name']}商机覆盖不足 {coverage:.1f} 倍",
            "dedupe_key": f"coverage:{org['org_id']}:{month}",
            "evidence": [
                _evidence("coverage", "商机覆盖率", f"{coverage:.1f} 倍", f"<{threshold:.1f} 倍",
                          f"开放管道 {_fmt_wan(pipeline)}；剩余目标 {_fmt_wan(remaining)}",
                          "opportunities.csv + contracts.csv + targets.csv", triggered_at, 1),
                _evidence("pipeline", "开放商机管道金额", _fmt_wan(pipeline),
                          f"需至少 {_fmt_wan(remaining * threshold)}", f"剩余目标 {_fmt_wan(remaining)}",
                          "opportunities.csv", triggered_at, 2),
                _evidence("remaining_target", "剩余签约目标", _fmt_wan(remaining), "大于 0",
                          f"月目标 {_fmt_wan(target['sign_target'])}；已签 {_fmt_wan(signed)}",
                          "targets.csv + contracts.csv", triggered_at, 3),
            ],
            "actions": [
                "盘点开放商机，优先推进高概率、近期可签项目。",
                "补充新商机储备，目标使覆盖率回到 2.5 倍以上。",
                "对长期停留同一阶段的商机逐单确认下一步动作。",
            ],
            "related": [],
            "objective": f"覆盖率 {coverage:.1f} 倍低于 {threshold:.1f} 倍",
        })
    out.sort(key=lambda x: x["object_id"])
    return out


def _candidates_churn(
    conn: sqlite3.Connection, as_of: date, params: dict, triggered_at: str
) -> list[dict]:
    min_amount = float(params.get("min_amount", 500000))
    days_limit = int(params.get("days_no_followup", 30))
    rows = conn.execute(
        """SELECT * FROM opportunities WHERE status='open' AND amount >= ?
           AND (created_date IS NULL OR created_date <= ?) ORDER BY opp_id""",
        (min_amount, as_of.isoformat()),
    ).fetchall()
    out = []
    for opp in rows:
        last = opp["last_followup_date"] or opp["created_date"]
        if not last:
            continue
        try:
            last_date = date.fromisoformat(last)
        except ValueError:
            continue
        days = (as_of - last_date).days
        if days < days_limit:
            continue
        owner = get_user(conn, opp["owner_id"])
        if not owner:
            continue
        org = get_org(conn, opp["org_id"])
        out.append({
            "rule_id": "churn", "level": "red", "object_type": "opportunity",
            "object_id": opp["opp_id"], "object_name": opp["customer"],
            "owner_user_id": opp["owner_id"], "org_id": opp["org_id"],
            "dept": org["name"] if org else opp["org_id"], "amount": float(opp["amount"]),
            "title": f"{opp['customer']} {days} 天未跟进",
            "dedupe_key": f"churn:{opp['opp_id']}",
            "evidence": [
                _evidence("no_followup_days", "距最后跟进天数", f"{days} 天",
                          f"≥{days_limit} 天", f"最后跟进 {last}",
                          "opportunities.csv + followups.csv", triggered_at, 1),
                _evidence("opportunity_amount", "开放商机金额", _fmt_wan(opp["amount"]),
                          f"≥{_fmt_wan(min_amount)}", f"阶段：{opp['stage'] or '—'}",
                          "opportunities.csv", triggered_at, 2),
                _evidence("customer", "客户", opp["customer"], "大客户商机",
                          f"预计成交 {opp['expected_close_date'] or '—'}",
                          "opportunities.csv", triggered_at, 3),
            ],
            "actions": [
                "安排客户高层回访，确认预算、决策链和竞争态势。",
                "补充最近一次有效沟通记录，更新下一跟进日期。",
                "若已失联，启动客户挽回或替换商机计划。",
            ],
            "related": [
                {"type": "opportunity", "id": opp["opp_id"], "label": opp["customer"],
                 "amount": money_wan_api(opp["amount"]), "stage": opp["stage"],
                 "last_followup_date": last},
            ],
            "objective": f"{days} 天未跟进",
        })
    return out


def _candidates_payment(
    conn: sqlite3.Connection, as_of: date, params: dict, triggered_at: str
) -> list[dict]:
    min_cancel = float(params.get("min_cancel_amount", 500000))
    overdue_limit = int(params.get("overdue_days", 30))
    out = []
    orders = conn.execute(
        """SELECT * FROM orders WHERE status='cancelled' AND amount >= ?
           AND order_date <= ? ORDER BY order_date, order_id""",
        (min_cancel, as_of.isoformat()),
    ).fetchall()
    for order in orders:
        owner = get_user(conn, order["owner_id"])
        if not owner:
            continue
        org = get_org(conn, order["org_id"])
        out.append({
            "rule_id": "payment", "level": "red", "object_type": "order",
            "object_id": order["order_id"], "object_name": order["customer"],
            "owner_user_id": order["owner_id"], "org_id": order["org_id"],
            "dept": org["name"] if org else order["org_id"], "amount": float(order["amount"]),
            "title": f"{order['customer']}订单取消 {_fmt_wan(order['amount'])}",
            "dedupe_key": f"payment:order:{order['order_id']}",
            "evidence": [
                _evidence("cancelled_amount", "单笔订单取消金额", _fmt_wan(order["amount"]),
                          f"≥{_fmt_wan(min_cancel)}", f"订单日期 {order['order_date']}",
                          "orders.csv", triggered_at, 1),
                _evidence("order_status", "订单状态", "已取消（cancelled）", "取消",
                          f"订单号 {order['order_id']}", "orders.csv", triggered_at, 2),
                _evidence("customer", "客户", order["customer"], "大额取消订单",
                          f"负责人 {owner['name']}", "orders.csv", triggered_at, 3),
            ],
            "actions": [
                "联系客户确认订单取消原因，评估挽回或替换订单。",
                "核查合同违约与库存/交付影响，形成处置意见。",
                "同步财务与销售总监，评估本月目标缺口。",
            ],
            "related": [
                {"type": "order", "id": order["order_id"], "label": order["customer"],
                 "amount": money_wan_api(order["amount"]), "status": order["status"]},
            ],
            "objective": f"取消订单 {_fmt_wan(order['amount'])}",
        })
    recvs = conn.execute(
        """SELECT * FROM receivables
           WHERE due_date <= ? AND (status <> 'paid' OR paid_amount < amount)
           ORDER BY due_date, recv_id""",
        (as_of.isoformat(),),
    ).fetchall()
    for recv in recvs:
        due = date.fromisoformat(recv["due_date"])
        overdue_days = (as_of - due).days
        if overdue_days < overdue_limit:
            continue
        outstanding = float(recv["amount"]) - float(recv["paid_amount"] or 0)
        if outstanding <= 0:
            continue
        owner = get_user(conn, recv["owner_id"])
        if not owner:
            continue
        org = get_org(conn, recv["org_id"])
        out.append({
            "rule_id": "payment", "level": "red", "object_type": "receivable",
            "object_id": recv["recv_id"], "object_name": recv["customer"],
            "owner_user_id": recv["owner_id"], "org_id": recv["org_id"],
            "dept": org["name"] if org else recv["org_id"], "amount": outstanding,
            "title": f"{recv['customer']}应收逾期 {overdue_days} 天",
            "dedupe_key": f"payment:receivable:{recv['recv_id']}",
            "evidence": [
                _evidence("overdue_days", "应收逾期天数", f"{overdue_days} 天",
                          f"≥{overdue_limit} 天", f"到期日 {recv['due_date']}",
                          "receivables.csv", triggered_at, 1),
                _evidence("outstanding", "未回款金额", _fmt_wan(outstanding),
                          "大于 0", f"应收 {_fmt_wan(recv['amount'])}；已回 {_fmt_wan(recv['paid_amount'])}",
                          "receivables.csv", triggered_at, 2),
                _evidence("customer", "客户", recv["customer"], "逾期应收",
                          f"应收单号 {recv['recv_id']}", "receivables.csv", triggered_at, 3),
            ],
            "actions": [
                "向客户发送逾期对账单，明确回款日期。",
                "评估信用额度与停供风险，必要时升级财务/法务。",
                "将回款节点纳入本周销售例会跟踪。",
            ],
            "related": [
                {"type": "receivable", "id": recv["recv_id"], "label": recv["customer"],
                 "amount": money_wan_api(outstanding), "due_date": recv["due_date"]},
            ],
            "objective": f"逾期 {overdue_days} 天",
        })
    return out


def money_wan_api(value: float | int | None) -> float | None:
    if value is None:
        return None
    return round(float(value) / 10000.0, 1)


CANDIDATE_BUILDERS = {
    "target_gap": _candidates_target_gap,
    "decline": _candidates_decline,
    "leads": _candidates_leads,
    "coverage": _candidates_coverage,
    "churn": _candidates_churn,
    "payment": _candidates_payment,
}


def evaluate_rules(
    conn: sqlite3.Connection, as_of: date, batch_id: str, now: datetime | None = None
) -> dict:
    """执行六类规则，返回新建/合并数量。

    必须在批处理事务内调用。相同业务日期重复运行时，已有风险不重复建单、
    不重复写事件、不重复发通知，保证同日重跑幂等。
    """
    now = now or now_bj()
    now_value = now.isoformat(timespec="seconds")
    cutoff = (now - timedelta(hours=24)).isoformat(timespec="seconds")
    as_of_str = as_of.isoformat()
    stats = {"created": 0, "merged": 0, "skipped": 0, "triggered": 0,
             "by_rule": {}, "risk_ids": []}
    for rule in load_rules(conn):
        if not rule["enabled"]:
            stats["by_rule"][rule["rule_id"]] = {"created": 0, "merged": 0, "skipped": 0}
            continue
        builder = CANDIDATE_BUILDERS.get(rule["rule_id"])
        if not builder:
            continue
        candidates = builder(conn, as_of, rule["params"], now_value)
        rule_stat = {"created": 0, "merged": 0, "skipped": 0}
        for candidate in candidates:
            stats["triggered"] += 1
            existing = _find_recent_risk(
                conn, candidate["rule_id"], candidate["object_type"], candidate["object_id"], cutoff
            )
            if existing:
                if existing.get("last_batch_date") == as_of_str:
                    # 同一天重跑：保持原风险、证据、事件、编号完全不变
                    rule_stat["skipped"] += 1
                    stats["skipped"] += 1
                    continue
                if existing["status"] in {"closed", "false_positive", "long_term"}:
                    rule_stat["skipped"] += 1
                    stats["skipped"] += 1
                    continue
                _merge_risk(conn, existing, candidate, as_of, now_value)
                rule_stat["merged"] += 1
                stats["merged"] += 1
                continue
            risk = _insert_risk(conn, batch_id, as_of, candidate, now_value)
            rule_stat["created"] += 1
            stats["created"] += 1
            stats["risk_ids"].append(risk["id"])
        stats["by_rule"][rule["rule_id"]] = rule_stat
    return stats
