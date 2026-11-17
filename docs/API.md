# API — `/api/study`

所有接口都有两种响应信封（HTTP 状态码同时表达语义）：

```json
{"ok": true,  "data": { }}
{"ok": false, "error": {"code": "VALIDATION_ERROR", "message": "title 不能为空", "details": {"title": "必填"}}}
```

| 错误码 | HTTP | 何时出现 |
|---|---|---|
| `UNAUTHORIZED` | 401 | 缺令牌 / 令牌无效 / 已吊销 / 绑定码无效 |
| `RATE_LIMITED` | 429 | 单 IP 超限（默认 120/min）或鉴权失败过多（20/min 封 10 分钟） |
| `VALIDATION_ERROR` | 400 | 字段级校验失败（含 `details`），永不 500 |
| `NOT_FOUND` | 404 | 资源不存在**或不属于当前主体**（不泄露存在性） |
| `CONFLICT` | 409 | 状态冲突（如删除已写入的计划） |
| `QUOTA_EXCEEDED` | 409 | 单主体配额超限 |
| `UPSTREAM_ERROR` | 502 | 依赖的上游（平台/AI）异常 |
| `INTERNAL` | 500 | 未预期异常（日志里有 traceback，响应里没有） |

鉴权：除 `GET /health`、`GET /auth/bind-status`、`POST /auth/bind-code`、`POST /auth/token` 外，
都需要 `Authorization: Bearer <token>`。

> 前缀省略：下文路径均以 `/api/study` 开头。

---

## 健康检查与信息

### `GET /health`（免鉴权）

只返回最少信息，零配置泄露。

```json
{"ok": true, "data": {"name": "astrbot_plugin_study_bridge", "version": "1.0.0", "status": "ok"}}
```

### `GET /info`

插件版本、AstrBot 版本、schema 版本、时区、记忆适配器状态、AI 状态、计数、告警。

```json
{
  "ok": true,
  "data": {
    "name": "astrbot_plugin_study_bridge",
    "plugin_version": "1.0.0",
    "astrbot_version": "4.30.0",
    "min_astrbot_version": "4.24.2",
    "schema_version": 2,
    "timezone": "Asia/Shanghai",
    "language": "zh-CN",
    "http": {"enabled": true, "host": "0.0.0.0", "port": 6188},
    "memory": {
      "active": {"name": "none", "ok": true, "reason": "未检测到可写的第三方记忆插件…", "degraded": true},
      "attempts": [
        {"name": "generic_tool", "ok": false, "reason": "当前无 AstrBot 工具注册表"},
        {"name": "none", "ok": true, "reason": "…", "degraded": true}
      ],
      "sync_mode": "upload_only"
    },
    "ai": {"mode": "astrbot", "provider_id": "", "model": "", "available": true},
    "capabilities": {"chat": true, "plan": true, "push": true, "memory_sync": "upload_only"},
    "counts": {"devices": 1, "tasks": 3},
    "warnings": []
  }
}
```

---

## 鉴权与主体

### `POST /auth/bind-code`（免鉴权）

生成等待认领的 6 位绑定码（5 分钟、一次性）。

```json
{"ok": true, "data": {"code": "482913", "expires_in": 300, "expires_at": "2026-11-17T09:02:11+00:00",
 "instruction": "在 QQ 私聊里发：/bind 482913"}}
```

### `GET /auth/bind-status?code=482913`（免鉴权）

只回答是否已被认领，不泄露任何主体信息。

```json
{"ok": true, "data": {"bound": true}}
```

### `POST /auth/token`（免鉴权，一次性）

```json
{"code": "482913", "label": "Android"}
```

```json
{"ok": true, "data": {"token": "dGhpcy1pcy1hLWZha2UtdG9rZW4…", "principal": {"id": "6f…", "kind": "user", "external_id": "10001", "display_name": "小明", "can_use_ai": true, "created_at": "2026-11-17T08:00:00+00:00"}, "device_count": 1}}
```

再次兑换同一个码 → `401 UNAUTHORIZED`。

### `GET /auth/me`

```json
{"ok": true, "data": {"principal": {"id": "6f…", "kind": "owner", "external_id": "10001"}, "device_count": 2, "binding_mode": "bind_code", "can_use_ai": true}}
```

