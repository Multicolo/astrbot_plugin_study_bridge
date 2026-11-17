"""任务：CRUD、时区边界、解析、校验、配额、提醒排程。"""

from __future__ import annotations

import json

import pytest

from core.errors import ApiError
from core.principal import get_or_create
from core.util import iso, local_date, utcnow

pytestmark = pytest.mark.asyncio


def _tmr(hour: int, minute: int = 0) -> tuple[str, str]:
    """构造「明天 hour:minute（本地）→ +1h」的 UTC 区间。"""
    from datetime import datetime, time, timedelta

    from core.util import get_tz

    tz = get_tz("Asia/Shanghai")
    day = local_date("Asia/Shanghai") + timedelta(days=1)
    start = datetime.combine(day, time(hour, minute), tzinfo=tz)
    return iso(start), iso(start + timedelta(hours=1))


async def test_create_and_get(app, principal):
    start, end = _tmr(15)
    task = await app.tasks.create(
        principal, {"title": "背单词", "start_at": start, "end_at": end}
    )
    assert task["title"] == "背单词"
    assert task["status"] == "pending"
    assert task["local_start"] == "15:00"
    fetched = await app.tasks.get(principal, task["id"])
    assert fetched is not None
    assert fetched["id"] == task["id"]


async def test_list_filters(app, principal):
    start, end = _tmr(9)
    await app.tasks.create(principal, {"title": "数学", "start_at": start, "end_at": end})
    await app.tasks.create(principal, {"title": "英语"})
    all_tasks = await app.tasks.list(principal)
    assert len(all_tasks) == 2
    waiting = await app.tasks.list(principal, status="pending")
    assert len(waiting) == 2
    found = await app.tasks.list(principal, query="英语")
    assert len(found) == 1 and found[0]["title"] == "英语"


async def test_update_and_status(app, principal):
    task = await app.tasks.create(principal, {"title": "化学"})
    updated = await app.tasks.update(principal, task["id"], {"title": "有机化学", "priority": 3})
    assert updated["title"] == "有机化学"
    assert updated["priority"] == 3
    done = await app.tasks.set_status(principal, task["id"], "done")
    assert done["status"] == "done"
    with pytest.raises(ApiError) as exc:
        await app.tasks.set_status(principal, task["id"], "flying")
    assert exc.value.code == "VALIDATION_ERROR"


async def test_soft_delete(app, principal):
    task = await app.tasks.create(principal, {"title": "物理"})
    await app.tasks.delete(principal, task["id"])
    assert await app.tasks.get(principal, task["id"]) is None
    rows = await app.db.fetch_all("SELECT deleted_at FROM task WHERE id = ?", (task["id"],))
    assert rows[0]["deleted_at"] is not None
    with pytest.raises(ApiError) as exc:
        await app.tasks.delete(principal, task["id"])
    assert exc.value.code == "NOT_FOUND"


async def test_validation(app, principal):
    with pytest.raises(ApiError):
        await app.tasks.create(principal, {"title": "   "})
    with pytest.raises(ApiError):
        await app.tasks.create(principal, {"title": "x", "priority": "高"})
    with pytest.raises(ApiError):
        await app.tasks.create(
            principal,
            {
                "title": "x",
                "start_at": "2026-11-18T10:00:00+00:00",
                "end_at": "2026-11-18T09:00:00+00:00",
            },
        )
    with pytest.raises(ApiError):
        await app.tasks.create(principal, {"title": "x", "remind_offsets": ["30"]})


async def test_today_timezone_boundary(app, principal):
    """23:59 属于今天，次日 00:00 不属于今天（按主体时区）。"""
    from datetime import datetime, time, timedelta

    from core.util import get_tz

    tz = get_tz("Asia/Shanghai")
    today = local_date(tz)
    late = datetime.combine(today, time(23, 59), tzinfo=tz)
    await app.tasks.create(
        principal,
        {
            "title": "睡前复习",
            "start_at": iso(late),
            "end_at": iso(late + timedelta(minutes=1)),
        },
    )
    midnight = datetime.combine(today + timedelta(days=1), time(0, 0), tzinfo=tz)
    await app.tasks.create(
        principal,
        {
            "title": "零点任务",
            "start_at": iso(midnight),
            "end_at": iso(midnight + timedelta(minutes=30)),
        },
    )
    today_view = await app.tasks.day_view(principal, 0)
    titles = [item["title"] for item in today_view["items"]]
    assert "睡前复习" in titles
    assert "零点任务" not in titles
    tomorrow_view = await app.tasks.day_view(principal, 1)
    assert [item["title"] for item in tomorrow_view["items"]] == ["零点任务"]


async def test_today_counts_and_rate(app, principal):
    from datetime import datetime, time, timedelta

    from core.util import get_tz

    tz = get_tz("Asia/Shanghai")
    base = datetime.combine(local_date(tz), time(9, 0), tzinfo=tz)
    first = await app.tasks.create(
        principal,
        {"title": "a", "start_at": iso(base), "end_at": iso(base + timedelta(minutes=30))},
    )
    await app.tasks.create(
        principal,
        {
            "title": "b",
            "start_at": iso(base + timedelta(hours=1)),
            "end_at": iso(base + timedelta(hours=2)),
        },
    )
    await app.tasks.set_status(principal, first["id"], "done")
    view = await app.tasks.day_view(principal, 0)
    assert view["total"] == 2 and view["done"] == 1 and view["rate"] == 50


