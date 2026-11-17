"""主体解析、令牌、绑定码。

约定：
- ``principal`` 是唯一的「数据归属者」；所有业务表用 ``owner_principal_id`` 指向它。
- 令牌明文只在兑换时返回一次，库里只存 SHA-256。
- 绑定码 6 位、5 分钟、一次性；错误尝试由 ``AttemptLimiter`` 计数。
- 本模块不 import astrbot / aiohttp。
"""

from __future__ import annotations

import hmac
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from .db import Database
from .util import iso, new_bind_code, new_id, new_token, sha256_hex, utcnow

# 绑定码在「等待 QQ 侧认领」阶段没有主体，用空串占位（schema 里 principal_id NOT NULL）
PENDING_PRINCIPAL = ""


@dataclass(slots=True)
class Principal:
    id: str
    kind: str
    external_id: str
    display_name: str | None
    can_use_ai: bool
    created_at: str

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "Principal":
        return cls(
            id=row["id"],
            kind=row["kind"],
            external_id=row["external_id"],
            display_name=row.get("display_name"),
            can_use_ai=bool(row.get("can_use_ai", 1)),
            created_at=row["created_at"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "external_id": self.external_id,
            "display_name": self.display_name,
            "can_use_ai": self.can_use_ai,
            "created_at": self.created_at,
        }


async def get_or_create(
    db: Database,
    *,
    kind: str,
    external_id: str,
    display_name: str | None = None,
) -> Principal:
    row = await db.fetch_one(
        "SELECT * FROM principal WHERE kind = ? AND external_id = ?",
        (kind, external_id),
    )
    if row:
        if display_name and display_name != row.get("display_name"):
            await db.execute(
                "UPDATE principal SET display_name = ? WHERE id = ?",
                (display_name, row["id"]),
            )
            row["display_name"] = display_name
        return Principal.from_row(row)
    pid = new_id()
    now = iso(utcnow())
    await db.execute(
        "INSERT INTO principal (id, kind, external_id, display_name, can_use_ai, created_at) "
        "VALUES (?, ?, ?, ?, 1, ?)",
        (pid, kind, external_id, display_name, now),
    )
    return Principal(
        id=pid,
        kind=kind,
        external_id=external_id,
        display_name=display_name,
        can_use_ai=True,
        created_at=now,
    )


async def get_by_id(db: Database, principal_id: str) -> Principal | None:
    row = await db.fetch_one("SELECT * FROM principal WHERE id = ?", (principal_id,))
    return Principal.from_row(row) if row else None


async def set_can_use_ai(db: Database, principal_id: str, enabled: bool) -> None:
    await db.execute(
        "UPDATE principal SET can_use_ai = ? WHERE id = ?",
        (1 if enabled else 0, principal_id),
    )


# ---------------------------------------------------------------- 令牌


async def issue_token(
    db: Database, *, principal_id: str, label: str | None = None
) -> tuple[str, str]:
    """签发令牌，返回 ``(明文令牌, token_id)``。明文不落库。"""
    token = new_token()
    token_id = new_id()
    await db.execute(
        "INSERT INTO auth_token (id, principal_id, token_hash, label, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (token_id, principal_id, sha256_hex(token), (label or "").strip(), iso(utcnow())),
    )
    return token, token_id


async def resolve_token(db: Database, token: str) -> Principal | None:
    """校验令牌：不存在/已吊销返回 None；成功则刷新 last_used_at。"""
    if not token or len(token) < 16:
        return None
    digest = sha256_hex(token)
    row = await db.fetch_one("SELECT * FROM auth_token WHERE token_hash = ?", (digest,))
    if not row:
        return None
    # 哈希索引查出来后仍做一次常量时间比较，避免按字节泄漏信息
    if not hmac.compare_digest(str(row["token_hash"]), digest):
        return None
    if row.get("revoked_at"):
        return None
    principal = await get_by_id(db, row["principal_id"])
    if principal is None:
        return None
    await db.execute(
        "UPDATE auth_token SET last_used_at = ? WHERE id = ?",
        (iso(utcnow()), row["id"]),
    )
    return principal


async def list_devices(db: Database, principal_id: str) -> list[dict[str, Any]]:
    rows = await db.fetch_all(
        "SELECT id, label, created_at, last_used_at, revoked_at FROM auth_token "
        "WHERE principal_id = ? ORDER BY created_at DESC",
        (principal_id,),
    )
    for row in rows:
        row["revoked"] = bool(row.get("revoked_at"))
    return rows


async def count_active_devices(db: Database, principal_id: str) -> int:
    value = await db.scalar(
        "SELECT COUNT(*) FROM auth_token WHERE principal_id = ? AND revoked_at IS NULL",
        (principal_id,),
        default=0,
    )
    return int(value)


async def revoke_token(db: Database, *, principal_id: str, token_id: str) -> bool:
    """吊销某设备令牌；不属于该主体时返回 False（上层转 404，不泄露存在性）。"""
    row = await db.fetch_one(
        "SELECT id FROM auth_token WHERE id = ? AND principal_id = ? AND revoked_at IS NULL",
        (token_id, principal_id),
    )
    if not row:
        return False
    await db.execute(
        "UPDATE auth_token SET revoked_at = ? WHERE id = ?", (iso(utcnow()), token_id)
    )
    return True


async def revoke_by_label(db: Database, *, principal_id: str, label: str) -> int:
    rows = await db.fetch_all(
        "SELECT id FROM auth_token WHERE principal_id = ? AND revoked_at IS NULL AND label = ?",
        (principal_id, label),
    )
    if not rows:
        return 0
    now = iso(utcnow())
    for row in rows:
        await db.execute("UPDATE auth_token SET revoked_at = ? WHERE id = ?", (now, row["id"]))
    return len(rows)


# ---------------------------------------------------------------- 绑定码

BIND_CODE_TTL_SECONDS = 300


async def create_bind_code(db: Database, *, ttl_seconds: int = BIND_CODE_TTL_SECONDS) -> dict[str, Any]:
    """创建一个等待认领的绑定码。会清理自己的过期码，避免表无限增长。"""
    now = utcnow()
    await db.execute(
        "DELETE FROM bind_code WHERE expires_at < ? OR used_at IS NOT NULL",
        (iso(now - timedelta(days=1)),),
    )
    for _ in range(12):
        code = new_bind_code()
        exists = await db.fetch_one("SELECT code FROM bind_code WHERE code = ?", (code,))
        if exists:
            continue
        expires = now + timedelta(seconds=ttl_seconds)
        await db.execute(
            "INSERT INTO bind_code (code, principal_id, expires_at, used_at, attempts) "
            "VALUES (?, ?, ?, NULL, 0)",
            (code, PENDING_PRINCIPAL, iso(expires)),
        )
        return {"code": code, "expires_at": iso(expires), "expires_in": ttl_seconds}
    raise RuntimeError("无法生成唯一绑定码")  # pragma: no cover - 概率极低


async def get_bind_code(db: Database, code: str) -> dict[str, Any] | None:
    return await db.fetch_one("SELECT * FROM bind_code WHERE code = ?", (code,))


def code_is_expired(row: dict[str, Any]) -> bool:
    from .util import parse_iso

    expires = parse_iso(row.get("expires_at"))
    return expires is None or expires <= utcnow()


async def bind_status(db: Database, code: str) -> dict[str, Any]:
    """免鉴权接口用：只回答「有没有被认领」，不泄露任何主体信息。"""
    row = await get_bind_code(db, code)
    if not row:
        return {"bound": False}
    if code_is_expired(row):
        return {"bound": False}
    return {"bound": bool(row["principal_id"]) and not row.get("used_at")}


async def claim_bind_code(db: Database, *, code: str, principal_id: str) -> str:
    """QQ 侧 ``/bind`` 调用：把待认领的码绑定到主体。

    返回 ``ok`` / ``not_found`` / ``expired`` / ``used`` / ``taken``。
    """
    row = await get_bind_code(db, code)
    if not row:
        return "not_found"
    if row.get("used_at"):
        return "used"
    if code_is_expired(row):
        return "expired"
    if row["principal_id"] and row["principal_id"] != principal_id:
        return "taken"
    await db.execute(
        "UPDATE bind_code SET principal_id = ? WHERE code = ?", (principal_id, code)
    )
    return "ok"


async def exchange_bind_code(db: Database, *, code: str, label: str | None = None) -> tuple[str, Principal] | None:
    """App 侧兑换：一次性，成功后码作废。返回 ``(token, principal)``。"""
    row = await get_bind_code(db, code)
    if not row or row.get("used_at") or not row["principal_id"]:
        return None
    if code_is_expired(row):
        return None
    principal = await get_by_id(db, row["principal_id"])
    if principal is None:
        return None
    token, _token_id = await issue_token(db, principal_id=principal.id, label=label)
    await db.execute(
        "UPDATE bind_code SET used_at = ? WHERE code = ?", (iso(utcnow()), code)
    )
    return token, principal


# ---------------------------------------------------------------- 失败计数


class AttemptLimiter:
    """进程内滑动窗口限流（单实例部署足够；多实例请改用外部存储）。"""

    def __init__(self, *, max_attempts: int, window_seconds: float, block_seconds: float) -> None:
        self.max_attempts = max_attempts
        self.window = window_seconds
        self.block = block_seconds
        self._hits: dict[str, list[float]] = {}
        self._blocked_until: dict[str, float] = {}

    def blocked(self, key: str, *, now: float | None = None) -> bool:
        now = now if now is not None else time.monotonic()
        until = self._blocked_until.get(key)
        if until is None:
            return False
        if until <= now:
            self._blocked_until.pop(key, None)
            self._hits.pop(key, None)
            return False
        return True

    def hit(self, key: str, *, now: float | None = None) -> bool:
        """记一次失败；返回 True 表示本次触发了封禁。"""
        now = now if now is not None else time.monotonic()
        hits = [t for t in self._hits.get(key, []) if now - t <= self.window]
        hits.append(now)
        self._hits[key] = hits
        if len(hits) >= self.max_attempts:
            self._blocked_until[key] = now + self.block
            return True
        return False

    def reset(self, key: str) -> None:
        self._hits.pop(key, None)
        self._blocked_until.pop(key, None)

    def retry_after(self, key: str, *, now: float | None = None) -> int:
        now = now if now is not None else time.monotonic()
        until = self._blocked_until.get(key, 0)
        return max(0, int(until - now))


class RateLimiter:
    """固定窗口计数器（每 IP 每分钟 N 次）。"""

    def __init__(self, *, limit: int, window_seconds: float = 60.0) -> None:
        self.limit = max(1, limit)
        self.window = window_seconds
        self._buckets: dict[str, tuple[float, int]] = {}

    def allow(self, key: str, *, now: float | None = None) -> tuple[bool, int]:
        now = now if now is not None else time.monotonic()
        start, count = self._buckets.get(key, (now, 0))
        if now - start >= self.window:
            start, count = now, 0
        count += 1
        self._buckets[key] = (start, count)
        remaining = max(0, self.limit - count)
        return count <= self.limit, remaining
