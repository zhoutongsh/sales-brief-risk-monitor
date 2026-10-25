"""日报与周报生成。

职责：
- 四类角色各自的数据范围；
- 日报固定：3 条结论 + 6 张指标卡 + 增长/下滑 Top3 + 风险 Top3 + 动作建议 + 数据说明；
- 周报：本周/上周、环比、风险闭环、排行榜、风险类型；
- 所有结论由服务端从指标和风险计算，不回退到前端假数据。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, time, timedelta

from .config import (
    DEMO_DATE,
    DEMO_WEEKDAY,
    METRIC_MAP,
    RISK_TYPES,
    TZ,
    now_bj,
    now_iso,
    money_wan,
    month_bounds,
    round_half_up,
)
from .metrics import (
    compute_channel_analysis,
    compute_movers,
    compute_trend,
    metric_display,
    metrics_summary_for_brief,
)
from .quality import load_quality_report
from .risk_service import query_risks, risk_access_clause
from .scope import (
    child_scope_orgs,
    demo_users,
    get_user,
    org_descendants,
    scope_label,
    scope_users,
    target_for_org,
    target_for_user,
    user_scope_root,
)


def _fmt_wan(value: float | int | None) -> str:
    if value is None:
        return "—"
    return f"{money_wan(value):,.1f} 万元"


def _num1(value: float | int | None) -> str:
    """统一按四舍五入保留 1 位小数，避免卡片与结论出现 0.1 的尾差。"""
    rounded = round_half_up(value, 1)
    return "—" if rounded is None else f"{rounded:.1f}"


def _pct1(value: float | int | None) -> str:
    text = _num1(value)
    return "—" if text == "—" else f"{text}%"


def _signed_pct(value: float | None) -> str:
    rounded = round_half_up(value, 1)
    return "—" if rounded is None else f"{rounded:+.1f}%"


def planned_daily_published_at(as_of: date) -> str:
    """日报计划发布时间：业务日期当天 08:30（北京时间）。"""
    return datetime.combine(as_of, time(8, 30), TZ).isoformat(timespec="seconds")


def planned_weekly_published_at(ranges: dict) -> str:
    """周报计划发布时间：本周周中版为周六 09:00，上周正式版为周一 09:00。"""
    if ranges["week_type"] == "last":
        publish_date = ranges["cur_start"] + timedelta(days=7)
    else:
        publish_date = ranges["cur_start"] + timedelta(days=5)
    return datetime.combine(publish_date, time(9, 0), TZ).isoformat(timespec="seconds")


def _tone_from_delta(value: float | None, good_above: float = 0) -> str:
    if value is None:
        return "neutral"
    return "good" if value > good_above else ("bad" if value < good_above else "neutral")


def _quality_block(conn: sqlite3.Connection, as_of: date) -> dict:
    report = load_quality_report(conn, as_of)
    if not report:
        return {"status": "unknown", "score": None, "message": "数据质量报告缺失（不以 0 代替）。",
                "batch": None}
    return {
        "status": report.get("status"),
        "score": report.get("score"),
        "message": report.get("summary", {}).get("message"),
        "checks": report.get("checks", []),
        "affected_metrics": report.get("affected_metrics", []),
        "batch": report.get("batch", {}),
        "as_of": report.get("as_of"),
    }


def _source_data(conn: sqlite3.Connection, quality: dict, as_of: date) -> dict:
    report = load_quality_report(conn, as_of)
    sources = []
    if report:
        for row in report.get("completeness", {}).get("by_source", []):
            sources.append({"file": row.get("source"), "rows": row.get("rows"),
                            "score": row.get("score"), "available": row.get("available")})
    return {
        "sources": sources,
        "source_count": len(sources),
        "latest_data_date": as_of.isoformat(),
        "amount_unit": "万元",
        "rate_precision": "1 位小数",
    }


def _common_notes(conn: sqlite3.Connection, as_of: date, quality: dict, metrics: dict | None = None) -> list[str]:
    notes = []
    status = quality.get("status")
    score = quality.get("score")
    if status == "pass":
        notes.append(f"数据质量检查通过，完整率 {_pct1(score)}。" if score is not None else "数据质量检查通过。")
    elif status == "warn":
        notes.append(f"数据质量存在提示，检查得分 {_pct1(score)}，相关指标已标注。" if score is not None else "数据质量存在提示。")
    elif status == "fail":
        notes.append("数据质量存在阻断问题，本简报不作为确定性经营结论。")
    else:
        notes.append("未找到当日数据质量报告。")
    missing_src = quality.get("batch") or {}
    notes.append("金额统一按万元展示、比率保留 1 位小数；缺失值显示「—」，没有用 0 代替。")
    notes.append("营销费用源未按组织拆分，营销 ROI 的分母使用公司当月投放费用，分子为当前数据范围的归因签约。")
    notes.append("线索/签约周环比均为本周一至业务日期 D，与上周同期同跨度比较。")
    if metrics is not None and metrics.get("target_completion_rate") is None:
        notes.append("当前数据范围缺少月目标，目标完成率与商机覆盖率显示为「—」，相关风险不触发。")
    return notes


def _risk_actions(conn: sqlite3.Connection, user: dict, top_risks: list[dict], metrics: dict | None = None) -> list[dict]:
    actions = []
    for risk in top_risks[:3]:
        row = conn.execute("SELECT actions_json FROM risks WHERE id=?", (risk["id"],)).fetchone()
        try:
            raw_actions = json.loads(row["actions_json"]) if row else []
        except (json.JSONDecodeError, TypeError):
            raw_actions = []
        if raw_actions:
            actions.append({
                "risk_id": risk["id"],
                "level": risk["level"],
                "title": risk["title"],
                "owner_name": risk.get("owner", {}).get("name") if risk.get("owner") else None,
                "text": raw_actions[0],
            })
    if not actions:
        if metrics and metrics.get("target_completion_rate") is not None:
            gap = metrics.get("time_progress", 0) - metrics["target_completion_rate"]
            if gap >= 3:
                actions.append({"risk_id": None, "level": "yellow", "title": "目标进度",
                                "owner_name": None,
                                "text": "按剩余目标拆解重点商机，逐单确认签约日期与卡点。"})
        if metrics and metrics.get("opportunity_coverage") is not None and metrics["opportunity_coverage"] < 2.5:
            actions.append({"risk_id": None, "level": "orange", "title": "商机覆盖",
                            "owner_name": None,
                            "text": "补充开放商机储备，使覆盖率回到 2.5 倍以上。"})
        if not actions:
            actions.append({"risk_id": None, "level": None, "title": "节奏保持",
                            "owner_name": None,
                            "text": "保持当前签约与线索节奏，继续跟踪重点商机下一步动作。"})
    return actions[:3]


def _daily_conclusions(conn: sqlite3.Connection, user: dict, raw: dict, stats: dict, top_risks: list[dict]) -> list[dict]:
    completion = raw.get("target_completion_rate")
    time_progress = raw.get("time_progress")
    if completion is not None and time_progress is not None:
        diff = completion - time_progress
        if diff >= 0:
            text = (
                f"本月目标完成率 {_pct1(completion)}，领先时间进度 {_num1(abs(diff))} 个百分点；"
                f"月累计签约 {_fmt_wan(raw['_month_signed'])}，按当前节奏进度健康。"
            )
            tone = "good"
        elif abs(diff) < 3:
            text = (
                f"本月目标完成率 {_pct1(completion)}，与时间进度 {_pct1(time_progress)} 基本持平；"
                f"剩余目标 {_fmt_wan(raw.get('_remaining_target'))}，需保持日签约节奏。"
            )
            tone = "neutral"
        else:
            text = (
                f"本月目标完成率 {_pct1(completion)}，落后时间进度 {_num1(abs(diff))} 个百分点；"
                f"剩余目标 {_fmt_wan(raw.get('_remaining_target'))}，存在目标缺口。"
            )
            tone = "bad"
    else:
        text = "当前数据范围缺少当月签约目标，目标完成率无法计算（显示为「—」），已列入数据说明。"
        tone = "warning"
    conclusion1 = {"index": 1, "title": "目标进度", "text": text, "tone": tone,
                   "tag": "目标", "metric_key": "target_completion_rate", "risk_id": None}

    wow = raw.get("leads_wow")
    coverage = raw.get("opportunity_coverage")
    pieces = []
    if wow is not None:
        pieces.append(f"本周新增线索 {raw.get('_cur_week_leads', 0)} 条，较上周同期 {_signed_pct(wow)}")
    else:
        pieces.append(f"本周新增线索 {raw.get('_cur_week_leads', 0)} 条，上周同期无数据，周环比不计算")
    if coverage is not None:
        pieces.append(f"开放管道 {_fmt_wan(raw.get('pipeline_amount'))}，商机覆盖率 {_num1(coverage)} 倍（健康线 2.5 倍）")
    else:
        pieces.append("商机覆盖率因剩余目标缺失或已完成为「—」")
    tone2 = "neutral"
    if (wow is not None and wow <= -30) or (coverage is not None and coverage < 2.5):
        tone2 = "bad"
    elif (wow is None or wow > 0) and (coverage is None or coverage >= 2.5):
        tone2 = "good"
    conclusion2 = {"index": 2, "title": "线索与商机", "text": "；".join(pieces) + "。",
                   "tone": tone2, "tag": "线索", "metric_key": "opportunity_coverage", "risk_id": None}

    active = stats.get("active", 0)
    red_active = stats.get("red_active", 0)
    if top_risks:
        top = top_risks[0]
        owner_name = top.get("owner", {}).get("name") if top.get("owner") else "—"
        text3 = (
            f"当前数据范围有 {active} 条未结束风险，其中红色 {red_active} 条；"
            f"最高优先级为「{top['title']}」，责任人 {owner_name}，{top.get('sla', {}).get('claim_text', '')}。"
        )
        tone3 = "bad" if red_active else "warning"
        ris_id = top["id"]
    else:
        text3 = "当前数据范围没有未结束风险，风险中心暂无待处理事项。"
        tone3 = "good"
        ris_id = None
    conclusion3 = {"index": 3, "title": "风险提醒", "text": text3, "tone": tone3,
                   "tag": "风险", "metric_key": None, "risk_id": ris_id}
    return [conclusion1, conclusion2, conclusion3]


def build_daily_brief(
    conn: sqlite3.Connection, user: dict, as_of: date = DEMO_DATE, batch_id: str | None = None,
    published_at: str | None = None, generated_at: str | None = None,
) -> dict:
    root = user_scope_root(conn, user)
    summary = metrics_summary_for_brief(conn, root, as_of)
    raw = summary["raw"]
    quality = _quality_block(conn, as_of)
    top_result = query_risks(conn, user, status="active", sort="priority", page=1, page_size=3)
    top_risks = top_result["items"]
    stats = top_result["stats"]
    conclusions = _daily_conclusions(conn, user, raw, stats, top_risks)
    actions = _risk_actions(conn, user, top_risks, raw)
    movers = compute_movers(conn, root, as_of)
    channels = compute_channel_analysis(conn, root, as_of)
    trend = compute_trend(conn, root, as_of, days=14)
    notes = _common_notes(conn, as_of, quality, raw)
    scope = {"org_id": root, "name": scope_label(conn, user),
             "role": user["role"], "role_label": user.get("title", user["role"])}
    top_title = top_risks[0]["title"] if top_risks else None
    if top_title:
        headline = f"{user['name']}，早上好。今日重点：{top_title}。"
    elif raw.get("target_completion_rate") is not None:
        headline = (f"{user['name']}，早上好。{scope['name']}暂无未结束风险，"
                    f"本月目标完成率 {_pct1(raw['target_completion_rate'])}。")
    else:
        headline = f"{user['name']}，早上好。{scope['name']}暂无未结束风险，请关注数据质量提示。"
    payload = {
        "date": as_of.isoformat(),
        "as_of": as_of.isoformat(),
        "weekday": DEMO_WEEKDAY,
        "published_at": published_at or planned_daily_published_at(as_of),
        "generated_at": generated_at or now_iso(),
        "publish_schedule": "每日 08:30 推送",
        "batch_id": batch_id,
        "greeting": f"{user['name']}，早上好",
        "headline": headline,
        "scope": scope,
        "data_status": "published",
        "kpis": summary["cards"],
        "conclusions": conclusions,
        "movers": movers,
        "top_risks": top_risks,
        "risk_stats": stats,
        "actions": actions,
        "channels": channels,
        "channel_period": {"days": 30, "end": as_of.isoformat()},
        "trend": trend,
        "data_notes": notes,
        "data_quality": quality,
        "source_data": _source_data(conn, quality, as_of),
        "data_source": "本地 CSV → SQLite 指标快照 → 规则引擎；所有数字由服务端实时读取。",
        "metric_definitions": [
            {k: v for k, v in meta.items() if k in ("key", "label", "unit", "formula", "source")}
            for meta in METRIC_MAP.values()
        ],
    }
    return payload


def save_daily_briefs(conn: sqlite3.Connection, as_of: date, batch_id: str) -> int:
    generated = now_iso()
    published = planned_daily_published_at(as_of)
    count = 0
    for user in demo_users(conn):
        payload = build_daily_brief(conn, user, as_of, batch_id, published, generated)
        conn.execute(
            """INSERT INTO daily_briefs
               (as_of, role, user_id, scope_org_id, batch_id, payload_json, generated_at, published_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(as_of, role, user_id) DO UPDATE SET scope_org_id=excluded.scope_org_id,
                 batch_id=excluded.batch_id, payload_json=excluded.payload_json,
                 generated_at=excluded.generated_at, published_at=excluded.published_at""",
            (as_of.isoformat(), user["role"], user["user_id"], user_scope_root(conn, user),
             batch_id, json.dumps(payload, ensure_ascii=False), generated, published),
        )
        count += 1
    return count


def publish_daily_briefs(conn: sqlite3.Connection, as_of: date, published_at: str) -> int:
    """批处理“发布”步骤：统一刷新当天日报的发布时间与载荷时间戳。"""
    rows = conn.execute("SELECT id, payload_json FROM daily_briefs WHERE as_of=?", (as_of.isoformat(),)).fetchall()
    for row in rows:
        payload = json.loads(row["payload_json"])
        payload["published_at"] = published_at
        conn.execute(
            "UPDATE daily_briefs SET published_at=?, payload_json=? WHERE id=?",
            (published_at, json.dumps(payload, ensure_ascii=False), row["id"]),
        )
    return len(rows)


def load_daily_brief(conn: sqlite3.Connection, user: dict, as_of: date = DEMO_DATE) -> dict | None:
    row = conn.execute(
        "SELECT * FROM daily_briefs WHERE as_of=? AND role=? AND user_id=?",
        (as_of.isoformat(), user["role"], user["user_id"]),
    ).fetchone()
    if not row:
        return None
    return json.loads(row["payload_json"])


# ---------------------------------------------------------------------------
# 周报
# ---------------------------------------------------------------------------

def _week_ranges(as_of: date, week_type: str) -> dict:
    monday = as_of - timedelta(days=as_of.weekday())
    if week_type == "last":
        cur_start = monday - timedelta(days=7)
        cur_end = cur_start + timedelta(days=6)
        compare_start = cur_start - timedelta(days=7)
        compare_end = compare_start + timedelta(days=6)
        data_end = cur_end
        partial = False
        label = f"上周（{cur_start.month}/{cur_start.day}–{cur_end.month}/{cur_end.day}）"
        edition = "上周正式版"
    else:
        cur_start = monday
        cur_end = monday + timedelta(days=6)
        compare_start = monday - timedelta(days=7)
        compare_end = compare_start + timedelta(days=(as_of - monday).days)
        data_end = as_of
        partial = True
        label = (f"本周（{cur_start.month}/{cur_start.day}–{cur_end.month}/{cur_end.day}，"
                 f"数据截至 {as_of.month}/{as_of.day}）")
        edition = "周中版"
    return {
        "week_type": week_type, "cur_start": cur_start, "cur_end": cur_end,
        "data_end": data_end, "compare_start": compare_start, "compare_end": compare_end,
        "days": (data_end - cur_start).days + 1,
        "partial": partial, "label": label, "edition": edition,
    }


def _period_activity(
    conn: sqlite3.Connection, root_org_id: str, start: date, end: date,
    owner_user_id: str | None = None,
) -> dict:
    org_ids = org_descendants(conn, root_org_id, include_self=True)
    ph = ",".join("?" for _ in org_ids)
    owner_sql = " AND owner_id = ?" if owner_user_id else ""
    owner_params = [owner_user_id] if owner_user_id else []
    lead = conn.execute(
        f"""SELECT COUNT(*) n, SUM(CASE WHEN status='valid' THEN 1 ELSE 0 END) valid,
                   SUM(CASE WHEN converted=1 THEN 1 ELSE 0 END) converted
            FROM leads WHERE created_date >= ? AND created_date <= ? AND org_id IN ({ph}){owner_sql}""",
        [start.isoformat(), end.isoformat()] + org_ids + owner_params,
    ).fetchone()
    contract = conn.execute(
        f"""SELECT COALESCE(SUM(amount),0) amount, COUNT(*) cnt
            FROM contracts WHERE status='active' AND sign_date >= ? AND sign_date <= ?
              AND org_id IN ({ph}){owner_sql}""",
        [start.isoformat(), end.isoformat()] + org_ids + owner_params,
    ).fetchone()
    opps = conn.execute(
        f"SELECT COUNT(*) n FROM opportunities WHERE created_date >= ? AND created_date <= ? "
        f"AND org_id IN ({ph}){owner_sql}",
        [start.isoformat(), end.isoformat()] + org_ids + owner_params,
    ).fetchone()[0]
    paid = conn.execute(
        f"""SELECT COALESCE(SUM(paid_amount),0) amount FROM receivables
            WHERE paid_date >= ? AND paid_date <= ? AND org_id IN ({ph}){owner_sql}""",
        [start.isoformat(), end.isoformat()] + org_ids + owner_params,
    ).fetchone()[0]
    return {
        "leads": int(lead["n"] or 0),
        "valid_leads": int(lead["valid"] or 0),
        "converted": int(lead["converted"] or 0),
        "sign": float(contract["amount"] or 0),
        "contracts": int(contract["cnt"] or 0),
        "new_opportunities": int(opps or 0),
        "paid": float(paid or 0),
    }


def _period_target(
    conn: sqlite3.Connection, root_org_id: str, as_of: date, days: int,
    owner_user_id: str | None = None,
) -> tuple[float | None, float | None]:
    month = f"{as_of.year:04d}-{as_of.month:02d}"
    target = target_for_user(conn, owner_user_id, month) if owner_user_id else target_for_org(conn, root_org_id, month)
    if not target:
        return None, None
    month_start, month_end = month_bounds(as_of)
    days_in_month = (month_end - month_start).days + 1
    ratio = min(days, days_in_month) / days_in_month
    sign_target = float(target["sign_target"]) * ratio if target.get("sign_target") is not None else None
    collection_target = float(target["collection_target"]) * ratio if target.get("collection_target") is not None else None
    return sign_target, collection_target


def _weekly_groups(conn: sqlite3.Connection, root_org_id: str) -> tuple[str, list[dict]]:
    children = child_scope_orgs(conn, root_org_id)
    if children:
        return "org", [{"id": c["org_id"], "name": c["name"], "type": "org"} for c in children]
    users = scope_users(conn, [root_org_id])
    return "user", [{"id": u["user_id"], "name": u["name"], "type": "user"} for u in users]


def _weekly_risk_stats(
    conn: sqlite3.Connection, user: dict, ranges: dict,
) -> dict:
    access, base_params = risk_access_clause(conn, user, "r")
    start = ranges["cur_start"].isoformat()
    end = ranges["cur_end"].isoformat()
    period_where = f"{access} AND r.as_of >= ? AND r.as_of <= ?"
    params = base_params + [start, end]
    total_new = conn.execute(f"SELECT COUNT(*) FROM risks r WHERE {period_where}", params).fetchone()[0]
    cohort_closed = conn.execute(
        f"SELECT COUNT(*) FROM risks r WHERE {period_where} "
        f"AND r.status IN ('closed','false_positive','long_term')", params,
    ).fetchone()[0]
    closed_in_week = conn.execute(
        f"""SELECT COUNT(*) FROM risks r WHERE {access}
            AND substr(r.closed_at,1,10) >= ? AND substr(r.closed_at,1,10) <= ?""",
        base_params + [start, end],
    ).fetchone()[0]
    avg_row = conn.execute(
        f"""SELECT AVG((julianday(r.closed_at) - julianday(r.created_at)) * 24)
            FROM risks r WHERE {period_where} AND r.closed_at IS NOT NULL""",
        params,
    ).fetchone()[0]
    by_level = {k: 0 for k in ["red", "orange", "yellow"]}
    for row in conn.execute(
        f"SELECT r.level, COUNT(*) c FROM risks r WHERE {period_where} GROUP BY r.level", params
    ).fetchall():
        by_level[row["level"]] = int(row["c"])
    by_status = {k: 0 for k in ["pending", "processing", "closed", "false_positive", "long_term"]}
    for row in conn.execute(
        f"SELECT r.status, COUNT(*) c FROM risks r WHERE {period_where} GROUP BY r.status", params
    ).fetchall():
        by_status[row["status"]] = int(row["c"])
    type_rows = conn.execute(
        f"""SELECT r.type, COUNT(*) c,
                   SUM(CASE WHEN r.status IN ('closed','false_positive','long_term') THEN 1 ELSE 0 END) closed
            FROM risks r WHERE {period_where} GROUP BY r.type ORDER BY c DESC, r.type""",
        params,
    ).fetchall()
    risk_types = [{
        "type": r["type"], "label": RISK_TYPES.get(r["type"], r["type"]),
        "count": int(r["c"]), "closed": int(r["closed"] or 0),
    } for r in type_rows]
    closure_rate = (cohort_closed / total_new * 100) if total_new else None
    return {
        "new_count": int(total_new),
        "closed_count": int(cohort_closed),
        "closed_in_week": int(closed_in_week),
        "open_count": int(total_new - cohort_closed),
        "closure_rate": round_half_up(closure_rate, 1) if closure_rate is not None else None,
        "avg_close_hours": round_half_up(float(avg_row), 1) if avg_row is not None else None,
        "by_level": by_level,
        "by_status": by_status,
        "risk_types": risk_types,
    }


def _weekly_ranking(conn: sqlite3.Connection, root_org_id: str, as_of: date, ranges: dict) -> list[dict]:
    kind, groups = _weekly_groups(conn, root_org_id)
    rows = []
    for g in groups:
        if kind == "org":
            org_ids = org_descendants(conn, g["id"], include_self=True)
            ph = ",".join("?" for _ in org_ids)
            cur = conn.execute(
                f"SELECT COALESCE(SUM(amount),0) FROM contracts WHERE status='active' "
                f"AND sign_date >= ? AND sign_date <= ? AND org_id IN ({ph})",
                [ranges["cur_start"].isoformat(), ranges["data_end"].isoformat()] + org_ids,
            ).fetchone()[0]
            prev = conn.execute(
                f"SELECT COALESCE(SUM(amount),0) FROM contracts WHERE status='active' "
                f"AND sign_date >= ? AND sign_date <= ? AND org_id IN ({ph})",
                [ranges["compare_start"].isoformat(), ranges["compare_end"].isoformat()] + org_ids,
            ).fetchone()[0]
            target, _ = _period_target(conn, g["id"], as_of, ranges["days"])
        else:
            cur = conn.execute(
                "SELECT COALESCE(SUM(amount),0) FROM contracts WHERE status='active' "
                "AND sign_date >= ? AND sign_date <= ? AND owner_id = ?",
                [ranges["cur_start"].isoformat(), ranges["data_end"].isoformat(), g["id"]],
            ).fetchone()[0]
            prev = conn.execute(
                "SELECT COALESCE(SUM(amount),0) FROM contracts WHERE status='active' "
                "AND sign_date >= ? AND sign_date <= ? AND owner_id = ?",
                [ranges["compare_start"].isoformat(), ranges["compare_end"].isoformat(), g["id"]],
            ).fetchone()[0]
            target, _ = _period_target(conn, root_org_id, as_of, ranges["days"], owner_user_id=g["id"])
        cur = float(cur or 0)
        prev = float(prev or 0)
        wow = (cur / prev * 100 - 100) if prev else None
        completion = (cur / target * 100) if target else None
        rows.append({
            "id": g["id"], "name": g["name"], "type": g["type"],
            "sign_wan": money_wan(cur),
            "wow_pct": round_half_up(wow, 1) if wow is not None else None,
            "target_wan": money_wan(target) if target else None,
            "completion_rate": round_half_up(completion, 1) if completion is not None else None,
        })
    rows.sort(key=lambda x: (-(x["sign_wan"] or 0), x["name"]))
    for idx, row in enumerate(rows, start=1):
        row["rank"] = idx
    return rows


def _weekly_conclusions(ranges: dict, cur: dict, prev: dict, kpis: dict, closure: dict, ranking: list[dict]) -> list[dict]:
    wow = kpis["contract_wow"]
    completion = kpis["target_completion"]
    if completion is not None:
        text1 = (
            f"{ranges['edition']}签约 {_fmt_wan(cur['sign'])}，较同期 {_signed_pct(wow)}；"
            f"按天折算周目标完成率 {_pct1(completion)}。"
        )
        tone1 = "good" if completion >= 100 else ("bad" if completion < 80 else "neutral")
    else:
        text1 = f"{ranges['edition']}签约 {_fmt_wan(cur['sign'])}，较同期 {_signed_pct(wow)}；当前范围缺少目标，周目标完成率为「—」。"
        tone1 = "warning"
    c1 = {"index": 1, "title": "业绩环比", "text": text1, "tone": tone1, "tag": "业绩",
          "metric_key": "contract_amount", "risk_id": None}

    if closure["new_count"]:
        rate_text = _pct1(closure["closure_rate"])
        top_type = closure["risk_types"][0]["label"] if closure["risk_types"] else "—"
        text2 = (
            f"本周新增风险 {closure['new_count']} 条，已闭环 {closure['closed_count']} 条，"
            f"闭环率 {rate_text}；主要风险类型为「{top_type}」。"
        )
        tone2 = "good" if (closure["closure_rate"] or 0) >= 60 else ("bad" if (closure["closure_rate"] or 0) < 30 else "neutral")
    else:
        text2 = "本周暂无新增风险记录，风险中心没有需要复盘的闭环数据。"
        tone2 = "neutral"
    c2 = {"index": 2, "title": "风险闭环", "text": text2, "tone": tone2, "tag": "风险",
          "metric_key": None, "risk_id": None}

    if ranking:
        top = ranking[0]
        tail = ranking[-1] if len(ranking) > 1 else None
        if tail and tail["id"] != top["id"]:
            text3 = (
                f"本周签约排名第一为 {top['name']}（{top['sign_wan']:,.1f} 万元）；"
                f"末位为 {tail['name']}（{tail['sign_wan']:,.1f} 万元），建议复盘其商机节奏。"
            )
        else:
            text3 = f"本周签约贡献最高为 {top['name']}（{top['sign_wan']:,.1f} 万元）。"
        tone3 = "neutral"
    else:
        text3 = "当前范围暂无可用于排行的签约数据。"
        tone3 = "warning"
    c3 = {"index": 3, "title": "团队排行", "text": text3, "tone": tone3, "tag": "团队",
          "metric_key": "contract_amount", "risk_id": None}
    return [c1, c2, c3]


def _weekly_points(conn: sqlite3.Connection, root_org_id: str, ranges: dict, as_of: date) -> list[dict]:
    org_ids = org_descendants(conn, root_org_id, include_self=True)
    ph = ",".join("?" for _ in org_ids)
    sign_rows = conn.execute(
        f"""SELECT sign_date, COALESCE(SUM(amount),0) amount FROM contracts
            WHERE status='active' AND sign_date >= ? AND sign_date <= ? AND org_id IN ({ph})
            GROUP BY sign_date""",
        [ranges["cur_start"].isoformat(), ranges["data_end"].isoformat()] + org_ids,
    ).fetchall()
    lead_rows = conn.execute(
        f"""SELECT created_date, COUNT(*) c FROM leads
            WHERE created_date >= ? AND created_date <= ? AND org_id IN ({ph})
            GROUP BY created_date""",
        [ranges["cur_start"].isoformat(), ranges["data_end"].isoformat()] + org_ids,
    ).fetchall()
    sign_map = {r["sign_date"]: float(r["amount"] or 0) for r in sign_rows}
    lead_map = {r["created_date"]: int(r["c"]) for r in lead_rows}
    target, _ = _period_target(conn, root_org_id, as_of, 31)
    month_target = None
    month = f"{as_of.year:04d}-{as_of.month:02d}"
    row = target_for_org(conn, root_org_id, month)
    if row and row.get("sign_target"):
        month_target = float(row["sign_target"])
    month_start, month_end = month_bounds(as_of)
    daily_target = month_target / ((month_end - month_start).days + 1) if month_target else None
    points = []
    cur = ranges["cur_start"]
    while cur <= ranges["data_end"]:
        points.append({
            "date": cur.isoformat(), "label": f"{cur.month}/{cur.day}",
            "sign_wan": money_wan(sign_map.get(cur.isoformat(), 0)),
            "target_wan": money_wan(daily_target) if daily_target else None,
            "leads": lead_map.get(cur.isoformat(), 0),
        })
        cur += timedelta(days=1)
    return points


def build_weekly_report(
    conn: sqlite3.Connection, user: dict, as_of: date = DEMO_DATE, week_type: str = "this",
    batch_id: str | None = None, published_at: str | None = None,
    generated_at: str | None = None,
) -> dict:
    week_type = week_type if week_type in {"this", "last"} else "this"
    ranges = _week_ranges(as_of, week_type)
    root = user_scope_root(conn, user)
    cur = _period_activity(conn, root, ranges["cur_start"], ranges["data_end"])
    prev = _period_activity(conn, root, ranges["compare_start"], ranges["compare_end"])
    target_sign, target_collection = _period_target(conn, root, as_of, ranges["days"])
    contract_wow = (cur["sign"] / prev["sign"] * 100 - 100) if prev["sign"] else None
    leads_wow = (cur["leads"] / prev["leads"] * 100 - 100) if prev["leads"] else None
    count_wow = (cur["contracts"] / prev["contracts"] * 100 - 100) if prev["contracts"] else None
    paid_wow = (cur["paid"] / prev["paid"] * 100 - 100) if prev["paid"] else None
    completion = (cur["sign"] / target_sign * 100) if target_sign else None
    collection_completion = (cur["paid"] / target_collection * 100) if target_collection else None
    closure = _weekly_risk_stats(conn, user, ranges)
    ranking = _weekly_ranking(conn, root, as_of, ranges)
    quality = _quality_block(conn, as_of)
    top_result = query_risks(
        conn, user, status="active", sort="priority", page_size=3,
        as_of_start=ranges["cur_start"], as_of_end=ranges["cur_end"],
    )
    top_risks = top_result["items"]
    actions = _risk_actions(conn, user, top_risks, None)

    def wow_obj(value: float | None) -> dict:
        return {
            "value": round_half_up(value, 1) if value is not None else None,
            "text": _signed_pct(value),
            "direction": "up" if value is not None and value > 0 else ("down" if value is not None and value < 0 else "flat"),
        }

    kpis = [
        {
            "key": "contract_amount", "label": "周签约额",
            "value": money_wan(cur["sign"]), "display": _fmt_wan(cur["sign"]), "unit": "万元",
            "wow": wow_obj(contract_wow),
            "sub": f"同期 {_fmt_wan(prev['sign'])}",
        },
        {
            "key": "target_completion_rate", "label": "周目标完成率",
            "value": round_half_up(completion, 1) if completion is not None else None,
            "display": _pct1(completion), "unit": "%",
            "wow": {"value": None, "text": "—", "direction": "flat"},
            "sub": f"按天折算周目标 {_fmt_wan(target_sign)}" if target_sign is not None else "目标缺失",
        },
        {
            "key": "new_leads", "label": "周新增线索",
            "value": cur["leads"], "display": f"{cur['leads']:,} 条", "unit": "条",
            "wow": wow_obj(leads_wow),
            "sub": f"有效 {cur['valid_leads']} 条",
        },
        {
            "key": "contract_count", "label": "周签约单数",
            "value": cur["contracts"], "display": f"{cur['contracts']:,} 单", "unit": "单",
            "wow": wow_obj(count_wow),
            "sub": f"同期 {prev['contracts']:,} 单",
        },
        {
            "key": "collection_amount", "label": "周回款额",
            "value": money_wan(cur["paid"]), "display": _fmt_wan(cur["paid"]), "unit": "万元",
            "wow": wow_obj(paid_wow),
            "sub": (f"周回款完成率 {_pct1(collection_completion)}" if collection_completion is not None else "回款目标缺失"),
        },
        {
            "key": "risk_closure_rate", "label": "风险闭环率",
            "value": closure["closure_rate"], "unit": "%",
            "display": _pct1(closure["closure_rate"]),
            "wow": {"value": None, "text": "—", "direction": "flat"},
            "sub": f"新增 {closure['new_count']} / 已闭环 {closure['closed_count']}",
            "raw_wow": None,
        },
    ]
    for card in kpis:
        w = card.get("wow") or {}
        card["tone"] = "good" if (w.get("value") or 0) > 0 else ("bad" if (w.get("value") or 0) < 0 else "neutral")
    # 目标完成率和闭环率以自身阈值判断颜色
    kpis[1]["tone"] = "good" if completion is not None and completion >= 100 else ("bad" if completion is not None and completion < 80 else "neutral")
    kpis[5]["tone"] = "good" if (closure["closure_rate"] or 0) >= 60 else ("bad" if closure["closure_rate"] is not None and closure["closure_rate"] < 30 else "neutral")

    conclusions = _weekly_conclusions(ranges, cur, prev, {
        "contract_wow": contract_wow, "target_completion": completion,
    }, closure, ranking)
    notes = _common_notes(conn, as_of, quality, None)
    notes.append(f"周报口径：{ranges['label']}；环比基期为 {ranges['compare_start'].month}/{ranges['compare_start'].day}–{ranges['compare_end'].month}/{ranges['compare_end'].day}。")
    if ranges["partial"]:
        notes.append("本周为周中版，数据截至业务日期 D，未包含周末数据。")
    payload = {
        "week": week_type,
        "week_type": week_type,
        "week_label": ranges["label"],
        "edition": ranges["edition"],
        "week_start": ranges["cur_start"].isoformat(),
        "week_end": ranges["cur_end"].isoformat(),
        "data_through": ranges["data_end"].isoformat(),
        "partial": ranges["partial"],
        "published_at": published_at or planned_weekly_published_at(ranges),
        "publish_schedule": "周一 09:00 正式版；周六 09:00 周中版",
        "generated_at": generated_at or now_iso(),
        "batch_id": batch_id,
        "role": user["role"],
        "scope": {"org_id": root, "name": scope_label(conn, user),
                  "role": user["role"], "role_label": user.get("title", user["role"])},
        "kpis": kpis,
        "comparison": {
            "current": {
                "start": ranges["cur_start"].isoformat(), "end": ranges["data_end"].isoformat(),
                "days": ranges["days"],
                **{k: v for k, v in cur.items() if k not in {"sign", "paid"}},
                "sign_wan": money_wan(cur["sign"]), "paid_wan": money_wan(cur["paid"]),
            },
            "previous": {
                "start": ranges["compare_start"].isoformat(), "end": ranges["compare_end"].isoformat(),
                "days": (ranges["compare_end"] - ranges["compare_start"]).days + 1,
                **{k: v for k, v in prev.items() if k not in {"sign", "paid"}},
                "sign_wan": money_wan(prev["sign"]), "paid_wan": money_wan(prev["paid"]),
            },
            "contract_wow": round_half_up(contract_wow, 1) if contract_wow is not None else None,
            "leads_wow": round_half_up(leads_wow, 1) if leads_wow is not None else None,
            "paid_wow": round_half_up(paid_wow, 1) if paid_wow is not None else None,
        },
        "risk_closure": closure,
        "risk_types": closure["risk_types"],
        "ranking": ranking,
        "daily": _weekly_points(conn, root, ranges, as_of),
        "conclusions": conclusions,
        "actions": actions,
        "top_risks": top_risks,
        "data_notes": notes,
        "data_quality": quality,
        "data_source": "SQLite 指标快照、风险事件与当前数据范围；周报闭环状态随处理进展实时更新。",
    }
    return payload


def save_weekly_reports(conn: sqlite3.Connection, as_of: date, batch_id: str) -> int:
    count = 0
    generated = now_iso()
    for week_type in ["this", "last"]:
        for user in demo_users(conn):
            payload = build_weekly_report(
                conn, user, as_of, week_type, batch_id, generated_at=generated
            )
            conn.execute(
                "DELETE FROM weekly_reports WHERE week_type=? AND week_start=? AND user_id=?",
                (week_type, payload["week_start"], user["user_id"]),
            )
            conn.execute(
                """INSERT INTO weekly_reports
                   (week_type, week_start, week_end, role, user_id, scope_org_id, batch_id,
                    payload_json, published_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (week_type, payload["week_start"], payload["week_end"], user["role"],
                 user["user_id"], payload["scope"]["org_id"], batch_id,
                 json.dumps(payload, ensure_ascii=False), payload["published_at"]),
            )
            count += 1
    return count


def patch_brief_batch_info(
    conn: sqlite3.Connection, as_of: date, finished_at: str, duration_seconds: float, steps: list[dict]
) -> None:
    """批处理结束后把最终耗时与步骤补进已生成简报，避免简报显示“进行中”。"""
    rows = conn.execute("SELECT id, payload_json FROM daily_briefs WHERE as_of=?", (as_of.isoformat(),)).fetchall()
    for row in rows:
        payload = json.loads(row["payload_json"])
        payload["batch"] = {
            "finished_at": finished_at, "duration_seconds": round(duration_seconds, 2), "steps": steps,
        }
        quality = payload.get("data_quality") or {}
        if quality.get("batch"):
            quality["batch"]["finished_at"] = finished_at
            quality["batch"]["duration_seconds"] = round(duration_seconds, 2)
            quality["batch"]["steps"] = steps
            payload["data_quality"] = quality
        conn.execute("UPDATE daily_briefs SET payload_json=? WHERE id=?", (json.dumps(payload, ensure_ascii=False), row["id"]))
