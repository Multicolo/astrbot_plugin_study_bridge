"""鉴权业务：绑定码、令牌兑换、设备管理。"""

from __future__ import annotations

from typing import Any

from .. import principal as principal_mod
from ..errors import not_found, unauthorized
from ..principal import AttemptLimiter, Principal


class AuthService:
    def __init__(self, app: Any) -> None:
        self.app = app
        # /bind 的错误尝试：同一 QQ 用户 10 分钟内错 5 次 -> 封 10 分钟
        self.bind_limiter = AttemptLimiter(
            max_attempts=5, window_seconds=600, block_seconds=600
        )

    # ------------------------------------------------------------ 绑定码
    async def create_bind_code(self) -> dict[str, Any]:
        return await principal_mod.create_bind_code(
            self.app.db, ttl_seconds=principal_mod.BIND_CODE_TTL_SECONDS
        )

    async def bind_status(self, code: str) -> dict[str, Any]:
        code = (code or "").strip()
        if not code:
            return {"bound": False}
        return await principal_mod.bind_status(self.app.db, code)

    async def exchange(self, code: str, label: str | None = None) -> dict[str, Any]:
        code = (code or "").strip()
        result = await principal_mod.exchange_bind_code(
            self.app.db, code=code, label=label
        )
        if result is None:
            # 统一 401：不区分「码不存在 / 过期 / 已被用」，避免枚举
            raise unauthorized("绑定码无效或已过期")
        token, principal = result
        return {
            "token": token,
            "principal": principal.to_dict(),
            "device_count": await principal_mod.count_active_devices(
                self.app.db, principal.id
            ),
        }

    # ------------------------------------------------------------ QQ 侧绑定
    async def claim_from_qq(
        self, principal: Principal, code: str
    ) -> tuple[str, str]:
        """返回 ``(status, message_key)``；status 见 principal.claim_bind_code。"""
        code = (code or "").strip()
        key = f"qq:{principal.external_id}"
        if self.bind_limiter.blocked(key):
            return "blocked", "cmd.bind.too_many"
        status = await principal_mod.claim_bind_code(
            self.app.db, code=code, principal_id=principal.id
        )
        if status != "ok":
            if self.bind_limiter.hit(key):
                return "blocked", "cmd.bind.too_many"
            return status, {
                "not_found": "cmd.bind.not_found",
                "expired": "cmd.bind.expired",
                "used": "cmd.bind.used",
                "taken": "cmd.bind.taken",
            }.get(status, "cmd.bind.not_found")
        self.bind_limiter.reset(key)
        return "ok", "cmd.bind.ok"

    # ------------------------------------------------------------ 主体信息
    async def me(self, principal: Principal) -> dict[str, Any]:
        devices = await principal_mod.count_active_devices(self.app.db, principal.id)
        return {
            "principal": principal.to_dict(),
            "device_count": devices,
            "binding_mode": "bind_code",
            "can_use_ai": principal.can_use_ai
            and self.app.cfg.get_bool("ai.allow_principal_ai", True),
        }

    async def devices(self, principal: Principal) -> list[dict[str, Any]]:
        return await principal_mod.list_devices(self.app.db, principal.id)

    async def revoke(self, principal: Principal, token_id: str) -> dict[str, Any]:
        ok = await principal_mod.revoke_token(
            self.app.db, principal_id=principal.id, token_id=(token_id or "").strip()
        )
        if not ok:
            raise not_found("设备不存在")
        return {"revoked": True, "token_id": token_id}

    async def unbind_by_label(self, principal: Principal, label: str) -> int:
        return await principal_mod.revoke_by_label(
            self.app.db, principal_id=principal.id, label=(label or "").strip()
        )
