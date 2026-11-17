"""QQ 指令层：只做参数解析、权限、格式化，业务全部调 service。

命名策略（红线：不抢别人的指令名）：
- 规范短指令（``/add`` ``/today`` ...）与 ``/study <sub>`` 两种入口指向同一实现；
- 如果短指令与其他插件冲突，用户随时可以用 ``/study add ...``，行为完全一致。
"""

from __future__ import annotations

from typing import Any

from .bridge import filter
from .errors import ApiError
from .principal import Principal
from .util import dumps, get_tz, iso, local_date, utcnow

HELP_TEXT_ORDER = (
    "bind",
    "whoami",
    "unbind",
    "addr",
    "umo",
    "settings",
    "today",
    "tomorrow",
    "week",
    "add",
    "done",
    "del",
    "plan",
    "apply",
    "report",
    "export",
    "memory",
    "forget",
    "reset",
)

COMMANDS = {
    "help": "指令列表",
    "bind": "绑定 App",
    "whoami": "当前主体",
    "unbind": "吊销设备",
    "addr": "服务地址",
    "umo": "当前会话 UMO",
    "settings": "个人设置",
    "today": "今日日程",
    "tomorrow": "明日日程",
    "week": "本周概览",
    "add": "新增任务",
    "done": "完成任务",
    "del": "删除任务",
    "plan": "计划",
    "apply": "写入日程",
    "report": "报表",
    "export": "导出数据",
    "memory": "记忆",
    "forget": "删除记忆",
    "reset": "清空会话",
}


def render_plan_preview(app: Any, plan: dict[str, Any]) -> str:
    """计划预览文本（``/plan new`` 与 AI 工具共用）。"""
    items = plan.get("items") or []
    lines = []
    for item in items[:14]:
        lines.append(
            f"{item['seq']:>2}. {item['scheduled_date']} · {item['duration_min']:>3} 分钟 · {item['title']}"
        )
    if len(items) > 14:
        lines.append(f"... 其余 {len(items) - 14} 项")
    return app.t(
        "cmd.plan.preview",
        title=plan.get("title") or "",
        goal=plan.get("goal") or "—",
        deadline=plan.get("deadline") or "—",
        daily=plan.get("daily_minutes") or 0,
        items=len(items),
        total_minutes=plan.get("total_minutes") or 0,
        preview="\n".join(lines),
    )


