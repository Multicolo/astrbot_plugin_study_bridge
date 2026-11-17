-- 001_init.sql — 学习桥梁初始 schema
-- 约定：
--   * 时间统一 UTC ISO8601 字符串
--   * jsonb -> TEXT（存 JSON 文本）
--   * text[] -> TEXT（存 JSON 数组）
--   * 所有业务表都有 owner_principal_id 并建索引

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

-- ---------------------------------------------------------------- 主体与鉴权
CREATE TABLE IF NOT EXISTS principal (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    external_id TEXT NOT NULL,
    display_name TEXT,
    can_use_ai INTEGER DEFAULT 1,
    created_at TEXT NOT NULL,
    UNIQUE (kind, external_id)
);

CREATE TABLE IF NOT EXISTS auth_token (
    id TEXT PRIMARY KEY,
    principal_id TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    label TEXT,
    created_at TEXT NOT NULL,
    last_used_at TEXT,
    revoked_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_auth_token_principal ON auth_token (principal_id);

CREATE TABLE IF NOT EXISTS bind_code (
    code TEXT PRIMARY KEY,
    principal_id TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at TEXT,
    attempts INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_bind_code_principal ON bind_code (principal_id);

-- ---------------------------------------------------------------- 业务
CREATE TABLE IF NOT EXISTS task (
    id TEXT PRIMARY KEY,
    owner_principal_id TEXT NOT NULL,
    title TEXT NOT NULL,
    note TEXT,
    start_at TEXT,
    end_at TEXT,
    all_day INTEGER DEFAULT 0,
    status TEXT DEFAULT 'pending',
    priority INTEGER DEFAULT 2,
    source TEXT DEFAULT 'manual',
    plan_item_id TEXT,
    remind_offsets TEXT DEFAULT '[30,0]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_task_owner ON task (owner_principal_id);
CREATE INDEX IF NOT EXISTS idx_task_owner_start ON task (owner_principal_id, start_at);
CREATE INDEX IF NOT EXISTS idx_task_plan_item ON task (plan_item_id);

CREATE TABLE IF NOT EXISTS plan (
    id TEXT PRIMARY KEY,
    owner_principal_id TEXT NOT NULL,
    title TEXT NOT NULL,
    goal TEXT,
    deadline TEXT,
    daily_minutes INTEGER,
    status TEXT DEFAULT 'active',
    origin_session_id TEXT,
    applied_at TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_plan_owner ON plan (owner_principal_id);

CREATE TABLE IF NOT EXISTS plan_item (
    id TEXT PRIMARY KEY,
    owner_principal_id TEXT NOT NULL,
    plan_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    title TEXT NOT NULL,
    scheduled_date TEXT NOT NULL,
    duration_min INTEGER NOT NULL,
    task_id TEXT,
    status TEXT DEFAULT 'pending'
);
CREATE INDEX IF NOT EXISTS idx_plan_item_owner ON plan_item (owner_principal_id);
CREATE INDEX IF NOT EXISTS idx_plan_item_plan ON plan_item (plan_id, seq);

CREATE TABLE IF NOT EXISTS material (
    id TEXT PRIMARY KEY,
    owner_principal_id TEXT NOT NULL,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    raw_text TEXT,
    summary TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_material_owner ON material (owner_principal_id);

CREATE TABLE IF NOT EXISTS notification (
    id TEXT PRIMARY KEY,
    owner_principal_id TEXT NOT NULL,
    umo TEXT NOT NULL,
    kind TEXT NOT NULL,
    title TEXT,
    content TEXT NOT NULL,
    scheduled_at TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    attempts INTEGER DEFAULT 0,
    sent_at TEXT,
    dedupe_key TEXT UNIQUE,
    error TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_notification_owner ON notification (owner_principal_id);
CREATE INDEX IF NOT EXISTS idx_notification_status ON notification (status, scheduled_at);

CREATE TABLE IF NOT EXISTS push_target (
    id TEXT PRIMARY KEY,
    owner_principal_id TEXT NOT NULL,
    umo TEXT NOT NULL,
    alias TEXT,
    enabled INTEGER DEFAULT 1,
    created_at TEXT NOT NULL,
    UNIQUE (owner_principal_id, umo)
);

CREATE TABLE IF NOT EXISTS setting (
    owner_principal_id TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (owner_principal_id, key)
);

-- ---------------------------------------------------------------- AI
CREATE TABLE IF NOT EXISTS llm_config (
    id TEXT PRIMARY KEY,
    mode TEXT NOT NULL,
    provider_id TEXT,
    base_url TEXT,
    api_key_enc TEXT,
    model TEXT,
    enabled INTEGER DEFAULT 1,
    created_at TEXT NOT NULL
);

-- ---------------------------------------------------------------- 对话
CREATE TABLE IF NOT EXISTS chat_session (
    id TEXT PRIMARY KEY,
    owner_principal_id TEXT NOT NULL,
    session_key TEXT NOT NULL UNIQUE,
    channel TEXT NOT NULL,
    umo TEXT,
    created_at TEXT NOT NULL,
    last_active_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chat_session_owner ON chat_session (owner_principal_id);

CREATE TABLE IF NOT EXISTS chat_message (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT,
    tool_name TEXT,
    tool_args TEXT,
    tool_result TEXT,
    token_est INTEGER,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chat_message_session ON chat_message (session_id, id);

CREATE TABLE IF NOT EXISTS chat_summary (
    session_id TEXT PRIMARY KEY,
    summary TEXT NOT NULL,
    covered_upto_msg_id INTEGER NOT NULL,
    updated_at TEXT NOT NULL
);

-- ---------------------------------------------------------------- 记忆
CREATE TABLE IF NOT EXISTS memory_note (
    id TEXT PRIMARY KEY,
    owner_principal_id TEXT NOT NULL,
    ns TEXT DEFAULT 'study',
    kind TEXT NOT NULL,
    content TEXT NOT NULL,
    tags TEXT,
    importance INTEGER DEFAULT 3,
    source TEXT NOT NULL,
    source_ref TEXT,
    hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT,
    UNIQUE (owner_principal_id, hash),
    UNIQUE (owner_principal_id, source_ref)
);
CREATE INDEX IF NOT EXISTS idx_memory_note_owner ON memory_note (owner_principal_id);

CREATE TABLE IF NOT EXISTS bot_memory_mirror (
    remote_ref TEXT PRIMARY KEY,
    owner_principal_id TEXT NOT NULL,
    content TEXT NOT NULL,
    tags TEXT,
    importance INTEGER,
    source_ref TEXT,
    origin TEXT DEFAULT 'bot',
    adopted INTEGER DEFAULT 0,
    remote_updated_at TEXT,
    synced_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_bot_mirror_owner ON bot_memory_mirror (owner_principal_id);

CREATE TABLE IF NOT EXISTS memory_sync (
    id TEXT PRIMARY KEY,
    owner_principal_id TEXT NOT NULL,
    local_id TEXT NOT NULL,
    remote_ref TEXT,
    synced_hash TEXT,
    state TEXT NOT NULL,
    attempts INTEGER DEFAULT 0,
    last_error TEXT,
    synced_at TEXT,
    UNIQUE (owner_principal_id, local_id)
);
CREATE INDEX IF NOT EXISTS idx_memory_sync_owner ON memory_sync (owner_principal_id, state);

CREATE TABLE IF NOT EXISTS sync_outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_principal_id TEXT NOT NULL,
    op TEXT NOT NULL,
    local_id TEXT NOT NULL,
    payload TEXT,
    retry INTEGER DEFAULT 0,
    next_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_sync_outbox_owner ON sync_outbox (owner_principal_id);

-- ---------------------------------------------------------------- 审计
CREATE TABLE IF NOT EXISTS ai_action_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_principal_id TEXT,
    session_id TEXT,
    tool_name TEXT,
    args TEXT,
    result TEXT,
    ok INTEGER,
    error TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ai_action_owner ON ai_action_log (owner_principal_id);

CREATE TABLE IF NOT EXISTS command_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_principal_id TEXT,
    umo TEXT,
    text TEXT,
    reply TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sync_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    op TEXT,
    ok INTEGER,
    detail TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS usage_counter (
    owner_principal_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    day TEXT NOT NULL,
    count INTEGER DEFAULT 0,
    PRIMARY KEY (owner_principal_id, kind, day)
);
