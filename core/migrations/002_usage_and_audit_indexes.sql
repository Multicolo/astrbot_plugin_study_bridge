-- 002_usage_and_audit_indexes.sql — 审计/用量表的查询索引（旧库升级示例）

CREATE INDEX IF NOT EXISTS idx_ai_action_created ON ai_action_log (created_at);
CREATE INDEX IF NOT EXISTS idx_command_log_created ON command_log (created_at);
CREATE INDEX IF NOT EXISTS idx_usage_counter_day ON usage_counter (day);
CREATE INDEX IF NOT EXISTS idx_bind_code_expiry ON bind_code (expires_at);
