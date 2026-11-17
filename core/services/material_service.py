"""资料业务：文本 / 链接 / 上传（multipart 由 HTTP 层读成文本后传进来）。"""

from __future__ import annotations

from typing import Any

from ..errors import invalid, not_found
from ..principal import Principal
from ..util import iso, new_id, utcnow

MAX_RAW_TEXT = 120_000


class MaterialService:
    def __init__(self, app: Any) -> None:
        self.app = app

    async def list(self, principal: Principal, *, limit: int = 100) -> list[dict[str, Any]]:
        rows = await self.app.db.fetch_all(
            "SELECT id, name, type, summary, LENGTH(COALESCE(raw_text,'')) AS raw_len, created_at "
            "FROM material WHERE owner_principal_id = ? ORDER BY created_at DESC LIMIT ?",
            (principal.id, max(1, min(200, limit))),
        )
        for row in rows:
            row["raw_len"] = int(row.get("raw_len") or 0)
        return rows

    async def get(self, principal: Principal, material_id: str) -> dict[str, Any]:
        row = await self.app.db.fetch_one(
            "SELECT * FROM material WHERE id = ? AND owner_principal_id = ?",
            (material_id, principal.id),
        )
        if not row:
            raise not_found("资料不存在")
        return row

    async def create(
        self,
        principal: Principal,
        *,
        name: str | None = None,
        kind: str = "text",
        raw_text: str | None = None,
        url: str | None = None,
    ) -> dict[str, Any]:
        if kind not in ("text", "url", "file"):
            raise invalid("type 只能是 text|url|file")
        if kind == "url":
            if not url or not str(url).startswith(("http://", "https://")):
                raise invalid("url 必须以 http:// 或 https:// 开头")
            raw_text = raw_text or ""
            name = name or str(url)[:80]
        else:
            if not raw_text or not str(raw_text).strip():
                raise invalid("raw_text 不能为空")
            if len(raw_text) > MAX_RAW_TEXT:
                raise invalid(f"文本过长（≤{MAX_RAW_TEXT} 字符）")
            name = name or (str(raw_text).strip().splitlines()[0][:40] or "未命名资料")
        material_id = new_id()
        await self.app.db.execute(
            "INSERT INTO material (id, owner_principal_id, name, type, raw_text, summary, created_at) "
            "VALUES (?, ?, ?, ?, ?, NULL, ?)",
            (
                material_id,
                principal.id,
                str(name)[:120],
                kind,
                (raw_text or "")[:MAX_RAW_TEXT],
                iso(utcnow()),
            ),
        )
        if kind == "url":
            await self.app.db.execute(
                "UPDATE material SET summary = ? WHERE id = ?",
                (f"链接资料：{url}", material_id),
            )
        return await self.get(principal, material_id)

    async def delete(self, principal: Principal, material_id: str) -> dict[str, Any]:
        await self.get(principal, material_id)
        await self.app.db.execute(
            "DELETE FROM material WHERE id = ? AND owner_principal_id = ?",
            (material_id, principal.id),
        )
        return {"id": material_id, "deleted": True}

    async def summarise(self, principal: Principal, text: str, *, limit: int = 400) -> str:
        """给计划拆解用的短摘要：优先用 LLM，失败就截断原文。"""
        if not text:
            return ""
        if await self.app.llm.available():
            try:
                prompt = (
                    "把下面的学习资料压缩成不超过 120 字的中文摘要，"
                    "保留章节结构与重点，不要编造：\n\n" + text[:6000]
                )
                result = await self.app.llm.complete(prompt, timeout=30)
                summary = result.strip().replace("\n", " ")
                if summary:
                    return summary[:limit]
            except Exception:  # noqa: BLE001 - 摘要失败不应阻塞上传
                pass
        return text.strip()[:limit]
