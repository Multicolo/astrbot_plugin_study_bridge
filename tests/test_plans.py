"""计划：生成、日期自洽、apply 幂等、rollback 跳过已改任务、越界拒绝。"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from core.errors import ApiError
from core.util import local_date

pytestmark = pytest.mark.asyncio


def _plan_payload(days: int = 3, duration: int = 45) -> dict:
    today = local_date("Asia/Shanghai")
    items = [
        {
            "seq": index + 1,
            "title": f"第 {index + 1} 章",
            "scheduled_date": (today + timedelta(days=index)).isoformat(),
            "duration_min": duration,
        }
        for index in range(days)
    ]
    return {"title": "考研数学冲刺", "items": items}


async def _make_plan(app, principal, days: int = 3, duration: int = 45):
    app.llm.push(_plan_payload(days=days, duration=duration))
    deadline = (local_date("Asia/Shanghai") + timedelta(days=13)).isoformat()
    return await app.plans.generate(
        principal, goal="考研数学", daily_minutes=60, deadline=deadline
    )


async def test_generate_creates_items_and_clamps_duration(app, principal):
    plan = await _make_plan(app, principal, days=3, duration=120)
    assert plan["title"] == "考研数学冲刺"
    assert len(plan["items"]) == 3
    # 单条不能超过 daily_minutes
    assert all(item["duration_min"] <= 60 for item in plan["items"])
    assert plan["total_minutes"] <= 3 * 60
    assert plan["applied_at"] is None


async def test_generate_filters_out_of_range_dates(app, principal):
    today = local_date("Asia/Shanghai")
    payload = {
        "title": "越界计划",
        "items": [
            {"seq": 1, "title": "过去", "scheduled_date": (today - timedelta(days=2)).isoformat(), "duration_min": 30},
            {"seq": 2, "title": "未来", "scheduled_date": (today + timedelta(days=60)).isoformat(), "duration_min": 30},
            {"seq": 3, "title": "合法", "scheduled_date": today.isoformat(), "duration_min": 30},
        ],
    }
    app.llm.push(payload)
    deadline = (today + timedelta(days=13)).isoformat()
    plan = await app.plans.generate(principal, goal="x", daily_minutes=60, deadline=deadline)
    assert [item["title"] for item in plan["items"]] == ["合法"]


async def test_generate_without_ai_is_400(app, principal):
    app.llm.available_flag = False
    with pytest.raises(ApiError) as exc:
        await app.plans.generate(principal, goal="x", daily_minutes=30)
    assert exc.value.code == "VALIDATION_ERROR"


async def test_apply_is_idempotent(app, principal):
    plan = await _make_plan(app, principal)
    first = await app.plans.apply(principal, plan["id"])
    assert first["created"] == plan and False or first["created"] == len(plan["items"])
    assert first["skipped"] == 0

    tasks = await app.tasks.list(principal)
    assert len(tasks) == len(plan["items"])
    assert all(task["source"] == "ai" for task in tasks)

    second = await app.plans.apply(principal, plan["id"])
    assert second["created"] == 0
    assert second["skipped"] == len(plan["items"])

    refreshed = await app.plans.get(principal, plan["id"])
    assert refreshed["applied_at"] is not None
    assert all(item["task_id"] for item in refreshed["items"])


async def test_apply_rejects_out_of_range_item(app, principal):
    plan = await _make_plan(app, principal)
    old = (date.today() - timedelta(days=3)).isoformat()
    await app.db.execute(
        "UPDATE plan_item SET scheduled_date = ? WHERE plan_id = ?", (old, plan["id"])
    )
    with pytest.raises(ApiError) as exc:
        await app.plans.apply(principal, plan["id"])
    assert exc.value.code == "VALIDATION_ERROR"
    assert exc.value.details["items"]


async def test_rollback_skips_modified_task(app, principal):
    plan = await _make_plan(app, principal)
    await app.plans.apply(principal, plan["id"])
    tasks = await app.tasks.list(principal)
    modified = tasks[0]
    await app.tasks.update(principal, modified["id"], {"title": "改过的标题"})

    result = await app.plans.rollback(principal, plan["id"])
    assert result["deleted"] == len(tasks) - 1
    assert len(result["skipped"]) == 1
    assert result["skipped"][0]["reason"] == "任务已被修改过"
    remaining = await app.tasks.list(principal)
    assert len(remaining) == 1
    assert remaining[0]["title"] == "改过的标题"


async def test_delete_applied_plan_conflict(app, principal):
    plan = await _make_plan(app, principal)
    await app.plans.apply(principal, plan["id"])
    with pytest.raises(ApiError) as exc:
        await app.plans.delete(principal, plan["id"])
    assert exc.value.code == "CONFLICT"


async def test_latest_draft_and_patch(app, principal):
    plan = await _make_plan(app, principal)
    draft = await app.plans.latest_draft(principal)
    assert draft is not None and draft["id"] == plan["id"]
    patched = await app.plans.patch(principal, plan["id"], {"title": "改名", "daily_minutes": 90})
    assert patched["title"] == "改名"
    assert patched["daily_minutes"] == 90
    with pytest.raises(ApiError):
        await app.plans.patch(principal, plan["id"], {"deadline": "不是日期"})


async def test_plan_quota(app, principal):
    app.cfg._raw["quota.max_plans"] = 1
    await _make_plan(app, principal)
    app.llm.push(_plan_payload())
    with pytest.raises(ApiError) as exc:
        await app.plans.generate(principal, goal="再来一个", daily_minutes=30)
    assert exc.value.code == "QUOTA_EXCEEDED"


async def test_progress_report(app, principal):
    plan = await _make_plan(app, principal)
    await app.plans.apply(principal, plan["id"])
    tasks = await app.tasks.list(principal)
    await app.tasks.set_status(principal, tasks[0]["id"], "done")
    progress = await app.plans.progress(principal)
    assert progress[0]["total"] == len(plan["items"])
    assert progress[0]["done"] == 1
    assert 0 < progress[0]["rate"] < 100


async def test_plans_are_scoped(app, principal):
    from core.principal import get_or_create

    other = await get_or_create(app.db, kind="user", external_id="other-plan")
    plan = await _make_plan(app, principal)
    assert await app.plans.get(other, plan["id"]) is None
    with pytest.raises(ApiError) as exc:
        await app.plans.apply(other, plan["id"])
    assert exc.value.status == 404
