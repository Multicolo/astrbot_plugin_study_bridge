"""多主体隔离：跨主体查询一律 404 / 空集。"""

from __future__ import annotations

import pytest

from core.errors import ApiError
from core.principal import get_or_create

from tests.conftest import make_settings
from tests.harness.fake_astrbot import FakeEvent

pytestmark = pytest.mark.asyncio


async def test_tasks_isolated_between_principals(app):
    a = await get_or_create(app.db, kind="user", external_id="A")
    b = await get_or_create(app.db, kind="user", external_id="B")
    task = await app.tasks.create(a, {"title": "A 的私事"})
    assert await app.tasks.get(b, task["id"]) is None
    assert await app.tasks.list(b) == []
    with pytest.raises(ApiError) as exc:
        await app.tasks.update(b, task["id"], {"title": "篡改"})
    assert exc.value.status == 404
    with pytest.raises(ApiError) as exc:
        await app.tasks.delete(b, task["id"])
    assert exc.value.status == 404
    with pytest.raises(ApiError) as exc:
        await app.tasks.set_status(b, task["id"], "done")
    assert exc.value.status == 404


async def test_memory_isolated(app):
    a = await get_or_create(app.db, kind="user", external_id="A")
    b = await get_or_create(app.db, kind="user", external_id="B")
    note = await app.memories.save_note(a, kind="preference", content="用户喜欢早上学习")
    assert await app.memories.list_notes(b) == []
    with pytest.raises(ApiError) as exc:
        await app.memories.delete_note(b, note["id"])
    assert exc.value.status == 404


async def test_push_targets_isolated(app):
    a = await get_or_create(app.db, kind="user", external_id="A")
    b = await get_or_create(app.db, kind="user", external_id="B")
    target = await app.notify.add_target(a, umo="qq:FriendMessage:A")
    assert await app.notify.list_targets(b) == []
    with pytest.raises(ApiError) as exc:
        await app.notify.delete_target(b, target["id"])
    assert exc.value.status == 404


async def test_group_per_user_mode_splits_members(app):
    event_a = FakeEvent(sender_id="A1", group_id="G1", umo="qq:GroupMessage:G1")
    event_b = FakeEvent(sender_id="B1", group_id="G1", umo="qq:GroupMessage:G1")
    pa = await app.principal_for_event(event_a)
    pb = await app.principal_for_event(event_b)
    assert pa.id != pb.id
    assert pa.kind == "user" and pb.kind == "user"


async def test_group_per_group_mode_shares(tmp_path):
    from core.app import StudyApp

    settings = make_settings({"scope": {"group_mode": "per_group"}})
    application = StudyApp(data_dir=tmp_path, cfg=settings)
    await application.startup()
    try:
        event_a = FakeEvent(sender_id="A1", group_id="G1")
        event_b = FakeEvent(sender_id="B1", group_id="G1")
        pa = await application.principal_for_event(event_a)
        pb = await application.principal_for_event(event_b)
        assert pa.id == pb.id
        assert pa.kind == "group"
        assert pa.external_id == "G1"
    finally:
        await application.shutdown()


async def test_admin_becomes_owner_principal(app):
    event = FakeEvent(sender_id="9", is_admin=True)
    principal = await app.principal_for_event(event)
    assert principal.kind == "owner"


async def test_http_cross_principal_task_is_404(app):
    from aiohttp.test_utils import TestClient, TestServer

    from core.http_server import HttpServer
    from core.principal import issue_token

    owner = await get_or_create(app.db, kind="user", external_id="X")
    intruder = await get_or_create(app.db, kind="user", external_id="Y")
    task = await app.tasks.create(owner, {"title": "X 的任务"})
    token, _ = await issue_token(app.db, principal_id=intruder.id)

    server = HttpServer(app)
    async with TestClient(TestServer(server.build())) as client:
        response = await client.get(
            f"/api/study/tasks/{task['id']}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status == 404
        payload = await response.json()
        assert payload["error"]["code"] == "NOT_FOUND"
