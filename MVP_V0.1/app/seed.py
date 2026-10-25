"""生成确定性的 30 天演示源数据。

数据故意只通过业务事实触发风险，风险清单另写 data/expected_risks.csv。
"""
from __future__ import annotations

import csv
import math
import random
from datetime import date, timedelta
from pathlib import Path

from .config import (
    DATE_RANGE_END,
    DATE_RANGE_START,
    DEMO_DATE,
    EXPECTED_RISKS_PATH,
    SOURCE_DIR,
)

RNG = random.Random(20261024)
NOW_STAMP = "2026-10-24T08:00:00+08:00"

ORGS = [
    ("C001", "全公司", None, "company", 0, "u_gm"),
    ("E100", "华东事业部", "C001", "region", 10, "u_bu"),
    ("E110", "华东一部", "E100", "department", 11, "u_sm"),
    ("E120", "华东二部", "E100", "department", 12, "u_ea2"),
    ("E130", "华东三部", "E100", "department", 13, "u_ea3"),
    ("E140", "华东四部", "E100", "department", 14, "u_ea4"),
    ("S200", "华南大区", "C001", "region", 20, "u_south"),
    ("S210", "华南一部", "S200", "department", 21, "u_south1"),
    ("S220", "华南二部", "S200", "department", 22, "u_south2"),
    ("N300", "华北大区", "C001", "region", 30, "u_north"),
    ("W400", "西部大区", "C001", "region", 40, "u_west"),
]
ORG_BY_ID = {o[0]: o for o in ORGS}

USERS = [
    # user_id, name, role, title, org_id, phone, email, manager_id, is_demo
    ("u_gm", "张建国", "gm", "公司总经理", "C001", "13800001001", "zhang.jianguo@corp.com", "", 1),
    ("u_sd", "李敏", "sd", "销售总监", "C001", "13800001002", "li.min@corp.com", "u_gm", 1),
    ("u_bu", "王强", "bu", "华东事业部总经理", "E100", "13800001003", "wang.qiang@corp.com", "u_sd", 1),
    ("u_sm", "李娜", "sm", "华东一部销售经理", "E110", "13800001004", "li.na@corp.com", "u_bu", 1),
    ("u_ea2", "周涛", "sm", "华东二部销售经理", "E120", "13800002001", "zhou.tao@corp.com", "u_bu", 0),
    ("u_ea3", "孙浩", "sm", "华东三部销售经理", "E130", "13800002002", "sun.hao@corp.com", "u_bu", 0),
    ("u_ea4", "吴迪", "sm", "华东四部销售经理", "E140", "13800002003", "wu.di@corp.com", "u_bu", 0),
    ("u_south", "赵磊", "bu", "华南大区总经理", "S200", "13800001005", "zhao.lei@corp.com", "u_sd", 0),
    ("u_south1", "周敏", "sm", "华南一部销售经理", "S210", "13800002004", "zhou.min@corp.com", "u_south", 0),
    ("u_south2", "冯霞", "sm", "华南二部销售经理", "S220", "13800002005", "feng.xia@corp.com", "u_south", 0),
    ("u_north", "刘洋", "bu", "华北大区总经理", "N300", "13800001006", "liu.yang@corp.com", "u_sd", 0),
    ("u_west", "陈刚", "bu", "西部大区总经理", "W400", "13800001007", "chen.gang@corp.com", "u_sd", 0),
    ("u_e101", "韩雪", "rep", "销售代表", "E110", "13800003001", "han.xue@corp.com", "u_sm", 0),
    ("u_e102", "张伟", "rep", "销售代表", "E110", "13800003002", "zhang.wei@corp.com", "u_sm", 0),
    ("u_e103", "高阳", "rep", "销售代表", "E110", "13800003003", "gao.yang@corp.com", "u_sm", 0),
    ("u_e201", "林菲", "rep", "销售代表", "E120", "13800003004", "lin.fei@corp.com", "u_ea2", 0),
    ("u_e202", "郑凯", "rep", "销售代表", "E120", "13800003005", "zheng.kai@corp.com", "u_ea2", 0),
    ("u_e301", "王磊", "rep", "销售代表", "E130", "13800003006", "wang.lei@corp.com", "u_ea3", 0),
    ("u_e302", "何静", "rep", "销售代表", "E130", "13800003007", "he.jing@corp.com", "u_ea3", 0),
    ("u_e401", "谢婷", "rep", "销售代表", "E140", "13800003008", "xie.ting@corp.com", "u_ea4", 0),
    ("u_e402", "罗军", "rep", "销售代表", "E140", "13800003009", "luo.jun@corp.com", "u_ea4", 0),
    ("u_s201", "马骏", "rep", "销售代表", "S210", "13800003010", "ma.jun@corp.com", "u_south1", 0),
    ("u_s202", "唐悦", "rep", "销售代表", "S210", "13800003011", "tang.yue@corp.com", "u_south1", 0),
    ("u_s221", "徐晨", "rep", "销售代表", "S220", "13800003012", "xu.chen@corp.com", "u_south2", 0),
    ("u_s222", "何雨", "rep", "销售代表", "S220", "13800003013", "he.yu@corp.com", "u_south2", 0),
    ("u_n301", "高翔", "rep", "销售代表", "N300", "13800003014", "gao.xiang@corp.com", "u_north", 0),
    ("u_n302", "李想", "rep", "销售代表", "N300", "13800003015", "li.xiang@corp.com", "u_north", 0),
    ("u_w401", "周杰", "rep", "销售代表", "W400", "13800003016", "zhou.jie@corp.com", "u_west", 0),
    ("u_w402", "段宁", "rep", "销售代表", "W400", "13800003017", "duan.ning@corp.com", "u_west", 0),
    ("u_mkt", "陈晨", "marketing", "市场/线索负责人", "C001", "13800001008", "chen.chen@corp.com", "u_sd", 0),
]
USER_BY_ID = {u[0]: u for u in USERS}
DEMO_USER_IDS = ["u_gm", "u_sd", "u_bu", "u_sm"]

