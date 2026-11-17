"""Function calling 工具：定义 + 执行器。

设计说明（见 docs/ARCHITECTURE.md §AI）：
- 工具定义只有这一份（``TOOL_SPECS``），既用于生成 system prompt，也用于参数校验；
- 协议是「JSON 工具调用」而不是 provider 原生 function calling：AstrBot 各
  provider 原生 tool 支持程度不一，JSON 协议在所有 OpenAI 兼容后端上都能跑，
  且单测可以完全离线验证（见 tests/test_chat.py）。
- 写操作全部落 ``ai_action_log``；``apply_plan`` 永不自动执行，需要用户二次确认。
"""

from __future__ import annotations

import json
from typing import Any

from ..errors import invalid
from ..util import dumps, iso, parse_iso, utcnow

TOOL_SPECS: list[dict[str, Any]] = [
    {
        "name": "create_task",
        "desc": "创建单个日程/任务（用户消息里必须有明确开始时间）",
        "params": {
            "title": "str",
            "start_at": "ISO8601",
            "end_at": "ISO8601?",
            "priority": "int?",
            "remind_offsets": "int[]?",
        },
    },
    {
        "name": "list_tasks",
        "desc": "按日期范围查询任务",
        "params": {"from": "date", "to": "date"},
    },
    {
        "name": "update_task_status",
        "desc": "标记任务完成/跳过",
        "params": {"task_id_or_keyword": "str", "status": "done|skipped"},
    },
    {
        "name": "create_plan",
        "desc": "生成并保存计划（只预览，不写入日程）",
        "params": {
            "title": "str",
            "goal": "str",
            "deadline": "date",
            "daily_minutes": "int",
            "items": "[{seq,title,scheduled_date,duration_min}]?",
        },
    },
    {
        "name": "apply_plan",
        "desc": "把计划写入日程（必须由用户二次确认，模型不得自行调用）",
        "params": {"plan_id": "str|latest"},
    },
    {
        "name": "query_stats",
        "desc": "查询完成率/趋势",
        "params": {"range": "today|week|month"},
    },
    {
        "name": "save_memory",
        "desc": "记录值得长期记住的信息",
        "params": {
            "kind": "preference|goal|fact|mistake|constraint",
            "content": "str",
            "tags": "str[]?",
            "importance": "int?",
        },
    },
]

TOOL_NAMES = {spec["name"] for spec in TOOL_SPECS}
MAX_TOOL_CALLS_PER_TURN = 3
MAX_ROUNDS = 6


def tools_prompt_text() -> str:
    lines = []
    for spec in TOOL_SPECS:
        params = ", ".join(f"{key}: {value}" for key, value in spec["params"].items())
        lines.append(f"- {spec['name']}({params}) — {spec['desc']}")
    return "\n".join(lines)