class StudyCommands:
    """所有 QQ / IM 指令的实现。"""

    def __init__(self, app: Any) -> None:
        self.app = app

    # ------------------------------------------------------------ 入口
    async def dispatch(self, event: Any, name: str, arg: str = "") -> str:
        principal: Principal | None = None
        try:
            principal = await self.app.principal_for_event(event)
            if not self._allowed(event):
                await self._log(event, principal, name, arg, "denied")
                return self.app.t("cmd.error.unauthorized")
            handler = getattr(self, f"_do_{name}", None)
            if handler is None:
                return self.app.t("cmd.help.body")
            reply = await handler(event, principal, (arg or "").strip())
            await self._log(event, principal, name, arg, (reply or "")[:500])
            return reply
        except ApiError as exc:
            await self._log(event, principal, name, arg, f"error:{exc.code}")
            return f"⚠️ {exc.message}"
        except Exception as exc:  # noqa: BLE001 - 指令绝不抛堆栈给用户
            self.app.logger.exception("指令 %s 执行失败: %s", name, exc)
            await self._log(event, principal, name, arg, f"exception:{exc}")
            return self.app.t("cmd.error.generic")

    def _allowed(self, event: Any) -> bool:
        if _call_bool(event, "is_admin"):
            return True
        cfg = self.app.cfg
        allowed_qq = {str(item) for item in cfg.get_list("scope.allowed_qq", [])}
        allowed_groups = {str(item) for item in cfg.get_list("scope.allowed_groups", [])}
        sender = _call_str(event, "get_sender_id")
        group = _call_str(event, "get_group_id")
        if not allowed_qq and not allowed_groups:
            return False  # 默认只允许机器人主人
        if group:
            if sender in allowed_qq:
                return True
            return group in allowed_groups
        return sender in allowed_qq

    async def _log(
        self,
        event: Any,
        principal: Principal | None,
        name: str,
        arg: str,
        reply: str,
    ) -> None:
        try:
            await self.app.db.execute(
                "INSERT INTO command_log (owner_principal_id, umo, text, reply, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    principal.id if principal else None,
                    _call_str(event, "get_umo") or str(getattr(event, "unified_msg_origin", ""))[:200],
                    f"/{name} {arg}"[:400],
                    reply[:500],
                    iso(utcnow()),
                ),
            )
        except Exception:  # noqa: BLE001 - 日志失败不影响指令
            pass

    # ------------------------------------------------------------ 指令实现
    async def _do_help(self, event: Any, principal: Principal, arg: str) -> str:
        return self.app.t("cmd.help.body")

    async def _do_bind(self, event: Any, principal: Principal, arg: str) -> str:
        if not _call_bool(event, "is_private_chat"):
            return self.app.t("cmd.bind.private_only")
        code = arg.split()[0] if arg else ""
        if not code or not code.isdigit() or len(code) != 6:
            return self.app.t("cmd.bind.usage")
        status, key = await self.app.auth.claim_from_qq(principal, code)
        if status == "blocked":
            return self.app.t(key, minutes=10)
        devices = await self.app.auth.me(principal)
        return self.app.t(key, devices=devices["device_count"])

    async def _do_whoami(self, event: Any, principal: Principal, arg: str) -> str:
        me = await self.app.auth.me(principal)
        ai_state = (
            self.app.t("cmd.whoami.ai_on")
            if me["can_use_ai"]
            else self.app.t("cmd.whoami.ai_off")
        )
        return self.app.t(
            "cmd.whoami.body",
            kind=principal.kind,
            external_id=principal.external_id,
            devices=me["device_count"],
            ai_state=ai_state,
        )

    async def _do_unbind(self, event: Any, principal: Principal, arg: str) -> str:
        if not arg:
            return self.app.t("cmd.unbind.usage")
        count = await self.app.auth.unbind_by_label(principal, arg)
        if not count:
            return self.app.t("cmd.unbind.none", label=arg)
        return self.app.t("cmd.unbind.ok", count=count, label=arg)

    async def _do_addr(self, event: Any, principal: Principal, arg: str) -> str:
        if not self.app.cfg.get_bool("http.enabled", True):
            return self.app.t("cmd.addr.disabled")
        base = self.app.cfg.get_str("http.public_base_url", "")
        if not base:
            host = self.app.cfg.get_str("http.host", "0.0.0.0")
            port = self.app.cfg.get_int("http.port", 6188)
            if host in ("0.0.0.0", "::"):
                host = "你的机器内网IP或域名"
            base = f"http://{host}:{port}"
        return self.app.t("cmd.addr.enabled", url=base.rstrip("/") + "/study/")

    async def _do_umo(self, event: Any, principal: Principal, arg: str) -> str:
        umo = str(getattr(event, "unified_msg_origin", "") or "")
        return self.app.t("cmd.umo.body", umo=umo or "（当前平台未提供 UMO）")

    async def _do_settings(self, event: Any, principal: Principal, arg: str) -> str:
        parts = arg.split()
        if not parts:
            data = await self.app.settings.get_all(principal)
            return self.app.t(
                "cmd.settings.show",
                tz=data["tz"],
                brief=data["brief"],
                nudge=data["nudge"],
                offsets=data["offsets"],
                duration=data["duration"],
            )
        if len(parts) < 2:
            return self.app.t("cmd.settings.usage")
        key, value = parts[0].lower(), " ".join(parts[1:])
        try:
            result = await self.app.settings.set(principal, key, value)
        except ApiError as exc:
            return self.app.t("cmd.settings.bad_value", value=exc.message)
        return self.app.t("cmd.settings.updated", key=result["key"], value=result["value"])

    async def _do_today(self, event: Any, principal: Principal, arg: str) -> str:
        return await self._day_text(principal, 0)

    async def _do_tomorrow(self, event: Any, principal: Principal, arg: str) -> str:
        return await self._day_text(principal, 1)

    async def _day_text(self, principal: Principal, offset: int) -> str:
        view = await self.app.tasks.day_view(principal, offset)
        if not view["items"]:
            return self.app.t("cmd.list.empty")
        lines = [
            self.app.t(
                "cmd.today.title" if offset == 0 else "cmd.tomorrow.title",
                date=view["date"],
                total=view["total"],
                done=view["done"],
                rate=view["rate"],
            )
        ]
        for index, item in enumerate(view["items"], start=1):
            mark = {
                "done": self.app.t("cmd.mark.done"),
                "skipped": self.app.t("cmd.mark.skip"),
            }.get(item["status"], self.app.t("cmd.mark.pending"))
            lines.append(
                self.app.t(
                    "cmd.list.item",
                    idx=index,
                    mark=mark,
                    time=item["local_start"] or "全天",
                    title=item["title"],
                )
            )
        if view["overdue"]:
            lines.append(self.app.t("cmd.list.overdue", count=view["overdue"]))
        return "\n".join(lines)

    async def _do_week(self, event: Any, principal: Principal, arg: str) -> str:
        view = await self.app.tasks.week_view(principal)
        lines = [
            self.app.t(
                "cmd.week.title",
                start=view["start"],
                end=view["end"],
                total=view["total"],
                done=view["done"],
                rate=view["rate"],
            )
        ]
        for item in view["items"][:20]:
            lines.append(
                f"{item['local_date']} {item['local_start'] or '全天'} · {item['title']}"
                f"（{item['status']}）"
            )
        if not view["items"]:
            lines.append(self.app.t("cmd.list.empty"))
        return "\n".join(lines)

    async def _do_add(self, event: Any, principal: Principal, arg: str) -> str:
        if not arg:
            return self.app.t("cmd.add.usage")
        parsed = await self.app.tasks.parse(principal, arg)
        draft = parsed.get("draft") or {}
        if not draft.get("start_at"):
            return self.app.t("cmd.add.need_time")
        try:
            task = await self.app.tasks.create(
                principal,
                {
                    "title": draft["title"],
                    "start_at": draft["start_at"],
                    "end_at": draft["end_at"],
                    "priority": draft.get("priority", 2),
                    "remind_offsets": draft.get("remind_offsets"),
                },
                source="qq",
            )
        except ApiError as exc:
            return self.app.t("cmd.add.failed", reason=exc.message)
        text = self.app.t(
            "cmd.add.ok",
            title=task["title"],
            start=f"{task['local_date']} {task['local_start']}",
            end=task["local_end"],
            source=task["source"],
        )
        if parsed.get("source") == "rule":
            text += "\n" + self.app.t("cmd.add.rule")
        return text

    async def _do_done(self, event: Any, principal: Principal, arg: str) -> str:
        if not arg:
            return self.app.t("cmd.done.usage")
        task = await self.app.tasks.resolve_reference(principal, arg)
        if task is None:
            return self.app.t("cmd.done.not_found", query=arg)
        await self.app.tasks.set_status(principal, task["id"], "done")
        return self.app.t("cmd.done.ok", title=task["title"])

    async def _do_del(self, event: Any, principal: Principal, arg: str) -> str:
        if not arg:
            return self.app.t("cmd.del.usage")
        task = await self.app.tasks.resolve_reference(principal, arg)
        if task is None:
            return self.app.t("cmd.del.not_found", idx=arg)
        await self.app.tasks.delete(principal, task["id"])
        return self.app.t("cmd.del.ok", title=task["title"])

    async def _do_plan(self, event: Any, principal: Principal, arg: str) -> str:
        parts = arg.split(maxsplit=1)
        sub = parts[0].lower() if parts else ""
        rest = parts[1] if len(parts) > 1 else ""
        if sub == "new":
            if not rest:
                return self.app.t("cmd.plan.usage")
            settings = await self.app.settings.get_all(principal)
            tz = settings["tz"]
            deadline = (local_date(tz) + __import__("datetime").timedelta(days=13)).isoformat()
            try:
                plan = await self.app.plans.generate(
                    principal,
                    goal=rest,
                    daily_minutes=int(settings["duration"]) * 2,
                    deadline=deadline,
                )
            except ApiError as exc:
                return self.app.t("cmd.add.failed", reason=exc.message)
            if not plan.get("items"):
                return self.app.t("cmd.plan.empty")
            return render_plan_preview(self.app, plan)
        if sub == "list" or not sub:
            plans = await self.app.plans.list(principal)
            if not plans:
                return self.app.t("cmd.plan.list.empty")
            lines = [self.app.t("cmd.plan.list.title", count=len(plans))]
            for index, plan in enumerate(plans, start=1):
                lines.append(
                    self.app.t(
                        "cmd.plan.list.item",
                        idx=index,
                        status=plan.get("status"),
                        title=plan.get("title"),
                        applied="已写入" if plan.get("applied_at") else "未写入",
                        id=plan.get("id"),
                    )
                )
            return "\n".join(lines)
        if sub == "show":
            plan = await self.app.plans.get(principal, rest.strip())
            if plan is None:
                return self.app.t("cmd.plan.not_found", plan_id=rest.strip())
            lines = [
                self.app.t(
                    "cmd.plan.show.title",
                    title=plan["title"],
                    goal=plan.get("goal") or "—",
                    deadline=plan.get("deadline") or "—",
                    daily=plan.get("daily_minutes") or 0,
                    status=plan.get("status"),
                )
            ]
            for item in plan["items"][:30]:
                lines.append(
                    self.app.t(
                        "cmd.plan.show.item",
                        idx=item["seq"],
                        date=item["scheduled_date"],
                        duration=item["duration_min"],
                        title=item["title"],
                        status=item["status"],
                    )
                )
            return "\n".join(lines)
        return self.app.t("cmd.plan.usage")

    async def _do_apply(self, event: Any, principal: Principal, arg: str) -> str:
        plan = await self.app.plans.latest_draft(principal)
        if plan is None:
            return self.app.t("cmd.plan.nothing")
        try:
            result = await self.app.plans.apply(principal, plan["id"])
        except ApiError as exc:
            return f"⚠️ {exc.message}"
        if result["created"] == 0:
            return self.app.t("cmd.plan.applied_none")
        return self.app.t(
            "cmd.plan.applied", created=result["created"], skipped=result["skipped"]
        )

    async def _do_report(self, event: Any, principal: Principal, arg: str) -> str:
        range_key = "week"
        arg = arg.strip().lower()
        if arg.startswith("m") or "月" in arg:
            range_key = "month"
        elif arg.startswith("w") or "周" in arg:
            range_key = "week"
        return await self.app.stats.text_report(principal, range_key)

    async def _do_export(self, event: Any, principal: Principal, arg: str) -> str:
        data = await self.app.export.dump(principal)
        text = dumps(data)
        chunks = [text[i : i + 1200] for i in range(0, len(text), 1200)]
        if len(chunks) == 1:
            return self.app.t("cmd.export.done", size=len(text) // 1024, parts=1) + "\n" + chunks[0]
        parts = []
        for index, chunk in enumerate(chunks[:10], start=1):
            parts.append(f"({index}/{min(len(chunks), 10)})\n{chunk}")
        return self.app.t(
            "cmd.export.done", size=len(text) // 1024, parts=min(len(chunks), 10)
        ) + "\n\n" + "\n\n".join(parts)

    async def _do_memory(self, event: Any, principal: Principal, arg: str) -> str:
        notes = await self.app.memories.list_notes(principal, limit=20)
        if not notes:
            return self.app.t("cmd.memory.empty")
        lines = [self.app.t("cmd.memory.title", count=len(notes))]
        for index, note in enumerate(notes, start=1):
            lines.append(
                self.app.t("cmd.memory.item", idx=index, kind=note["kind"], content=note["content"])
            )
        adapter = self.app.memory_manager.active
        if adapter.name in ("none",):
            lines.append(self.app.t("cmd.memory.degraded"))
        return "\n".join(lines)

    async def _do_forget(self, event: Any, principal: Principal, arg: str) -> str:
        if not arg.isdigit():
            return self.app.t("cmd.memory.forget.usage")
        index = int(arg)
        notes = await self.app.memories.list_notes(principal, limit=20)
        if not 1 <= index <= len(notes):
            return self.app.t("cmd.memory.forget.not_found", idx=index)
        note = notes[index - 1]
        await self.app.memories.delete_note(principal, note["id"])
        return self.app.t("cmd.memory.forget.ok", content=note["content"][:40])

    async def _do_reset(self, event: Any, principal: Principal, arg: str) -> str:
        umo = str(getattr(event, "unified_msg_origin", "") or "default")
        await self.app.chat.reset(principal, session_key=umo)
        return self.app.t("cmd.reset.ok")


def _call_str(event: Any, method: str) -> str:
    fn = getattr(event, method, None)
    if callable(fn):
        try:
            value = fn()
            return str(value) if value else ""
        except Exception:  # noqa: BLE001
            return ""
    return ""


def _call_bool(event: Any, method: str) -> bool:
    fn = getattr(event, method, None)
    if callable(fn):
        try:
            return bool(fn())
        except Exception:  # noqa: BLE001
            return False
    return False


_ = (get_tz,)