LEAF_ORGS = ["E110", "E120", "E130", "E140", "S210", "S220", "N300", "W400"]
ORG_TARGETS = {
    "C001": (60_000_000, 48_000_000),
    "E100": (25_000_000, 20_000_000),
    "E110": (8_000_000, 6_400_000),
    "E120": (6_500_000, 5_200_000),
    "E130": (5_500_000, 4_400_000),
    "E140": (5_000_000, 4_000_000),
    "S200": (14_000_000, 11_200_000),
    "S210": (7_500_000, 6_000_000),
    "S220": (6_500_000, 5_200_000),
    "N300": (11_000_000, 8_800_000),
    "W400": (10_000_000, 8_000_000),
}
CONTRACT_MONTH_TOTALS = {
    "E110": 6_900_000,
    "E120": 5_200_000,
    "E130": 4_000_000,
    "E140": 3_000_000,
    "S210": 7_000_000,
    "S220": 6_000_000,
    "N300": 8_500_000,
    "W400": 5_000_000,
}
PIPELINE_TARGETS = {
    "E110": 5_000_000,
    "E120": 2_500_000,
    "E130": 4_200_000,
    "E140": 5_600_000,
    "S210": 5_500_000,
    "S220": 5_000_000,
    "N300": 11_000_000,
    "W400": 14_000_000,
}
OPEN_OPP_COUNTS = {
    "E110": 28,
    "E120": 20,
    "E130": 22,
    "E140": 20,
    "S210": 18,
    "S220": 16,
    "N300": 20,
    "W400": 16,
}
COLLECTION_TARGETS = {
    "E110": 4_800_000,
    "E120": 3_600_000,
    "E130": 2_800_000,
    "E140": 2_000_000,
    "S210": 5_000_000,
    "S220": 4_200_000,
    "N300": 6_500_000,
    "W400": 4_000_000,
}

# 每周线索口径：上周 10/12-10/17 与本周 10/19-10/24 同为 6 天。
LEAD_WEEK_PROFILE = {
    "E110": {"prev": 35, "curr": 38, "vp": 23, "cp": 25, "cvp": 4, "cvc": 4},
    "E120": {"prev": 28, "curr": 30, "vp": 17, "cp": 19, "cvp": 2, "cvc": 3},
    "E130": {"prev": 25, "curr": 24, "vp": 15, "cp": 15, "cvp": 2, "cvc": 2},
    # 本周线索量比上周同期下降 50%，触发橙色线索异常
    "E140": {"prev": 30, "curr": 15, "vp": 20, "cp": 10, "cvp": 6, "cvc": 3},
    "S210": {"prev": 32, "curr": 34, "vp": 20, "cp": 22, "cvp": 3, "cvc": 4},
    "S220": {"prev": 27, "curr": 29, "vp": 16, "cp": 17, "cvp": 2, "cvc": 2},
    # 转化率 27.8% -> 20.0%（相对 -28%），触发黄色线索异常
    "N300": {"prev": 30, "curr": 33, "vp": 18, "cp": 20, "cvp": 5, "cvc": 4},
    "W400": {"prev": 25, "curr": 25, "vp": 16, "cp": 16, "cvp": 3, "cvc": 3},
}
LEAD_TOTALS = {
    "E110": 160,
    "E120": 130,
    "E130": 115,
    "E140": 100,
    "S210": 140,
    "S220": 120,
    "N300": 130,
    "W400": 105,
}

CHANNELS = ["信息流", "自然搜索", "渠道伙伴", "老客转介绍", "内容营销"]
CAMPAIGN_BY_CHANNEL = {
    "信息流": "CMP-INFO-01",
    "自然搜索": "CMP-SEO-01",
    "渠道伙伴": "CMP-PARTNER-01",
    "老客转介绍": "CMP-REFERRAL-01",
    "内容营销": "CMP-CONTENT-01",
}
CHANNEL_BY_CAMPAIGN = {v: k for k, v in CAMPAIGN_BY_CHANNEL.items()}
CHANNEL_WEIGHTS = [34, 21, 18, 11, 16]
LEAD_SOURCES = CHANNELS