### `GET /auth/devices`

```json
{"ok": true, "data": {"devices": [{"id": "a1…", "label": "Android", "created_at": "…", "last_used_at": "…", "revoked_at": null, "revoked": false}]}}
```

### `POST /auth/revoke`

```json
{"token_id": "a1…"}
```

吊销后该令牌下一次请求立即 401；不属于自己的 token_id → 404。

---

## 任务

### `GET /tasks?from&to&status&q&limit&offset`

```json
{"ok": true, "data": {"tasks": [{
  "id": "2f…", "title": "背单词", "note": null,
  "start_at": "2026-11-18T07:00:00+00:00", "end_at": "2026-11-18T08:00:00+00:00",
  "all_day": false, "status": "pending", "priority": 2, "source": "manual",
  "plan_item_id": null, "remind_offsets": [30, 0],
  "local_date": "2026-11-18", "local_start": "15:00", "local_end": "16:00"
}], "count": 1}}
```

### `POST /tasks`

```json
{"title": "背单词", "start_at": "2026-11-18T07:00:00+00:00", "end_at": "2026-11-18T08:00:00+00:00", "priority": 2, "remind_offsets": [30, 0]}
```

→ `201` + 任务对象。校验失败示例：

```json
{"ok": false, "error": {"code": "VALIDATION_ERROR", "message": "end_at 不能早于 start_at", "details": {"end_at": "早于 start_at"}}}
```

### `GET /tasks/today?offset=0`

`offset` 只接受 `0`（今天）或 `1`（明天）。

```json
{"ok": true, "data": {"date": "2026-11-17", "items": [], "total": 0, "done": 0, "rate": 0, "overdue": 0, "now": "2026-11-17T08:20:00+00:00"}}
```

### `GET /tasks/{id}` · `PUT /tasks/{id}` · `DELETE /tasks/{id}`

- `PUT` 是部分更新（只改传入字段）；
- `DELETE` 是软删除（`deleted_at`），之后 `GET` 返回 404；
- 时间或提醒变更会作废旧的重叠提醒。

### `PATCH /tasks/{id}/status`

```json
{"status": "done"}
```

`status ∈ {pending, done, skipped}`。

### `POST /tasks/parse`

自然语言 → 草稿（**不落库**）。

```json
{"text": "明天下午三点背单词一小时"}
```

```json
{"ok": true, "data": {
  "draft": {"title": "背单词", "start_at": "2026-11-18T07:00:00+00:00", "end_at": "2026-11-18T08:00:00+00:00",
            "all_day": false, "priority": 2, "remind_offsets": [15, 0],
            "local_date": "2026-11-18", "local_start": "15:00", "local_end": "16:00"},
  "confidence": 0.93, "source": "ai", "warnings": []
}}
```

模型返回非法 JSON：自动重试 1 次，仍失败 → `source: "rule"` + `warnings`（接口依旧 200）。

---

## 计划

### `POST /plans/generate`

```json
{"goal": "考研数学 14 天冲刺", "material_ids": [], "daily_minutes": 60, "deadline": "2026-11-30"}
```

```json
{"ok": true, "data": {
  "id": "p1…", "title": "考研数学 14 天冲刺", "goal": "考研数学 14 天冲刺",
  "deadline": "2026-11-30", "daily_minutes": 60, "status": "draft", "applied_at": null,
  "items": [{"id": "i1…", "seq": 1, "title": "极限与连续", "scheduled_date": "2026-11-18", "duration_min": 60, "task_id": null, "status": "pending"}],
  "total_minutes": 300, "warnings": [], "generated_by": "ai"
}}
```

服务端会做**日期自洽**：越界（早于今天 / 晚于 deadline）条目被丢弃，单条时长被夹到 `daily_minutes` 以内。

### `GET /plans?status` · `GET /plans/{id}` · `PATCH /plans/{id}` · `DELETE /plans/{id}`

删除已 `applied_at` 的计划 → `409 CONFLICT`（先 rollback）。

### `POST /plans/{id}/apply`

幂等：只处理 `plan_item.task_id IS NULL` 的条目。

```json
{"ok": true, "data": {"created": 14, "skipped": 0, "plan_id": "p1…"}}
```

