"""适配器工厂：按配置顺序探测，首个可用者生效。"""

from __future__ import annotations

from typing import Any

from .base import AdapterStatus, MemoryAdapter
from .generic_file import FileAdapter
from .generic_tool import GenericToolAdapter
from .livingmemory import LivingMemoryAdapter
from .null_adapter import NullAdapter

ADAPTER_TYPES = {
    "generic_tool": GenericToolAdapter,
    "livingmemory": LivingMemoryAdapter,
    "file": FileAdapter,
    "none": NullAdapter,
}

__all__ = [
    "MemoryAdapter",
    "AdapterStatus",
    "FileAdapter",
    "GenericToolAdapter",
    "LivingMemoryAdapter",
    "NullAdapter",
    "ADAPTER_TYPES",
]


class MemoryManager:
    """负责探测与持有当前生效的适配器。"""

    def __init__(self, app: Any) -> None:
        self.app = app
        self.active: MemoryAdapter = NullAdapter(app)
        self.attempts: list[dict[str, Any]] = []
        self._big_lock = None

    async def start(self) -> MemoryAdapter:
        order = [str(item) for item in self.app.cfg.get_list("memory.adapter_order", ["none"])]
        if not order:
            order = ["none"]
        self.attempts = []
        for name in order:
            cls = ADAPTER_TYPES.get(name)
            if cls is None:
                self.attempts.append(
                    {"name": name, "ok": False, "reason": "未知适配器（配置拼写错误？）"}
                )
                continue
            adapter = cls(self.app)
            try:
                ok = await adapter.probe()
            except Exception as exc:  # noqa: BLE001 - 适配器异常一律降级
                ok = False
                self.app.logger.warning("适配器 %s 探测异常：%s", name, exc)
            self.attempts.append(adapter.describe())
            if ok:
                self.active = adapter
                self.app.logger.info("记忆适配器已启用：%s", name)
                return adapter
        self.active = NullAdapter(self.app)
        await self.active.probe()
        self.attempts.append(self.active.describe())
        return self.active

    def describe(self) -> dict[str, Any]:
        return {
            "active": self.active.describe(),
            "attempts": self.attempts,
            "sync_mode": self.app.cfg.get_str("memory.sync_mode", "upload_only"),
        }
