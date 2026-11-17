"""记忆适配器抽象基类。

契约（见 docs/MEMORY_SYNC.md）：
- ``probe()`` 必须**永不抛异常**，只回 bool；不可用时由调用方降级到下一个适配器。
- ``upsert`` 幂等：同一个 ``source_ref`` 重复写入必须只留一条（由适配器或远端保证）。
- ``delete`` 返回 False 表示「远端不支持删除」，上层会标 ``orphan`` 并如实展示。
- ``export`` 返回 ``(entries, next_cursor)``；不支持导出就返回 ``([], None)``。

所有方法都必须 try/except 兜底：适配器失败绝不能影响插件主流程。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AdapterStatus:
    name: str
    ok: bool
    reason: str = ""
    version: str = ""
    degraded: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "ok": self.ok,
            "reason": self.reason,
            "version": self.version,
            "degraded": self.degraded,
            **self.extra,
        }


class MemoryAdapter(ABC):
    name: str = "base"
    version: str = "0"
    #: 远端是否支持删除（决定删除传播策略）
    supports_delete: bool = False
    #: 远端是否支持导出（决定下行同步）
    supports_export: bool = False

    def __init__(self, app: Any) -> None:
        self.app = app
        self.status = AdapterStatus(name=self.name, ok=False, reason="未探测")

    @abstractmethod
    async def probe(self) -> bool:
        """探测可用性；True 表示后续 upsert 可以成功。"""

    @abstractmethod
    async def upsert(
        self,
        *,
        source_ref: str,
        content: str,
        tags: list[str] | None = None,
        importance: int = 3,
    ) -> str:
        """写入/覆盖一条记忆，返回远端引用（空串表示没有远端）。"""

    @abstractmethod
    async def delete(self, source_ref: str) -> bool:
        """按 source_ref 删除远端记忆；返回是否确认删除成功。"""

    @abstractmethod
    async def export(self, cursor: str | None = None) -> tuple[list[dict[str, Any]], str | None]:
        """增量导出远端记忆。"""

    async def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """可选的检索能力，用于注入与对账；默认不支持。"""
        return []

    def describe(self) -> dict[str, Any]:
        return self.status.to_dict()
