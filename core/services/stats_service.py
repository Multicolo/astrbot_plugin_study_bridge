"""统计业务：概览、每日趋势、计划进度、纯文本报表（供 /report 用）。"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from ..errors import invalid
from ..principal import Principal
from ..util import get_tz, iso, local_date, parse_iso

RANGES = ("today", "week", "month")


class StatsService:
    def __init__(self, app: Any) -> None:
        self.app = app

    def _range_days(self, range_key: str, tz: str) -> tuple[date, date]:
        today = local_date(tz)
        if range_key == "today":
            return today, today
        if range_key == "week":
            monday = today - timedelta(days=today.weekday())
            return monday, monday + timedelta(days=6)
        if range_key == "month":
            first = today.replace(day=1)
            next_month = (first + timedelta(days=32)).replace(day=1)
            return first, next_month - timedelta(days=1)
        raise invalid(f"range 只能是 {RANGES}")

    async def _rows(self, principal: Principal, start: date, end: date, tz: str) -> list[dict[str, Any]]:
        from datetime import datetime

        bounds_start = datetime.combine(start, datetime.min.time(), tzinfo=get_tz(tz))
        bounds_end = datetime.combine(end + timedelta(days=1), datetime.min.time(), tzinfo=get_tz(tz))
        return await self.app.db.fetch_all(
            "SELECT * FROM task WHERE owner_principal_id = ? AND deleted_at IS NULL "
            "AND COALESCE(start_at, created_at) >= ? AND COALESCE(start_at, created_at) < ?",
            (principal.id, iso(bounds_start), iso(bounds_end)),
        )

    async def overview(self, principal: Principal, range_key: str = "week") -> dict[str, Any]:
        if range_key not in RANGES:
            raise invalid(f"range 只能是 {RANGES}")
        tz = await self.app.settings.get_tz(principal)
        start, end = self._range_days(range_key, tz)
        rows = await self._rows(principal, start, end, tz)
        total = len(rows)
        done = sum(1 for row in rows if row["status"] == "done")
        minutes = 0
        for row in rows:
            if row["status"] != "done":
                continue
            begin, finish = parse_iso(row.get("start_at")), parse_iso(row.get("end_at"))
            if begin and finish:
                minutes += max(0, int((finish - begin).total_seconds() // 60))
        sources: dict[str, int] = {}
        for row in rows:
            sources[row.get("source") or "manual"] = sources.get(row.get("source") or "manual", 0) + 1
        daily = await self.daily(principal, start.isoformat(), end.isoformat())
        return {
            "range": range_key,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "total": total,
            "done": done,
            "rate": int(round(done * 100 / total)) if total else 0,
            "minutes": minutes,
            "sources": sources,
            "daily": daily,
        }

    async def daily(
        self, principal: Principal, date_from: str | None = None, date_to: str | None = None
    ) -> list[dict[str, Any]]:
        tz = await self.app.settings.get_tz(principal)
        today = local_date(tz)
        try:
            start = date.fromisoformat(date_from) if date_from else today - timedelta(days=6)
            end = date.fromisoformat(date_to) if date_to else today
        except ValueError:
            raise invalid("日期格式应为 YYYY-MM-DD") from None
        if end < start:
            raise invalid("to 不能早于 from")
        if (end - start).days > 92:
            raise invalid("查询区间不能超过 92 天")
        rows = await self._rows(principal, start, end, tz)
        buckets: dict[str, dict[str, Any]] = {}
        cursor = start
        while cursor <= end:
            buckets[cursor.isoformat()] = {"date": cursor.isoformat(), "total": 0, "done": 0, "minutes": 0}
            cursor += timedelta(days=1)
        zone = get_tz(tz)
        for row in rows:
            begin = parse_iso(row.get("start_at")) or parse_iso(row.get("created_at"))
            if begin is None:
                continue
            key = begin.astimezone(zone).date().isoformat()
            bucket = buckets.get(key)
            if bucket is None:
                continue
            bucket["total"] += 1
            if row["status"] == "done":
                bucket["done"] += 1
                finish = parse_iso(row.get("end_at"))
                if finish and begin:
                    bucket["minutes"] += max(0, int((finish - begin).total_seconds() // 60))
        return list(buckets.values())

    async def plan_progress(self, principal: Principal) -> list[dict[str, Any]]:
        return await self.app.plans.progress(principal)

    async def text_report(self, principal: Principal, range_key: str = "week") -> str:
        """``/report`` 的纯文本报表（含字符进度条）。"""
        data = await self.overview(principal, range_key)
        label = {"today": "今日", "week": "本周", "month": "本月"}.get(range_key, range_key)
        plans = await self.plan_progress(principal)
        plan_lines = []
        for plan in plans[:5]:
            total = plan["total"] or 0
            done = plan["done"]
            filled = int(round((done / total) * 10)) if total else 0
            bar = "█" * filled + "░" * (10 - filled)
            plan_lines.append(
                self.app.t(
                    "cmd.report.plan_bar",
                    title=plan["title"],
                    bar=bar,
                    done=done,
                    total=total,
                )
            )
        if not data["total"] and not plan_lines:
            return self.app.t("cmd.report.empty")
        return self.app.t(
            "cmd.report.title",
            range=label,
            start=data["start"],
            end=data["end"],
            done=data["done"],
            total=data["total"],
            rate=data["rate"],
            minutes=data["minutes"],
            plans="\n".join(plan_lines) if plan_lines else "—",
        )
