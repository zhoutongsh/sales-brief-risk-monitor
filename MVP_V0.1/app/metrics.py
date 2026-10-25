"""指标计算与下钻。

口径统一在服务端完成：
- 金额源数据以元存储，输出时转万元并保留 1 位小数；
- 率、倍数保留 1 位小数；
- 分母为 0 或目标缺失时返回 null，绝不以 0 冒充缺失；
- 组织指标按组织子树聚合，个人指标按 owner_id 过滤。
"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta

from .config import (
    AUX_METRIC_DEFS,
    DEMO_DATE,
    METRIC_DEFS,
    METRIC_MAP,
    money_wan,
    month_bounds,
    round_half_up,
)
from .scope import (
    all_orgs,
    child_scope_orgs,
    org_descendants,
    scope_label,
    scope_users,
    target_for_org,
    target_for_user,
    user_scope_root,
)

CAMPAIGN_CHANNEL = {
    "CMP-INFO": "信息流",
    "CMP-SEO": "自然搜索",
    "CMP-PARTNER": "渠道伙伴",
    "CMP-REFERRAL": "老客转介绍",
    "CMP-CONTENT": "内容营销",
}

CHANNELS = ["信息流", "自然搜索", "渠道伙伴", "老客转介绍", "内容营销"]


def _ph(items: list[str]) -> str:
    return ",".join("?" for _ in items)


def _channel_of_campaign(campaign_id: str | None) -> str | None:
    if not campaign_id:
        return None
    for prefix, channel in CAMPAIGN_CHANNEL.items():
        if campaign_id.startswith(prefix):
            return channel
    return None


def _owner_clause(owner_user_id: str | None, alias: str = "") -> tuple[str, list]:
    if not owner_user_id:
        return "", []
    col = f"{alias}.owner_id" if alias else "owner_id"
    return f" AND {col} = ?", [owner_user_id]


def _sum(conn: sqlite3.Connection, sql: str, params: list | tuple = ()) -> float:
    row = conn.execute(sql, params).fetchone()
    return float(row[0] or 0)


def compute_metrics(
    conn: sqlite3.Connection,
    root_org_id: str,
    as_of: date | str = DEMO_DATE,
    owner_user_id: str | None = None,
) -> dict:
    """计算某组织（子树）或某用户在业务日期 D 的 12 项指标及辅助指标。

    返回值中的金额均为元，比率均为百分数，倍数为原始倍数。
    目标缺失时依赖目标的指标为 None。
    """
    d = date.fromisoformat(as_of) if isinstance(as_of, str) else as_of
    d_str = d.isoformat()
    month_start, month_end = month_bounds(d)
    month = f"{d.year:04d}-{d.month:02d}"
    org_ids = org_descendants(conn, root_org_id, include_self=True)
    if owner_user_id:
        owner_org = conn.execute("SELECT org_id FROM users WHERE user_id = ?", (owner_user_id,)).fetchone()
        if owner_org and owner_org["org_id"] not in org_ids:
            org_ids = [owner_org["org_id"]]
    ph = _ph(org_ids)
    params_org = list(org_ids)
    owner_sql, owner_params = _owner_clause(owner_user_id)

    # --- 线索（当日） ---
    lead_where = f"created_date = ? AND org_id IN ({ph}){owner_sql}"
    lead_params = [d_str] + params_org + owner_params
    new_leads = int(_sum(conn, f"SELECT COUNT(*) FROM leads WHERE {lead_where}", lead_params))
    valid_leads = int(
        _sum(conn, f"SELECT COUNT(*) FROM leads WHERE {lead_where} AND status = 'valid'", lead_params)
    )
    converted = int(
        _sum(conn, f"SELECT COUNT(*) FROM leads WHERE {lead_where} AND converted = 1", lead_params)
    )
    lead_valid_rate = valid_leads / new_leads * 100 if new_leads else None
    lead_conversion_rate = converted / valid_leads * 100 if valid_leads else None

    # --- 商机 ---
    opp_where = f"created_date = ? AND org_id IN ({ph}){owner_sql}"
    new_opps = int(
        _sum(conn, f"SELECT COUNT(*) FROM opportunities WHERE {opp_where}", [d_str] + params_org + owner_params)
    )
    pipeline_where = f"status = 'open' AND created_date <= ? AND org_id IN ({ph}){owner_sql}"
    pipeline = _sum(
        conn,
        f"SELECT COALESCE(SUM(amount),0) FROM opportunities WHERE {pipeline_where}",
        [d_str] + params_org + owner_params,
    )

    # --- 签约（当日与当月累计） ---
    sign_where = f"sign_date = ? AND status = 'active' AND org_id IN ({ph}){owner_sql}"
    sign_params = [d_str] + params_org + owner_params
    contract_amount = _sum(conn, f"SELECT COALESCE(SUM(amount),0) FROM contracts WHERE {sign_where}", sign_params)
    contract_count = int(_sum(conn, f"SELECT COUNT(*) FROM contracts WHERE {sign_where}", sign_params))
    month_sign_where = f"sign_date >= ? AND sign_date <= ? AND status = 'active' AND org_id IN ({ph}){owner_sql}"
    month_sign_params = [month_start.isoformat(), d_str] + params_org + owner_params
    month_signed = _sum(
        conn,
        f"SELECT COALESCE(SUM(amount),0) FROM contracts WHERE {month_sign_where}",
        month_sign_params,
    )

    # --- 目标 ---
    target_row = target_for_user(conn, owner_user_id, month) if owner_user_id else target_for_org(conn, root_org_id, month)
    target_sign = float(target_row["sign_target"]) if target_row and target_row.get("sign_target") is not None else None
    target_collection = float(target_row["collection_target"]) if target_row and target_row.get("collection_target") is not None else None

    target_completion_rate = month_signed / target_sign * 100 if target_sign else None
    remaining_target = (target_sign - month_signed) if target_sign is not None else None
    opportunity_coverage = pipeline / remaining_target if remaining_target and remaining_target > 0 else None

    # --- 回款（当月累计） ---
    paid_where = f"paid_date >= ? AND paid_date <= ? AND org_id IN ({ph}){owner_sql}"
    collection_amount = _sum(
        conn,
        f"SELECT COALESCE(SUM(paid_amount),0) FROM receivables WHERE {paid_where}",
        [month_start.isoformat(), d_str] + params_org + owner_params,
    )
    collection_completion_rate = collection_amount / target_collection * 100 if target_collection else None

    # --- 投放与 ROI（投放源为公司级，分母使用当月公司投放费用） ---
    ad_spend = _sum(
        conn,
        "SELECT COALESCE(SUM(spend),0) FROM ad_spend WHERE date >= ? AND date <= ?",
        [month_start.isoformat(), d_str],
    )
    attributed_where = (
        f"sign_date >= ? AND sign_date <= ? AND status = 'active' "
        f"AND COALESCE(campaign_id,'') <> '' AND org_id IN ({ph}){owner_sql}"
    )
    attributed_signed = _sum(
        conn,
        f"SELECT COALESCE(SUM(amount),0) FROM contracts WHERE {attributed_where}",
        [month_start.isoformat(), d_str] + params_org + owner_params,
    )
    marketing_roi = attributed_signed / ad_spend if ad_spend else None

    # --- 周环比辅助口径：本周一至 D vs 上周一至同跨度 ---
    week_start = d - timedelta(days=d.weekday())
    span = (d - week_start).days + 1
    prev_week_start = week_start - timedelta(days=7)
    prev_week_end = prev_week_start + timedelta(days=span - 1)
    cur_leads = int(_sum(
        conn,
        f"SELECT COUNT(*) FROM leads WHERE created_date >= ? AND created_date <= ? AND org_id IN ({ph}){owner_sql}",
        [week_start.isoformat(), d_str] + params_org + owner_params,
    ))
    prev_leads = int(_sum(
        conn,
        f"SELECT COUNT(*) FROM leads WHERE created_date >= ? AND created_date <= ? AND org_id IN ({ph}){owner_sql}",
        [prev_week_start.isoformat(), prev_week_end.isoformat()] + params_org + owner_params,
    ))
    leads_wow = (cur_leads / prev_leads * 100 - 100) if prev_leads else None
    cur_sign = _sum(
        conn,
        f"SELECT COALESCE(SUM(amount),0) FROM contracts WHERE sign_date >= ? AND sign_date <= ? AND status = 'active' AND org_id IN ({ph}){owner_sql}",
        [week_start.isoformat(), d_str] + params_org + owner_params,
    )
    prev_sign = _sum(
        conn,
        f"SELECT COALESCE(SUM(amount),0) FROM contracts WHERE sign_date >= ? AND sign_date <= ? AND status = 'active' AND org_id IN ({ph}){owner_sql}",
        [prev_week_start.isoformat(), prev_week_end.isoformat()] + params_org + owner_params,
    )
    contract_wow = (cur_sign / prev_sign * 100 - 100) if prev_sign else None

    days_in_month = (month_end - month_start).days + 1
    time_progress = d.day / days_in_month * 100

    return {
        "new_leads": new_leads,
        "valid_leads": valid_leads,
        "lead_valid_rate": lead_valid_rate,
        "lead_conversion_rate": lead_conversion_rate,
        "new_opportunities": new_opps,
        "pipeline_amount": pipeline,
        "opportunity_coverage": opportunity_coverage,
        "contract_amount": contract_amount,
        "contract_count": contract_count,
        "target_completion_rate": target_completion_rate,
        "collection_completion_rate": collection_completion_rate,
        "marketing_roi": marketing_roi,
        "ad_spend": ad_spend,
        "collection_amount": collection_amount,
        "leads_wow": leads_wow,
        "contract_wow": contract_wow,
        "time_progress": time_progress,
        # 仅用于简报组装，不直接作为 12 项指标返回
        "_month_signed": month_signed,
        "_target_sign": target_sign,
        "_target_collection": target_collection,
        "_remaining_target": remaining_target,
        "_attributed_signed": attributed_signed,
        "_week_start": week_start.isoformat(),
        "_week_span": span,
        "_cur_week_sign": cur_sign,
        "_prev_week_sign": prev_sign,
        "_cur_week_leads": cur_leads,
        "_prev_week_leads": prev_leads,
    }


def format_metric_value(key: str, raw: float | int | None) -> float | int | None:
    meta = METRIC_MAP.get(key) or next((m for m in AUX_METRIC_DEFS if m["key"] == key), None)
    if raw is None or not meta:
        return None
    kind = meta["kind"]
    if kind == "count":
        return int(round(float(raw)))
    if kind == "money_wan":
        return money_wan(raw)
    return round_half_up(float(raw), 1)


def metric_display(key: str, raw: float | int | None) -> str:
    meta = METRIC_MAP.get(key) or next((m for m in AUX_METRIC_DEFS if m["key"] == key), None)
    if raw is None or not meta:
        return "—"
    if meta["unit"] == "%":
        return f"{format_metric_value(key, raw):.1f}%"
    if meta["unit"] == "万元":
        return f"{format_metric_value(key, raw):,.1f} 万元"
    if meta["unit"] == "倍":
        return f"{format_metric_value(key, raw):.1f} 倍"
    if meta["unit"] == "条":
        return f"{int(format_metric_value(key, raw)):,} 条"
    if meta["unit"] == "单":
        return f"{int(format_metric_value(key, raw)):,} 单"
    return str(format_metric_value(key, raw))


def metric_item(key: str, raw: float | int | None, meta: dict | None = None) -> dict:
    meta = meta or METRIC_MAP.get(key) or next((m for m in AUX_METRIC_DEFS if m["key"] == key), {})
    value = format_metric_value(key, raw)
    return {
        "key": key,
        "label": meta.get("label", key),
        "unit": meta.get("unit", ""),
        "kind": meta.get("kind", ""),
        "formula": meta.get("formula", ""),
        "source": meta.get("source", ""),
        "value": value,
        "display": metric_display(key, raw),
        "available": value is not None,
    }


def load_metric_payload(conn: sqlite3.Connection, user: dict, d: date | None = None) -> dict:
    d = d or DEMO_DATE
    root = user_scope_root(conn, user)
    rows = conn.execute(
        "SELECT * FROM metric_snapshots WHERE as_of = ? AND scope_type = 'org' AND scope_id = ?",
        (d.isoformat(), root),
    ).fetchall()
    by_key = {r["metric_key"]: r for r in rows}
    batch_id = rows[0]["batch_id"] if rows else None
    batch = conn.execute("SELECT * FROM batch_runs WHERE batch_id = ?", (batch_id,)).fetchone() if batch_id else None
    generated_at = batch["finished_at"] if batch and batch["finished_at"] else (batch["started_at"] if batch else None)
    payload = {
        "date": d.isoformat(),
        "as_of": d.isoformat(),
        "generated_at": generated_at,
        "batch_id": batch_id,
        "batch_status": batch["status"] if batch else None,
        "scope": {
            "org_id": root,
            "name": scope_label(conn, user),
            "role": user["role"],
            "role_label": user.get("title", user["role"]),
        },
        "data_available": bool(rows),
        "metrics": [],
        "auxiliary": [],
    }
    if not rows:
        payload["message"] = "当天没有已发布的指标快照，请先运行批处理。"
        for meta in METRIC_DEFS:
            payload["metrics"].append(metric_item(meta["key"], None, meta))
        for meta in AUX_METRIC_DEFS:
            payload["auxiliary"].append(metric_item(meta["key"], None, meta))
        return payload
    for meta in METRIC_DEFS:
        row = by_key.get(meta["key"])
        raw = row["value"] if row else None
        item = metric_item(meta["key"], raw, meta)
        item["available"] = row is not None and row["value"] is not None
        payload["metrics"].append(item)
    for meta in AUX_METRIC_DEFS:
        row = by_key.get(meta["key"])
        payload["auxiliary"].append(metric_item(meta["key"], row["value"] if row else None, meta))
    return payload


def store_metric_snapshots(conn: sqlite3.Connection, batch_id: str, d: date) -> int:
    """为每个组织写入 12 项指标和 5 项辅助指标快照，同日重跑覆盖。"""
    from .config import now_iso

    now = now_iso()
    count = 0
    for org in all_orgs(conn):
        values = compute_metrics(conn, org["org_id"], d)
        for meta in list(METRIC_DEFS) + list(AUX_METRIC_DEFS):
            raw = values.get(meta["key"])
            conn.execute(
                """INSERT INTO metric_snapshots
                   (batch_id, as_of, scope_type, scope_id, metric_key, value, unit, formula, source, created_at)
                   VALUES (?, ?, 'org', ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(as_of, scope_type, scope_id, metric_key)
                   DO UPDATE SET batch_id=excluded.batch_id, value=excluded.value,
                                 unit=excluded.unit, formula=excluded.formula,
                                 source=excluded.source, created_at=excluded.created_at""",
                (batch_id, d.isoformat(), org["org_id"], meta["key"], raw, meta.get("unit"),
                 meta.get("formula"), meta.get("source"), now),
            )
            count += 1
    return count


def _drill_candidates(conn: sqlite3.Connection, root_org_id: str) -> tuple[str, list[dict]]:
    orgs = child_scope_orgs(conn, root_org_id)
    if orgs:
        return "org", [
            {"id": o["org_id"], "name": o["name"], "type": "org", "org_id": o["org_id"]}
            for o in orgs
        ]
    users = scope_users(conn, [root_org_id])
    return "user", [
        {"id": u["user_id"], "name": u["name"], "type": "user", "org_id": u["org_id"],
         "title": u.get("title", "")}
        for u in users
    ]


def build_drill(conn: sqlite3.Connection, user: dict, metric_key: str, d: date | None = None) -> dict | None:
    meta = METRIC_MAP.get(metric_key) or next((m for m in AUX_METRIC_DEFS if m["key"] == metric_key), None)
    if not meta:
        return None
    d = d or DEMO_DATE
    root = user_scope_root(conn, user)
    drill_type, candidates = _drill_candidates(conn, root)
    total_values = compute_metrics(conn, root, d)
    total_raw = total_values.get(metric_key)
    items = []
    for c in candidates:
        if drill_type == "org":
            vals = compute_metrics(conn, c["id"], d)
            raw = vals.get(metric_key)
        else:
            vals = compute_metrics(conn, root, d, owner_user_id=c["id"])
            raw = vals.get(metric_key)
        display_value = format_metric_value(metric_key, raw)
        share = None
        if meta["kind"] in {"money_wan", "count"} and total_raw and raw is not None:
            share = round_half_up(float(raw) / float(total_raw) * 100, 1)
        items.append({
            "id": c["id"],
            "name": c["name"],
            "type": c["type"],
            "org_id": c["org_id"],
            "title": c.get("title", ""),
            "value": display_value,
            "display": metric_display(metric_key, raw),
            "share": share,
            "unit": meta["unit"],
            "available": display_value is not None,
        })
    items.sort(key=lambda x: (x["value"] is None, -(x["value"] or 0), x["name"]))
    return {
        "date": d.isoformat(),
        "metric": meta,
        "scope": {"org_id": root, "name": scope_label(conn, user)},
        "drill_type": drill_type,
        "total": metric_item(metric_key, total_raw, meta),
        "items": items,
        "data_available": any(i["available"] for i in items),
    }


def _candidate_groups(conn: sqlite3.Connection, root_org_id: str) -> tuple[str, list[dict]]:
    orgs = child_scope_orgs(conn, root_org_id)
    if orgs:
        return "org", [{"id": o["org_id"], "name": o["name"], "type": "org"} for o in orgs]
    users = scope_users(conn, [root_org_id])
    return "user", [{"id": u["user_id"], "name": u["name"], "type": "user"} for u in users]


def compute_movers(conn: sqlite3.Connection, root_org_id: str, d: date, limit: int = 3) -> dict:
    """近 7 个自然日 vs 前 7 个自然日的签约额变化，返回增长/下滑 Top N。"""
    cur_start = d - timedelta(days=6)
    prev_start = d - timedelta(days=13)
    prev_end = d - timedelta(days=7)
    kind, groups = _candidate_groups(conn, root_org_id)
    rows = []
    for g in groups:
        if kind == "org":
            org_ids = org_descendants(conn, g["id"], include_self=True)
            ph = _ph(org_ids)
            cur = _sum(
                conn,
                f"SELECT COALESCE(SUM(amount),0) FROM contracts WHERE sign_date >= ? AND sign_date <= ? AND status='active' AND org_id IN ({ph})",
                [cur_start.isoformat(), d.isoformat()] + org_ids,
            )
            prev = _sum(
                conn,
                f"SELECT COALESCE(SUM(amount),0) FROM contracts WHERE sign_date >= ? AND sign_date <= ? AND status='active' AND org_id IN ({ph})",
                [prev_start.isoformat(), prev_end.isoformat()] + org_ids,
            )
        else:
            cur = _sum(
                conn,
                "SELECT COALESCE(SUM(amount),0) FROM contracts WHERE sign_date >= ? AND sign_date <= ? AND status='active' AND owner_id = ?",
                [cur_start.isoformat(), d.isoformat(), g["id"]],
            )
            prev = _sum(
                conn,
                "SELECT COALESCE(SUM(amount),0) FROM contracts WHERE sign_date >= ? AND sign_date <= ? AND status='active' AND owner_id = ?",
                [prev_start.isoformat(), prev_end.isoformat(), g["id"]],
            )
        delta = cur - prev
        change_pct = (cur / prev * 100 - 100) if prev > 0 else None
        if cur == 0 and prev == 0:
            continue
        rows.append({
            "id": g["id"],
            "name": g["name"],
            "type": g["type"],
            "current_wan": money_wan(cur),
            "previous_wan": money_wan(prev),
            "change_wan": money_wan(delta),
            "change_pct": round_half_up(change_pct, 1) if change_pct is not None else None,
            "direction": "up" if delta > 0 else ("down" if delta < 0 else "flat"),
        })
    growth = sorted(
        [r for r in rows if r["change_wan"] and r["change_wan"] > 0],
        key=lambda x: x["change_wan"], reverse=True,
    )[:limit]
    decline = sorted(
        [r for r in rows if r["change_wan"] and r["change_wan"] < 0],
        key=lambda x: x["change_wan"],
    )[:limit]
    return {
        "growth": growth,
        "decline": decline,
        "period": {
            "cur_start": cur_start.isoformat(), "cur_end": d.isoformat(),
            "prev_start": prev_start.isoformat(), "prev_end": prev_end.isoformat(),
        },
    }


def compute_channel_analysis(
    conn: sqlite3.Connection, root_org_id: str, d: date, owner_user_id: str | None = None
) -> list[dict]:
    """渠道表：近 30 天线索、有效、转化、归因签约、投放、ROI 与线索周环比。"""
    start = d - timedelta(days=29)
    org_ids = org_descendants(conn, root_org_id, include_self=True)
    ph = _ph(org_ids)
    owner_sql, owner_params = _owner_clause(owner_user_id)
    lead_rows = conn.execute(
        f"""SELECT source, COUNT(*) AS leads,
                   SUM(CASE WHEN status='valid' THEN 1 ELSE 0 END) AS valid,
                   SUM(CASE WHEN converted=1 THEN 1 ELSE 0 END) AS converted
            FROM leads WHERE created_date >= ? AND created_date <= ? AND org_id IN ({ph}){owner_sql}
            GROUP BY source""",
        [start.isoformat(), d.isoformat()] + org_ids + owner_params,
    ).fetchall()
    lead_map = {r["source"]: dict(r) for r in lead_rows}
    contract_rows = conn.execute(
        f"""SELECT campaign_id, amount FROM contracts
            WHERE sign_date >= ? AND sign_date <= ? AND status='active' AND org_id IN ({ph}){owner_sql}""",
        [start.isoformat(), d.isoformat()] + org_ids + owner_params,
    ).fetchall()
    sign_by_channel: dict[str, float] = {}
    for r in contract_rows:
        ch = _channel_of_campaign(r["campaign_id"])
        if ch:
            sign_by_channel[ch] = sign_by_channel.get(ch, 0) + float(r["amount"] or 0)
    spend_rows = conn.execute(
        "SELECT channel, COALESCE(SUM(spend),0) AS spend FROM ad_spend WHERE date >= ? AND date <= ? GROUP BY channel",
        (start.isoformat(), d.isoformat()),
    ).fetchall()
    spend_map = {r["channel"]: float(r["spend"] or 0) for r in spend_rows}
    week_start = d - timedelta(days=d.weekday())
    prev_start = week_start - timedelta(days=7)
    span = (d - week_start).days
    prev_end = prev_start + timedelta(days=span)
    cur_week = conn.execute(
        f"SELECT source, COUNT(*) AS c FROM leads WHERE created_date >= ? AND created_date <= ? AND org_id IN ({ph}){owner_sql} GROUP BY source",
        [week_start.isoformat(), d.isoformat()] + org_ids + owner_params,
    ).fetchall()
    prev_week = conn.execute(
        f"SELECT source, COUNT(*) AS c FROM leads WHERE created_date >= ? AND created_date <= ? AND org_id IN ({ph}){owner_sql} GROUP BY source",
        [prev_start.isoformat(), prev_end.isoformat()] + org_ids + owner_params,
    ).fetchall()
    cur_map = {r["source"]: int(r["c"]) for r in cur_week}
    prev_map = {r["source"]: int(r["c"]) for r in prev_week}
    total_leads = sum(int(r["leads"] or 0) for r in lead_map.values())
    rows = []
    for channel in CHANNELS:
        lm = lead_map.get(channel, {})
        leads_n = int(lm.get("leads", 0) or 0)
        valid_n = int(lm.get("valid", 0) or 0)
        conv_n = int(lm.get("converted", 0) or 0)
        spend = spend_map.get(channel, 0)
        signed = sign_by_channel.get(channel, 0)
        wow = (cur_map.get(channel, 0) / prev_map[channel] * 100 - 100) if prev_map.get(channel, 0) else None
        rows.append({
            "channel": channel,
            "leads": leads_n,
            "valid_leads": valid_n,
            "valid_rate": round_half_up(valid_n / leads_n * 100, 1) if leads_n else None,
            "converted": conv_n,
            "conversion_rate": round_half_up(conv_n / valid_n * 100, 1) if valid_n else None,
            "share": round_half_up(leads_n / total_leads * 100, 1) if total_leads else None,
            "contract_amount_wan": money_wan(signed),
            "spend_wan": money_wan(spend),
            "roi": round_half_up(signed / spend, 1) if spend else None,
            "leads_wow": round_half_up(wow, 1) if wow is not None else None,
        })
    rows.sort(key=lambda x: (-x["leads"], x["channel"]))
    return rows


def compute_trend(conn: sqlite3.Connection, root_org_id: str, d: date, days: int = 14) -> dict:
    start = d - timedelta(days=days - 1)
    org_ids = org_descendants(conn, root_org_id, include_self=True)
    ph = _ph(org_ids)
    sign_rows = conn.execute(
        f"""SELECT sign_date, COALESCE(SUM(amount),0) AS amount, COUNT(*) AS cnt
            FROM contracts WHERE sign_date >= ? AND sign_date <= ? AND status='active'
              AND org_id IN ({ph}) GROUP BY sign_date""",
        [start.isoformat(), d.isoformat()] + org_ids,
    ).fetchall()
    lead_rows = conn.execute(
        f"""SELECT created_date, COUNT(*) AS cnt FROM leads
            WHERE created_date >= ? AND created_date <= ? AND org_id IN ({ph})
            GROUP BY created_date""",
        [start.isoformat(), d.isoformat()] + org_ids,
    ).fetchall()
    sign_map = {r["sign_date"]: float(r["amount"] or 0) for r in sign_rows}
    count_map = {r["sign_date"]: int(r["cnt"] or 0) for r in sign_rows}
    lead_map = {r["created_date"]: int(r["cnt"] or 0) for r in lead_rows}
    month_start, month_end = month_bounds(d)
    target = target_for_org(conn, root_org_id, f"{d.year:04d}-{d.month:02d}")
    daily_target = (float(target["sign_target"]) / ((month_end - month_start).days + 1)) if target else None
    points = []
    cur = start
    while cur <= d:
        signed = sign_map.get(cur.isoformat(), 0.0)
        points.append({
            "date": cur.isoformat(),
            "label": f"{cur.month}/{cur.day}",
            "sign_wan": money_wan(signed),
            "target_wan": money_wan(daily_target) if daily_target else None,
            "contracts": count_map.get(cur.isoformat(), 0),
            "leads": lead_map.get(cur.isoformat(), 0),
        })
        cur += timedelta(days=1)
    return {
        "start": start.isoformat(), "end": d.isoformat(), "points": points,
        "daily_target_wan": money_wan(daily_target) if daily_target else None,
    }


def _fmt_wan(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{money_wan(value):,.1f} 万元"


def metrics_summary_for_brief(conn: sqlite3.Connection, root_org_id: str, d: date) -> dict:
    vals = compute_metrics(conn, root_org_id, d)
    prev = compute_metrics(conn, root_org_id, d - timedelta(days=1))
    cards = []
    for key in [
        "contract_amount", "target_completion_rate", "new_leads",
        "marketing_roi", "opportunity_coverage", "collection_completion_rate",
    ]:
        meta = METRIC_MAP[key]
        value = format_metric_value(key, vals.get(key))
        delta = None
        delta_unit = ""
        if key == "target_completion_rate":
            if vals.get(key) is not None:
                delta = round_half_up(vals[key] - vals["time_progress"], 1)
                delta_unit = "pp"
        elif key == "collection_completion_rate":
            if vals.get(key) is not None:
                delta = round_half_up(vals[key] - vals["time_progress"], 1)
                delta_unit = "pp"
        elif key == "opportunity_coverage":
            if vals.get(key) is not None:
                delta = round_half_up(vals[key] - 2.5, 2)
                delta_unit = "倍"
        else:
            old = prev.get(key)
            if vals.get(key) is not None and old:
                delta = round_half_up((vals[key] / old - 1) * 100, 1)
                delta_unit = "%"
        sub = ""
        if key == "contract_amount":
            sub = f"月累计 {_fmt_wan(vals['_month_signed'])}"
        elif key == "target_completion_rate":
            sub = f"时间进度 {round_half_up(vals['time_progress'], 1):.1f}%"
        elif key == "new_leads":
            sub = (
                f"有效 {vals['valid_leads']} 条 · 转化率 "
                f"{metric_display('lead_conversion_rate', vals['lead_conversion_rate'])}"
            )
        elif key == "marketing_roi":
            sub = f"本月投放 {_fmt_wan(vals['ad_spend'])}"
        elif key == "opportunity_coverage":
            rem = vals["_remaining_target"]
            sub = f"剩余目标 {_fmt_wan(rem)}" if rem is not None else "剩余目标缺失"
        elif key == "collection_completion_rate":
            sub = f"月累计回款 {_fmt_wan(vals['collection_amount'])}"
        cards.append({
            "key": key,
            "label": meta["label"],
            "value": value,
            "display": metric_display(key, vals.get(key)),
            "unit": meta["unit"],
            "sub": sub,
            "delta": delta,
            "delta_unit": delta_unit,
            "tone": "good" if delta is not None and delta > 0 else ("bad" if delta is not None and delta < 0 else "neutral"),
            "meaning": meta["formula"],
        })
    return {"raw": vals, "cards": cards}