CUSTOMER_POOL = [
    "恒远科技", "宏达集团", "北辰智造", "启明电子", "云帆软件", "嘉禾物流",
    "博远医疗", "泰和能源", "中科智造", "海联工业", "新锐材料", "联诚汽车",
    "华光信息", "盛达食品", "安捷科技", "瑞丰纺织", "天成机械", "星河传媒",
    "卓越机电", "远航建设", "汇智教育", "同创环保", "金桥商贸", "德胜生物",
]
FOLLOWUP_TYPES = ["电话", "微信", "拜访", "邮件"]
REP_BY_ORG = {
    "E110": ["u_e101", "u_e102", "u_e103"],
    "E120": ["u_e201", "u_e202"],
    "E130": ["u_e301", "u_e302"],
    "E140": ["u_e401", "u_e402"],
    "S210": ["u_s201", "u_s202"],
    "S220": ["u_s221", "u_s222"],
    "N300": ["u_n301", "u_n302"],
    "W400": ["u_w401", "u_w402"],
}
MANAGER_BY_ORG = {org_id: ORG_BY_ID[org_id][5] for org_id in LEAF_ORGS}
EMPLOYEES_BY_ORG = {
    org: [MANAGER_BY_ORG[org]] + REP_BY_ORG[org] for org in LEAF_ORGS
}


def split_int(total: int, weights: list[float]) -> list[int]:
    """按权重分配整数，保证合计严格等于 total。"""
    if not weights:
        return []
    total = int(total)
    s = sum(weights)
    if s <= 0:
        weights = [1.0] * len(weights)
        s = float(len(weights))
    raw = [total * w / s for w in weights]
    base = [math.floor(x) for x in raw]
    remainder = total - sum(base)
    if remainder > 0:
        order = sorted(
            range(len(raw)),
            key=lambda i: (-(raw[i] - base[i]), i),
        )
        for i in range(remainder):
            base[order[i % len(order)]] += 1
    elif remainder < 0:
        order = sorted(range(len(raw)), key=lambda i: (raw[i] - base[i], i))
        for i in range(-remainder):
            base[order[i % len(order)]] -= 1
    return base


def split_total(total: int, n: int) -> list[int]:
    weights = [0.85 + ((i * 37) % 17) / 40.0 for i in range(n)]
    return split_int(total, weights)


def distribute_count(total: int, dates: list[date]) -> dict[date, int]:
    if not dates:
        return {}
    weights = []
    for d in dates:
        weights.append(0.55 if d.weekday() >= 5 else 1.0)
    counts = split_int(total, weights)
    return dict(zip(dates, counts))


def all_days() -> list[date]:
    days: list[date] = []
    d = DATE_RANGE_START
    while d <= DATE_RANGE_END:
        days.append(d)
        d += timedelta(days=1)
    return days


def write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def generate_org_users_targets() -> tuple[list[dict], list[dict], list[dict]]:
    org_rows = [
        {
            "org_id": o[0],
            "name": o[1],
            "parent_id": o[2] or "",
            "type": o[3],
            "sort_order": o[4],
            "manager_user_id": o[5],
        }
        for o in ORGS
    ]
    user_rows = [
        {
            "user_id": u[0],
            "name": u[1],
            "role": u[2],
            "title": u[3],
            "org_id": u[4],
            "phone": u[5],
            "email": u[6],
            "manager_id": u[7],
            "is_demo": u[8],
        }
        for u in USERS
    ]
    target_rows: list[dict] = []
    idx = 0
    for org_id, (sign_target, collection_target) in ORG_TARGETS.items():
        idx += 1
        target_rows.append(
            {
                "target_id": f"T-{idx:03d}",
                "month": "2026-10",
                "org_id": org_id,
                "user_id": "",
                "sign_target": sign_target,
                "collection_target": collection_target,
            }
        )
    for org_id in LEAF_ORGS:
        sign_target, collection_target = ORG_TARGETS[org_id]
        emps = EMPLOYEES_BY_ORG[org_id]
        if len(emps) == 4:
            weights = [0.36, 0.23, 0.21, 0.20]
        else:
            weights = [0.40, 0.30, 0.30]
        sign_parts = split_int(sign_target, weights)
        coll_parts = split_int(collection_target, weights)
        for uid, s_part, c_part in zip(emps, sign_parts, coll_parts):
            idx += 1
            target_rows.append(
                {
                    "target_id": f"T-{idx:03d}",
                    "month": "2026-10",
                    "org_id": org_id,
                    "user_id": uid,
                    "sign_target": s_part,
                    "collection_target": c_part,
                }
            )
    return org_rows, user_rows, target_rows


