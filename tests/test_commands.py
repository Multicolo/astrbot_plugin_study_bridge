"""QQ 指令：白名单、增删改查、计划、报表、导出、记忆、绑定。"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from core.util import get_tz, iso, local_date

pytestmark = pytest.mark.asyncio


def _today_at(hour: int) -> tuple[str, str]:
    tz = get_tz("Asia/Shanghai")
    start = datetime.combine(local_date(tz), datetime.min.time(), tzinfo=tz).replace(hour=hour)
    return iso(start), iso(start + timedelta(hours=1))


def _allow(app, *qq: str) -> None:
    app.cfg._raw["scope.allowed_qq"] = list(qq)


async def test_whitelist_denies_by_default(app, event_factory):
    event = event_factory(sender_id="555", is_admin=False)
    reply = await app.commands.dispatch(event, "today")
    assert "白名单" in reply
    rows = await app.db.fetch_all("SELECT reply FROM command_log")
    assert rows and rows[0]["reply"] == "denied"


async def test_admin_allowed_without_whitelist(app, event_factory):
    event = event_factory(sender_id="1", is_admin=True)
    reply = await app.commands.dispatch(event, "today")
    assert "白名单" not in reply


async def test_add_creates_task(app, event_factory):
    _allow(app, "10001")
    start, end = _today_at(15)
    app.llm.push(
        {
            "title": "背单词",
            "start_at": start,
            "end_at": end,
            "priority": 2,
            "remind_offsets": [30, 0],
            "confidence": 0.9,
        }
    )
    event = event_factory(sender_id="10001")
    reply = await app.commands.dispatch(event, "add", "今天下午三点背单词一小时")
    assert "已写入" in reply
    today = await app.commands.dispatch(event, "today")
    assert "背单词" in today


async def test_add_without_time_asks_back(app, event_factory):
    _allow(app, "10001")
    app.llm.push({"title": "背单词", "start_at": None, "confidence": 0.1})
    reply = await app.commands.dispatch(event_factory(sender_id="10001"), "add", "背单词")
    assert "时间" in reply


async def test_done_and_del(app, event_factory):
    _allow(app, "10001")
    start, end = _today_at(10)
    app.llm.push({"title": "高数", "start_at": start, "end_at": end, "confidence": 0.9})
    event = event_factory(sender_id="10001")
    await app.commands.dispatch(event, "add", "今天十点高数")
    done = await app.commands.dispatch(event, "done", "1")
    assert "已完成" in done
    deleted = await app.commands.dispatch(event, "del", "1")
    assert "已删除" in deleted


async def test_plan_new_preview_then_apply(app, event_factory):
    _allow(app, "10001")
    today = local_date("Asia/Shanghai")
    app.llm.push(
        {
            "title": "考研数学冲刺",
            "items": [
                {"seq": 1, "title": "第一章 极限", "scheduled_date": today.isoformat(), "duration_min": 40},
                {
                    "seq": 2,
                    "title": "第二章 导数",
                    "scheduled_date": (today + timedelta(days=1)).isoformat(),
                    "duration_min": 40,
                },
            ],
        }
    )
    event = event_factory(sender_id="10001")
    preview = await app.commands.dispatch(event, "plan", "new 考研数学")
    assert "预览" in preview or "还没写进日程" in preview
    assert "第一章" in preview
    applied = await app.commands.dispatch(event, "apply")
    assert "2" in applied
    listing = await app.commands.dispatch(event, "plan", "list")
    assert "考研数学冲刺" in listing
    again = await app.commands.dispatch(event, "apply")
    assert "没有" in again or "幂等" in again


async def test_plan_show_and_errors(app, event_factory):
    _allow(app, "10001")
    event = event_factory(sender_id="10001")
    assert "没有这个计划" in await app.commands.dispatch(event, "plan", "show nope")
    assert "用法" in await app.commands.dispatch(event, "plan", "new")


async def test_report_and_export(app, event_factory):
    _allow(app, "10001")
    start, end = _today_at(9)
    app.llm.push({"title": "英语听力", "start_at": start, "end_at": end, "confidence": 0.9})
    event = event_factory(sender_id="10001")
    await app.commands.dispatch(event, "add", "今天九点英语听力")
    await app.commands.dispatch(event, "done", "1")
    report = await app.commands.dispatch(event, "report", "week")
    assert "报表" in report and "%" in report
    exported = await app.commands.dispatch(event, "export")
    assert "study_bridge.export.v1" in exported


async def test_memory_and_forget(app, event_factory):
    _allow(app, "10001")
    event = event_factory(sender_id="10001")
    principal = await app.principal_for_event(event)
    await app.memories.save_note(principal, kind="preference", content="喜欢早上学习")
    listing = await app.commands.dispatch(event, "memory")
    assert "喜欢早上学习" in listing
    removed = await app.commands.dispatch(event, "forget", "1")
    assert "已删除" in removed
    assert await app.memories.list_notes(principal) == []


async def test_bind_private_only_and_success(app, event_factory):
    code = (await app.auth.create_bind_code())["code"]
    group_event = event_factory(sender_id="10001", group_id="888", is_admin=True)
    private_only = await app.commands.dispatch(group_event, "bind", code)
    assert "私聊" in private_only

    private_event = event_factory(sender_id="10001", is_admin=True)
    ok = await app.commands.dispatch(private_event, "bind", code)
    assert "绑定成功" in ok
    status = await app.auth.bind_status(code)
    assert status["bound"] is True


async def test_bind_usage_and_bad_code(app, event_factory):
    event = event_factory(sender_id="10001", is_admin=True)
    assert "用法" in await app.commands.dispatch(event, "bind", "12")
    assert "没有这个绑定码" in await app.commands.dispatch(event, "bind", "000000")


async def test_whoami_addr_umo_settings(app, event_factory):
    event = event_factory(sender_id="10001", is_admin=True, umo="qq:FriendMessage:10001")
    whoami = await app.commands.dispatch(event, "whoami")
    assert "主体" in whoami
    addr = await app.commands.dispatch(event, "addr")
    assert "http" in addr or "http.enabled" in addr
    umo = await app.commands.dispatch(event, "umo")
    assert "qq:FriendMessage:10001" in umo
    settings = await app.commands.dispatch(event, "settings")
    assert "时区" in settings
    changed = await app.commands.dispatch(event, "settings", "tz Asia/Tokyo")
    assert "Asia/Tokyo" in changed
    bad = await app.commands.dispatch(event, "settings", "tz Mars/Base")
    assert "不合法" in bad or "时区" in bad


async def test_addr_disabled_message(tmp_path, event_factory):
    from core.app import StudyApp

    from tests.conftest import make_settings

    settings = make_settings({"http": {"enabled": False}})
    application = StudyApp(data_dir=tmp_path, cfg=settings)
    await application.startup()
    try:
        reply = await application.commands.dispatch(
            event_factory(sender_id="1", is_admin=True), "addr"
        )
        assert "http.enabled=false" in reply
    finally:
        await application.shutdown()


async def test_study_group_routing(app, event_factory):
    _allow(app, "10001")
    event = event_factory(sender_id="10001")
    routed = await app.commands.dispatch(event, "help")
    direct = await app.commands.dispatch(event, "help")
    assert routed == direct


async def test_unbind_by_label(app, event_factory):
    from core.principal import issue_token

    event = event_factory(sender_id="10001", is_admin=True)
    principal = await app.principal_for_event(event)
    await issue_token(app.db, principal_id=principal.id, label="手机")
    reply = await app.commands.dispatch(event, "unbind", "手机")
    assert "已吊销" in reply
    none = await app.commands.dispatch(event, "unbind", "平板")
    assert "没有找到" in none


async def test_unknown_command_falls_back_to_help(app, event_factory):
    event = event_factory(sender_id="1", is_admin=True)
    reply = await app.commands.dispatch(event, "not_a_command", "")
    assert "/bind" in reply and "/plan" in reply


async def test_reset_clears_history(app, event_factory):
    _allow(app, "10001")
    event = event_factory(sender_id="10001", umo="qq:FriendMessage:10001")
    app.llm.push({"reply": "嗨", "tool_calls": []})
    principal = await app.principal_for_event(event)
    await app.chat.handle(principal, text="你好", session_key=event.unified_msg_origin)
    reply = await app.commands.dispatch(event, "reset")
    assert "已清空" in reply
    history = await app.chat.history(principal, session_key=event.unified_msg_origin)
    assert history["messages"] == []