第二次调用：

```json
{"ok": true, "data": {"created": 0, "skipped": 14, "plan_id": "p1…"}}
```

有越界条目 → `400` 并指出是哪几条：

```json
{"ok": false, "error": {"code": "VALIDATION_ERROR", "message": "计划中有条目的日期越界…", "details": {"items": [{"item_id": "i3…", "date": "2026-11-10"}]}}}
```

### `POST /plans/{id}/rollback`

只删「由该计划生成且 `updated_at == created_at`」的任务：

```json
{"ok": true, "data": {"deleted": 12, "skipped": [{"item_id": "i7…", "reason": "任务已被修改过"}]}}
```

---

## 资料

### `GET /materials`

```json
{"ok": true, "data": {"materials": [{"id": "m1…", "name": "高数笔记", "type": "text", "summary": null, "raw_len": 812, "created_at": "…"}], "count": 1}}
```

### `POST /materials`

三种入参：

- JSON 文本：`{"text": "…", "name": "可选"}`
- JSON 链接：`{"url": "https://…", "name": "可选"}`
- `multipart/form-data`：字段 `file`（.txt/.md，读成文本）+ 可选 `name`

### `DELETE /materials/{id}`

---

## 报表

### `GET /stats/overview?range=today|week|month`

```json
{"ok": true, "data": {"range": "week", "start": "2026-11-16", "end": "2026-11-22",
 "total": 3, "done": 1, "rate": 33, "minutes": 30,
 "sources": {"manual": 2, "ai": 1},
 "daily": [{"date": "2026-11-16", "total": 1, "done": 1, "minutes": 30}, …]}}
```

### `GET /stats/daily?from&to`

返回补齐空日的序列（最多 92 天）：

```json
{"ok": true, "data": {"daily": [{"date": "2026-11-17", "total": 0, "done": 0, "minutes": 0}]}}
```

### `GET /stats/plan-progress`

```json
{"ok": true, "data": {"plans": [{"plan_id": "p1…", "title": "考研数学", "deadline": "2026-11-30", "status": "active", "applied": true, "total": 14, "done": 3, "rate": 21}]}}
```

---

## 对话（QQ 与 App 共用 pipeline）

### `POST /chat`

```json
{"session_key": "app-default", "text": "明天下午三点背单词一小时"}
```

```json
{"ok": true, "data": {
  "reply": "已经写进明天 15:00 的日程了",
  "ai": true,
  "tool_calls": [{"name": "create_task", "args": {"title": "背单词", "start_at": "…", "end_at": "…"},
                  "ok": true, "result": {"ok": true, "display": "已写入「背单词」（15:00 - 16:00）"}}],
  "plan_draft": null
}}
```

- `tool_calls[].ok=false` 时 `result` 里带 `needs_confirmation` 或 `error`；
- 需要二次确认的动作（`apply_plan`）永远不会自动执行，返回 `plan_id` + `needs_confirmation`；
- 模型不可用 → `ai: false` + 友好文案（接口 200）。

### `GET /chat/history?session_key&limit` · `POST /chat/reset`

```json
{"ok": true, "data": {"session_key": "app:…:app-default", "summary": null, "messages": [{"id": 1, "role": "user", "content": "你好", "created_at": "…"}]}}
```

---

## 记忆

### `GET /memory/notes?kind&q`

```json
{"ok": true, "data": {"notes": [{"id": "n1…", "kind": "preference", "content": "晚上 8 点后才有空",
  "tags": ["时间"], "importance": 4, "source": "user", "source_ref": null, "created_at": "…"}], "count": 1}}
```

### `POST /memory/notes`（扩展接口，便于 App 直接录入）

```json
{"kind": "preference", "content": "晚上 8 点后才有空", "importance": 4}
```

超过 200 字 / 含代码块 / 含 `{}`、`[]` / 来源为系统 → `400`（污染过滤器）。

### `PATCH /memory/notes/{id}` · `DELETE /memory/notes/{id}`

`DELETE` 会尝试同步删除远端；远端不支持删除 → 该条标 `orphan` 并在 `sync-status` 里如实显示。

### `GET /memory/bot` · `POST /memory/bot/{remote_ref}/adopt`

