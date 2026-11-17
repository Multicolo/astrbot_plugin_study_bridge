"""调度：到点发送、幂等去重、重启不重发、失败重试、早报/督促/consolidation。"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from core.principal import get_or_create
from core.util import get_tz, iso, local_date, utcnow

pytestmark = pytest.mark.asyncio


class Recorder:
    def __init__(self, ok: bool = True) -> None:
        self.sent: list[tuple[str, str]] = []
        self.ok = ok

    async def __call__(self, umo: str, text: str) -> bool:
        self.sent.append((umo, text))
        return self.ok


async def _setup(app, principal, *, umo="qq:FriendMessage:10001"):
    await app.notify.add_target(principal, umo=umo, alias="私聊")
    return umo


def _at_local(hour: int, minute: int = 0, *, day_offset: int = 0) -> str:
    tz = get_tz("Asia/Shanghai")
    day = local_date(tz) + timedelta(days=day_offset)
    return iso(datetime.combine(day, datetime.min.time(), tzinfo=tz).replace(hour=hour, minute=minute))


def _quiet(app) -> None:
    """把周期性任务推到当天最后一分钟，让测试只验证想验证的那一条。"""
    app.cfg._raw["notify.early_brief_time"] = "23:59"
    app.cfg._raw["notify.nudge_time"] = "23:59"
    app.cfg._raw["notify.weekly_report_weekday"] = 0


async def test_due_notification_sent_once(app, principal):
    _quiet(app)
    recorder = Recorder()
    app.sender = recorder
    umo = await _setup(app, principal)
    await app.notify.enqueue(
        principal,
        umo=umo,
        kind="custom",
        title="t",
        content="hello",
        scheduled_at=iso(utcnow() - timedelta(seconds=5)),
        dedupe_key="custom:1",
    )
    first = await app.scheduler.run_once()
    assert first["sent"] == 1
    second = await app.scheduler.run_once()
    assert second["sent"] == 0
    assert len(recorder.sent) == 1


async def test_dedupe_key_prevents_duplicate_enqueue(app, principal):
    umo = await _setup(app, principal)
    payload = dict(
        umo=umo,
        kind="daily_brief",
        title="t",
        content="c",
        scheduled_at=iso(utcnow()),
        dedupe_key="daily_brief:x:2026-11-17",
    )
    first = await app.notify.enqueue(principal, **payload)
    second = await app.notify.enqueue(principal, **payload)
    assert first is not None
    assert second is None


async def test_restart_does_not_resend(tmp_path):
    from core.app import StudyApp

    from tests.conftest import make_settings

    settings = make_settings()
    app1 = StudyApp(data_dir=tmp_path, cfg=settings)
    await app1.startup()
    _quiet(app1)
    recorder = Recorder()
    app1.sender = recorder
    principal = await get_or_create(app1.db, kind="user", external_id="restart")
    umo = await _setup(app1, principal)
    await app1.notify.enqueue(
        principal,
        umo=umo,
        kind="reminder",
        title="t",
        content="c",
        scheduled_at=iso(utcnow() - timedelta(seconds=1)),
        dedupe_key="task:abc:30",
    )
    await app1.scheduler.run_once()
    assert len(recorder.sent) == 1
    await app1.shutdown()

    app2 = StudyApp(data_dir=tmp_path, cfg=settings)
    await app2.startup()
    _quiet(app2)
    recorder2 = Recorder()
    app2.sender = recorder2
    await app2.scheduler.run_once()
    assert recorder2.sent == []
    await app2.shutdown()


async def test_failed_send_retried_then_marked_failed(app, principal):
    _quiet(app)
    app.sender = Recorder(ok=False)
    umo = await _setup(app, principal)
    await app.notify.enqueue(
        principal,
        umo=umo,
        kind="custom",
        title="t",
        content="c",
        scheduled_at=iso(utcnow() - timedelta(seconds=1)),
        dedupe_key="custom:fail",
    )
    for _ in range(3):
        await app.scheduler.run_once()
    row = await app.db.fetch_one(
        "SELECT status, attempts FROM notification WHERE dedupe_key = ?", ("custom:fail",)
    )
    assert row["status"] == "failed"
    assert row["attempts"] >= 1


async def test_daily_brief_enqueued_at_brief_time(app, principal):
    app.sender = Recorder()
    await _setup(app, principal)
    result = await app.scheduler.run_once(now_iso=_at_local(9, 0))
    assert result["brief"] == 1
    row = await app.db.fetch_one(
        "SELECT dedupe_key FROM notification WHERE owner_principal_id = ? AND kind = 'daily_brief'",
        (principal.id,),
    )
    assert row["dedupe_key"].startswith("daily_brief:")
    # 再跑一次不会重复
    again = await app.scheduler.run_once(now_iso=_at_local(9, 5))
    assert again["brief"] == 0


async def test_no_brief_before_brief_time(app, principal):
    app.sender = Recorder()
    await _setup(app, principal)
    result = await app.scheduler.run_once(now_iso=_at_local(6, 0))
    assert result["brief"] == 0


async def test_plan_nudge_only_when_items_pending(app, principal):
    app.sender = Recorder()
    await _setup(app, principal)
    today = local_date("Asia/Shanghai")
    app.llm.push(
        {
            "title": "督促测试",
            "items": [
                {"seq": 1, "title": "第一章", "scheduled_date": today.isoformat(), "duration_min": 30}
            ],
        }
    )
    plan = await app.plans.generate(
        principal, goal="x", daily_minutes=60, deadline=(today + timedelta(days=5)).isoformat()
    )
    await app.plans.apply(principal, plan["id"])
    result = await app.scheduler.run_once(now_iso=_at_local(21, 30))
    assert result["nudge"] == 1
    tasks = await app.tasks.list(principal)
    await app.tasks.set_status(principal, tasks[0]["id"], "done")
    await app.db.execute("DELETE FROM setting WHERE key = '__job:nudge'")
    result2 = await app.scheduler.run_once(now_iso=_at_local(21, 35))
    assert result2["nudge"] == 0


async def test_unknown_umo_is_not_fatal(app, principal):
    """推送目标对应平台不在线时，发送失败也不能影响其它主体。"""
    _quiet(app)
    app.sender = None
    umo = await _setup(app, principal, umo="qq:GroupMessage:999")
    await app.notify.enqueue(
        principal,
        umo=umo,
        kind="custom",
        title="t",
        content="c",
        scheduled_at=iso(utcnow() - timedelta(seconds=1)),
        dedupe_key="custom:nosender",
    )
    result = await app.scheduler.run_once()
    assert result["sent"] == 0


async def test_consolidation_marker(app, principal):
    app.sender = Recorder()
    await _setup(app, principal)
    result = await app.scheduler.run_once(now_iso=_at_local(23, 45))
    assert result["nightly"] >= 1
    again = await app.scheduler.run_once(now_iso=_at_local(23, 50))
    assert again["nightly"] == 0


async def test_stop_cancels_loop(app):
    app.scheduler.start()
    await app.scheduler.stop()
    assert app.scheduler._task is None
