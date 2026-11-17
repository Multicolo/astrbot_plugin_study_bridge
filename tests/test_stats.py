"""报表数值正确性 + 纯文本报表格式。"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from core.util import get_tz, iso, local_date

pytestmark = pytest.mark.asyncio


async def _add(app, principal, day_offset: int, hour: int, minutes: int, *, done: bool) -> dict:
    tz = get_tz("Asia/Shanghai")
    day = local_date(tz) + timedelta(days=day_offset)
    start = datetime.combine(day, datetime.min.time(), tzinfo=tz).replace(hour=hour)
    task = await app.tasks.create(
        principal,
        {
            "title": f"任务 {day_offset}-{hour}",
            "start_at": iso(start),
            "end_at": iso(start + timedelta(minutes=minutes)),
        },
    )
    if done:
        await app.tasks.set_status(principal, task["id"], "done")
    return task


async def test_overview_counts_and_minutes(app, principal):
    await _add(app, principal, 0, 9, 60, done=True)
    await _add(app, principal, 0, 11, 30, done=False)
    overview = await app.stats.overview(principal, "today")
    assert overview["total"] == 2
    assert overview["done"] == 1
    assert overview["rate"] == 50
    assert overview["minutes"] == 60
    assert overview["sources"]["manual"] == 2


async def test_daily_series_fills_empty_days(app, principal):
    await _add(app, principal, 0, 9, 60, done=True)
    await _add(app, principal, -2, 9, 60, done=True)
    series = await app.stats.daily(principal)
    assert len(series) == 7
    by_date = {row["date"]: row for row in series}
    today = local_date("Asia/Shanghai").isoformat()
    assert by_date[today]["total"] == 1
    yesterday = (local_date("Asia/Shanghai") - timedelta(days=1)).isoformat()
    assert by_date[yesterday]["total"] == 0


async def test_daily_range_validation(app, principal):
    from core.errors import ApiError

    with pytest.raises(ApiError):
        await app.stats.daily(principal, "2026-11-01", "2026-10-01")
    with pytest.raises(ApiError):
        await app.stats.daily(principal, "不是日期")
    with pytest.raises(ApiError):
        await app.stats.overview(principal, "year")


async def test_report_text_contains_bar(app, principal):
    from datetime import timedelta as _timedelta

    today = local_date("Asia/Shanghai")
    app.llm.push(
        {
            "title": "报表计划",
            "items": [
                {"seq": 1, "title": "第一章", "scheduled_date": today.isoformat(), "duration_min": 30},
                {
                    "seq": 2,
                    "title": "第二章",
                    "scheduled_date": (today + _timedelta(days=1)).isoformat(),
                    "duration_min": 30,
                },
            ],
        }
    )
    plan = await app.plans.generate(
        principal, goal="x", daily_minutes=60, deadline=(today + _timedelta(days=5)).isoformat()
    )
    await app.plans.apply(principal, plan["id"])
    tasks = await app.tasks.list(principal)
    await app.tasks.set_status(principal, tasks[0]["id"], "done")
    report = await app.stats.text_report(principal, "week")
    assert "报表" in report
    assert "█" in report or "░" in report


async def test_empty_report(app, principal):
    report = await app.stats.text_report(principal, "week")
    assert "还没有" in report


async def test_plan_progress_endpoint_data(app, principal):
    from datetime import timedelta as _timedelta

    today = local_date("Asia/Shanghai")
    app.llm.push(
        {
            "title": "进度计划",
            "items": [
                {"seq": 1, "title": "唯一一节", "scheduled_date": today.isoformat(), "duration_min": 30}
            ],
        }
    )
    plan = await app.plans.generate(
        principal, goal="x", daily_minutes=60, deadline=(today + _timedelta(days=3)).isoformat()
    )
    await app.plans.apply(principal, plan["id"])
    progress = await app.stats.plan_progress(principal)
    assert progress[0]["total"] == 1
    assert progress[0]["done"] == 0