def generate_contracts() -> list[dict]:
    days = all_days()
    weekdays = [d for d in days if d.weekday() < 5]
    schedule_days = sorted(set(weekdays + [DEMO_DATE]))
    recent_workdays = [d for d in weekdays if d <= DEMO_DATE][-3:]
    recent_special = {
        "E110": [380_000, 400_000, 420_000, 300_000],
        "E120": [280_000, 300_000, 320_000, 250_000],
        "E130": [800_000, 500_000, 300_000, 200_000],
        "E140": [180_000, 190_000, 200_000, 150_000],
        "S210": [350_000, 360_000, 380_000, 200_000],
        "S220": [300_000, 320_000, 330_000, 180_000],
        "N300": [450_000, 460_000, 480_000, 300_000],
        "W400": [250_000, 260_000, 270_000, 200_000],
    }
    by_org_date: dict[tuple[str, date], int] = {}
    for org_id in LEAF_ORGS:
        target = CONTRACT_MONTH_TOTALS[org_id]
        special_values = recent_special[org_id]
        for d, amt in zip(recent_workdays, special_values[:3]):
            by_org_date[(org_id, d)] = amt
        by_org_date[(org_id, DEMO_DATE)] = special_values[3]

        early_oct_dates = [
            d for d in weekdays
            if d.month == 10 and d not in recent_workdays and d <= DEMO_DATE
        ]
        remaining = target - sum(special_values)
        early_amounts = split_total(remaining, len(early_oct_dates))
        for d, amt in zip(early_oct_dates, early_amounts):
            by_org_date[(org_id, d)] = amt
        assert sum(
            by_org_date[(org_id, d)]
            for d in schedule_days
            if d.month == 10 and d <= DEMO_DATE
        ) == target

        sep_dates = [d for d in weekdays if d.month == 9]
        sep_weights = [0.7 + ((i * 13 + len(org_id)) % 7) / 10 for i in range(len(sep_dates))]
        sep_total = int(target * 0.16)
        for d, amt in zip(sep_dates, split_int(sep_total, sep_weights)):
            by_org_date[(org_id, d)] = max(20_000, amt)

    contracts: list[dict] = []
    for d in schedule_days:
        for org_id in LEAF_ORGS:
            amount = by_org_date.get((org_id, d))
            if amount is None:
                continue
            employee = EMPLOYEES_BY_ORG[org_id][(d.day + ORGS.index(ORG_BY_ID[org_id])) % len(EMPLOYEES_BY_ORG[org_id])]
            contracts.append(
                {
                    "customer": CUSTOMER_POOL[(d.toordinal() + ORGS.index(ORG_BY_ID[org_id])) % len(CUSTOMER_POOL)],
                    "owner_id": employee,
                    "org_id": org_id,
                    "amount": int(amount),
                    "sign_date": d.isoformat(),
                    "status": "active",
                    "campaign_id": "",
                }
            )
    contracts.sort(key=lambda r: (r["sign_date"], r["org_id"], r["owner_id"]))
    for i, row in enumerate(contracts, start=1):
        row["contract_id"] = f"HT-2026-{i:04d}"
        # 约 60% 的合同可归因到投放活动，保证营销 ROI 有真实分母和分子
        if (i * 37 + ORGS.index(ORG_BY_ID[row["org_id"]]) * 11) % 10 < 6:
            channel = CHANNELS[(i + ORGS.index(ORG_BY_ID[row["org_id"]])) % len(CHANNELS)]
            row["campaign_id"] = CAMPAIGN_BY_CHANNEL[channel]
        row.pop("_idx", None)
    return contracts


def generate_opportunities() -> tuple[list[dict], list[dict]]:
    """返回 open 商机与已结束商机；open 最后补齐跟进日期。"""
    open_opps: list[dict] = []
    starts = DATE_RANGE_START
    for org_id in LEAF_ORGS:
        amount_total = PIPELINE_TARGETS[org_id]
        count = OPEN_OPP_COUNTS[org_id]
        emps = EMPLOYEES_BY_ORG[org_id]
        if org_id == "E110":
            # 大客户流失样本：320 万，最后跟进 2026-09-20
            open_opps.append(
                {
                    "customer": "恒远科技",
                    "owner_id": "u_sm",
                    "org_id": org_id,
                    "amount": 3_200_000,
                    "stage": "方案确认",
                    "created_date": "2026-08-01",
                    "last_followup_date": "2026-09-20",
                    "expected_close_date": "2026-10-30",
                    "status": "open",
                    "_special": "churn",
                }
            )
            rest_amount = amount_total - 3_200_000
            rest_count = count - 1
        else:
            rest_amount = amount_total
            rest_count = count
        amounts = split_total(rest_amount, rest_count)
        for i, amt in enumerate(amounts):
            created = starts + timedelta(days=(i * 3 + len(org_id)) % 28)
            if created > DEMO_DATE:
                created = DEMO_DATE
            open_opps.append(
                {
                    "customer": CUSTOMER_POOL[(i + len(org_id) + ORGS.index(ORG_BY_ID[org_id]) * 2) % len(CUSTOMER_POOL)],
                    "owner_id": emps[i % len(emps)],
                    "org_id": org_id,
                    "amount": int(amt),
                    "stage": ["初步接触", "需求确认", "方案确认", "商务谈判"][(i + len(org_id)) % 4],
                    "created_date": created.isoformat(),
                    "last_followup_date": "",
                    "expected_close_date": (DEMO_DATE + timedelta(days=10 + i % 50)).isoformat(),
                    "status": "open",
                }
            )
    # 已结束商机，不进入 open 管道
    closed_opps: list[dict] = []
    for i in range(30):
        org_id = LEAF_ORGS[i % len(LEAF_ORGS)]
        emps = EMPLOYEES_BY_ORG[org_id]
        created = DATE_RANGE_START + timedelta(days=(i * 2) % 25)
        closed_opps.append(
            {
                "customer": CUSTOMER_POOL[(i * 3 + 5) % len(CUSTOMER_POOL)],
                "owner_id": emps[i % len(emps)],
                "org_id": org_id,
                "amount": int(120_000 + (i * 37_000) % 1_200_000),
                "stage": "赢单" if i % 3 else "输单",
                "created_date": created.isoformat(),
                "last_followup_date": (created + timedelta(days=4)).isoformat(),
                "expected_close_date": (created + timedelta(days=20)).isoformat(),
                "status": "won" if i % 3 else "lost",
            }
        )
    for org_id in LEAF_ORGS:
        total = sum(o["amount"] for o in open_opps if o["org_id"] == org_id)
        assert total == PIPELINE_TARGETS[org_id], (org_id, total)
    return open_opps, closed_opps


