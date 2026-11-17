"""HTTP 契约：逐条走一遍 API.md 里的接口。"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from core.util import get_tz, iso, local_date

pytestmark = pytest.mark.asyncio


def _today_at(hour: int) -> tuple[str, str]:
    tz = get_tz("Asia/Shanghai")
    start = datetime.combine(local_date(tz), datetime.min.time(), tzinfo=tz).replace(hour=hour)
    return iso(start), iso(start + timedelta(hours=1))


async def test_info_endpoint(auth_client):
    response = await auth_client.get("/api/study/info")
    payload = await response.json()
    data = payload["data"]
    assert data["plugin_version"]
    assert data["memory"]["active"]["name"] in ("none", "generic_tool", "livingmemory", "file")
    assert "capabilities" in data
    assert "warnings" in data


async def test_task_lifecycle(auth_client):
    start, end = _today_at(14)
    created = await auth_client.post(
        "/api/study/tasks",
        json={"title": "线代", "start_at": start, "end_at": end, "priority": 3},
    )
    assert created.status == 201
    task = (await created.json())["data"]

    listed = await auth_client.get("/api/study/tasks")
    assert (await listed.json())["data"]["count"] == 1

    fetched = await auth_client.get(f"/api/study/tasks/{task['id']}")
    assert (await fetched.json())["data"]["title"] == "线代"

    updated = await auth_client.put(
        f"/api/study/tasks/{task['id']}", json={"title": "线性代数"}
    )
    assert (await updated.json())["data"]["title"] == "线性代数"

    done = await auth_client.patch(
        f"/api/study/tasks/{task['id']}/status", json={"status": "done"}
    )
    assert (await done.json())["data"]["status"] == "done"

    deleted = await auth_client.delete(f"/api/study/tasks/{task['id']}")
    assert (await deleted.json())["data"]["deleted"] is True

    missing = await auth_client.get(f"/api/study/tasks/{task['id']}")
    assert missing.status == 404


async def test_tasks_today_and_parse(auth_client, app):
    today = await auth_client.get("/api/study/tasks/today")
    assert (await today.json())["data"]["date"] == local_date("Asia/Shanghai").isoformat()

    start, end = _today_at(16)
    app.llm.push({"title": "背单词", "start_at": start, "end_at": end, "confidence": 0.88})
    parsed = await auth_client.post("/api/study/tasks/parse", json={"text": "四点半背单词"})
    payload = (await parsed.json())["data"]
    assert payload["source"] == "ai"
    assert payload["draft"]["title"] == "背单词"


async def test_plan_flow(auth_client, app):
    today = local_date("Asia/Shanghai")
    app.llm.push(
        {
            "title": "两周冲刺",
            "items": [
                {"seq": 1, "title": "第一章", "scheduled_date": today.isoformat(), "duration_min": 30},
                {
                    "seq": 2,
                    "title": "第二章",
                    "scheduled_date": (today + timedelta(days=1)).isoformat(),
                    "duration_min": 30,
                },
            ],
        }
    )
    generated = await auth_client.post(
        "/api/study/plans/generate",
        json={
            "goal": "考研数学",
            "daily_minutes": 60,
            "deadline": (today + timedelta(days=10)).isoformat(),
        },
    )
    assert generated.status == 201
    plan = (await generated.json())["data"]
    assert len(plan["items"]) == 2

    listed = await auth_client.get("/api/study/plans")
    assert (await listed.json())["data"]["count"] == 1

    patched = await auth_client.patch(
        f"/api/study/plans/{plan['id']}", json={"title": "新标题"}
    )
    assert (await patched.json())["data"]["title"] == "新标题"

    applied = await auth_client.post(f"/api/study/plans/{plan['id']}/apply")
    assert (await applied.json())["data"]["created"] == 2
    again = await auth_client.post(f"/api/study/plans/{plan['id']}/apply")
    assert (await again.json())["data"]["created"] == 0

    rolled = await auth_client.post(f"/api/study/plans/{plan['id']}/rollback")
    assert (await rolled.json())["data"]["deleted"] == 2


async def test_materials(auth_client):
    created = await auth_client.post(
        "/api/study/materials", json={"text": "第一章：极限\n第二章：导数", "name": "高数笔记"}
    )
    assert created.status == 201
    material = (await created.json())["data"]
    listed = await auth_client.get("/api/study/materials")
    assert (await listed.json())["data"]["count"] == 1
    removed = await auth_client.delete(f"/api/study/materials/{material['id']}")
    assert (await removed.json())["data"]["deleted"] is True


async def test_material_url_validation(auth_client):
    response = await auth_client.post("/api/study/materials", json={"url": "ftp://x"})
    assert response.status == 400


async def test_stats(auth_client):
    start, end = _today_at(9)
    await auth_client.post("/api/study/tasks", json={"title": "a", "start_at": start, "end_at": end})
    overview = await auth_client.get("/api/study/stats/overview?range=week")
    data = (await overview.json())["data"]
    assert data["total"] >= 1
    assert isinstance(data["daily"], list)
    daily = await auth_client.get("/api/study/stats/daily")
    assert "daily" in (await daily.json())["data"]
    progress = await auth_client.get("/api/study/stats/plan-progress")
    assert "plans" in (await progress.json())["data"]


async def test_chat_endpoints(auth_client, app):
    app.llm.push({"reply": "我在", "tool_calls": []})
    reply = await auth_client.post(
        "/api/study/chat", json={"text": "在吗", "session_key": "app-session"}
    )
    assert (await reply.json())["data"]["reply"] == "我在"
    history = await auth_client.get("/api/study/chat/history?session_key=app-session")
    assert len((await history.json())["data"]["messages"]) >= 2
    reset = await auth_client.post("/api/study/chat/reset", json={"session_key": "app-session"})
    assert (await reset.json())["data"]["reset"] is True


async def test_memory_endpoints(auth_client, app):
    created = await app.memories.save_note(
        (await app.principal_for_event(_FakeEvent())), kind="preference", content="喜欢早上学习"
    )
    listed = await auth_client.get("/api/study/memory/notes")
    data = (await listed.json())["data"]
    assert data["count"] == 1

    patched = await auth_client.patch(
        f"/api/study/memory/notes/{created['id']}", json={"importance": 5}
    )
    assert (await patched.json())["data"]["importance"] == 5

    status = await auth_client.get("/api/study/memory/sync-status")
    assert "adapter" in (await status.json())["data"]

    compact = await auth_client.post("/api/study/memory/compact")
    assert (await compact.json())["data"]["removed"] >= 0

    bot = await auth_client.get("/api/study/memory/bot")
    assert (await bot.json())["data"]["count"] == 0

    removed = await auth_client.delete(f"/api/study/memory/notes/{created['id']}")
    assert (await removed.json())["data"]["deleted"] is True


async def test_push_targets_and_notifications(auth_client):
    created = await auth_client.post(
        "/api/study/push-targets", json={"umo": "qq:FriendMessage:10001", "alias": "私聊"}
    )
    assert created.status == 201
    target = (await created.json())["data"]

    listed = await auth_client.get("/api/study/push-targets")
    assert (await listed.json())["data"]["count"] == 1

    patched = await auth_client.patch(
        f"/api/study/push-targets/{target['id']}", json={"enabled": False}
    )
    assert (await patched.json())["data"]["enabled"] is False

    tested = await auth_client.post(f"/api/study/push-targets/{target['id']}/test")
    payload = (await tested.json())["data"]
    assert payload["ok"] is False  # 没有平台 sender，如实返回失败
    assert payload["umo"] == "qq:FriendMessage:10001"

    notifications = await auth_client.get("/api/study/notifications")
    assert "notifications" in (await notifications.json())["data"]

    removed = await auth_client.delete(f"/api/study/push-targets/{target['id']}")
    assert (await removed.json())["data"]["deleted"] is True


async def test_ai_endpoints(auth_client, app):
    providers = await auth_client.get("/api/study/ai/providers")
    data = (await providers.json())["data"]
    assert data["mode"] in ("astrbot", "manual")
    assert "providers" in data

    manual = await auth_client.get("/api/study/ai/manual")
    assert (await manual.json())["data"]["configured"] is False

    saved = await auth_client.put(
        "/api/study/ai/manual",
        json={"base_url": "https://api.example.com/v1", "api_key": "test-key-do-not-use", "model": "gpt-4o-mini"},
    )
    payload = (await saved.json())["data"]
    assert payload["has_key"] is True
    assert "test-key-do-not-use" not in str(payload)

    fetched = await auth_client.get("/api/study/ai/manual")
    fetched_data = (await fetched.json())["data"]
    assert fetched_data["has_key"] is True
    assert "api_key" not in fetched_data

    row = await app.db.fetch_one("SELECT api_key_enc, mode FROM llm_config")
    assert row["mode"] == "manual"
    assert row["api_key_enc"] and "test-key-do-not-use" not in row["api_key_enc"]

    tested = await auth_client.post("/api/study/ai/test")
    assert (await tested.json())["data"]["ok"] is True


async def test_select_provider_rejects_unknown(auth_client):
    response = await auth_client.post("/api/study/ai/select", json={"provider_id": "nope"})
    assert response.status == 400


async def test_settings_and_export(auth_client):
    fetched = await auth_client.get("/api/study/settings")
    assert (await fetched.json())["data"]["tz"]

    updated = await auth_client.put("/api/study/settings", json={"tz": "Asia/Tokyo"})
    assert (await updated.json())["data"]["tz"] == "Asia/Tokyo"

    bad = await auth_client.put("/api/study/settings", json={"tz": "Nowhere/Land"})
    assert bad.status == 400

    exported = await auth_client.get("/api/study/export")
    data = (await exported.json())["data"]
    assert data["format"] == "study_bridge.export.v1"
    assert "tasks" in data and "memory_notes" in data


async def test_me_and_devices(auth_client):
    me = await auth_client.get("/api/study/auth/me")
    data = (await me.json())["data"]
    assert data["device_count"] >= 1
    devices = await auth_client.get("/api/study/auth/devices")
    assert len((await devices.json())["data"]["devices"]) >= 1


async def test_static_site_responds(client):
    response = await client.get("/study/")
    assert response.status in (200, 503)
    text = await response.text()
    assert "study" in text.lower() or "前端尚未构建" in text


async def test_root_redirect(client):
    response = await client.get("/", allow_redirects=False)
    assert response.status == 302
    assert response.headers["Location"] == "/study/"


class _FakeEvent:
    def get_sender_id(self) -> str:
        return "10001"

    def get_group_id(self) -> str:
        return ""

    def is_private_chat(self) -> bool:
        return True

    def is_admin(self) -> bool:
        return False

    def get_sender_name(self) -> str:
        return "tester"


async def test_port_conflict_raises_and_reports(app):
    """端口被占用：抛 OSError + 明确提示，且不静默换端口。"""
    import socket

    from core.http_server import HttpServer

    holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    holder.bind(("127.0.0.1", 0))
    holder.listen(1)
    port = holder.getsockname()[1]
    try:
        app.cfg._raw["http.host"] = "127.0.0.1"
        app.cfg._raw["http.port"] = port
        server = HttpServer(app)
        with pytest.raises(OSError):
            await server.start()
        assert server.error and "http.port" in server.error
        assert server.bound_port is None
    finally:
        holder.close()


async def test_invalid_json_returns_envelope(client, auth_client):
    response = await auth_client.put("/api/study/settings", data="[]", headers={"Content-Type": "application/json"})
    assert response.status == 400
    payload = await response.json()
    assert payload["error"]["code"] == "VALIDATION_ERROR"
