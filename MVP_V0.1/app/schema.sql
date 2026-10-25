PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS orgs (
    org_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    parent_id TEXT,
    type TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    manager_user_id TEXT
);

CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    role TEXT NOT NULL,
    title TEXT NOT NULL,
    org_id TEXT NOT NULL,
    phone TEXT,
    email TEXT,
    manager_id TEXT,
    is_demo INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS targets (
    target_id TEXT PRIMARY KEY,
    month TEXT NOT NULL,
    org_id TEXT NOT NULL,
    user_id TEXT,
    sign_target REAL NOT NULL DEFAULT 0,
    collection_target REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS leads (
    lead_id TEXT PRIMARY KEY,
    created_date TEXT NOT NULL,
    source TEXT,
    owner_id TEXT,
    org_id TEXT,
    customer TEXT,
    phone TEXT,
    status TEXT,
    converted INTEGER NOT NULL DEFAULT 0,
    campaign_id TEXT,
    batch_as_of TEXT,
    ingested_at TEXT
);

CREATE TABLE IF NOT EXISTS opportunities (
    opp_id TEXT PRIMARY KEY,
    customer TEXT,
    owner_id TEXT,
    org_id TEXT,
    amount REAL NOT NULL DEFAULT 0,
    stage TEXT,
    created_date TEXT,
    last_followup_date TEXT,
    expected_close_date TEXT,
    status TEXT,
    batch_as_of TEXT,
    ingested_at TEXT
);

CREATE TABLE IF NOT EXISTS contracts (
    contract_id TEXT PRIMARY KEY,
    customer TEXT,
    owner_id TEXT,
    org_id TEXT,
    amount REAL NOT NULL DEFAULT 0,
    sign_date TEXT,
    status TEXT,
    campaign_id TEXT,
    batch_as_of TEXT,
    ingested_at TEXT
);

CREATE TABLE IF NOT EXISTS orders (
    order_id TEXT PRIMARY KEY,
    customer TEXT,
    owner_id TEXT,
    org_id TEXT,
    amount REAL NOT NULL DEFAULT 0,
    order_date TEXT,
    status TEXT,
    batch_as_of TEXT,
    ingested_at TEXT
);

CREATE TABLE IF NOT EXISTS receivables (
    recv_id TEXT PRIMARY KEY,
    customer TEXT,
    owner_id TEXT,
    org_id TEXT,
    amount REAL NOT NULL DEFAULT 0,
    due_date TEXT,
    paid_amount REAL NOT NULL DEFAULT 0,
    paid_date TEXT,
    status TEXT,
    batch_as_of TEXT,
    ingested_at TEXT
);

CREATE TABLE IF NOT EXISTS ad_spend (
    spend_key TEXT PRIMARY KEY,
    date TEXT NOT NULL,
    channel TEXT NOT NULL,
    spend REAL NOT NULL DEFAULT 0,
    impressions INTEGER NOT NULL DEFAULT 0,
    clicks INTEGER NOT NULL DEFAULT 0,
    leads_count INTEGER NOT NULL DEFAULT 0,
    batch_as_of TEXT,
    ingested_at TEXT
);

CREATE TABLE IF NOT EXISTS followups (
    followup_id TEXT PRIMARY KEY,
    opp_id TEXT NOT NULL,
    user_id TEXT,
    date TEXT NOT NULL,
    type TEXT,
    note TEXT,
    batch_as_of TEXT,
    ingested_at TEXT
);

CREATE TABLE IF NOT EXISTS batch_runs (
    batch_id TEXT PRIMARY KEY,
    as_of TEXT NOT NULL,
    status TEXT NOT NULL,
    trigger_type TEXT NOT NULL DEFAULT 'manual',
    triggered_by TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    steps_json TEXT NOT NULL DEFAULT '[]',
    stats_json TEXT NOT NULL DEFAULT '{}',
    error TEXT
);

CREATE TABLE IF NOT EXISTS metric_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id TEXT NOT NULL,
    as_of TEXT NOT NULL,
    scope_type TEXT NOT NULL DEFAULT 'org',
    scope_id TEXT NOT NULL,
    metric_key TEXT NOT NULL,
    value REAL,
    unit TEXT,
    formula TEXT,
    source TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (as_of, scope_type, scope_id, metric_key)
);

CREATE TABLE IF NOT EXISTS quality_reports (
    as_of TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL,
    status TEXT NOT NULL,
    report_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS daily_briefs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    as_of TEXT NOT NULL,
    role TEXT NOT NULL,
    user_id TEXT NOT NULL,
    scope_org_id TEXT NOT NULL,
    batch_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    published_at TEXT,
    UNIQUE (as_of, role, user_id)
);

