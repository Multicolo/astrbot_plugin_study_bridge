"""按主体隔离的个人设置（时区、早报时间、提醒偏移、默认时长）。"""

from __future__ import annotations

import re
from typing import Any

from ..errors import invalid
from ..principal import Principal
from ..util import iso, parse_hhmm, utcnow

# key -> (默认值来源, 说明)
DEFAULT_OFFSETS = "30,0"
DEFAULT_DURATION = 30

ALLOWED_KEYS = ("tz", "brief", "nudge", "offsets", "duration")


class SettingsService:
    def __init__(self, app: Any) -> None:
        self.app = app

    async def _raw(self, principal: Principal) -> dict[str, str]:
        rows = await self.app.db.fetch_all(
            "SELECT key, value FROM setting WHERE owner_principal_id = ?", (principal.id,)
        )
        return {row["key"]: row["value"] for row in rows}

    async def get_all(self, principal: Principal) -> dict[str, Any]:
        raw = await self._raw(principal)
        cfg = self.app.cfg
        return {
            "tz": raw.get("tz") or cfg.timezone,
            "brief": raw.get("brief") or cfg.get_str("notify.early_brief_time", "08:00"),
            "nudge": raw.get("nudge") or cfg.get_str("notify.plan_nudge_time", "21:00"),
            "offsets": raw.get("offsets") or ",".join(str(x) for x in cfg.get_list("notify.default_remind_offsets", [30, 0])),
            "duration": int(raw.get("duration") or DEFAULT_DURATION),
            "weekly_report_weekday": raw.get("weekly_report_weekday") or str(cfg.get_int("notify.weekly_report_weekday", 1)),
            "weekly_report_time": raw.get("weekly_report_time") or cfg.get_str("notify.weekly_report_time", "09:00"),
        }

    async def get_tz(self, principal: Principal) -> str:
        return (await self.get_all(principal))["tz"]

    async def set(self, principal: Principal, key: str, value: str) -> dict[str, Any]:
        key = (key or "").strip().lower()
        value = (value or "").strip()
        if key not in ALLOWED_KEYS:
            raise invalid(f"未知设置项：{key}")
        if key == "tz":
            from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

            try:
                ZoneInfo(value)
            except (ZoneInfoNotFoundError, ValueError, OSError):
                raise invalid(f"时区不存在：{value}（例：Asia/Shanghai）") from None
            normalized = value
        elif key in ("brief", "nudge"):
            if not re.fullmatch(r"\d{1,2}:\d{2}", value):
                raise invalid("时间格式应为 HH:MM")
            parse_hhmm(value)  # 校验范围
            normalized = "%02d:%02d" % (parse_hhmm(value).hour, parse_hhmm(value).minute)
        elif key == "offsets":
            try:
                values = [int(part) for part in value.replace(" ", "").split(",") if part != ""]
            except ValueError:
                raise invalid("提醒偏移应为逗号分隔的分钟数，例：30,0") from None
            if not values or any(v < 0 or v > 1440 for v in values):
                raise invalid("提醒偏移需在 0~1440 分钟之间")
            normalized = ",".join(str(v) for v in sorted(set(values), reverse=True))
        else:  # duration
            if not value.isdigit() or not (5 <= int(value) <= 600):
                raise invalid("默认时长需为 5~600 的整数分钟")
            normalized = str(int(value))
        now = iso(utcnow())
        await self.app.db.execute(
            "INSERT INTO setting (owner_principal_id, key, value, updated_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(owner_principal_id, key) DO UPDATE SET value = excluded.value, "
            "updated_at = excluded.updated_at",
            (principal.id, key, normalized, now),
        )
        return {"key": key, "value": normalized, "settings": await self.get_all(principal)}

    async def offsets_list(self, principal: Principal) -> list[int]:
        values = (await self.get_all(principal))["offsets"]
        result = []
        for part in str(values).replace(" ", "").split(","):
            if part.isdigit():
                result.append(int(part))
        return result or [30, 0]

    async def put_raw(self, principal: Principal, updates: dict[str, Any]) -> dict[str, Any]:
        """HTTP ``PUT /settings`` 用：批量写入，返回最新全量设置。"""
        for key, value in (updates or {}).items():
            if str(key).lower() in ALLOWED_KEYS:
                await self.set(principal, str(key), "" if value is None else str(value))
        return await self.get_all(principal)
