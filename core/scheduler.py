"""插件内调度器：单 asyncio 循环，30s tick，按 principal 分别读配置后触发。

不做的事：
- 不引入 APScheduler（红线：不新增重依赖）；
- 不用 threading 起常驻线程（红线 8）；
- 不静默吞异常：单主体失败只影响该主体，并记 sync_log。
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any

from .services.notify_service import NotifyService
from .util import get_tz, iso, local_date, parse_hhmm, parse_iso, utcnow

TICK_SECONDS = 30


class Scheduler:
    def __init__(self, app: Any, *, tick_seconds: int = TICK_SECONDS) -> None:
        self.app = app
        self.tick_seconds = tick_seconds
        self._task: asyncio.Task | None = None
        self._stopping = False

    # ------------------------------------------------------------ 生命周期
    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stopping = False
        self._task = asyncio.create_task(self._loop(), name="study_bridge_scheduler")

    async def stop(self) -> None:
        self._stopping = True
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
        self._task = None

    async def _loop(self) -> None:
        while not self._stopping:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - 调度异常不能杀死循环
                self.app.logger.exception("调度任务异常：%s", exc)
            await asyncio.sleep(self.tick_seconds)

    # ------------------------------------------------------------ 单次
    async def run_once(self, *, now_iso: str | None = None) -> dict[str, Any]:
        now = parse_iso(now_iso or iso(utcnow()))
        assert now is not None
        result = {"sent": 0, "brief": 0, "nudge": 0, "weekly": 0, "nightly": 0, "outbox": 0}
        result["sent"] = await self.app.notify.run_due(now_iso=iso(now))
        result["outbox"] = await self.app.memories.process_outbox()
        for principal in await self._principals():
            try:
                await self._for_principal(principal, now, result)
            except Exception as exc:  # noqa: BLE001 - 单主体失败不影响其它主体
                self.app.logger.warning(
                    "调度主体 %s 失败：%s", getattr(principal, "id", "?"), exc
                )
        return result

    async def _principals(self) -> list[Any]:
        rows = await self.app.db.fetch_all(
            "SELECT DISTINCT p.* FROM principal p JOIN push_target t "
            "ON t.owner_principal_id = p.id AND t.enabled = 1"
        )
        from .principal import Principal

        return [Principal.from_row(row) for row in rows]

    async def _for_principal(self, principal: Any, now: datetime, result: dict[str, Any]) -> None:
        settings = await self.app.settings.get_all(principal)
        tz = settings["tz"]
        local = now.astimezone(get_tz(tz))
        day = local.date().isoformat()
        umo = await self.app.notify.primary_umo(principal)
        if not umo:
            return

        # 早报
        if local.time() >= parse_hhmm(settings["brief"]):
            marker = await self._job_done(principal, "brief")
            if marker != day:
                view = await self.app.tasks.day_view(principal, 0)
                plans = await self.app.plans.progress(principal)
                active = [p for p in plans if p["applied"]]
                brief = self.app.notify.render_daily_brief(
                    day=day,
                    total=view["total"],
                    done=view["done"],
                    overdue=view["overdue"],
                    plan_title=active[0]["title"] if active else None,
                )
                created = await self.app.notify.enqueue(
                    principal,
                    umo=umo,
                    kind="daily_brief",
                    title=brief["title"],
                    content=brief["content"],
                    scheduled_at=iso(now),
                    dedupe_key=f"daily_brief:{principal.id}:{day}",
                )
                await self._mark_job(principal, "brief", day)
                if created:
                    result["brief"] += 1

        # 计划督促
        if local.time() >= parse_hhmm(settings["nudge"]):
            marker = await self._job_done(principal, "nudge")
            if marker != day:
                pending = await self._pending_plan_items(principal)
                if pending:
                    body = self.app.t(
                        "notify.nudge.body",
                        plan=pending["plan_title"],
                        count=len(pending["items"]),
                        items="\n".join(f"- {item}" for item in pending["items"][:5]),
                    )
                    created = await self.app.notify.enqueue(
                        principal,
                        umo=umo,
                        kind="plan_nudge",
                        title=self.app.t("notify.nudge.title"),
                        content=body,
                        scheduled_at=iso(now),
                        dedupe_key=f"plan_nudge:{principal.id}:{day}",
                    )
                    if created:
                        result["nudge"] += 1
                await self._mark_job(principal, "nudge", day)

        # 周报
        weekday = self.app.cfg.get_int("notify.weekly_report_weekday", 1)
        weekly_time = self.app.cfg.get_str("notify.weekly_report_time", "09:00")
        if local.isoweekday() == weekday and local.time() >= parse_hhmm(weekly_time):
            week_key = f"{local.isocalendar()[0]}-W{local.isocalendar()[1]:02d}"
            marker = await self._job_done(principal, "weekly")
            if marker != week_key:
                stats = await self.app.stats.overview(principal, "week")
                report = self.app.notify.render_weekly(
                    start=stats["start"],
                    end=stats["end"],
                    total=stats["total"],
                    done=stats["done"],
                    rate=stats["rate"],
                    minutes=stats["minutes"],
                )
                created = await self.app.notify.enqueue(
                    principal,
                    umo=umo,
                    kind="weekly_report",
                    title=report["title"],
                    content=report["content"],
                    scheduled_at=iso(now),
                    dedupe_key=f"weekly_report:{principal.id}:{week_key}",
                )
                await self._mark_job(principal, "weekly", week_key)
                if created:
                    result["weekly"] += 1

        # 每日 23:30 consolidation：进度上行 + 下行镜像
        if local.time() >= parse_hhmm("23:30"):
            marker = await self._job_done(principal, "consolidation")
            if marker != day:
                await self.app.memories.push_progress(principal)
                await self.app.db.execute(
                    "INSERT INTO sync_log (op, ok, detail, created_at) VALUES ('consolidation', 1, ?, ?)",
                    (f"principal={principal.id}", iso(utcnow())),
                )
                await self.app.memories.process_outbox()
                await self._mark_job(principal, "consolidation", day)
                result["nightly"] += 1

        # 每周日 03:10 记忆对账
        if local.isoweekday() == 7 and local.time() >= parse_hhmm("03:10"):
            week_key = f"{local.isocalendar()[0]}-W{local.isocalendar()[1]:02d}"
            marker = await self._job_done(principal, "reconcile")
            if marker != week_key:
                await self.app.memories.reconcile(principal)
                await self._mark_job(principal, "reconcile", week_key)

    async def _pending_plan_items(self, principal: Any) -> dict[str, Any] | None:
        plans = await self.app.plans.progress(principal)
        for plan in plans:
            if not plan["applied"]:
                continue
            rows = await self.app.db.fetch_all(
                "SELECT pi.title FROM plan_item pi LEFT JOIN task t ON t.id = pi.task_id "
                "WHERE pi.plan_id = ? AND pi.owner_principal_id = ? "
                "AND (t.status IS NULL OR t.status = 'pending') LIMIT 5",
                (plan["plan_id"], principal.id),
            )
            if rows:
                return {"plan_title": plan["title"], "items": [row["title"] for row in rows]}
        return None

    # ------------------------------------------------------------ 任务标记
    async def _job_done(self, principal: Any, job: str) -> str | None:
        row = await self.app.db.fetch_one(
            "SELECT value FROM setting WHERE owner_principal_id = ? AND key = ?",
            (principal.id, f"__job:{job}"),
        )
        return (row or {}).get("value")

    async def _mark_job(self, principal: Any, job: str, value: str) -> None:
        await self.app.db.execute(
            "INSERT INTO setting (owner_principal_id, key, value, updated_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(owner_principal_id, key) DO UPDATE SET value = excluded.value, "
            "updated_at = excluded.updated_at",
            (principal.id, f"__job:{job}", value, iso(utcnow())),
        )


_ = (NotifyService, local_date, timedelta)
