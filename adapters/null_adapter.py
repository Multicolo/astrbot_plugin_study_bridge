"""兜底适配器：没有装任何记忆插件时使用。

- ``probe()`` 恒 True：插件状态必须是「正常可用」，不是「异常」；
- 写入是空操作并标记 ``degraded``，数据仍完整保存在本插件自己的 SQLite 里；
- ``delete`` 返回 True：本地即唯一事实源，没有远端需要清理。
"""

from __future__ import annotations

from typing import Any

from .base import AdapterStatus, MemoryAdapter


class NullAdapter(MemoryAdapter):
    name = "none"
    version = "builtin"
    supports_delete = True
    supports_export = False

    def __init__(self, app: Any) -> None:
        super().__init__(app)
        self.degraded = True

    async def probe(self) -> bool:
        self.status = AdapterStatus(
            name=self.name,
            ok=True,
            reason="未检测到可写的第三方记忆插件，记忆保存在本插件本地库（正常状态）",
            version=self.version,
            degraded=True,
        )
        return True

    async def upsert(
        self,
        *,
        source_ref: str,
        content: str,
        tags: list[str] | None = None,
        importance: int = 3,
    ) -> str:
        return ""

    async def delete(self, source_ref: str) -> bool:
        return True

    async def export(self, cursor: str | None = None) -> tuple[list[dict[str, Any]], str | None]:
        return [], None
