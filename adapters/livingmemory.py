"""LivingMemory 适配器（可选，零侵入）。

已验证版本：**2.13.0**（`metadata.yaml` `version: 2.13.0`，仓库 HEAD 2026-11-17）。

写入路径（P1）：插件的 ``initializer.memory_engine.add_memory(...)``。
- 该入口也是 LivingMemory 自己的 Page API 使用的入口
  （``core/page_api.py:735``），因此属于「稳定可用的公开面」；
- ``initializer`` 不是下划线属性，但仍属实现细节 → 按红线 6 处理：
  ``getattr`` + 版本白名单 + ``try/except`` + 文档标注；
- 版本不符或结构不存在 → ``probe()`` False + WARN，由上层降级，不影响启动。

删除路径：``memory_engine.delete_memory(int(doc_id))``，返回值即是否删除成功；
不支持时返回 False，上层标 ``orphan`` 并在 App 明示。
"""

from __future__ import annotations

from typing import Any

from .base import AdapterStatus, MemoryAdapter

PLUGIN_NAME = "astrbot_plugin_livingmemory"
SUPPORTED_VERSIONS = {"2.13.0"}
#: 已知兼容的 AstrBot 版本区间（与插件 metadata 的 astrbot_version 对齐）
MIN_ASTRBOT = "4.24.2"


