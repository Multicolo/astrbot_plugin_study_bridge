"""通用 tool 映射适配器：通过 AstrBot 的 LLM 工具注册表调用第三方记忆工具。

零侵入要点：
- 只读工具注册表（``context.get_llm_tool_manager()``），不改别人的表、不 patch；
- 直接调用工具函数（``tool.handler``），**不经过模型**；
- 工具不存在/签名不符/抛异常 → 全部 try/except，``probe()`` 返回 False 由上层降级。
"""

from __future__ import annotations

import inspect
from typing import Any

from .base import AdapterStatus, MemoryAdapter


class GenericToolAdapter(MemoryAdapter):
    name = "generic_tool"
    version = "1"
    supports_delete = False
    supports_export = False

    def __init__(self, app: Any) -> None:
        super().__init__(app)
        cfg = app.cfg
        self.write_tool = cfg.get_str("memory.generic_tool.write_tool", "remember")
        self.search_tool = cfg.get_str("memory.generic_tool.search_tool", "recall")
        self.write_arg = cfg.get_str("memory.generic_tool.write_arg", "text")
        self.search_arg = cfg.get_str("memory.generic_tool.search_arg", "query")
        self.delete_tool = cfg.get_str("memory.generic_tool.delete_tool", "")
        self._write = None
        self._search = None
        self._delete = None

    # ------------------------------------------------------------ 探测
    async def probe(self) -> bool:
        try:
            manager = self.app.context.get_llm_tool_manager() if self.app.context else None
            if manager is None:
                self.status = AdapterStatus(
                    name=self.name,
                    ok=False,
                    reason="当前无 AstrBot 工具注册表",
                    version=self.version,
                )
                return False
            self._write = manager.get_func(self.write_tool)
            self._search = manager.get_func(self.search_tool) if self.search_tool else None
            self._delete = manager.get_func(self.delete_tool) if self.delete_tool else None
            if self._write is None:
                self.status = AdapterStatus(
                    name=self.name,
                    ok=False,
                    reason=f"未找到写入工具 {self.write_tool}",
                    version=self.version,
                )
                return False
            self.supports_delete = self._delete is not None
            self.status = AdapterStatus(
                name=self.name,
                ok=True,
                reason=f"已映射工具 {self.write_tool} / {self.search_tool or '-'}",
                version=self.version,
                extra={"write_tool": self.write_tool, "search_tool": self.search_tool},
            )
            return True
        except Exception as exc:  # noqa: BLE001 - 探测失败必须降级
            self.status = AdapterStatus(
                name=self.name, ok=False, reason=f"探测异常：{exc}", version=self.version
            )
            return False

    # ------------------------------------------------------------ 调用
    async def _call(self, tool: Any, kwargs: dict[str, Any]) -> Any:
        """直接调工具函数：兼容 ``handler(event, **kw)`` 与 ``handler(**kw)``。"""
        handler = getattr(tool, "handler", None)
        if handler is None:
            raise RuntimeError("工具没有 handler，无法直接调用")
        event = self.app.current_event()
        attempts: list[Any] = []
        if event is not None:
            attempts.append(lambda: handler(event, **kwargs))
        attempts.append(lambda: handler(**kwargs))
        last_error: Exception | None = None
        for build in attempts:
            try:
                result = build()
                if inspect.isasyncgen(result):
                    last: Any = None
                    async for item in result:
                        last = item
                    return last
                if inspect.isawaitable(result):
                    return await result
                return result
            except TypeError as exc:
                last_error = exc
                continue
        if last_error:
            raise last_error
        raise RuntimeError("工具调用失败")

    async def upsert(
        self,
        *,
        source_ref: str,
        content: str,
        tags: list[str] | None = None,
        importance: int = 3,
    ) -> str:
        if self._write is None:
            return ""
        result = await self._call(self._write, {self.write_arg: content})
        text = str(result)[:200] if result is not None else ""
        return text or source_ref

    async def delete(self, source_ref: str) -> bool:
        if self._delete is None:
            return False
        try:
            await self._call(self._delete, {self.search_arg: source_ref})
            return True
        except Exception:  # noqa: BLE001
            return False

    async def export(self, cursor: str | None = None) -> tuple[list[dict[str, Any]], str | None]:
        return [], None

    async def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        if self._search is None:
            return []
        try:
            result = await self._call(self._search, {self.search_arg: query})
        except Exception:  # noqa: BLE001
            return []
        entries: list[dict[str, Any]] = []
        raw = result
        if isinstance(raw, str):
            entries = [{"content": raw}]
        elif isinstance(raw, dict):
            for key in ("results", "items", "memories", "data"):
                if isinstance(raw.get(key), list):
                    raw = raw[key]
                    break
            if isinstance(raw, dict):
                entries = [raw]
        if isinstance(raw, list):
            for item in raw[:limit]:
                if isinstance(item, dict):
                    entries.append(
                        {
                            "content": item.get("content")
                            or item.get("text")
                            or item.get("memory")
                            or str(item)[:200],
                            "tags": item.get("tags") or [],
                            "importance": item.get("importance"),
                            "remote_ref": str(item.get("id") or item.get("memory_id") or ""),
                        }
                    )
                elif isinstance(item, str):
                    entries.append({"content": item})
        return entries[:limit]
