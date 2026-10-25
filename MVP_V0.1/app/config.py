"""MVP 全局配置。

演示环境的业务日期固定为 2026-10-24；实际批处理运行时间仍取当前时间。
金额在数据库中以“元”存储，在 API 层统一转为“万元”。
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
SOURCE_DIR = DATA_DIR / "source"
WEB_DIR = BASE_DIR / "web"
DB_PATH = Path(os.environ.get("MVP_DB_PATH", DATA_DIR / "mvp.db"))
EXPECTED_RISKS_PATH = DATA_DIR / "expected_risks.csv"

DEMO_DATE = date(2026, 10, 24)
DEMO_DATE_STR = DEMO_DATE.isoformat()
DEMO_WEEKDAY = "星期六"
DATE_RANGE_START = date(2026, 9, 25)
DATE_RANGE_END = date(2026, 10, 24)

TZ = timezone(timedelta(hours=8))

SECRET_KEY = os.environ.get(
    "MVP_SECRET_KEY", "demo-only-not-for-production-7f3a-sales-brief-v01"
)
SESSION_COOKIE = "mvp_demo_session"
SESSION_MAX_AGE = 8 * 60 * 60

DEMO_ROLE_TITLES = {
    "gm": "公司总经理",
    "sd": "销售总监",
    "bu": "事业部总经理",
    "sm": "部门销售经理",
}

DEMO_ROLE_SCOPES = {
    "gm": "全公司",
    "sd": "全公司销售条线",
    "bu": "本事业部及下级",
    "sm": "本部门及本人",
}

LEVEL_LABELS = {"red": "红色", "orange": "橙色", "yellow": "黄色"}
LEVEL_WEIGHTS = {"red": 3, "orange": 2, "yellow": 1}

STATUS_LABELS = {
    "pending": "待认领",
    "processing": "处理中",
    "closed": "已关闭",
    "false_positive": "误报",
    "long_term": "长期跟踪",
}
STATUS_ALIASES = {
    "待认领": "pending",
    "处理中": "processing",
    "已关闭": "closed",
    "误报": "false_positive",
    "长期跟踪": "long_term",
    "已超时": "pending",
}

LEVEL_ALIASES = {"red": "red", "orange": "orange", "yellow": "yellow", "红色": "red", "橙色": "orange", "黄色": "yellow"}

# 认领时限与关闭时限（工作日按周一至周五计）
SLA_CLAIM = {
    "red": {"hours": 4, "workdays": None, "label": "4 小时"},
    "orange": {"hours": 8, "workdays": None, "label": "8 小时"},
    "yellow": {"hours": None, "workdays": 1, "label": "1 个工作日"},
}
SLA_CLOSE_WORKDAYS = {"red": 3, "orange": 5, "yellow": 10}

RISK_TYPES = {
    "target_gap": "目标缺口",
    "decline": "业绩下滑",
    "leads": "线索异常",
    "coverage": "商机覆盖",
    "churn": "大客户流失",
    "payment": "订单/回款",
}

METRIC_DEFS = [
    {
        "key": "new_leads",
        "label": "新增线索数",
        "unit": "条",
        "kind": "count",
        "formula": "count(leads.created_date = D)",
        "source": "CRM · leads.csv",
    },
    {
        "key": "valid_leads",
        "label": "有效线索数",
        "unit": "条",
        "kind": "count",
        "formula": "count(leads.created_date = D and status = valid)",
        "source": "CRM · leads.csv",
    },
    {
        "key": "lead_valid_rate",
        "label": "线索有效率",
        "unit": "%",
        "kind": "rate",
        "formula": "有效线索数 ÷ 新增线索数 × 100",
        "source": "CRM · leads.csv",
    },
    {
        "key": "lead_conversion_rate",
        "label": "线索转化率",
        "unit": "%",
        "kind": "rate",
        "formula": "已转化线索数 ÷ 有效线索数 × 100",
        "source": "CRM · leads.csv",
    },
    {
        "key": "new_opportunities",
        "label": "新增商机数",
        "unit": "条",
        "kind": "count",
        "formula": "count(opportunities.created_date = D)",
        "source": "CRM · opportunities.csv",
    },
    {
        "key": "pipeline_amount",
        "label": "商机管道金额",
        "unit": "万元",
        "kind": "money_wan",
        "formula": "sum(opportunities.amount where status = open)",
        "source": "CRM · opportunities.csv",
    },
    {
        "key": "opportunity_coverage",
        "label": "商机覆盖率",
        "unit": "倍",
        "kind": "multiple",
        "formula": "商机管道金额 ÷ 剩余目标（月目标 − 月累计签约）",
        "source": "CRM + 目标系统",
    },
    {
        "key": "contract_amount",
        "label": "签约额",
        "unit": "万元",
        "kind": "money_wan",
        "formula": "sum(contracts.amount where sign_date = D and status = active)",
        "source": "CRM · contracts.csv",
    },
    {
        "key": "contract_count",
        "label": "签约单数",
        "unit": "单",
        "kind": "count",
        "formula": "count(contracts where sign_date = D and status = active)",
        "source": "CRM · contracts.csv",
    },
    {
        "key": "target_completion_rate",
        "label": "目标完成率",
        "unit": "%",
        "kind": "rate",
        "formula": "月累计签约 ÷ 月签约目标 × 100",
        "source": "CRM + 目标系统",
    },
    {
        "key": "collection_completion_rate",
        "label": "回款完成率",
        "unit": "%",
        "kind": "rate",
        "formula": "月累计回款 ÷ 月回款目标 × 100",
        "source": "ERP · receivables.csv + 目标系统",
    },
    {
        "key": "marketing_roi",
        "label": "营销 ROI",
        "unit": "倍",
        "kind": "multiple",
        "formula": "月累计归因签约（campaign_id 非空）÷ 月累计投放费用",
        "source": "CRM · contracts.csv + 投放 · ad_spend.csv",
    },
]
METRIC_MAP = {m["key"]: m for m in METRIC_DEFS}

AUX_METRIC_DEFS = [
    {"key": "ad_spend", "label": "营销费用", "unit": "万元", "kind": "money_wan",
     "formula": "sum(ad_spend.spend where date 在当月且 ≤D)", "source": "投放 · ad_spend.csv"},
    {"key": "collection_amount", "label": "回款额", "unit": "万元", "kind": "money_wan",
     "formula": "sum(receivables.paid_amount where paid_date 在当月且 ≤D)", "source": "ERP · receivables.csv"},
    {"key": "leads_wow", "label": "线索周环比", "unit": "%", "kind": "rate",
     "formula": "本周新增线索 ÷ 上周同期 × 100 − 100", "source": "CRM · leads.csv"},
    {"key": "contract_wow", "label": "签约周环比", "unit": "%", "kind": "rate",
     "formula": "本周签约额 ÷ 上周同期 × 100 − 100", "source": "CRM · contracts.csv"},
    {"key": "time_progress", "label": "时间进度", "unit": "%", "kind": "rate",
     "formula": "当月已过自然日 ÷ 当月总天数 × 100", "source": "日期口径"},
]

SIX_KPI_KEYS = [
    "contract_amount",
    "target_completion_rate",
    "new_leads",
    "marketing_roi",
    "opportunity_coverage",
    "collection_completion_rate",
]

APPROVED_CLOSE_STATUSES = {"closed", "false_positive", "long_term"}


def now_bj() -> datetime:
    return datetime.now(TZ)


def now_iso() -> str:
    return now_bj().isoformat(timespec="seconds")


def iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    return dt.astimezone(TZ).isoformat(timespec="seconds")


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    return dt.astimezone(TZ)


def add_workdays(dt: datetime, days: int) -> datetime:
    """在指定时刻上增加工作日，跳过周六、周日。"""
    result = dt
    remaining = days
    while remaining > 0:
        result += timedelta(days=1)
        if result.weekday() < 5:
            remaining -= 1
    return result


def month_bounds(d: date) -> tuple[date, date]:
    start = d.replace(day=1)
    if start.month == 12:
        next_start = date(start.year + 1, 1, 1)
    else:
        next_start = date(start.year, start.month + 1, 1)
    return start, next_start - timedelta(days=1)


def round_half_up(value: float | int | None, digits: int = 1) -> float | None:
    if value is None:
        return None
    quant = Decimal("1").scaleb(-digits)
    return float(Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP))


def money_wan(value: float | int | None) -> float | None:
    if value is None:
        return None
    return round_half_up(float(value) / 10000.0, 1)


def round_rate(value: float | None) -> float | None:
    if value is None:
        return None
    return round_half_up(float(value), 1)