def generate_followups(open_opps: list[dict], closed_opps: list[dict]) -> list[dict]:
    """每个进行中商机生成 2 条跟进，已结束商机生成 1 条结案跟进。

    调用前商机已经分配 opp_id；这里只构造跟进记录并回填
    opportunities.last_followup_date。
    """
    followups: list[dict] = []
    open_sorted = sorted(open_opps, key=lambda x: (x["org_id"], x["customer"], x["amount"]))
    for i, opp in enumerate(open_sorted):
        if opp.get("_special") == "churn":
            dates = [date(2026, 9, 5), date(2026, 9, 20)]
            opp["last_followup_date"] = dates[-1].isoformat()
        else:
            last = DEMO_DATE - timedelta(days=i % 9)
            earlier = last - timedelta(days=3 + (i % 4))
            created = date.fromisoformat(opp["created_date"])
            if earlier < created:
                earlier = created
            dates = [earlier, last]
            opp["last_followup_date"] = last.isoformat()
        for j, d in enumerate(dates):
            followups.append(
                {
                    "opp_id": opp["opp_id"],
                    "user_id": opp["owner_id"],
                    "date": d.isoformat(),
                    "type": FOLLOWUP_TYPES[(i + j) % len(FOLLOWUP_TYPES)],
                    "note": [
                        "确认预算与决策链，客户要求补充方案",
                        "沟通使用场景，约定下一次演示",
                        "客户内部评估中，需持续跟进",
                        "已发送报价，等待商务确认",
                    ][(i + j) % 4],
                }
            )
    for i, opp in enumerate(closed_opps):
        created = date.fromisoformat(opp["created_date"])
        d = min(DEMO_DATE, created + timedelta(days=4))
        followups.append(
            {
                "opp_id": opp["opp_id"],
                "user_id": opp["owner_id"],
                "date": d.isoformat(),
                "type": FOLLOWUP_TYPES[i % len(FOLLOWUP_TYPES)],
                "note": "项目复盘与结案沟通",
            }
        )
    followups.sort(key=lambda x: (x["date"], x["opp_id"]))
    for i, f in enumerate(followups, start=1):
        f["followup_id"] = f"FU-2026-{i:04d}"
    return followups


def generate_leads() -> list[dict]:
    all_dates = all_days()
    current_dates = [DEMO_DATE - timedelta(days=5 - i) for i in range(6)]
    prev_dates = [DEMO_DATE - timedelta(days=12 - i) for i in range(6)]
    other_dates = [d for d in all_dates if d not in set(current_dates + prev_dates)]
    rows: list[dict] = []
    for org_index, org_id in enumerate(LEAF_ORGS):
        profile = LEAD_WEEK_PROFILE[org_id]
        total = LEAD_TOTALS[org_id]
        other_total = total - profile["prev"] - profile["curr"]

        def add_period(dates: list[date], count: int, valid_count: int, converted_count: int, mark: str) -> None:
            date_counts = distribute_count(count, dates)
            slots: list[dict] = []
            for d in dates:
                for _ in range(date_counts.get(d, 0)):
                    slots.append({"date": d})
            for i, slot in enumerate(slots):
                is_valid = i < valid_count
                is_converted = i < converted_count
                rows.append(
                    {
                        "created_date": slot["date"].isoformat(),
                        "source": "",
                        "owner_id": "",
                        "org_id": org_id,
                        "customer": "",
                        "phone": "",
                        "status": "valid" if is_valid else "invalid",
                        "converted": 1 if (is_valid and is_converted) else 0,
                        "_mark": mark,
                        "_seq": i,
                    }
                )

        add_period(prev_dates, profile["prev"], profile["vp"], profile["cvp"], "prev")
        add_period(current_dates, profile["curr"], profile["cp"], profile["cvc"], "curr")
        other_count = distribute_count(other_total, other_dates)
        seq = 0
        base_valid = round(profile["vp"] / profile["prev"] * 100)
        base_conv = max(5, round(profile["cvp"] / max(1, profile["vp"]) * 100))
        for d in other_dates:
            for _ in range(other_count.get(d, 0)):
                valid = ((seq * 7 + org_index * 11) % 100) < base_valid
                converted = valid and (((seq * 13 + org_index) % 100) < base_conv)
                rows.append(
                    {
                        "created_date": d.isoformat(),
                        "source": "",
                        "owner_id": "",
                        "org_id": org_id,
                        "customer": "",
                        "phone": "",
                        "status": "valid" if valid else "invalid",
                        "converted": 1 if converted else 0,
                        "_mark": "other",
                        "_seq": seq,
                    }
                )
                seq += 1
    rows.sort(key=lambda r: (r["created_date"], r["org_id"], r["_mark"], r["_seq"]))
    for i, row in enumerate(rows, start=1):
        org_id = row["org_id"]
        emps = EMPLOYEES_BY_ORG[org_id]
        row["lead_id"] = f"LEAD-2026-{i:04d}"
        source = CHANNELS[0]
        # 按渠道权重确定性分配，避免随机波动影响周对比
        pick = (i * 41 + ORGS.index(ORG_BY_ID[org_id]) * 13) % 100
        acc = 0
        for ch, weight in zip(CHANNELS, CHANNEL_WEIGHTS):
            acc += weight
            if pick < acc:
                source = ch
                break
        row["source"] = source
        row["campaign_id"] = CAMPAIGN_BY_CHANNEL[source]
        row["owner_id"] = emps[(i + row["_seq"]) % len(emps)]
        row["customer"] = f"{CUSTOMER_POOL[(i * 5 + 3) % len(CUSTOMER_POOL)]}-{i:04d}"
        row["phone"] = f"139{10000000 + i:08d}"
        row.pop("_mark", None)
        row.pop("_seq", None)
    assert len(rows) == sum(LEAD_TOTALS.values())
    return rows


