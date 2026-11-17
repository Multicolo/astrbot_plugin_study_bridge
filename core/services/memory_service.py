"""记忆业务：本地记忆库、污染过滤、上下行同步、对账、注入。

数据流（详见 docs/MEMORY_SYNC.md）：
- 本地 ``memory_note`` 是唯一事实源；
- ``memory_sync`` 记录每条本地记忆在远端的映射与状态（pending/synced/failed/orphan）；
- ``sync_outbox`` 记录待重试的上行写操作（指数退避，最多 10 次）；
- 下行只进 ``bot_memory_mirror``（``origin='bot'``，永不再次上行）。
"""

from __future__ import annotations

import re
from typing import Any

from ..errors import invalid, not_found
from ..principal import Principal
from ..util import (
    dumps,
    estimate_tokens,
    iso,
    loads,
    new_id,
    norm_text,
    parse_iso,
    sha256_hex,
    similarity,
    utcnow,
)

NOTE_KINDS = ("preference", "goal", "fact", "mistake", "constraint")
MAX_CONTENT = 200
SYNC_SIMILARITY = 0.95
OUTBOX_MAX_RETRY = 10


def _strip_source_tag(text: str, prefix: str) -> str:
    return re.sub(re.escape(prefix) + r"[^\]]*\]", "", text or "")


