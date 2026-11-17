"""对话业务：QQ 与 App 共用同一条 pipeline（会话、记忆注入、工具循环）。"""

from __future__ import annotations

import json
from typing import Any

from ..ai.tools import (
    MAX_TOOL_CALLS_PER_TURN,
    ToolExecutor,
    parse_tool_payload,
    tools_prompt_text,
    validate_tool_args,
)
from ..errors import invalid
from ..llm import LLMError, render_prompt
from ..principal import Principal
from ..util import dumps, estimate_tokens, get_tz, iso, new_id, parse_iso, utcnow

MAX_HISTORY_MESSAGES = 12
SUMMARY_TRIGGER_MESSAGES = 20
SUMMARY_TRIGGER_TOKENS = 2000


class ChatService:
    def __init__(self, app: Any) -> None:
        self.app = app
        self.executor = ToolExecutor(app)

    # ------------------------------------------------------------ 会话
    async def ensure_session(
        self,
        principal: Principal,
        *,
        session_key: str,
        channel: str = "app",
        umo: str | None = None,
    ) -> dict[str, Any]:
        key = f"{channel}:{principal.id}:{session_key}"
        row = await self.app.db.fetch_one(
            "SELECT * FROM chat_session WHERE session_key = ?", (key,)
        )
        now = iso(utcnow())
        if row:
            await self.app.db.execute(
                "UPDATE chat_session SET last_active_at = ? WHERE id = ?", (now, row["id"])
            )
            return row
        session_id = new_id()
        await self.app.db.execute(
            "INSERT INTO chat_session (id, owner_principal_id, session_key, channel, umo, "
            "created_at, last_active_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (session_id, principal.id, key, channel, umo, now, now),
        )
        return {
            "id": session_id,
            "owner_principal_id": principal.id,
            "session_key": key,
            "channel": channel,
            "umo": umo,
            "created_at": now,
            "last_active_at": now,
        }

    async def history(
        self, principal: Principal, *, session_key: str, limit: int = 30
    ) -> dict[str, Any]:
        session = await self.ensure_session(principal, session_key=session_key)
        rows = await self.app.db.fetch_all(
            "SELECT id, role, content, tool_name, tool_result, created_at FROM chat_message "
            "WHERE session_id = ? ORDER BY id DESC LIMIT ?",
            (session["id"], max(1, min(200, limit))),
        )
        rows.reverse()
        summary = await self.app.db.fetch_one(
            "SELECT summary FROM chat_summary WHERE session_id = ?", (session["id"],)
        )
        return {"session_key": session["session_key"], "summary": (summary or {}).get("summary"), "messages": rows}

    async def reset(self, principal: Principal, *, session_key: str) -> dict[str, Any]:
        session = await self.ensure_session(principal, session_key=session_key)
        await self.app.db.execute("DELETE FROM chat_message WHERE session_id = ?", (session["id"],))
        await self.app.db.execute("DELETE FROM chat_summary WHERE session_id = ?", (session["id"],))
        return {"session_key": session["session_key"], "reset": True}

    # ------------------------------------------------------------ 对话
    async def handle(
        self,
        principal: Principal,
        *,
        text: str,
        session_key: str,
        channel: str = "app",
        umo: str | None = None,
    ) -> dict[str, Any]:
        text = (text or "").strip()
        if not text:
            raise invalid("text 不能为空")
        if len(text) > 4000:
            raise invalid("单条消息过长（≤4000 字）")
        session = await self.ensure_session(
            principal, session_key=session_key, channel=channel, umo=umo
        )
        await self._append(session["id"], "user", text)

        if not self.app.llm.allowed_for(principal):
            reply = self.app.t("cmd.error.ai_unavailable")
            await self._append(session["id"], "assistant", reply)
            return {"reply": reply, "tool_calls": [], "plan_draft": None, "ai": False}

        tz = await self.app.settings.get_tz(principal)
        system = await self._build_system_prompt(principal, question=text, tz=tz)
        messages = await self._recent_messages(session["id"], system=system)
        tool_calls_log: list[dict[str, Any]] = []
        plan_draft: dict[str, Any] | None = None
        reply = ""
        rounds = self.app.cfg.get_int("ai.max_tool_rounds", 6)
        for _round in range(max(1, rounds)):
            try:
                raw = await self.app.llm.chat_completion(system, messages)
            except LLMError as exc:
                reply = f"{self.app.t('cmd.error.ai_unavailable')}（{exc}）"
                await self._append(session["id"], "assistant", reply)
                return {
                    "reply": reply,
                    "tool_calls": tool_calls_log,
                    "plan_draft": plan_draft,
                    "ai": False,
                }
            payload = parse_tool_payload(raw)
            if payload is None:
                reply = raw.strip()
                break
            calls = payload.get("tool_calls") or []
            if not isinstance(calls, list) or not calls:
                reply = str(payload.get("reply") or "").strip()
                break
            reply = str(payload.get("reply") or "").strip()
            results: list[str] = []
            for call in calls[:MAX_TOOL_CALLS_PER_TURN]:
                if not isinstance(call, dict):
                    continue
                name = str(call.get("name") or "")
                args, error = validate_tool_args(name, call.get("args") or {})
                if error:
                    results.append(f"[{name}] 参数错误：{error}")
                    tool_calls_log.append(
                        {
                            "name": name,
                            "args": args,
                            "ok": False,
                            "error": error,
                            "result": {"ok": False, "error": error},
                        }
                    )
                    continue
                outcome = await self.executor.execute(
                    principal, session_id=session["id"], name=name, args=args
                )
                tool_calls_log.append(
                    {
                        "name": name,
                        "args": args,
                        "ok": bool(outcome.get("ok")),
                        "result": outcome,
                    }
                )
                if outcome.get("needs_confirmation") and name == "create_plan":
                    plan_draft = outcome.get("plan")
                if outcome.get("ok"):
                    results.append(f"[{name}] {json.dumps(outcome, ensure_ascii=False)[:800]}")
                else:
                    results.append(f"[{name}] 失败：{outcome.get('error')}")
                await self._append(
                    session["id"],
                    "tool",
                    content=None,
                    tool_name=name,
                    tool_args=dumps(args),
                    tool_result=dumps(outcome)[:4000],
                )
            messages.append({"role": "assistant", "content": raw})
            messages.append(
                {
                    "role": "tool_result",
                    "content": "工具执行结果：\n" + "\n".join(results)
                    + "\n\n请用自然语言总结给用户；不要重复调用同样的工具。",
                }
            )
        else:
            reply = reply or "工具调用轮次超过上限，先停在这里。你可以说得更具体一点。"

        await self._append(session["id"], "assistant", reply or "（无回复）")
        await self._bump_usage(principal, "chat")
        await self._maybe_summarise(session["id"])
        return {
            "reply": reply,
            "tool_calls": tool_calls_log,
            "plan_draft": plan_draft,
            "ai": True,
        }

    # ------------------------------------------------------------ 内部
    async def _append(
        self,
        session_id: str,
        role: str,
        content: str | None,
        *,
        tool_name: str | None = None,
        tool_args: str | None = None,
        tool_result: str | None = None,
    ) -> None:
        await self.app.db.execute(
            "INSERT INTO chat_message (session_id, role, content, tool_name, tool_args, tool_result, "
            "token_est, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                session_id,
                role,
                content,
                tool_name,
                tool_args,
                tool_result,
                estimate_tokens(content or tool_result or ""),
                iso(utcnow()),
            ),
        )

    async def _recent_messages(self, session_id: str, *, system: str) -> list[dict[str, str]]:
        rows = await self.app.db.fetch_all(
            "SELECT role, content FROM chat_message WHERE session_id = ? AND content IS NOT NULL "
            "ORDER BY id DESC LIMIT ?",
            (session_id, MAX_HISTORY_MESSAGES),
        )
        rows.reverse()
        return [{"role": row["role"], "content": row["content"]} for row in rows]

    async def _build_system_prompt(
        self, principal: Principal, *, question: str, tz: str
    ) -> str:
        memory_block = await self.app.memories.build_context_block(
            principal, question=question
        )
        plans = await self.app.plans.progress(principal)
        active = [p for p in plans if p["applied"]][:3]
        plan_context = (
            "\n".join(
                f"- {p['title']}：{p['done']}/{p['total']}（{p['rate']}%）"
                for p in active
            )
            or "（暂无已写入的计划）"
        )
        day = await self.app.tasks.day_view(principal, 0)
        schedule = (
            "\n".join(
                f"- {item['local_start'] or '全天'} {item['title']}（{item['status']}）"
                for item in day["items"][:8]
            )
            or "（今天没有安排）"
        )
        return render_prompt(
            "system",
            self.app.lang,
            now=iso(utcnow()),
            tz=tz,
            principal_kind=principal.kind,
            tools=tools_prompt_text(),
            profile=memory_block or "（暂无记忆）",
            plan_context=plan_context,
            schedule_context=schedule,
            bot_memory="（未开启双向同步）"
            if self.app.cfg.get_str("memory.sync_mode", "upload_only") != "bidirectional"
            else "（见记忆中心的 bot 记忆分区）",
        )

    async def _bump_usage(self, principal: Principal, kind: str) -> None:
        day = utcnow().date().isoformat()
        await self.app.db.execute(
            "INSERT INTO usage_counter (owner_principal_id, kind, day, count) VALUES (?, ?, ?, 1) "
            "ON CONFLICT(owner_principal_id, kind, day) DO UPDATE SET count = count + 1",
            (principal.id, kind, day),
        )

    async def _maybe_summarise(self, session_id: str) -> None:
        row = await self.app.db.fetch_one(
            "SELECT COUNT(*) AS n, COALESCE(SUM(token_est),0) AS tokens FROM chat_message "
            "WHERE session_id = ? AND content IS NOT NULL",
            (session_id,),
        )
        count = int((row or {}).get("n") or 0)
        tokens = int((row or {}).get("tokens") or 0)
        if count <= SUMMARY_TRIGGER_MESSAGES and tokens <= SUMMARY_TRIGGER_TOKENS:
            return
        latest = await self.app.db.fetch_one(
            "SELECT id FROM chat_message WHERE session_id = ? ORDER BY id DESC LIMIT 1",
            (session_id,),
        )
        if latest is None:
            return
        existing = await self.app.db.fetch_one(
            "SELECT * FROM chat_summary WHERE session_id = ?", (session_id,)
        )
        if existing and existing["covered_upto_msg_id"] >= latest["id"]:
            return
        rows = await self.app.db.fetch_all(
            "SELECT role, content FROM chat_message WHERE session_id = ? AND content IS NOT NULL "
            "ORDER BY id DESC LIMIT 12",
            (session_id,),
        )
        rows.reverse()
        text = "\n".join(f"{row['role']}: {row['content']}" for row in rows)
        try:
            summary = await self.app.llm.complete(
                "把下面的对话压缩成不超过 120 字的要点，保留事实与承诺，不要编造：\n\n" + text,
                timeout=30,
            )
        except Exception:  # noqa: BLE001 - 摘要失败不影响对话
            return
        await self.app.db.execute(
            "INSERT INTO chat_summary (session_id, summary, covered_upto_msg_id, updated_at) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(session_id) DO UPDATE SET summary = excluded.summary, "
            "covered_upto_msg_id = excluded.covered_upto_msg_id, updated_at = excluded.updated_at",
            (session_id, summary.strip()[:1000], latest["id"], iso(utcnow())),
        )


_ = (get_tz, parse_iso)