def generate_receivables() -> list[dict]:
    rows: list[dict] = []
    paid_dates = [date(2026, 10, 3), date(2026, 10, 9), date(2026, 10, 14), date(2026, 10, 19), date(2026, 10, 23)]
    other_due_offsets = [5, 12, 18, 27, 13]
    for org_index, org_id in enumerate(LEAF_ORGS):
        emps = EMPLOYEES_BY_ORG[org_id]
        paid_amounts = split_total(COLLECTION_TARGETS[org_id], 5)
        for i, amount in enumerate(paid_amounts):
            customer = CUSTOMER_POOL[(org_index * 2 + i) % len(CUSTOMER_POOL)]
            rows.append(
                {
                    "customer": customer,
                    "owner_id": emps[i % len(emps)],
                    "org_id": org_id,
                    "amount": int(amount + 30_000),
                    "due_date": (paid_dates[i] - timedelta(days=10)).isoformat(),
                    "paid_amount": int(amount + 30_000),
                    "paid_date": paid_dates[i].isoformat(),
                    "status": "paid",
                    "_special": "",
                }
            )
        for i in range(5):
            if org_id == "S220" and i == 0:
                rows.append(
                    {
                        "customer": "宏达集团",
                        "owner_id": "u_south2",
                        "org_id": org_id,
                        "amount": 1_200_000,
                        "due_date": "2026-09-10",
                        "paid_amount": 0,
                        "paid_date": "",
                        "status": "open",
                        "_special": "overdue",
                    }
                )
                continue
            amount = 120_000 + ((org_index * 131_000 + i * 87_000) % 780_000)
            due = DEMO_DATE - timedelta(days=other_due_offsets[i])
            rows.append(
                {
                    "customer": CUSTOMER_POOL[(org_index * 3 + i + 7) % len(CUSTOMER_POOL)],
                    "owner_id": emps[(i + 1) % len(emps)],
                    "org_id": org_id,
                    "amount": int(amount),
                    "due_date": due.isoformat(),
                    "paid_amount": 0,
                    "paid_date": "",
                    "status": "open",
                    "_special": "",
                }
            )
    rows.sort(key=lambda r: (r["org_id"], r["due_date"], r["customer"]))
    for i, row in enumerate(rows, start=1):
        row["recv_id"] = f"AR-2026-{i:04d}"
        row.pop("_special", None)
    return rows


def generate_orders() -> list[dict]:
    days = all_days()
    rows: list[dict] = []
    for i in range(60):
        d = days[(i * 3 + 2) % len(days)]
        org_id = LEAF_ORGS[i % len(LEAF_ORGS)]
        emps = EMPLOYEES_BY_ORG[org_id]
        cancelled = i == 0
        rows.append(
            {
                "customer": "海联工业" if cancelled else CUSTOMER_POOL[(i * 7 + 2) % len(CUSTOMER_POOL)],
                "owner_id": "u_south1" if cancelled else emps[i % len(emps)],
                "org_id": "S210" if cancelled else org_id,
                "amount": 800_000 if cancelled else 60_000 + (i * 67_000) % 620_000,
                "order_date": (DEMO_DATE - timedelta(days=2) if cancelled else d).isoformat(),
                "status": "cancelled" if cancelled else ("completed" if i % 4 else "pending"),
            }
        )
    rows.sort(key=lambda r: (r["order_date"], r["org_id"]))
    for i, row in enumerate(rows, start=1):
        row["order_id"] = f"SO-2026-{i:04d}"
    return rows