class MemoryService:
    def __init__(self, app: Any) -> None:
        self.app = app

    @property
    def adapter(self):
        return self.app.memory_manager.active

    @property
    def sync_mode(self) -> str:
        mode = self.app.cfg.get_str("memory.sync_mode", "upload_only")
        return mode if mode in ("off", "upload_only", "bidirectional") else "upload_only"

    @property
    def tag_prefix(self) -> str:
        return self.app.cfg.source_tag_prefix

    def tag_for(self, source_ref: str) -> str:
        return f"{self.tag_prefix}{source_ref}]"

    # ------------------------------------------------------------ 污染过滤
    def check_pollution(
        self, *, content: str, source: str, origin_tag: str = ""
    ) -> str | None:
        """返回拒绝原因；None 表示通过。

        规则对应需求 10.4-1/2：
        - 长度 > 200、含三引号代码块、含结构化块（{} / []）；
        - 来源属于 injected/assistant/tool。
        """
        text = (content or "").strip()
        if not text:
            return "内容为空"
        if len(text) > MAX_CONTENT:
            return f"内容超过 {MAX_CONTENT} 字上限"
        if "```" in text:
            return "含代码块"
        bare = _strip_source_tag(text, self.tag_prefix)
        if origin_tag:
            bare = bare.replace(origin_tag, "")
        if re.search(r"[{}\[\]]", bare):
            return "含结构化块（{} / []）"
        if re.search(r"<(system|tool|assistant|function)>", bare, re.IGNORECASE):
            return "含系统标记"
        if source in ("injected", "assistant", "tool"):
            return f"来源 {source} 禁止上行"
        return None

    # ------------------------------------------------------------ 本地记忆
    async def list_notes(
        self,
        principal: Principal,
        *,
        kind: str | None = None,
        query: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM memory_note WHERE owner_principal_id = ? AND deleted_at IS NULL"
        params: list[Any] = [principal.id]
        if kind:
            sql += " AND kind = ?"
            params.append(kind)
        if query:
            sql += " AND content LIKE ?"
            params.append(f"%{query}%")
        sql += " ORDER BY importance DESC, created_at DESC LIMIT ?"
        params.append(max(1, min(300, limit)))
        rows = await self.app.db.fetch_all(sql, tuple(params))
        for row in rows:
            row["tags"] = loads(row.get("tags"), []) or []
        return rows

    async def get_note(self, principal: Principal, note_id: str) -> dict[str, Any]:
        row = await self.app.db.fetch_one(
            "SELECT * FROM memory_note WHERE id = ? AND owner_principal_id = ? AND deleted_at IS NULL",
            (note_id, principal.id),
        )
        if not row:
            raise not_found("记忆不存在")
        row["tags"] = loads(row.get("tags"), []) or []
        return row

    async def save_note(
        self,
        principal: Principal,
        *,
        kind: str,
        content: str,
        tags: list[str] | None = None,
        importance: int = 3,
        source: str = "user",
        source_ref: str | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        if kind not in NOTE_KINDS:
            raise invalid(f"kind 只能是 {NOTE_KINDS}")
        content = (content or "").strip()
        reason = self.check_pollution(content=content, source=source)
        if reason and not force:
            raise invalid(f"内容被污染过滤器拒绝：{reason}")
        importance = max(1, min(5, int(importance or 3)))
        tags = [str(tag)[:24] for tag in (tags or [])][:8]
        digest = sha256_hex(f"{kind}:{norm_text(content)}")
        now = iso(utcnow())

        if source_ref:
            existing = await self.app.db.fetch_one(
                "SELECT * FROM memory_note WHERE owner_principal_id = ? AND source_ref = ?",
                (principal.id, source_ref),
            )
            if existing:
                await self.app.db.execute(
                    "UPDATE memory_note SET content = ?, hash = ?, tags = ?, importance = ?, "
                    "updated_at = ?, deleted_at = NULL WHERE id = ?",
                    (content, digest, dumps(tags), importance, now, existing["id"]),
                )
                await self._enqueue_upsert(principal, existing["id"], "upsert")
                return await self.get_note(principal, existing["id"])

        duplicate = await self.app.db.fetch_one(
            "SELECT * FROM memory_note WHERE owner_principal_id = ? AND hash = ? AND deleted_at IS NULL",
            (principal.id, digest),
        )
        if duplicate:
            return await self.get_note(principal, duplicate["id"])

        note_id = new_id()
        await self.app.db.execute(
            "INSERT INTO memory_note (id, owner_principal_id, ns, kind, content, tags, importance, "
            "source, source_ref, hash, created_at, updated_at, deleted_at) "
            "VALUES (?, ?, 'study', ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)",
            (
                note_id,
                principal.id,
                kind,
                content,
                dumps(tags),
                importance,
                source,
                source_ref,
                digest,
                now,
                now,
            ),
        )
        await self._enqueue_upsert(principal, note_id, "upsert")
        return await self.get_note(principal, note_id)

    async def patch_note(
        self, principal: Principal, note_id: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        note = await self.get_note(principal, note_id)
        updates: dict[str, Any] = {}
        if "content" in data:
            content = str(data.get("content") or "").strip()
            reason = self.check_pollution(content=content, source=note["source"])
            if reason:
                raise invalid(f"内容被污染过滤器拒绝：{reason}")
            updates["content"] = content
            updates["hash"] = sha256_hex(f"{note['kind']}:{norm_text(content)}")
        if "tags" in data:
            updates["tags"] = dumps([str(tag)[:24] for tag in (data.get("tags") or [])][:8])
        if "importance" in data:
            updates["importance"] = max(1, min(5, int(data["importance"])))
        if "kind" in data:
            kind = str(data["kind"])
            if kind not in NOTE_KINDS:
                raise invalid(f"kind 只能是 {NOTE_KINDS}")
            updates["kind"] = kind
        if not updates:
            return note
        updates["updated_at"] = iso(utcnow())
        assignments = ", ".join(f"{key} = :{key}" for key in updates)
        await self.app.db.execute(
            f"UPDATE memory_note SET {assignments} WHERE id = :id AND owner_principal_id = :owner",
            {**updates, "id": note_id, "owner": principal.id},
        )
        await self._enqueue_upsert(principal, note_id, "upsert")
        return await self.get_note(principal, note_id)

    async def delete_note(self, principal: Principal, note_id: str) -> dict[str, Any]:
        await self.get_note(principal, note_id)
        now = iso(utcnow())
        await self.app.db.execute(
            "UPDATE memory_note SET deleted_at = ?, updated_at = ? WHERE id = ? AND owner_principal_id = ?",
            (now, now, note_id, principal.id),
        )
        await self._enqueue_upsert(principal, note_id, "delete")
        return {"id": note_id, "deleted": True}

    # ------------------------------------------------------------ 同步队列
    async def _enqueue_upsert(self, principal: Principal, local_id: str, op: str) -> None:
        if self.sync_mode == "off":
            await self._set_sync_state(principal, local_id, state="local")
            return
        await self.app.db.execute(
            "INSERT INTO sync_outbox (owner_principal_id, op, local_id, payload, retry, next_at) "
            "VALUES (?, ?, ?, NULL, 0, ?)",
            (principal.id, op, local_id, iso(utcnow())),
        )
        await self._set_sync_state(principal, local_id, state="pending")

    async def _set_sync_state(
        self,
        principal: Principal,
        local_id: str,
        *,
        state: str,
        remote_ref: str | None = None,
        error: str | None = None,
    ) -> None:
        row = await self.app.db.fetch_one(
            "SELECT * FROM memory_sync WHERE owner_principal_id = ? AND local_id = ?",
            (principal.id, local_id),
        )
        now = iso(utcnow())
        if row:
            await self.app.db.execute(
                "UPDATE memory_sync SET state = ?, remote_ref = COALESCE(?, remote_ref), "
                "last_error = ?, synced_at = ? WHERE id = ?",
                (state, remote_ref, error, now if state == "synced" else row.get("synced_at"), row["id"]),
            )
        else:
            await self.app.db.execute(
                "INSERT INTO memory_sync (id, owner_principal_id, local_id, remote_ref, synced_hash, "
                "state, attempts, last_error, synced_at) VALUES (?, ?, ?, ?, NULL, ?, 0, ?, ?)",
                (new_id(), principal.id, local_id, remote_ref, state, error, now if state == "synced" else None),
            )

    async def process_outbox(self, *, limit: int = 20) -> int:
        """处理待同步项：成功置 synced，失败按指数退避重试（最多 10 次）。"""
        now = iso(utcnow())
        rows = await self.app.db.fetch_all(
            "SELECT * FROM sync_outbox WHERE next_at IS NULL OR next_at <= ? ORDER BY id ASC LIMIT ?",
            (now, limit),
        )
        done = 0
        for row in rows:
            principal = await self.app.principal_by_id(row["owner_principal_id"])
            if principal is None:
                await self.app.db.execute("DELETE FROM sync_outbox WHERE id = ?", (row["id"],))
                continue
            ok = await self._apply_one(principal, row)
            if ok:
                await self.app.db.execute("DELETE FROM sync_outbox WHERE id = ?", (row["id"],))
                done += 1
                continue
            retry = int(row.get("retry") or 0) + 1
            if retry >= OUTBOX_MAX_RETRY:
                await self.app.db.execute("DELETE FROM sync_outbox WHERE id = ?", (row["id"],))
                await self._set_sync_state(
                    principal, row["local_id"], state="failed", error="重试超过上限"
                )
                await self._log_sync("upsert", False, f"{row['local_id']} 超过重试上限")
                continue
            delay = min(3600, 30 * (2 ** (retry - 1)))
            next_at = iso(utcnow() + __import__("datetime").timedelta(seconds=delay))
            await self.app.db.execute(
                "UPDATE sync_outbox SET retry = ?, next_at = ? WHERE id = ?",
                (retry, next_at, row["id"]),
            )
            await self._set_sync_state(
                principal, row["local_id"], state="pending", error="等待重试"
            )
        return done

    async def _apply_one(self, principal: Principal, row: dict[str, Any]) -> bool:
        local_id = row["local_id"]
        note_row = await self.app.db.fetch_one(
            "SELECT * FROM memory_note WHERE id = ? AND owner_principal_id = ?",
            (local_id, principal.id),
        )
        if note_row is None:
            await self.app.db.execute("DELETE FROM sync_outbox WHERE id = ?", (row["id"],))
            return True
        if row["op"] == "delete":
            sync_row = await self.app.db.fetch_one(
                "SELECT * FROM memory_sync WHERE owner_principal_id = ? AND local_id = ?",
                (principal.id, local_id),
            )
            remote_ref = (sync_row or {}).get("remote_ref")
            adapter = self.adapter
            if not adapter.supports_delete:
                await self._set_sync_state(
                    principal,
                    local_id,
                    state="orphan",
                    error="远端不支持删除，已在 App 标记 orphan",
                )
                await self._log_sync("delete", False, f"{local_id} 远端不支持删除 -> orphan")
                return True
            ok = True
            if remote_ref:
                ok = await adapter.delete(remote_ref)
            if ok:
                await self._set_sync_state(principal, local_id, state="local")
                await self._log_sync("delete", True, local_id)
                return True
            await self._set_sync_state(
                principal, local_id, state="orphan", error="远端删除失败"
            )
            await self._log_sync("delete", False, f"{local_id} 删除失败 -> orphan")
            return True

        content = self._compose_remote_content(note_row)
        reason = self.check_pollution(content=content, source=note_row["source"])
        if reason:
            await self._set_sync_state(
                principal, local_id, state="failed", error=f"污染过滤：{reason}"
            )
            await self._log_sync("upsert", False, f"{local_id} 过滤：{reason}")
            return True
        recent = await self.app.db.fetch_all(
            "SELECT n.content FROM memory_note n JOIN memory_sync s ON s.local_id = n.id "
            "WHERE n.owner_principal_id = ? AND s.state = 'synced' AND n.id != ? "
            "AND (s.synced_at IS NULL OR s.synced_at >= ?)",
            (principal.id, local_id, iso(utcnow() - __import__("datetime").timedelta(hours=24))),
        )
        # 相似度比较只比"正文"，不带来源标记（否则标记里的随机 id 会把相似度压下去）
        normalized_content = note_row["content"]
        for item in recent:
            if similarity(item["content"], normalized_content) > SYNC_SIMILARITY:
                await self._set_sync_state(
                    principal, local_id, state="synced", error="24h 内相似条目已同步，跳过"
                )
                await self._log_sync("upsert", True, f"{local_id} 相似跳过")
                return True
        remote_ref = await self.adapter.upsert(
            source_ref=note_row["id"],
            content=content,
            tags=loads(note_row.get("tags"), []) or [],
            importance=int(note_row.get("importance") or 3),
        )
        if not remote_ref:
            if self.adapter.name == "none":
                await self._set_sync_state(principal, local_id, state="local")
                return True
            return False
        await self._set_sync_state(
            principal, local_id, state="synced", remote_ref=remote_ref
        )
        await self._log_sync("upsert", True, f"{local_id} -> {remote_ref}")
        return True

    def _compose_remote_content(self, note_row: dict[str, Any]) -> str:
        """≤120 字第三人称陈述句 + 固定来源标记。"""
        content = (note_row.get("content") or "").strip()
        if len(content) > 110:
            content = content[:110] + "…"
        return f"{content} {self.tag_for(note_row['id'])}"

    async def _log_sync(self, op: str, ok: bool, detail: str) -> None:
        await self.app.db.execute(
            "INSERT INTO sync_log (op, ok, detail, created_at) VALUES (?, ?, ?, ?)",
            (op, 1 if ok else 0, detail[:500], iso(utcnow())),
        )

    # ------------------------------------------------------------ 下行
    async def pull_bot_memory(self, principal: Principal, *, limit: int = 50) -> int:
        """bot → App：增量导出到 ``bot_memory_mirror``（不参与上行）。"""
        if self.sync_mode != "bidirectional":
            return 0
        if not self.adapter.supports_export:
            return 0
        cursor_row = await self.app.db.fetch_one(
            "SELECT value FROM setting WHERE owner_principal_id = ? AND key = '__memory_cursor'",
            (principal.id,),
        )
        cursor = (cursor_row or {}).get("value")
        try:
            entries, next_cursor = await self.adapter.export(cursor)
        except Exception as exc:  # noqa: BLE001
            await self._log_sync("pull", False, f"导出失败：{exc}")
            return 0
        ingested = 0
        now = iso(utcnow())
        for entry in entries[:limit]:
            content = (entry.get("content") or "").strip()
            if not content:
                continue
            # 防回环：带自己来源标记的条目一律丢弃
            if self.tag_prefix in content:
                continue
            remote_ref = str(entry.get("remote_ref") or sha256_hex(content)[:16])
            exists = await self.app.db.fetch_one(
                "SELECT remote_ref FROM bot_memory_mirror WHERE remote_ref = ?", (remote_ref,)
            )
            if exists:
                continue
            await self.app.db.execute(
                "INSERT INTO bot_memory_mirror (remote_ref, owner_principal_id, content, tags, importance, "
                "source_ref, origin, adopted, remote_updated_at, synced_at) "
                "VALUES (?, ?, ?, ?, ?, NULL, 'bot', 0, ?, ?)",
                (
                    remote_ref,
                    principal.id,
                    content[:1000],
                    dumps(entry.get("tags") or []),
                    entry.get("importance"),
                    entry.get("remote_updated_at"),
                    now,
                ),
            )
            ingested += 1
        if next_cursor is not None:
            await self.app.db.execute(
                "INSERT INTO setting (owner_principal_id, key, value, updated_at) VALUES (?, "
                "'__memory_cursor', ?, ?) ON CONFLICT(owner_principal_id, key) DO UPDATE SET "
                "value = excluded.value, updated_at = excluded.updated_at",
                (principal.id, str(next_cursor), now),
            )
        if ingested:
            await self._log_sync("pull", True, f"ingest {ingested}")
        return ingested

    async def list_bot_memory(self, principal: Principal, *, limit: int = 100) -> list[dict[str, Any]]:
        rows = await self.app.db.fetch_all(
            "SELECT * FROM bot_memory_mirror WHERE owner_principal_id = ? ORDER BY synced_at DESC LIMIT ?",
            (principal.id, max(1, min(300, limit))),
        )
        for row in rows:
            row["adopted"] = bool(row.get("adopted"))
            row["tags"] = loads(row.get("tags"), []) or []
        return rows

    async def adopt(self, principal: Principal, remote_ref: str) -> dict[str, Any]:
        row = await self.app.db.fetch_one(
            "SELECT * FROM bot_memory_mirror WHERE owner_principal_id = ? AND remote_ref = ?",
            (principal.id, remote_ref),
        )
        if not row:
            raise not_found("bot 记忆不存在")
        note = await self.save_note(
            principal,
            kind="fact",
            content=row["content"][:200],
            tags=loads(row.get("tags"), []) or [],
            importance=3,
            source="user",
        )
        await self.app.db.execute(
            "UPDATE bot_memory_mirror SET adopted = 1 WHERE remote_ref = ?", (remote_ref,)
        )
        return note

    # ------------------------------------------------------------ 进度快照
    async def push_progress(self, principal: Principal) -> int:
        """把每个活跃计划的进度写成**固定 source_ref** 的记忆（覆盖式，不膨胀）。"""
        plans = await self.app.plans.progress(principal)
        count = 0
        for plan in plans:
            if not plan["applied"]:
                continue
            content = (
                f"用户的计划「{plan['title']}」已完成 {plan['done']}/{plan['total']} 项"
                f"（{plan['rate']}%），截止 {plan.get('deadline') or '未设置'}。"
            )
            await self.save_note(
                principal,
                kind="goal",
                content=content[:200],
                tags=["plan-progress"],
                importance=3,
                source="user",
                source_ref=f"study:plan-progress:{plan['plan_id']}",
                force=True,
            )
            count += 1
        return count

    # ------------------------------------------------------------ 对账
    async def reconcile(self, principal: Principal) -> dict[str, Any]:
        """每周对账：本地重要记忆与远端逐条比对，缺失补写、已删标记。"""
        notes = await self.app.db.fetch_all(
            "SELECT * FROM memory_note WHERE owner_principal_id = ? AND deleted_at IS NULL "
            "AND importance >= 3",
            (principal.id,),
        )
        missing = 0
        orphan = 0
        for note in notes:
            sync_row = await self.app.db.fetch_one(
                "SELECT * FROM memory_sync WHERE owner_principal_id = ? AND local_id = ?",
                (principal.id, note["id"]),
            )
            state = (sync_row or {}).get("state")
            if state in ("synced", "local"):
                continue
            if self.sync_mode == "off":
                continue
            await self.app.db.execute(
                "INSERT INTO sync_outbox (owner_principal_id, op, local_id, payload, retry, next_at) "
                "VALUES (?, 'upsert', ?, NULL, 0, ?)",
                (principal.id, note["id"], iso(utcnow())),
            )
            missing += 1
            if state == "orphan":
                orphan += 1
        await self._log_sync("reconcile", True, f"补写 {missing}，orphan {orphan}")
        return {"checked": len(notes), "missing": missing, "orphan": orphan}

    # ------------------------------------------------------------ 压缩
    async def compact(self, principal: Principal) -> dict[str, Any]:
        """合并高度相似记忆：新的保留，旧的软删（不跨主体、不动 bot 镜像）。"""
        notes = await self.list_notes(principal, limit=300)
        removed = 0
        for index, note in enumerate(notes):
            for other in notes[index + 1 :]:
                if note["kind"] != other["kind"]:
                    continue
                if similarity(note["content"], other["content"]) > 0.95:
                    await self.delete_note(principal, other["id"])
                    removed += 1
                    break
        return {"removed": removed, "remaining": len(notes) - removed}

    # ------------------------------------------------------------ 注入
    async def build_context_block(
        self, principal: Principal, *, question: str, budget_tokens: int | None = None
    ) -> str:
        """按需求 10.5 的顺序拼注入块，超预算从上往下砍。"""
        budget = budget_tokens or self.app.cfg.get_int("memory.budget_tokens", 1500)
        blocks: list[str] = []
        used = 0

        def take(text: str) -> bool:
            nonlocal used
            cost = estimate_tokens(text)
            if used + cost > budget:
                return False
            blocks.append(text)
            used += cost
            return True

        notes = await self.list_notes(principal, limit=15)
        profile = [n for n in notes if n["kind"] in ("preference", "goal", "constraint")][:15]
        if profile:
            lines = [f"- [{n['kind']}] {n['content']}" for n in profile]
            take("【用户画像】\n" + "\n".join(lines))

        plans = await self.app.plans.progress(principal)
        active = [p for p in plans if p["applied"]][:3]
        if active:
            lines = [
                f"- {p['title']}：{p['done']}/{p['total']}（{p['rate']}%），截止 {p.get('deadline') or '-'}"
                for p in active
            ]
            take("【活跃计划】\n" + "\n".join(lines))

        day = await self.app.tasks.day_view(principal, 0)
        items = day["items"][:8]
        if items:
            lines = [
                f"- {item['local_start'] or '全天'} {item['title']}（{item['status']}）"
                for item in items
            ]
            take("【今天】\n" + "\n".join(lines))

        if self.sync_mode == "bidirectional":
            mirrors = await self.list_bot_memory(principal, limit=10)
            relevant = mirrors[:5]
            if relevant:
                lines = [f"- {m['content'][:120]}" for m in relevant]
                take("【bot 记忆】\n" + "\n".join(lines))

        return "\n\n".join(blocks)

    # ------------------------------------------------------------ 状态
    async def sync_status(self, principal: Principal) -> dict[str, Any]:
        rows = await self.app.db.fetch_all(
            "SELECT state, COUNT(*) AS n FROM memory_sync WHERE owner_principal_id = ? GROUP BY state",
            (principal.id,),
        )
        counts = {row["state"]: int(row["n"]) for row in rows}
        pending_outbox = int(
            await self.app.db.scalar(
                "SELECT COUNT(*) FROM sync_outbox WHERE owner_principal_id = ?",
                (principal.id,),
                default=0,
            )
        )
        logs = await self.app.db.fetch_all(
            "SELECT op, ok, detail, created_at FROM sync_log ORDER BY id DESC LIMIT 20"
        )
        adapter = self.adapter
        return {
            "mode": self.sync_mode,
            "adapter": adapter.describe(),
            "attempts": self.app.memory_manager.attempts,
            "states": counts,
            "pending_outbox": pending_outbox,
            "orphan": counts.get("orphan", 0),
            "recent": logs,
        }

    async def forget_all(self, principal: Principal) -> int:
        notes = await self.list_notes(principal, limit=300)
        for note in notes:
            await self.delete_note(principal, note["id"])
        return len(notes)


_ = (parse_iso,)