class ToolExecutor:
    def __init__(self, app: Any) -> None:
        self.app = app

    async def execute(
        self,
        principal: Any,
        *,
        session_id: str | None,
        name: str,
        args: dict[str, Any],
    ) -> dict[str, Any]:
        handler = {
            "create_task": self._create_task,
            "list_tasks": self._list_tasks,
            "update_task_status": self._update_task_status,
            "create_plan": self._create_plan,
            "apply_plan": self._apply_plan,
            "query_stats": self._query_stats,
            "save_memory": self._save_memory,
        }.get(name)
        if handler is None:
            return {"ok": False, "error": f"未知工具：{name}"}
        args = args if isinstance(args, dict) else {}
        try:
            result = await handler(principal, session_id, args)
        except Exception as exc:  # noqa: BLE001 - 工具失败必须回灌模型而不是 500
            await self._log(principal, session_id, name, args, None, False, str(exc))
            return {"ok": False, "error": str(exc)}
        await self._log(
            principal, session_id, name, args, result, True, None
        )
        return result

    # ------------------------------------------------------------ 写审计
    async def _log(
        self,
        principal: Any,
        session_id: str | None,
        tool_name: str,
        args: dict[str, Any],
        result: Any,
        ok: bool,
        error: str | None,
    ) -> None:
        await self.app.db.execute(
            "INSERT INTO ai_action_log (owner_principal_id, session_id, tool_name, args, result, ok, "
            "error, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                principal.id,
                session_id,
                tool_name,
                dumps(args)[:4000],
                dumps(result)[:4000] if result is not None else None,
                1 if ok else 0,
                error,
                iso(utcnow()),
            ),
        )

    # ------------------------------------------------------------ 工具实现
    async def _create_task(self, principal: Any, session_id: str | None, args: dict[str, Any]) -> dict[str, Any]:
        title = str(args.get("title") or "").strip()
        start = parse_iso(args.get("start_at"))
        if not title:
            return {"ok": False, "error": "缺少 title"}
        if start is None:
            return {
                "ok": False,
                "error": "缺少明确开始时间，请先问用户具体时间",
                "need_clarification": True,
            }
        end = parse_iso(args.get("end_at"))
        if end is None:
            from datetime import timedelta

            end = start + timedelta(minutes=30)
        task = await self.app.tasks.create(
            principal,
            {
                "title": title,
                "start_at": iso(start),
                "end_at": iso(end),
                "priority": args.get("priority", 2),
                "remind_offsets": args.get("remind_offsets"),
                "source": "ai",
            },
            source="ai",
        )
        return {
            "ok": True,
            "task": task,
            "display": f"已写入「{task['title']}」（{task['local_start']} - {task['local_end']}）",
        }

    async def _list_tasks(self, principal: Any, session_id: str | None, args: dict[str, Any]) -> dict[str, Any]:
        date_from = args.get("from") or args.get("from_date")
        date_to = args.get("to") or args.get("to_date")
        rows = await self.app.tasks.list(
            principal, date_from=date_from, date_to=date_to, limit=50
        )
        return {
            "ok": True,
            "count": len(rows),
            "tasks": [
                {
                    "id": row["id"],
                    "title": row["title"],
                    "start_at": row["start_at"],
                    "status": row["status"],
                }
                for row in rows
            ],
        }

    async def _update_task_status(self, principal: Any, session_id: str | None, args: dict[str, Any]) -> dict[str, Any]:
        reference = str(args.get("task_id_or_keyword") or "").strip()
        status = str(args.get("status") or "done")
        if status not in ("done", "skipped"):
            return {"ok": False, "error": "status 只能是 done 或 skipped"}
        task = await self.app.tasks.get(principal, reference)
        if task is None:
            task = await self.app.tasks.resolve_reference(principal, reference)
        if task is None:
            return {"ok": False, "error": f"没找到任务：{reference}"}
        updated = await self.app.tasks.set_status(principal, task["id"], status)
        return {"ok": True, "task": updated, "display": f"已标记「{updated['title']}」为 {status}"}

    async def _create_plan(self, principal: Any, session_id: str | None, args: dict[str, Any]) -> dict[str, Any]:
        plan = await self.app.plans.generate(
            principal,
            goal=str(args.get("goal") or args.get("title") or ""),
            daily_minutes=int(args.get("daily_minutes") or 30),
            deadline=args.get("deadline"),
            title=args.get("title"),
        )
        from ..commands import render_plan_preview

        preview = render_plan_preview(self.app, plan)
        return {
            "ok": True,
            "plan": {
                "id": plan["id"],
                "title": plan["title"],
                "items": len(plan["items"]),
                "total_minutes": plan["total_minutes"],
                "deadline": plan["deadline"],
            },
            "preview": preview,
            "display": "计划已生成（仅预览，未写入日程）",
            "needs_confirmation": True,
        }

    async def _apply_plan(self, principal: Any, session_id: str | None, args: dict[str, Any]) -> dict[str, Any]:
        # 永远不自动执行：返回「需要用户确认」，由 /apply 或 App 点击触发
        plan_id = str(args.get("plan_id") or "latest")
        if plan_id == "latest":
            plan = await self.app.plans.latest_draft(principal)
            plan_id = plan["id"] if plan else ""
        return {
            "ok": False,
            "needs_confirmation": True,
            "plan_id": plan_id,
            "error": "写入日程需要用户确认：请提示用户发送 /apply 或在 App 里点「写入日程」",
        }

    async def _query_stats(self, principal: Any, session_id: str | None, args: dict[str, Any]) -> dict[str, Any]:
        range_key = str(args.get("range") or "week")
        if range_key not in ("today", "week", "month"):
            range_key = "week"
        stats = await self.app.stats.overview(principal, range_key)
        return {"ok": True, "range": range_key, "stats": stats}

    async def _save_memory(self, principal: Any, session_id: str | None, args: dict[str, Any]) -> dict[str, Any]:
        kind = str(args.get("kind") or "fact")
        content = str(args.get("content") or "").strip()
        if not content:
            return {"ok": False, "error": "缺少 content"}
        note = await self.app.memories.save_note(
            principal,
            kind=kind,
            content=content,
            tags=args.get("tags") or [],
            importance=int(args.get("importance") or 3),
            source="ai",
            source_ref=None,
        )
        return {"ok": True, "note": note, "display": "已记住"}


def parse_tool_payload(text: str) -> dict[str, Any] | None:
    """从模型输出里抠出 ``{"reply":..., "tool_calls":[...]}``。

    容忍 ```json 代码块与前后废话；解析失败返回 None。
    """
    if not text:
        return None
    candidate = text.strip()
    if candidate.startswith("```"):
        lines = [line for line in candidate.splitlines() if not line.strip().startswith("```")]
        candidate = "\n".join(lines)
    try:
        data = json.loads(candidate)
        if isinstance(data, dict) and ("reply" in data or "tool_calls" in data):
            return data
    except ValueError:
        pass
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start >= 0 and end > start:
        try:
            data = json.loads(candidate[start : end + 1])
            if isinstance(data, dict) and ("reply" in data or "tool_calls" in data):
                return data
        except ValueError:
            return None
    return None


def validate_tool_args(name: str, args: Any) -> tuple[dict[str, Any], str | None]:
    """轻量参数校验：只保证「是 dict 且必需字段存在」，类型细化交给各工具。"""
    if not isinstance(args, dict):
        return {}, f"{name} 的 args 必须是对象"
    required = {
        # start_at 故意不放在必填里：交给工具自己回「请先问用户具体时间」，
        # 比统一的「缺少参数」对模型更有指引意义
        "create_task": ("title",),
        "list_tasks": (),
        "update_task_status": ("task_id_or_keyword", "status"),
        "create_plan": ("goal",),
        "apply_plan": (),
        "query_stats": (),
        "save_memory": ("kind", "content"),
    }.get(name, ())
    missing = [key for key in required if not args.get(key)]
    if missing:
        return args, f"{name} 缺少参数：{', '.join(missing)}"
    return args, None


def bad_tool_call(name: str) -> dict[str, Any]:
    raise invalid(f"未知工具：{name}")