async def test_week_view(app, principal):
    from datetime import datetime, time, timedelta

    from core.util import get_tz, local_date

    tz = get_tz("Asia/Shanghai")
    today = local_date(tz)
    monday = today - timedelta(days=today.weekday())
    point = datetime.combine(monday, time(10, 0), tzinfo=tz)
    await app.tasks.create(
        principal,
        {"title": "周一任务", "start_at": iso(point), "end_at": iso(point + timedelta(hours=1))},
    )
    view = await app.tasks.week_view(principal)
    assert view["start"] == monday.isoformat()
    assert any(item["title"] == "周一任务" for item in view["items"])


async def test_parse_with_valid_ai_json(app, principal):
    start, end = _tmr(15)
    app.llm.push(
        {
            "title": "背单词",
            "start_at": start,
            "end_at": end,
            "all_day": False,
            "priority": 2,
            "remind_offsets": [15, 0],
            "confidence": 0.93,
        }
    )
    result = await app.tasks.parse(principal, "明天下午三点背单词一小时")
    assert result["source"] == "ai"
    assert result["confidence"] == pytest.approx(0.93)
    assert result["draft"]["title"] == "背单词"
    assert result["draft"]["local_start"] == "15:00"


async def test_parse_retries_once_then_rule_fallback(app, principal):
    # 两次都返回非法 JSON -> 规则解析
    app.llm.push("这不是 JSON", "还是不是 JSON")
    result = await app.tasks.parse(principal, "明天下午三点背单词一小时")
    assert result["source"] == "rule"
    assert result["draft"]["title"][:3] in ("背单词", "背单词一小时", "背单词 一小时")
    assert result["draft"]["start_at"] is not None
    # 一次非法 + 一次合法 -> 走 AI
    app.llm.push("坏 JSON", json.dumps({"title": "重试成功", "start_at": None}))
    second = await app.tasks.parse(principal, "随便")
    assert second["source"] == "ai"


async def test_parse_without_time_keeps_start_null(app, principal):
    app.llm.push({"title": "复习数学", "start_at": None, "confidence": 0.2})
    result = await app.tasks.parse(principal, "复习数学")
    assert result["draft"]["start_at"] is None
    assert result["confidence"] < 0.5


async def test_rule_parser_handles_common_phrases():
    from core.llm import rule_parse

    draft = rule_parse("明天下午三点背单词一小时", "Asia/Shanghai")
    assert draft["start_at"] is not None
    assert draft["end_at"] is not None
    assert "背单词" in draft["title"]
    empty = rule_parse("随便记一下", "Asia/Shanghai")
    assert empty["start_at"] is None


async def test_quota_exceeded(app, principal):
    app.cfg._raw["quota.max_tasks"] = 1
    await app.tasks.create(principal, {"title": "唯一一条"})
    with pytest.raises(ApiError) as exc:
        await app.tasks.create(principal, {"title": "第二条"})
    assert exc.value.code == "QUOTA_EXCEEDED"
    assert exc.value.status == 409


async def test_reminders_scheduled_with_push_target(app, principal):
    from datetime import datetime, time, timedelta

    from core.util import get_tz

    tz = get_tz("Asia/Shanghai")
    await app.notify.add_target(principal, umo="qq:FriendMessage:10001", alias="私聊")
    start = datetime.combine(local_date(tz) + timedelta(days=1), time(15, 0), tzinfo=tz)
    await app.tasks.create(
        principal,
        {
            "title": "提醒测试",
            "start_at": iso(start),
            "end_at": iso(start + timedelta(hours=1)),
            "remind_offsets": [30, 0],
        },
    )
    rows = await app.db.fetch_all(
        "SELECT dedupe_key, kind FROM notification WHERE owner_principal_id = ?",
        (principal.id,),
    )
    keys = {row["dedupe_key"] for row in rows}
    assert any(key.endswith(":30") for key in keys)
    assert any(key.endswith(":0") for key in keys)


async def test_resolve_reference_by_index_and_keyword(app, principal):
    from datetime import datetime, time, timedelta

    from core.util import get_tz

    tz = get_tz("Asia/Shanghai")
    base = datetime.combine(local_date(tz), time(10, 0), tzinfo=tz)
    await app.tasks.create(
        principal,
        {"title": "线性代数", "start_at": iso(base), "end_at": iso(base + timedelta(minutes=30))},
    )
    by_index = await app.tasks.resolve_reference(principal, "1")
    assert by_index is not None and by_index["title"] == "线性代数"
    by_keyword = await app.tasks.resolve_reference(principal, "线性")
    assert by_keyword is not None and by_keyword["id"] == by_index["id"]
    assert await app.tasks.resolve_reference(principal, "不存在的东西") is None


async def test_tasks_are_scoped(app):
    a = await get_or_create(app.db, kind="user", external_id="A")
    b = await get_or_create(app.db, kind="user", external_id="B")
    task = await app.tasks.create(a, {"title": "A 的任务"})
    assert await app.tasks.get(b, task["id"]) is None
    assert await app.tasks.list(b) == []
    _ = utcnow()
