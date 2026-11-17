"""通用小工具：时间、JSON、ID、哈希、token 估算。

设计约束：
- 时间一律以 **UTC ISO8601 字符串**（带 +00:00）入库；
- 展示/计算「今天」时按主体时区换算；
- 本模块不 import astrbot，也不 import aiohttp，方便单测。
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import secrets
import unicodedata
import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

UTC = timezone.utc


# ---------------------------------------------------------------- 时间

def utcnow() -> datetime:
    return datetime.now(tz=UTC)


def utcnow_iso() -> str:
    """当前 UTC 时间，形如 ``2026-11-17T07:57:01.123456+00:00``。"""
    return utcnow().isoformat()


def iso(dt: datetime) -> str:
    """把 datetime 规范化为 UTC ISO8601 字符串（保留微秒，便于判断"是否改过"）。"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat()


def parse_iso(value: str | datetime | None) -> datetime | None:
    """解析 ISO8601；容忍 ``Z`` 结尾与只有日期的情况。解析失败返回 None。"""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        try:
            dt = datetime.strptime(text[:10], "%Y-%m-%d")
        except ValueError:
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def get_tz(name: str | ZoneInfo | None) -> ZoneInfo:
    """取时区；非法名字回退 UTC，绝不抛异常。也接受已实例化的 ZoneInfo。"""
    if isinstance(name, ZoneInfo):
        return name
    if name:
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError, OSError, TypeError):
            pass
    return ZoneInfo("UTC")


def local_now(tz_name: str | ZoneInfo | None) -> datetime:
    return utcnow().astimezone(get_tz(tz_name))


def local_date(tz_name: str | ZoneInfo | None) -> date:
    return local_now(tz_name).date()


def day_bounds_utc(day: date, tz_name: str | None) -> tuple[str, str]:
    """某本地日期 [00:00, 次日 00:00) 对应的 UTC ISO 区间（左闭右开）。"""
    tz = get_tz(tz_name)
    start = datetime.combine(day, time.min, tzinfo=tz)
    end = start + timedelta(days=1)
    return iso(start), iso(end)


def local_day_of(dt: datetime | None, tz_name: str | None) -> date | None:
    if dt is None:
        return None
    return dt.astimezone(get_tz(tz_name)).date()


def is_date_text(text: str) -> bool:
    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", (text or "").strip()))


def parse_hhmm(text: str, default: time = time(8, 0)) -> time:
    """解析 ``H:MM`` / ``HH:MM``，失败返回 default。"""
    m = re.fullmatch(r"\s*(\d{1,2})\s*:\s*(\d{2})\s*", text or "")
    if not m:
        return default
    hour, minute = int(m.group(1)), int(m.group(2))
    if 0 <= hour <= 23 and 0 <= minute <= 59:
        return time(hour, minute)
    return default


def human_duration(minutes: int) -> str:
    minutes = int(minutes or 0)
    if minutes < 60:
        return f"{minutes} 分钟"
    hours, rest = divmod(minutes, 60)
    if rest == 0:
        return f"{hours} 小时"
    return f"{hours} 小时 {rest} 分钟"


# ---------------------------------------------------------------- JSON / 杂项

def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def loads(text: Any, default: Any = None) -> Any:
    if text is None or text == "":
        return default
    if isinstance(text, (dict, list, int, float, bool)):
        return text
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return default


def new_id() -> str:
    return uuid.uuid4().hex


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def new_token() -> str:
    """32 字节随机令牌（URL-safe，无 padding）。"""
    return secrets.token_urlsafe(32)


def new_bind_code() -> str:
    """6 位数字绑定码（首位可为 0，安全随机）。"""
    return f"{secrets.randbelow(1_000_000):06d}"


def norm_text(text: str) -> str:
    """归一化文本用于相似度比较：全角转半角、去标点空白、小写。"""
    text = unicodedata.normalize("NFKC", text or "")
    kept = []
    for char in text:
        category = unicodedata.category(char)
        # 保留字母/数字/组合符号/CJK；去掉标点、空格、符号
        if category[0] in ("L", "N", "M"):
            kept.append(char)
    return "".join(kept).lower()


def similarity(a: str, b: str) -> float:
    """轻量相似度（字符二元组 Jaccard），避免引入额外依赖。"""
    na, nb = norm_text(a), norm_text(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    ga = {na[i : i + 2] for i in range(max(1, len(na) - 1))}
    gb = {nb[i : i + 2] for i in range(max(1, len(nb) - 1))}
    if not ga or not gb:
        return 0.0
    inter = len(ga & gb)
    return inter / math.sqrt(len(ga) * len(gb))


def estimate_tokens(text: str) -> int:
    """粗略 token 估算：CJK 每字 1 token，其余按 4 字符 1 token。"""
    if not text:
        return 0
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    return int(cjk + (len(text) - cjk) / 4) + 1


def clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))