bot 侧记忆（只读镜像，灰显），`adopt` 复制成一条学习记忆。只有 `memory.sync_mode=bidirectional` 才有数据。

### `GET /memory/sync-status`

```json
{"ok": true, "data": {"mode": "upload_only",
 "adapter": {"name": "none", "ok": true, "reason": "…", "degraded": true},
 "attempts": [{"name": "generic_tool", "ok": false, "reason": "…"}],
 "states": {"synced": 3}, "pending_outbox": 0, "orphan": 0,
 "recent": [{"op": "upsert", "ok": 1, "detail": "…", "created_at": "…"}]}}
```

### `POST /memory/compact`

```json
{"ok": true, "data": {"removed": 2, "remaining": 8}}
```

---

## 推送

### `GET /push-targets` · `POST /push-targets`

```json
{"umo": "qq:FriendMessage:10001", "alias": "我的私聊"}
```

```json
{"ok": true, "data": {"id": "t1…", "umo": "qq:FriendMessage:10001", "alias": "我的私聊", "enabled": true, "created_at": "…"}}
```

### `PATCH /push-targets/{id}`（`enabled` / `alias`）· `DELETE /push-targets/{id}`

### `POST /push-targets/{id}/test`

```json
{"ok": true, "data": {"ok": false, "umo": "qq:FriendMessage:10001", "message": "🔔 这是一条测试推送…"}}
```

`data.ok=false` 表示**真的没发出去**（平台不在线/找不到会话），不伪装成功。

### `GET /notifications?status&limit`

```json
{"ok": true, "data": {"notifications": [{"id": "x1…", "kind": "daily_brief", "title": "☀️ 今天的学习安排",
  "content": "…", "scheduled_at": "2026-11-17T00:00:00+00:00", "status": "sent", "attempts": 1,
  "sent_at": "…", "error": null}], "count": 1}}
```

---

## AI

### `GET /ai/providers`

```json
{"ok": true, "data": {"mode": "astrbot", "providers": [{"id": "openai-gpt", "model": "gpt-4o-mini", "type": "openai"}], "selected": {"provider_id": "openai-gpt", "model": ""}, "error": null}}
```

### `POST /ai/select`

```json
{"provider_id": "openai-gpt", "model": "gpt-4o-mini"}
```

### `GET /ai/manual` · `PUT /ai/manual`

```json
{"ok": true, "data": {"configured": true, "base_url": "https://api.example.com/v1", "model": "gpt-4o-mini", "has_key": true}}
```

```json
{"base_url": "https://api.example.com/v1", "api_key": "（一次性写入）", "model": "gpt-4o-mini"}
```

Key 用 Fernet 加密存 `llm_config.api_key_enc`，接口永远只回 `has_key`。

### `POST /ai/test`

```json
{"ok": true, "data": {"ok": true, "latency_ms": 842, "reply": "可用", "mode": "manual", "model": "gpt-4o-mini"}}
```

---

## 设置与导出

### `GET /settings` · `PUT /settings`

```json
{"tz": "Asia/Shanghai", "brief": "08:00", "nudge": "21:00", "offsets": "30,0", "duration": 30, "weekly_report_weekday": 1, "weekly_report_time": "09:00"}
```

非法时区 / 时间格式 → `400`。

### `GET /export`

```json
{"ok": true, "data": {"format": "study_bridge.export.v1", "generated_at": "…", "plugin_version": "1.0.0",
  "principal": {}, "tasks": [], "plans": [], "plan_items": [], "materials": [], "memory_notes": [],
  "bot_memory_mirror": [], "push_targets": [], "settings": [], "notifications": [],
  "counts": {"tasks": 0, "plans": 0, "materials": 0, "memory_notes": 0}}}
```

---

## 静态站点

| 路径 | 行为 |
|---|---|
| `/study` | 302 → `/study/` |
| `/study/` | 返回 `web/index.html`；未构建时返回 503 + 中文提示 |
| `/study/{path}` | 有对应文件则返回文件，否则回退 `index.html`（SPA 路由） |
| `/` | 302 → `/study/` |

> 限流只作用于 `/api/study/*`：静态资源不占用 120/min 的 API 配额（否则一次页面加载就能打满）。
