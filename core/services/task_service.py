"""任务（日程）业务：CRUD、今日/本周聚合、自然语言解析、配额。"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from ..errors import invalid, not_found, quota
from ..principal import Principal
from ..util import (
    clamp,
    dumps,
    get_tz,
    iso,
    loads,
    local_date,
    local_day_of,
    parse_iso,
    utcnow,
)

VALID_STATUS = ("pending", "done", "skipped")
VALID_SOURCE = ("manual", "ai", "qq")


def _row_to_task(row: dict[str, Any], tz: str) -> dict[str, Any]:
    start = parse_iso(row.get("start_at"))
    end = parse_iso(row.get("end_at"))
    task = dict(row)
    task["all_day"] = bool(row.get("all_day", 0))
    task["remind_offsets"] = loads(row.get("remind_offsets"), [30, 0]) or []
    task["start_at"] = iso(start) if start else None
    task["end_at"] = iso(end) if end else None
    task["local_date"] = local_day_of(start, tz).isoformat() if start else None
    task["local_start"] = start.astimezone(get_tz(tz)).strftime("%H:%M") if start else None
    task["local_end"] = end.astimezone(get_tz(tz)).strftime("%H:%M") if end else None
    task["deleted"] = bool(row.get("deleted_at"))
    return task


class TaskService:
    def __init__(self, app: Any) -> None:
        self.app = app

    # ------------------------------------------------------------ 内部
    async def _count(self, principal: Principal) -> int:
        value = await self.app.db.scalar(
            "SELECT COUNT(*) FROM task WHERE owner_principal_id = ? AND deleted_at IS NULL",
            (principal.id,),
            default=0,
        )
        return int(value)

    async def _check_quota(self, principal: Principal) -> None:
        limit = self.app.cfg.get_int("quota.max_tasks", 2000)
        if await self._count(principal) >= limit:
            raise quota(f"任务数量已达上限（{limit}），请先清理已完成任务")

    async def _tz(self, principal: Principal) -> str:
        return await self.app.settings.get_tz(principal)

    # ------------------------------------------------------------ 校验
    def _validate_payload(self, data: dict[str, Any], *, partial: bool = False) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if "title" in data or not partial:
            title = (data.get("title") or "").strip()
            if not title:
                raise invalid("title 不能为空", {"title": "必填"})
            if len(title) > 200:
                raise invalid("title 过长（≤200 字）", {"title": "≤200 字"})
            out["title"] = title
        if "note" in data:
            note = data.get("note")
            out["note"] = None if note is None else str(note)[:2000]
        start = parse_iso(data.get("start_at")) if "start_at" in data else None
        end = parse_iso(data.get("end_at")) if "end_at" in data else None
        if "start_at" in data:
            out["start_at"] = iso(start) if start else None
        if "end_at" in data:
            out["end_at"] = iso(end) if end else None
        if start and end and end < start:
            raise invalid("end_at 不能早于 start_at", {"end_at": "早于 start_at"})
        if "all_day" in data:
            out["all_day"] = 1 if data.get("all_day") else 0
        if "priority" in data:
            try:
                priority = int(data["priority"])
            except (TypeError, ValueError):
                raise invalid("priority 必须是 1~3 的整数", {"priority": "1~3"}) from None
            out["priority"] = clamp(priority, 1, 3)
        if "status" in data:
            status = str(data["status"])
            if status not in VALID_STATUS:
                raise invalid(f"status 只能是 {VALID_STATUS}", {"status": "非法值"})
            out["status"] = status
        if "remind_offsets" in data:
            self._validate_offsets(data.get("remind_offsets"))
            out["remind_offsets"] = dumps(data["remind_offsets"])
        if "source" in data:
            source = str(data["source"])
            out["source"] = source if source in VALID_SOURCE else "manual"
        return out

    def _validate_offsets(self, value: Any) -> None:
        if value is None:
            return
        if not isinstance(value, list) or any(
            not isinstance(item, int) or item < 0 or item > 1440 for item in value
        ):
            raise invalid(
                "remind_offsets 必须是 0~1440 的整数数组",
                {"remind_offsets": "例：[30,0]"},
            )

    # ------------------------------------------------------------ 写
    async def create(
        self,
        principal: Principal,
        data: dict[str, Any],
        *,
        source: str = "manual",
        plan_item_id: str | None = None,
    ) -> dict[str, Any]:
        await self._check_quota(principal)
        payload = self._validate_payload(data)
        from ..util import new_id

        task_id = new_id()
        now = iso(utcnow())
        tz = await self._tz(principal)
        values = {
            "id": task_id,
            "owner_principal_id": principal.id,
            "title": payload["title"],
            "note": payload.get("note"),
            "start_at": payload.get("start_at"),
            "end_at": payload.get("end_at"),
            "all_day": payload.get("all_day", 0),
            "status": payload.get("status", "pending"),
            "priority": payload.get("priority", 2),
            "source": payload.get("source", source),
            "plan_item_id": plan_item_id,
            "remind_offsets": payload.get(
                "remind_offsets",
                dumps(self.app.cfg.get_list("notify.default_remind_offsets", [30, 0])),
            ),
            "created_at": now,
            "updated_at": now,
            "deleted_at": None,
        }
        await self.app.db.execute(
            "INSERT INTO task (id, owner_principal_id, title, note, start_at, end_at, all_day, "
            "status, priority, source, plan_item_id, remind_offsets, created_at, updated_at, deleted_at) "
            "VALUES (:id, :owner_principal_id, :title, :note, :start_at, :end_at, :all_day, "
            ":status, :priority, :source, :plan_item_id, :remind_offsets, :created_at, :updated_at, :deleted_at)",
            values,
        )
        task = await self.get(principal, task_id)
        assert task is not None
        await self._schedule_reminders(principal, task, tz)
        return task

    async def update(
        self, principal: Principal, task_id: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        existing = await self.get(principal, task_id)
        if existing is None:
            raise not_found("任务不存在")
        payload = self._validate_payload(data, partial=True)
        if not payload:
            return existing
        payload["updated_at"] = iso(utcnow())
        payload["id"] = task_id
        assignments = ", ".join(f"{key} = :{key}" for key in payload)
        await self.app.db.execute(
            f"UPDATE task SET {assignments} WHERE id = :id AND owner_principal_id = :owner",
            {**payload, "id": task_id, "owner": principal.id},
        )
        # 时间变了就重排提醒（旧的待发提醒作废）
        if "start_at" in payload or "remind_offsets" in payload:
            await self.app.db.execute(
                "UPDATE notification SET status = 'cancelled' WHERE dedupe_key LIKE ? "
                "AND status = 'pending'",
                (f"task:{task_id}:%",),
            )
            task = await self.get(principal, task_id)
            assert task is not None
            await self._schedule_reminders(principal, task, await self._tz(principal))
        return await self.get(principal, task_id)  # type: ignore[return-value]

    async def set_status(
        self, principal: Principal, task_id: str, status: str
    ) -> dict[str, Any]:
        if status not in VALID_STATUS:
            raise invalid(f"status 只能是 {VALID_STATUS}")
        existing = await self.get(principal, task_id)
        if existing is None:
            raise not_found("任务不存在")
        await self.app.db.execute(
            "UPDATE task SET status = ?, updated_at = ? WHERE id = ? AND owner_principal_id = ?",
            (status, iso(utcnow()), task_id, principal.id),
        )
        return await self.get(principal, task_id)  # type: ignore[return-value]

    async def delete(self, principal: Principal, task_id: str) -> dict[str, Any]:
        existing = await self.get(principal, task_id)
        if existing is None:
            raise not_found("任务不存在")
        now = iso(utcnow())
        await self.app.db.execute(
            "UPDATE task SET deleted_at = ?, updated_at = ? WHERE id = ? AND owner_principal_id = ?",
            (now, now, task_id, principal.id),
        )
        return {"id": task_id, "deleted": True}

    # ------------------------------------------------------------ 读
    async def get(self, principal: Principal, task_id: str) -> dict[str, Any] | None:
        row = await self.app.db.fetch_one(
            "SELECT * FROM task WHERE id = ? AND owner_principal_id = ? AND deleted_at IS NULL",
            (task_id, principal.id),
        )
        if not row:
            return None
        return _row_to_task(row, await self._tz(principal))

    async def list(
        self,
        principal: Principal,
        *,
        date_from: str | None = None,
        date_to: str | None = None,
        status: str | None = None,
        query: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        tz = await self._tz(principal)
        sql = [
            "SELECT * FROM task WHERE owner_principal_id = ? AND deleted_at IS NULL"
        ]
        params: list[Any] = [principal.id]
        if date_from:
            start, _ = self._day_bounds(date_from, tz)
            sql.append("AND COALESCE(start_at, created_at) >= ?")
            params.append(start)
        if date_to:
            _, end = self._day_bounds(date_to, tz)
            sql.append("AND COALESCE(start_at, created_at) < ?")
            params.append(end)
        if status:
            sql.append("AND status = ?")
            params.append(status)
        if query:
            sql.append("AND (title LIKE ? OR COALESCE(note,'') LIKE ?)")
            like = f"%{query}%"
            params.extend([like, like])
        sql.append("ORDER BY COALESCE(start_at, created_at) ASC LIMIT ? OFFSET ?")
        params.extend([clamp(int(limit), 1, 500), max(0, int(offset))])
        rows = await self.app.db.fetch_all(" ".join(sql), tuple(params))
        return [_row_to_task(row, tz) for row in rows]

    def _day_bounds(self, day_text: str, tz: str) -> tuple[str, str]:
        try:
            day = date.fromisoformat(day_text) if isinstance(day_text, str) else day_text
        except ValueError:
            raise invalid(f"日期格式应为 YYYY-MM-DD：{day_text}") from None
        start = datetime.combine(day, datetime.min.time(), tzinfo=get_tz(tz))
        end = start + timedelta(days=1)
        return iso(start), iso(end)

    async def day_view(self, principal: Principal, day_offset: int = 0) -> dict[str, Any]:
        """某本地日期（今天 + offset）的聚合视图，供 /today /tomorrow App 首页共用。"""
        tz = await self._tz(principal)
        day = local_date(tz) + timedelta(days=day_offset)
        start, end = self._day_bounds(day.isoformat(), tz)
        rows = await self.app.db.fetch_all(
            "SELECT * FROM task WHERE owner_principal_id = ? AND deleted_at IS NULL "
            "AND start_at >= ? AND start_at < ? ORDER BY start_at ASC",
            (principal.id, start, end),
        )
        items = [_row_to_task(row, tz) for row in rows]
        done = sum(1 for item in items if item["status"] == "done")
        total = len(items)
        now = iso(utcnow())
        overdue_row = await self.app.db.fetch_all(
            "SELECT id FROM task WHERE owner_principal_id = ? AND deleted_at IS NULL "
            "AND status = 'pending' AND start_at < ?",
            (principal.id, start),
        )
        return {
            "date": day.isoformat(),
            "items": items,
            "total": total,
            "done": done,
            "rate": int(round(done * 100 / total)) if total else 0,
            "overdue": len(overdue_row),
            "now": now,
        }

    async def week_view(self, principal: Principal, week_offset: int = 0) -> dict[str, Any]:
        tz = await self._tz(principal)
        today = local_date(tz)
        monday = today - timedelta(days=today.weekday()) + timedelta(weeks=week_offset)
        sunday = monday + timedelta(days=6)
        tasks = await self.list(
            principal,
            date_from=monday.isoformat(),
            date_to=sunday.isoformat(),
            limit=500,
        )
        done = sum(1 for item in tasks if item["status"] == "done")
        total = len(tasks)
        return {
            "start": monday.isoformat(),
            "end": sunday.isoformat(),
            "items": tasks,
            "total": total,
            "done": done,
            "rate": int(round(done * 100 / total)) if total else 0,
        }

    # ------------------------------------------------------------ 提醒排程
    async def _schedule_reminders(
        self, principal: Principal, task: dict[str, Any], tz: str
    ) -> None:
        start = parse_iso(task.get("start_at"))
        if not start:
            return
        umo = await self.app.notify.primary_umo(principal)
        if not umo:
            return
        offsets = task.get("remind_offsets") or []
        for offset in offsets:
            send_at = start - timedelta(minutes=int(offset))
            if send_at <= utcnow():
                continue
            dedupe = f"task:{task['id']}:{offset}"
            await self.app.notify.enqueue(
                principal,
                umo=umo,
                kind="reminder",
                title=task["title"],
                content="",
                scheduled_at=iso(send_at),
                dedupe_key=dedupe,
                payload={"task_id": task["id"], "offset": offset},
            )

    # ------------------------------------------------------------ 解析
    async def parse(self, principal: Principal, text: str) -> dict[str, Any]:
        text = (text or "").strip()
        if not text:
            raise invalid("text 不能为空")
        tz = await self._tz(principal)
        draft = await self.app.llm.parse_task(principal, text, tz=tz)
        return draft

    # ------------------------------------------------------------ 指令辅助
    async def resolve_reference(self, principal: Principal, reference: str) -> dict[str, Any] | None:
        """把 ``/done 2`` 或 ``/done 背单词`` 解析成任务。"""
        reference = (reference or "").strip()
        if not reference:
            return None
        today = await self.day_view(principal, 0)
        items = today["items"]
        if reference.isdigit():
            idx = int(reference)
            if 1 <= idx <= len(items):
                return items[idx - 1]
            # 编号越界时回退到当天全部任务（含非今天的）
            return None
        rows = await self.app.db.fetch_all(
            "SELECT * FROM task WHERE owner_principal_id = ? AND deleted_at IS NULL "
            "AND status = 'pending' AND title LIKE ? ORDER BY COALESCE(start_at, created_at) ASC LIMIT 1",
            (principal.id, f"%{reference}%"),
        )
        if not rows:
            return None
        return _row_to_task(rows[0], await self._tz(principal))
