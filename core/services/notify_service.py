"""推送业务：推送目标、通知记录、到点发送、模板渲染。"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from ..errors import invalid, not_found
from ..principal import Principal
from ..util import dumps, get_tz, iso, loads, parse_iso, utcnow


class NotifyService:
    def __init__(self, app: Any) -> None:
        self.app = app

    # ------------------------------------------------------------ 推送目标
    async def list_targets(self, principal: Principal) -> list[dict[str, Any]]:
        rows = await self.app.db.fetch_all(
            "SELECT * FROM push_target WHERE owner_principal_id = ? ORDER BY created_at ASC",
            (principal.id,),
        )
        for row in rows:
            row["enabled"] = bool(row.get("enabled", 1))
        return rows

    async def add_target(
        self, principal: Principal, *, umo: str, alias: str | None = None
    ) -> dict[str, Any]:
        umo = (umo or "").strip()
        if not umo:
            raise invalid("umo 不能为空（在 QQ 里发 /umo 可获取）")
        exists = await self.app.db.fetch_one(
            "SELECT * FROM push_target WHERE owner_principal_id = ? AND umo = ?",
            (principal.id, umo),
        )
        if exists:
            raise invalid("这个会话已经在推送目标里了")
        from ..util import new_id

        target_id = new_id()
        await self.app.db.execute(
            "INSERT INTO push_target (id, owner_principal_id, umo, alias, enabled, created_at) "
            "VALUES (?, ?, ?, ?, 1, ?)",
            (target_id, principal.id, umo, (alias or "").strip() or None, iso(utcnow())),
        )
        return await self._get_target(principal, target_id)

    async def _get_target(self, principal: Principal, target_id: str) -> dict[str, Any]:
        row = await self.app.db.fetch_one(
            "SELECT * FROM push_target WHERE id = ? AND owner_principal_id = ?",
            (target_id, principal.id),
        )
        if not row:
            raise not_found("推送目标不存在")
        row["enabled"] = bool(row.get("enabled", 1))
        return row

    async def update_target(
        self, principal: Principal, target_id: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        await self._get_target(principal, target_id)
        updates: dict[str, Any] = {}
        if "enabled" in data:
            updates["enabled"] = 1 if data.get("enabled") else 0
        if "alias" in data:
            updates["alias"] = (str(data.get("alias") or "").strip() or None)
        if updates:
            assignments = ", ".join(f"{key} = :{key}" for key in updates)
            await self.app.db.execute(
                f"UPDATE push_target SET {assignments} WHERE id = :id AND owner_principal_id = :owner",
                {**updates, "id": target_id, "owner": principal.id},
            )
        return await self._get_target(principal, target_id)

    async def delete_target(self, principal: Principal, target_id: str) -> dict[str, Any]:
        await self._get_target(principal, target_id)
        await self.app.db.execute(
            "DELETE FROM push_target WHERE id = ? AND owner_principal_id = ?",
            (target_id, principal.id),
        )
        return {"id": target_id, "deleted": True}

    async def primary_umo(self, principal: Principal) -> str | None:
        row = await self.app.db.fetch_one(
            "SELECT umo FROM push_target WHERE owner_principal_id = ? AND enabled = 1 "
            "ORDER BY created_at ASC LIMIT 1",
            (principal.id,),
        )
        return row["umo"] if row else None

    async def test_target(self, principal: Principal, target_id: str) -> dict[str, Any]:
        target = await self._get_target(principal, target_id)
        text = self.app.t("notify.test.body", umo=target["umo"])
        ok = await self.send_text(target["umo"], text)
        return {"ok": ok, "umo": target["umo"], "message": text}

    # ------------------------------------------------------------ 发送
    async def send_text(self, umo: str, text: str) -> bool:
        sender = self.app.sender
        if sender is None:
            return False
        try:
            return bool(await sender(umo, text))
        except Exception as exc:  # noqa: BLE001 - 平台异常不能拖垮调度
            self.app.logger.warning("发送失败 umo=%s: %s", umo, exc)
            return False

    # ------------------------------------------------------------ 通知
    async def enqueue(
        self,
        principal: Principal,
        *,
        umo: str,
        kind: str,
        title: str | None,
        content: str,
        scheduled_at: str,
        dedupe_key: str,
        payload: dict[str, Any] | None = None,
    ) -> str | None:
        """写入待发送通知；``dedupe_key`` 冲突时静默跳过（幂等/重启不重发）。"""
        limit = self.app.cfg.get_int("quota.max_notifications", 5000)
        count = int(
            await self.app.db.scalar(
                "SELECT COUNT(*) FROM notification WHERE owner_principal_id = ?",
                (principal.id,),
                default=0,
            )
        )
        if count >= limit:
            self.app.logger.warning("通知记录已达上限，跳过入队 principal=%s", principal.id)
            return None
        from ..util import new_id

        exists = await self.app.db.fetch_one(
            "SELECT id FROM notification WHERE dedupe_key = ?", (dedupe_key,)
        )
        if exists:
            return None
        note_id = new_id()
        body = content or dumps(payload or {})
        await self.app.db.execute(
            "INSERT INTO notification (id, owner_principal_id, umo, kind, title, content, scheduled_at, "
            "status, attempts, sent_at, dedupe_key, error, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', 0, NULL, ?, NULL, ?)",
            (
                note_id,
                principal.id,
                umo,
                kind,
                title,
                body,
                scheduled_at,
                dedupe_key,
                iso(utcnow()),
            ),
        )
        return note_id

    async def list_notifications(
        self, principal: Principal, *, status: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM notification WHERE owner_principal_id = ?"
        params: list[Any] = [principal.id]
        if status:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY scheduled_at DESC, created_at DESC LIMIT ?"
        params.append(max(1, min(200, limit)))
        return await self.app.db.fetch_all(sql, tuple(params))

    async def run_due(self, *, now_iso: str | None = None) -> int:
        """发送所有到期通知；返回成功发送数。"""
        now = parse_iso(now_iso or iso(utcnow()))
        assert now is not None
        retry_max = self.app.cfg.get_int("notify.retry_max", 3)
        rows = await self.app.db.fetch_all(
            "SELECT * FROM notification WHERE status = 'pending' AND scheduled_at <= ? "
            "ORDER BY scheduled_at ASC LIMIT 50",
            (iso(now),),
        )
        sent = 0
        for row in rows:
            text = self._render(row)
            ok = await self.send_text(row["umo"], text)
            now_text = iso(utcnow())
            if ok:
                await self.app.db.execute(
                    "UPDATE notification SET status = 'sent', attempts = attempts + 1, sent_at = ? "
                    "WHERE id = ?",
                    (now_text, row["id"]),
                )
                sent += 1
            else:
                attempts = int(row.get("attempts") or 0) + 1
                status = "failed" if attempts >= max(1, retry_max) else "pending"
                await self.app.db.execute(
                    "UPDATE notification SET attempts = ?, status = ?, error = ? WHERE id = ?",
                    (attempts, status, "send_failed", row["id"]),
                )
            await self.app.db.execute(
                "INSERT INTO sync_log (op, ok, detail, created_at) VALUES (?, ?, ?, ?)",
                ("notify.send", 1 if ok else 0, f"{row['kind']}:{row['id']}", now_text),
            )
        return sent

    def _render(self, row: dict[str, Any]) -> str:
        content = row.get("content") or ""
        payload = loads(content, None)
        if not isinstance(payload, dict):
            return content
        kind = row.get("kind")
        if kind == "reminder":
            return self.app.t(
                "notify.reminder.body",
                title=payload.get("title") or row.get("title") or "",
                when=self.app.t(
                    "notify.reminder.before", minutes=payload.get("offset", 0)
                )
                if payload.get("offset")
                else self.app.t("notify.reminder.now"),
                start=payload.get("start") or "",
                end=payload.get("end") or "",
            )
        return content

    # ------------------------------------------------------------ 模板
    def render_reminder(
        self, principal: Principal, task: dict[str, Any], offset: int, *, tz: str
    ) -> dict[str, Any]:
        when = (
            self.app.t("notify.reminder.before", minutes=offset)
            if offset
            else self.app.t("notify.reminder.now")
        )
        body = self.app.t(
            "notify.reminder.body",
            title=task["title"],
            when=when,
            start=task.get("local_start") or "",
            end=task.get("local_end") or "",
        )
        return {
            "title": self.app.t("notify.reminder.title"),
            "content": body,
            "payload": {
                "task_id": task["id"],
                "offset": offset,
                "start": task.get("local_start"),
                "end": task.get("local_end"),
                "title": task["title"],
                "tz": tz,
            },
        }

    def render_daily_brief(
        self,
        *,
        day: str,
        total: int,
        done: int,
        overdue: int,
        plan_title: str | None,
    ) -> dict[str, Any]:
        overdue_text = (
            self.app.t("notify.brief.overdue", count=overdue) if overdue else ""
        )
        body = self.app.t(
            "notify.brief.body",
            date=day,
            total=total,
            done=done,
            overdue=overdue_text,
            plan=plan_title or self.app.t("notify.brief.no_plan"),
        )
        return {"title": self.app.t("notify.brief.title"), "content": body}

    def render_weekly(
        self, *, start: str, end: str, total: int, done: int, rate: int, minutes: int
    ) -> dict[str, Any]:
        body = self.app.t(
            "notify.weekly.body",
            start=start,
            end=end,
            total=total,
            done=done,
            rate=rate,
            minutes=minutes,
        )
        return {"title": self.app.t("notify.weekly.title"), "content": body}

    def next_occurrence(self, hhmm: str, tz: str, *, base=None):
        """今天/明天的下一次 HH:MM（本地时间）。"""
        from datetime import datetime

        from ..util import parse_hhmm

        clock = parse_hhmm(hhmm)
        now = (base or utcnow()).astimezone(get_tz(tz))
        candidate = now.replace(hour=clock.hour, minute=clock.minute, second=0, microsecond=0)
        if candidate <= now:
            candidate = candidate + timedelta(days=1)
        return candidate


_ = get_tz  # 保持导入（模板函数中延迟导入亦可）