def generate_ad_spend() -> list[dict]:
    rows: list[dict] = []
    base = {"信息流": 90_000, "自然搜索": 40_000, "渠道伙伴": 30_000, "老客转介绍": 12_000, "内容营销": 18_000}
    for i, d in enumerate(all_days()):
        for j, channel in enumerate(CHANNELS):
            factor = 0.8 + ((i * 13 + j * 7) % 9) / 20.0
            if d.weekday() >= 5:
                factor *= 0.7
            spend = int(round(base[channel] * factor / 100) * 100)
            clicks = int(spend / (3.2 + j * 0.45))
            impressions = clicks * (42 + j * 5)
            leads_count = max(1, int(clicks * (0.075 - j * 0.006)))
            rows.append(
                {
                    "spend_key": f"SPEND-{d.isoformat()}-{j}",
                    "date": d.isoformat(),
                    "channel": channel,
                    "spend": spend,
                    "impressions": impressions,
                    "clicks": clicks,
                    "leads_count": leads_count,
                }
            )
    return rows


def generate_source_files() -> dict[str, int]:
    org_rows, user_rows, target_rows = generate_org_users_targets()
    write_csv(
        SOURCE_DIR / "orgs.csv",
        ["org_id", "name", "parent_id", "type", "sort_order", "manager_user_id"],
        org_rows,
    )
    write_csv(
        SOURCE_DIR / "users.csv",
        ["user_id", "name", "role", "title", "org_id", "phone", "email", "manager_id", "is_demo"],
        user_rows,
    )
    write_csv(
        SOURCE_DIR / "targets.csv",
        ["target_id", "month", "org_id", "user_id", "sign_target", "collection_target"],
        target_rows,
    )

    contracts = generate_contracts()
    write_csv(
        SOURCE_DIR / "contracts.csv",
        ["contract_id", "customer", "owner_id", "org_id", "amount", "sign_date", "status", "campaign_id"],
        contracts,
    )
    open_opps, closed_opps = generate_opportunities()
    all_opps = sorted(open_opps + closed_opps, key=lambda x: (x["created_date"], x["customer"], x["amount"]))
    for i, opp in enumerate(all_opps, start=1):
        opp["opp_id"] = f"OPP-2026-{i:04d}"
    followups = generate_followups(open_opps, closed_opps)
    churn_opp_id = next(o["opp_id"] for o in all_opps if o["customer"] == "恒远科技" and o["status"] == "open")
    for opp in all_opps:
        opp.pop("_special", None)
    write_csv(
        SOURCE_DIR / "opportunities.csv",
        ["opp_id", "customer", "owner_id", "org_id", "amount", "stage", "created_date", "last_followup_date", "expected_close_date", "status"],
        [
            {
                "opp_id": o["opp_id"],
                "customer": o["customer"],
                "owner_id": o["owner_id"],
                "org_id": o["org_id"],
                "amount": o["amount"],
                "stage": o["stage"],
                "created_date": o["created_date"],
                "last_followup_date": o["last_followup_date"],
                "expected_close_date": o["expected_close_date"],
                "status": o["status"],
            }
            for o in all_opps
        ],
    )
    write_csv(
        SOURCE_DIR / "followups.csv",
        ["followup_id", "opp_id", "user_id", "date", "type", "note"],
        [
            {
                "followup_id": f["followup_id"],
                "opp_id": f["opp_id"],
                "user_id": f["user_id"],
                "date": f["date"],
                "type": f["type"],
                "note": f["note"],
            }
            for f in followups
        ],
    )
    leads = generate_leads()
    write_csv(
        SOURCE_DIR / "leads.csv",
        ["lead_id", "created_date", "source", "owner_id", "org_id", "customer", "phone", "status", "converted", "campaign_id"],
        [
            {
                "lead_id": l["lead_id"],
                "created_date": l["created_date"],
                "source": l["source"],
                "owner_id": l["owner_id"],
                "org_id": l["org_id"],
                "customer": l["customer"],
                "phone": l["phone"],
                "status": l["status"],
                "converted": l["converted"],
                "campaign_id": l["campaign_id"],
            }
            for l in leads
        ],
    )
    receivables = generate_receivables()
    write_csv(
        SOURCE_DIR / "receivables.csv",
        ["recv_id", "customer", "owner_id", "org_id", "amount", "due_date", "paid_amount", "paid_date", "status"],
        [
            {
                "recv_id": r["recv_id"],
                "customer": r["customer"],
                "owner_id": r["owner_id"],
                "org_id": r["org_id"],
                "amount": r["amount"],
                "due_date": r["due_date"],
                "paid_amount": r["paid_amount"],
                "paid_date": r["paid_date"],
                "status": r["status"],
            }
            for r in receivables
        ],
    )
    orders = generate_orders()
    write_csv(
        SOURCE_DIR / "orders.csv",
        ["order_id", "customer", "owner_id", "org_id", "amount", "order_date", "status"],
        orders,
    )
    ad_spend = generate_ad_spend()
    write_csv(
        SOURCE_DIR / "ad_spend.csv",
        ["spend_key", "date", "channel", "spend", "impressions", "clicks", "leads_count"],
        ad_spend,
    )
    stats = {
        "orgs": len(org_rows),
        "users": len(user_rows),
        "targets": len(target_rows),
        "contracts": len(contracts),
        "opportunities": len(all_opps),
        "followups": len(followups),
        "leads": len(leads),
        "receivables": len(receivables),
        "orders": len(orders),
        "ad_spend": len(ad_spend),
    }
    write_expected_risks(orders, receivables, churn_opp_id)
    return stats


