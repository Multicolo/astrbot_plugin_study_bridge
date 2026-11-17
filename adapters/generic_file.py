"""JSONL 落地适配器（默认关闭）：把记忆逐行追加到用户指定文件，供其它工具导入。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .base import AdapterStatus, MemoryAdapter


class FileAdapter(MemoryAdapter):
    name = "file"
    version = "1"
    supports_delete = True
    supports_export = True

    def __init__(self, app: Any) -> None:
        super().__init__(app)
        configured = app.cfg.get_str("memory.file_adapter_path", "")
        self.path = (
            Path(configured)
            if configured
            else Path(app.data_dir) / "memory_mirror.jsonl"
        )
        self._deleted: set[str] = set()

    async def probe(self) -> bool:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8"):
                pass
            self.status = AdapterStatus(
                name=self.name,
                ok=True,
                reason=f"写入 {self.path}",
                version=self.version,
                extra={"path": str(self.path)},
            )
            return True
        except OSError as exc:
            self.status = AdapterStatus(
                name=self.name, ok=False, reason=f"文件不可写：{exc}", version=self.version
            )
            return False

    def _append(self, record: dict[str, Any]) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    async def upsert(
        self,
        *,
        source_ref: str,
        content: str,
        tags: list[str] | None = None,
        importance: int = 3,
    ) -> str:
        import asyncio

        record = {
            "op": "upsert",
            "source_ref": source_ref,
            "content": content,
            "tags": tags or [],
            "importance": importance,
        }
        await asyncio.to_thread(self._append, record)
        return source_ref

    async def delete(self, source_ref: str) -> bool:
        import asyncio

        try:
            await asyncio.to_thread(
                self._append, {"op": "delete", "source_ref": source_ref}
            )
            self._deleted.add(source_ref)
            return True
        except OSError:
            return False

    async def export(self, cursor: str | None = None) -> tuple[list[dict[str, Any]], str | None]:
        import asyncio

        offset = int(cursor or 0)
        try:
            lines = await asyncio.to_thread(
                lambda: self.path.read_text(encoding="utf-8").splitlines()
            )
        except OSError:
            return [], None
        entries: list[dict[str, Any]] = []
        live: dict[str, dict[str, Any]] = {}
        for index, line in enumerate(lines):
            if index < offset:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            ref = record.get("source_ref")
            if record.get("op") == "delete":
                live.pop(ref, None)
            else:
                live[ref] = record
        for ref, record in live.items():
            entries.append(
                {
                    "remote_ref": ref,
                    "content": record.get("content", ""),
                    "tags": record.get("tags") or [],
                    "importance": record.get("importance"),
                }
            )
        return entries, str(len(lines))