class LivingMemoryAdapter(MemoryAdapter):
    name = "livingmemory"
    version = SUPPORTED_VERSIONS.copy().pop()
    supports_delete = True
    supports_export = False

    def __init__(self, app: Any) -> None:
        super().__init__(app)
        self._engine: Any = None
        self._plugin: Any = None
        self._remote_version: str | None = None
        self.allow_private = app.cfg.get_bool("memory.livingmemory.allow_private_attrs", True)
        self.persona_id = app.cfg.get_str("memory.livingmemory.persona_id", "") or None

    # ------------------------------------------------------------ 探测
    async def probe(self) -> bool:
        try:
            ctx = self.app.context
            if ctx is None:
                self.status = AdapterStatus(
                    name=self.name, ok=False, reason="当前无 AstrBot Context", version=self.version
                )
                return False
            metadata = ctx.get_registered_star(PLUGIN_NAME)
            if metadata is None or getattr(metadata, "star_cls", None) is None:
                self.status = AdapterStatus(
                    name=self.name,
                    ok=False,
                    reason=f"未安装 {PLUGIN_NAME}",
                    version=self.version,
                )
                return False
            self._plugin = metadata.star_cls
            self._remote_version = str(getattr(metadata, "version", "") or "")
            if self._remote_version not in SUPPORTED_VERSIONS:
                self.app.logger.warning(
                    "LivingMemory 版本 %s 不在已验证列表 %s 内，降级为不可写",
                    self._remote_version,
                    sorted(SUPPORTED_VERSIONS),
                )
                self.status = AdapterStatus(
                    name=self.name,
                    ok=False,
                    reason=f"版本不兼容：{self._remote_version}（已验证 {self.version}）",
                    version=self.version,
                )
                return False
            engine = self._find_engine()
            if engine is None:
                self.status = AdapterStatus(
                    name=self.name,
                    ok=False,
                    reason="未找到 memory_engine（插件未完成初始化或结构变化）",
                    version=self.version,
                )
                return False
            if not hasattr(engine, "add_memory") or not hasattr(engine, "delete_memory"):
                self.status = AdapterStatus(
                    name=self.name,
                    ok=False,
                    reason="memory_engine 缺少 add_memory / delete_memory",
                    version=self.version,
                )
                return False
            self._engine = engine
            self.status = AdapterStatus(
                name=self.name,
                ok=True,
                reason=f"已连接 {PLUGIN_NAME} {self._remote_version}",
                version=self.version,
                extra={"remote_version": self._remote_version},
            )
            return True
        except Exception as exc:  # noqa: BLE001 - 探测失败必须降级
            self.status = AdapterStatus(
                name=self.name, ok=False, reason=f"探测异常：{exc}", version=self.version
            )
            return False

    def _find_engine(self) -> Any:
        """按「公开优先」顺序找记忆引擎。"""
        candidates = (
            ("initializer", "memory_engine"),
            ("memory_engine", None),
            ("_initializer", "memory_engine"),
        )
        for first, second in candidates:
            if not hasattr(self._plugin, first):
                continue
            value = getattr(self._plugin, first, None)
            if value is None:
                continue
            if second is None:
                if hasattr(value, "add_memory"):
                    return value
                continue
            if not self.allow_private and first.startswith("_"):
                continue
            engine = getattr(value, "memory_engine", None)
            if engine is not None:
                return engine
        return None

    # ------------------------------------------------------------ 写入
    async def upsert(
        self,
        *,
        source_ref: str,
        content: str,
        tags: list[str] | None = None,
        importance: int = 3,
    ) -> str:
        if self._engine is None:
            return ""
        try:
            memory_id = await self._engine.add_memory(
                content,
                session_id=self._session_tag(source_ref),
                persona_id=self.persona_id,
                importance=_map_importance(importance),
                metadata={
                    "topics": list(tags or [])[:5],
                    "source_ref": source_ref,
                    "origin": "astrbot_plugin_study_bridge",
                },
            )
            return str(memory_id)
        except Exception as exc:  # noqa: BLE001
            self.app.logger.warning("LivingMemory 写入失败 source_ref=%s: %s", source_ref, exc)
            return ""

    async def delete(self, source_ref: str) -> bool:
        if self._engine is None or not source_ref.isdigit():
            return False
        try:
            return bool(await self._engine.delete_memory(int(source_ref)))
        except Exception as exc:  # noqa: BLE001
            self.app.logger.warning("LivingMemory 删除失败 ref=%s: %s", source_ref, exc)
            return False

    async def export(self, cursor: str | None = None) -> tuple[list[dict[str, Any]], str | None]:
        """增量导出：使用其公开的 ``list_memories_page``（存在才用，否则不支持）。"""
        if self._engine is None or not self.allow_private:
            return [], None
        page = getattr(self._engine, "list_memories_page", None)
        if page is None:
            return [], None
        try:
            offset = int(cursor or 0)
            rows = await page(offset=offset, limit=50)
        except TypeError:
            try:
                rows = await page(offset=int(cursor or 0))
            except Exception:  # noqa: BLE001
                return [], None
        except Exception:  # noqa: BLE001
            return [], None
        entries: list[dict[str, Any]] = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            entries.append(
                {
                    "remote_ref": str(row.get("id") or row.get("memory_id") or ""),
                    "content": str(row.get("content") or "")[:1000],
                    "tags": row.get("tags") or [],
                    "importance": row.get("importance"),
                    "remote_updated_at": row.get("updated_at") or row.get("created_at"),
                }
            )
        return entries, str(int(cursor or 0) + len(entries))

    async def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        if self._engine is None:
            return []
        try:
            results = await self._engine.search_memories(query, k=limit, persona_id=self.persona_id)
        except Exception:  # noqa: BLE001
            return []
        entries: list[dict[str, Any]] = []
        for item in results or []:
            content = getattr(item, "content", None) or (
                item.get("content") if isinstance(item, dict) else None
            )
            if not content:
                continue
            ref = getattr(item, "id", None) or (
                item.get("id") if isinstance(item, dict) else None
            )
            entries.append({"content": str(content)[:500], "remote_ref": str(ref or "")})
        return entries[:limit]

    @staticmethod
    def _session_tag(source_ref: str) -> str:
        """把 source_ref 映射成稳定的 session 标签，便于在远端按来源筛选。"""
        return f"study:{source_ref}"[:120]


def _map_importance(importance: int) -> float:
    """本插件 1~5 → LivingMemory 0.0~1.0。"""
    mapping = {1: 0.3, 2: 0.5, 3: 0.7, 4: 0.85, 5: 0.95}
    return mapping.get(int(importance or 3), 0.7)