def write_expected_risks(orders: list[dict], receivables: list[dict], churn_opp_id: str) -> None:
    """独立于规则引擎手写的初始预期清单（对象 + 规则 + 级别 + 责任人）。"""
    cancelled = next(o for o in orders if o["status"] == "cancelled" and o["amount"] >= 500_000)
    overdue = next(
        r for r in receivables
        if r["status"] == "open" and r["customer"] == "宏达集团" and r["due_date"] == "2026-09-10"
    )
    rows = [
        {
            "risk_id": "R-20261024-001", "rule_key": "target_gap", "type": "目标缺口",
            "level": "yellow", "object_type": "org", "object_id": "E130", "object_name": "华东三部",
            "owner_user_id": "u_ea3", "amount": 1_500_000,
            "reason": "时间进度 77.4%，完成率 72.7%，缺口 4.7pp",
        },
        {
            "risk_id": "R-20261024-002", "rule_key": "target_gap", "type": "目标缺口",
            "level": "red", "object_type": "org", "object_id": "E140", "object_name": "华东四部",
            "owner_user_id": "u_ea4", "amount": 2_000_000,
            "reason": "时间进度 77.4%，完成率 60.0%，缺口 17.4pp",
        },
        {
            "risk_id": "R-20261024-003", "rule_key": "target_gap", "type": "目标缺口",
            "level": "red", "object_type": "org", "object_id": "W400", "object_name": "西部大区",
            "owner_user_id": "u_west", "amount": 5_000_000,
            "reason": "时间进度 77.4%，完成率 50.0%，缺口 27.4pp",
        },
        {
            "risk_id": "R-20261024-004", "rule_key": "decline", "type": "业绩下滑",
            "level": "red", "object_type": "org", "object_id": "E130", "object_name": "华东三部",
            "owner_user_id": "u_ea3", "amount": 300_000,
            "reason": "最近 3 个工作日 80→50→30 万，连续环比 -37.5% / -40.0%",
        },
        {
            "risk_id": "R-20261024-005", "rule_key": "leads", "type": "线索异常",
            "level": "orange", "object_type": "org", "object_id": "E140", "object_name": "华东四部",
            "owner_user_id": "u_ea4", "amount": 0,
            "reason": "本周新增线索 15 条，较上周同期 30 条下降 50%",
        },
        {
            "risk_id": "R-20261024-006", "rule_key": "leads", "type": "线索异常",
            "level": "yellow", "object_type": "org", "object_id": "N300", "object_name": "华北大区",
            "owner_user_id": "u_north", "amount": 0,
            "reason": "线索转化率 20.0%，较上周同期 27.8% 相对下降 28.0%",
        },
        {
            "risk_id": "R-20261024-007", "rule_key": "coverage", "type": "商机覆盖",
            "level": "orange", "object_type": "org", "object_id": "E120", "object_name": "华东二部",
            "owner_user_id": "u_ea2", "amount": 0,
            "reason": "管道 250 万，剩余目标 130 万，覆盖率 1.9 倍",
        },
        {
            "risk_id": "R-20261024-008", "rule_key": "churn", "type": "大客户流失",
            "level": "red", "object_type": "opportunity", "object_id": churn_opp_id,
            "object_name": "恒远科技", "owner_user_id": "u_sm", "amount": 3_200_000,
            "reason": "商机 320 万，最后跟进 2026-09-20，已 34 天未跟进",
        },
        {
            "risk_id": "R-20261024-009", "rule_key": "payment", "type": "订单/回款",
            "level": "red", "object_type": "order", "object_id": cancelled["order_id"],
            "object_name": "海联工业", "owner_user_id": "u_south1", "amount": 800_000,
            "reason": "单笔订单取消 80 万（阈值 ≥50 万）",
        },
        {
            "risk_id": "R-20261024-010", "rule_key": "payment", "type": "订单/回款",
            "level": "red", "object_type": "receivable", "object_id": overdue["recv_id"],
            "object_name": "宏达集团", "owner_user_id": "u_south2", "amount": 1_200_000,
            "reason": "应收 120 万，到期 2026-09-10，逾期 44 天",
        },
    ]
    # 恒远科技商机的真实编号在生成时确定；expected 文件使用可读的稳定业务键。
    write_csv(
        EXPECTED_RISKS_PATH,
        ["risk_id", "rule_key", "type", "level", "object_type", "object_id", "object_name", "owner_user_id", "amount", "reason"],
        rows,
    )


if __name__ == "__main__":
    print(generate_source_files())