CREATE TABLE IF NOT EXISTS weekly_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    week_type TEXT NOT NULL,
    week_start TEXT NOT NULL,
    week_end TEXT NOT NULL,
    role TEXT NOT NULL,
    user_id TEXT NOT NULL,
    scope_org_id TEXT NOT NULL,
    batch_id TEXT,
    payload_json TEXT NOT NULL,
    published_at TEXT
);

CREATE TABLE IF NOT EXISTS risk_rules (
    rule_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    params_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT,
    updated_by TEXT
);

CREATE TABLE IF NOT EXISTS risks (
    id TEXT PRIMARY KEY,
    batch_id TEXT,
    as_of TEXT NOT NULL,
    rule_id TEXT NOT NULL,
    dedupe_key TEXT NOT NULL,
    type TEXT NOT NULL,
    level TEXT NOT NULL,
    title TEXT NOT NULL,
    object_type TEXT NOT NULL,
    object_id TEXT NOT NULL,
    object_name TEXT NOT NULL,
    amount REAL NOT NULL DEFAULT 0,
    org_id TEXT NOT NULL,
    dept TEXT,
    owner_user_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    claimed_at TEXT,
    claimed_by TEXT,
    claim_due_at TEXT NOT NULL,
    close_due_at TEXT NOT NULL,
    closed_at TEXT,
    close_result_status TEXT,
    close_reason TEXT,
    close_action TEXT,
    close_result TEXT,
    escalation_level INTEGER NOT NULL DEFAULT 0,
    escalated_to TEXT,
    actions_json TEXT NOT NULL DEFAULT '[]',
    related_json TEXT NOT NULL DEFAULT '[]',
    merged_count INTEGER NOT NULL DEFAULT 0,
    trigger_count INTEGER NOT NULL DEFAULT 1,
    last_batch_date TEXT
);

CREATE TABLE IF NOT EXISTS risk_evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    risk_id TEXT NOT NULL,
    evidence_key TEXT NOT NULL,
    label TEXT NOT NULL,
    current_value TEXT NOT NULL,
    threshold TEXT NOT NULL,
    baseline TEXT NOT NULL,
    source TEXT NOT NULL,
    triggered_at TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS risk_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    risk_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    actor_user_id TEXT,
    from_status TEXT,
    to_status TEXT,
    note TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS risk_watchers (
    risk_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    PRIMARY KEY (risk_id, user_id)
);

CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    channel TEXT NOT NULL DEFAULT 'in_app',
    link TEXT,
    related_risk_id TEXT,
    batch_id TEXT,
    dedupe_key TEXT NOT NULL UNIQUE,
    is_read INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT,
    action TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id TEXT,
    detail TEXT NOT NULL DEFAULT '',
    ip TEXT,
    user_agent TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_leads_date_org ON leads (created_date, org_id);
CREATE INDEX IF NOT EXISTS idx_contracts_date_org ON contracts (sign_date, org_id);
CREATE INDEX IF NOT EXISTS idx_opps_status_org ON opportunities (status, org_id);
CREATE INDEX IF NOT EXISTS idx_recv_due_org ON receivables (due_date, org_id);
CREATE INDEX IF NOT EXISTS idx_metrics_scope_date ON metric_snapshots (as_of, scope_id);
CREATE INDEX IF NOT EXISTS idx_risks_status_level ON risks (status, level, created_at);
CREATE INDEX IF NOT EXISTS idx_risks_org ON risks (org_id);
CREATE INDEX IF NOT EXISTS idx_events_risk ON risk_events (risk_id, created_at);
CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications (user_id, is_read, created_at);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_logs (created_at);

INSERT OR IGNORE INTO risk_rules (rule_id, name, description, enabled, params_json, updated_at, updated_by) VALUES
('target_gap', '目标缺口', '时间进度−完成进度达到阈值时触发；缺口越大级别越高。', 1,
 '{"yellow_gap_pp":3,"orange_gap_pp":8,"red_gap_pp":15}', NULL, NULL),
('decline', '业绩下滑', '最近 3 个有数据的工作日出现连续两段环比下降，且两段降幅均达到阈值。', 1,
 '{"orange_drop_pct":20,"red_drop_pct":30,"workdays":3}', NULL, NULL),
('leads', '线索异常', '本周一至 D 对比上周同期；新增线索下降或线索转化率相对下降。', 1,
 '{"volume_drop_pct":30,"conversion_drop_pct":20}', NULL, NULL),
('coverage', '商机覆盖', '开放商机管道金额 ÷ 剩余目标低于阈值时触发。', 1,
 '{"min_coverage":2.5}', NULL, NULL),
('churn', '大客户流失', '开放商机金额达到门槛且超过指定天数未跟进时触发。', 1,
 '{"min_amount":500000,"days_no_followup":30}', NULL, NULL),
('payment', '订单/回款', '订单取消金额达到门槛，或应收逾期达到天数时触发。', 1,
 '{"min_cancel_amount":500000,"overdue_days":30}', NULL, NULL);
