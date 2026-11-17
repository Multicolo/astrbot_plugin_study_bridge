"""计划业务：AI 生成 → 预览 → apply（幂等）→ rollback。"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from ..errors import conflict, invalid, not_found, quota
from ..principal import Principal
from ..util import clamp, iso, local_date, new_id, parse_iso, utcnow

VALID_PLAN_STATUS = ("draft", "active", "done", "archived")


def _row_to_item(row: dict[str, Any]) -> dict[str, Any]:
    item = dict(row)
    item["duration_min"] = int(row.get("duration_min") or 0)
    item["seq"] = int(row.get("seq") or 0)
    return item


class PlanService:
    def __init__(self, app: Any) -> None:
        self.app = app

    # ------------------------------------------------------------ 生成
    async def generate(
        self,
        principal: Principal,
        *,
        goal: str = "",
        material_ids: list[str] | None = None,
        daily_minutes: int | None = None,
        deadline: str | None = None,
        title: str | None = None,
    ) -> dict[str, Any]:
        limit = self.app.cfg.get_int("quota.max_plans", 200)
        count = int(
            await self.app.db.scalar(
                "SELECT COUNT(*) FROM plan WHERE owner_principal_id = ?",
                (principal.id,),
                default=0,
            )
        )
        if count >= limit:
            raise quota(f"计划数量已达上限（{limit}）")
        tz = await self.app.settings.get_tz(principal)
        today = local_date(tz)
        if deadline:
            try:
                deadline_date = date.fromisoformat(deadline)
            except ValueError:
                raise invalid("deadline 格式应为 YYYY-MM-DD") from None
            if deadline_date < today:
                raise invalid("deadline 不能早于今天")
        else:
            deadline_date = today + timedelta(days=13)
        daily = clamp(int(daily_minutes or 30), 5, 720)
        materials: list[dict[str, Any]] = []
        if material_ids:
            for mid in material_ids:
                row = await self.app.db.fetch_one(
                    "SELECT * FROM material WHERE id = ? AND owner_principal_id = ?",
                    (mid, principal.id),
                )
                if row:
                    materials.append(row)
        generated = await self.app.llm.generate_plan(
            principal,
            goal=goal,
            materials=materials,
            daily_minutes=daily,
            deadline=deadline_date.isoformat(),
            today=today.isoformat(),
            tz=tz,
        )
        items: list[dict[str, Any]] = generated.get("items") or []
        normalised = self._normalise_items(
            items, today=today, deadline=deadline_date, daily=daily
        )
        if not normalised:
            raise invalid(generated.get("error") or "没能生成有效的计划条目，请补充目标或延长截止日期")
        plan_id = new_id()
        now = iso(utcnow())
        plan_title = (title or generated.get("title") or goal or "学习计划").strip()[:120]
        async with self.app.db.transaction() as tx:
            await tx.execute(
                "INSERT INTO plan (id, owner_principal_id, title, goal, deadline, daily_minutes, "
                "status, origin_session_id, applied_at, created_at) VALUES (?, ?, ?, ?, ?, ?, "
                "'draft', NULL, NULL, ?)",
                (plan_id, principal.id, plan_title, goal or None, deadline_date.isoformat(), daily, now),
            )
            for item in normalised:
                await tx.execute(
                    "INSERT INTO plan_item (id, owner_principal_id, plan_id, seq, title, "
                    "scheduled_date, duration_min, task_id, status) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 'pending')",
                    (
                        new_id(),
                        principal.id,
                        plan_id,
                        item["seq"],
                        item["title"],
                        item["scheduled_date"],
                        item["duration_min"],
                    ),
                )
        plan = await self.get(principal, plan_id)
        assert plan is not None
        plan["warnings"] = generated.get("warnings") or []
        plan["generated_by"] = generated.get("source", "ai")
        return plan

    def _normalise_items(
        self,
        items: Any,
        *,
        today: date,
        deadline: date,
        daily: int,
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        if not isinstance(items, list):
            return result
        for index, raw in enumerate(items, start=1):
            if not isinstance(raw, dict):
                continue
            title = str(raw.get("title") or "").strip()
            if not title:
                continue
            try:
                scheduled = date.fromisoformat(str(raw.get("scheduled_date"))[:10])
            except ValueError:
                continue
            if scheduled < today or scheduled > deadline:
                continue
            try:
                duration = int(raw.get("duration_min") or daily)
            except (TypeError, ValueError):
                duration = daily
            duration = clamp(duration, 5, daily)
            result.append(
                {
                    "seq": len(result) + 1,
                    "title": title[:120],
                    "scheduled_date": scheduled.isoformat(),
                    "duration_min": duration,
                }
            )
        return result

    # ------------------------------------------------------------ 读
    async def list(
        self, principal: Principal, *, status: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM plan WHERE owner_principal_id = ?"
        params: list[Any] = [principal.id]
        if status:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(clamp(limit, 1, 200))
        rows = await self.app.db.fetch_all(sql, tuple(params))
        return [dict(row) for row in rows]

    async def get(self, principal: Principal, plan_id: str) -> dict[str, Any] | None:
        row = await self.app.db.fetch_one(
            "SELECT * FROM plan WHERE id = ? AND owner_principal_id = ?",
            (plan_id, principal.id),
        )
        if not row:
            return None
        items = await self.app.db.fetch_all(
            "SELECT * FROM plan_item WHERE plan_id = ? AND owner_principal_id = ? ORDER BY seq ASC",
            (plan_id, principal.id),
        )
        plan = dict(row)
        plan["items"] = [_row_to_item(item) for item in items]
        plan["total_minutes"] = sum(item["duration_min"] for item in plan["items"])
        return plan

    async def latest_draft(self, principal: Principal) -> dict[str, Any] | None:
        row = await self.app.db.fetch_one(
            "SELECT id FROM plan WHERE owner_principal_id = ? AND applied_at IS NULL "
            "ORDER BY created_at DESC LIMIT 1",
            (principal.id,),
        )
        if not row:
            return None
        return await self.get(principal, row["id"])

    # ------------------------------------------------------------ 改
    async def patch(
        self, principal: Principal, plan_id: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        plan = await self.get(principal, plan_id)
        if plan is None:
            raise not_found("计划不存在")
        updates: dict[str, Any] = {}
        if "title" in data:
            title = str(data["title"] or "").strip()
            if not title:
                raise invalid("title 不能为空")
            updates["title"] = title[:120]
        if "goal" in data:
            updates["goal"] = None if data["goal"] is None else str(data["goal"])[:2000]
        if "deadline" in data:
            try:
                date.fromisoformat(str(data["deadline"]))
            except ValueError:
                raise invalid("deadline 格式应为 YYYY-MM-DD") from None
            updates["deadline"] = str(data["deadline"])
        if "daily_minutes" in data:
            updates["daily_minutes"] = clamp(int(data["daily_minutes"]), 5, 720)
        if "status" in data:
            status = str(data["status"])
            if status not in VALID_PLAN_STATUS:
                raise invalid(f"status 只能是 {VALID_PLAN_STATUS}")
            updates["status"] = status
        if not updates:
            return plan
        assignments = ", ".join(f"{key} = :{key}" for key in updates)
        await self.app.db.execute(
            f"UPDATE plan SET {assignments} WHERE id = :id AND owner_principal_id = :owner",
            {**updates, "id": plan_id, "owner": principal.id},
        )
        return await self.get(principal, plan_id)  # type: ignore[return-value]

    async def delete(self, principal: Principal, plan_id: str) -> dict[str, Any]:
        plan = await self.get(principal, plan_id)
        if plan is None:
            raise not_found("计划不存在")
        if plan.get("applied_at"):
            raise conflict("计划已写入日程，请先 rollback 再删除")
        await self.app.db.execute(
            "DELETE FROM plan_item WHERE plan_id = ? AND owner_principal_id = ?",
            (plan_id, principal.id),
        )
        await self.app.db.execute(
            "DELETE FROM plan WHERE id = ? AND owner_principal_id = ?", (plan_id, principal.id)
        )
        return {"id": plan_id, "deleted": True}

    # ------------------------------------------------------------ apply
    async def apply(self, principal: Principal, plan_id: str) -> dict[str, Any]:
        plan = await self.get(principal, plan_id)
        if plan is None:
            raise not_found("计划不存在")
        tz = await self.app.settings.get_tz(principal)
        today = local_date(tz)
        deadline = plan.get("deadline")
        deadline_date = date.fromisoformat(deadline) if deadline else None
        out_of_range = [
            item
            for item in plan["items"]
            if date.fromisoformat(item["scheduled_date"]) < today
            or (deadline_date and date.fromisoformat(item["scheduled_date"]) > deadline_date)
        ]
        if out_of_range:
            raise invalid(
                "计划中有条目的日期越界（已过今天或超过 deadline），请先修改计划",
                {
                    "items": [
                        {"item_id": item["id"], "date": item["scheduled_date"]}
                        for item in out_of_range
                    ]
                },
            )
        created = 0
        skipped = 0
        daily = int(plan.get("daily_minutes") or 30)
        for item in plan["items"]:
            if item.get("task_id"):
                skipped += 1
                continue
            start_dt = self._datetime_for(item["scheduled_date"], plan.get("daily_minutes"), tz)
            task = await self.app.tasks.create(
                principal,
                {
                    "title": item["title"],
                    "start_at": iso(start_dt),
                    "end_at": iso(start_dt + timedelta(minutes=item["duration_min"])),
                    "priority": 2,
                    "source": "ai",
                },
                source="ai",
                plan_item_id=item["id"],
            )
            await self.app.db.execute(
                "UPDATE plan_item SET task_id = ?, status = 'applied' WHERE id = ? AND owner_principal_id = ?",
                (task["id"], item["id"], principal.id),
            )
            created += 1
        await self.app.db.execute(
            "UPDATE plan SET applied_at = ?, status = 'active' WHERE id = ? AND owner_principal_id = ?",
            (iso(utcnow()), plan_id, principal.id),
        )
        _ = daily
        return {"created": created, "skipped": skipped, "plan_id": plan_id}

    def _datetime_for(self, scheduled_date: str, daily_minutes: int | None, tz: str):
        """把「日期 + 默认时长」落成具体时段：默认 19:00 开始（不占上课时间）。"""
        from datetime import datetime, time

        from ..util import get_tz

        day = date.fromisoformat(scheduled_date)
        return datetime.combine(day, time(19, 0), tzinfo=get_tz(tz))

    # ------------------------------------------------------------ rollback
    async def rollback(self, principal: Principal, plan_id: str) -> dict[str, Any]:
        plan = await self.get(principal, plan_id)
        if plan is None:
            raise not_found("计划不存在")
        deleted = 0
        skipped: list[dict[str, Any]] = []
        for item in plan["items"]:
            task_id = item.get("task_id")
            if not task_id:
                continue
            row = await self.app.db.fetch_one(
                "SELECT * FROM task WHERE id = ? AND owner_principal_id = ?",
                (task_id, principal.id),
            )
            if not row:
                await self.app.db.execute(
                    "UPDATE plan_item SET task_id = NULL, status = 'pending' WHERE id = ?",
                    (item["id"],),
                )
                continue
            if row.get("updated_at") != row.get("created_at"):
                skipped.append({"item_id": item["id"], "reason": "任务已被修改过"})
                continue
            if row.get("deleted_at"):
                await self.app.db.execute(
                    "UPDATE plan_item SET task_id = NULL, status = 'pending' WHERE id = ?",
                    (item["id"],),
                )
                continue
            await self.app.db.execute(
                "UPDATE task SET deleted_at = ?, updated_at = ? WHERE id = ?",
                (iso(utcnow()), iso(utcnow()), task_id),
            )
            await self.app.db.execute(
                "UPDATE plan_item SET task_id = NULL, status = 'pending' WHERE id = ?",
                (item["id"],),
            )
            deleted += 1
        await self.app.db.execute(
            "UPDATE plan SET applied_at = NULL, status = 'draft' WHERE id = ? AND owner_principal_id = ?",
            (plan_id, principal.id),
        )
        return {"deleted": deleted, "skipped": skipped}

    # ------------------------------------------------------------ 进度
    async def progress(self, principal: Principal) -> list[dict[str, Any]]:
        plans = await self.app.db.fetch_all(
            "SELECT * FROM plan WHERE owner_principal_id = ? AND status != 'archived' "
            "ORDER BY created_at DESC LIMIT 20",
            (principal.id,),
        )
        out: list[dict[str, Any]] = []
        for plan in plans:
            items = await self.app.db.fetch_all(
                "SELECT pi.*, t.status AS task_status FROM plan_item pi "
                "LEFT JOIN task t ON t.id = pi.task_id "
                "WHERE pi.plan_id = ? AND pi.owner_principal_id = ?",
                (plan["id"], principal.id),
            )
            total = len(items)
            done = sum(1 for item in items if item.get("task_status") == "done")
            out.append(
                {
                    "plan_id": plan["id"],
                    "title": plan["title"],
                    "deadline": plan.get("deadline"),
                    "status": plan.get("status"),
                    "applied": bool(plan.get("applied_at")),
                    "total": total,
                    "done": done,
                    "rate": int(round(done * 100 / total)) if total else 0,
                }
            )
        return out
