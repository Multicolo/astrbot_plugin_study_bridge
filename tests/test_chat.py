"""对话 pipeline：工具循环、参数校验回灌、二次确认、轮次上限、记忆注入。"""

from __future__ import annotations

from datetime import timedelta

import pytest

from core.llm import LLMError
from core.util import iso, local_date

pytestmark = pytest.mark.asyncio


def _task_args(hour: int = 15) -> dict:
    from datetime import datetime, time

    from core.util import get_tz

    tz = get_tz("Asia/Shanghai")
    day = local_date(tz) + timedelta(days=1)
    start = datetime.combine(day, time(hour, 0), tzinfo=tz)
    return {
        "title": "背单词",
        "start_at": iso(start),
        "end_at": iso(start + timedelta(hours=1)),
    }


async def test_plain_reply(app, principal):
    app.llm.push({"reply": "你好，我是学习助手", "tool_calls": []})
    result = await app.chat.handle(principal, text="你好", session_key="s1")
    assert result["reply"] == "你好，我是学习助手"
    assert result["tool_calls"] == []
    assert result["ai"] is True


async def test_creates_task_via_tool(app, principal):
    app.llm.push(
        {
            "reply": "好的",
            "tool_calls": [{"name": "create_task", "args": _task_args()}],
        }
    )
    app.llm.push({"reply": "已经写进明天下午 3 点了", "tool_calls": []})
    result = await app.chat.handle(principal, text="明天下午3点背单词一小时", session_key="s2")
    tasks = await app.tasks.list(principal)
    assert len(tasks) == 1
    assert tasks[0]["title"] == "背单词"
    assert result["reply"].startswith("已经")
    assert result["tool_calls"][0]["ok"] is True


async def test_tool_argument_error_is_fed_back(app, principal):
    app.llm.push(
        {
            "reply": "这就建",
            "tool_calls": [{"name": "create_task", "args": {"title": "背单词"}}],
        }
    )
    app.llm.push({"reply": "请告诉我具体几点？", "tool_calls": []})
    result = await app.chat.handle(principal, text="背单词", session_key="s3")
    assert result["tool_calls"][0]["ok"] is False
    assert "缺少明确开始时间" in str(result["tool_calls"][0]["result"])
    assert await app.tasks.list(principal) == []
    # 工具失败结果必须回灌给模型（第 2 轮 prompt 里出现）
    assert any("缺少明确开始时间" in prompt for prompt in app.llm.prompts[1:])


async def test_apply_plan_never_auto_executes(app, principal):
    today = local_date("Asia/Shanghai")
    app.llm.push(
        {
            "title": "小计划",
            "items": [
                {"seq": 1, "title": "第一章", "scheduled_date": today.isoformat(), "duration_min": 30}
            ],
        }
    )
    plan = await app.plans.generate(
        principal, goal="x", daily_minutes=60, deadline=(today + timedelta(days=5)).isoformat()
    )
    app.llm.push(
        {
            "reply": "要不要写入？",
            "tool_calls": [{"name": "apply_plan", "args": {"plan_id": plan["id"]}}],
        }
    )
    app.llm.push({"reply": "发 /apply 就能写入", "tool_calls": []})
    result = await app.chat.handle(principal, text="把计划写进日程", session_key="s4")
    assert result["tool_calls"][0]["ok"] is False
    assert result["tool_calls"][0]["result"]["needs_confirmation"] is True
    refreshed = await app.plans.get(principal, plan["id"])
    assert refreshed["applied_at"] is None
    assert await app.tasks.list(principal) == []


async def test_create_plan_returns_preview(app, principal):
    today = local_date("Asia/Shanghai")
    deadline = (today + timedelta(days=5)).isoformat()
    app.llm.push(
        {
            "reply": "我来拆一下计划",
            "tool_calls": [
                {
                    "name": "create_plan",
                    "args": {"goal": "考研数学", "daily_minutes": 60, "deadline": deadline},
                }
            ],
        }
    )
    # 第 2 轮：plans.generate 内部向模型要计划条目
    app.llm.push(
        {
            "title": "周计划",
            "items": [
                {"seq": 1, "title": "第一章", "scheduled_date": today.isoformat(), "duration_min": 30}
            ],
        }
    )
    app.llm.push({"reply": "计划已生成，只是预览", "tool_calls": []})
    result = await app.chat.handle(principal, text="帮我定个计划", session_key="s5")
    assert result["plan_draft"] is not None
    assert result["tool_calls"][0]["result"]["needs_confirmation"] is True
    # 只是预览：没有写入日程
    assert await app.tasks.list(principal) == []


async def test_max_tool_rounds(app, principal):
    app.cfg._raw["ai.max_tool_rounds"] = 2
    for _ in range(3):
        app.llm.push(
            {
                "reply": "继续",
                "tool_calls": [{"name": "list_tasks", "args": {}}],
            }
        )
    result = await app.chat.handle(principal, text="查任务", session_key="s6")
    assert len(result["tool_calls"]) >= 2
    assert result["reply"]


async def test_llm_error_is_friendly(app, principal):
    app.llm.push(LLMError("上游超时"))
    result = await app.chat.handle(principal, text="你好", session_key="s7")
    assert result["ai"] is False
    assert "AI" in result["reply"]


async def test_ai_disabled_for_principal(app, principal):
    app.cfg._raw["ai.allow_principal_ai"] = False
    result = await app.chat.handle(principal, text="你好", session_key="s8")
    assert result["ai"] is False
    assert app.llm.prompts == []  # 一次模型都没调


async def test_memory_injected_into_system_prompt(app, principal):
    from core.principal import get_or_create

    await app.memories.save_note(
        principal, kind="preference", content="用户晚上八点后才有空", importance=4
    )
    app.llm.push({"reply": "好", "tool_calls": []})
    await app.chat.handle(principal, text="我什么时候有空", session_key="s9")
    system = app.llm.systems[0] or ""
    assert "用户晚上八点后才有空" in system
    _ = get_or_create


async def test_save_memory_tool(app, principal):
    app.llm.push(
        {
            "reply": "记住了",
            "tool_calls": [
                {
                    "name": "save_memory",
                    "args": {"kind": "preference", "content": "喜欢在图书馆学习", "importance": 4},
                }
            ],
        }
    )
    app.llm.push({"reply": "已记住你的偏好", "tool_calls": []})
    result = await app.chat.handle(principal, text="我喜欢在图书馆学习", session_key="s10")
    notes = await app.memories.list_notes(principal)
    assert len(notes) == 1
    assert notes[0]["source"] == "ai"
    assert result["tool_calls"][0]["ok"] is True


async def test_history_and_reset(app, principal):
    app.llm.push({"reply": "第一次回复", "tool_calls": []})
    await app.chat.handle(principal, text="第一句", session_key="s11")
    history = await app.chat.history(principal, session_key="s11")
    contents = [row["content"] for row in history["messages"]]
    assert "第一句" in contents
    assert "第一次回复" in contents
    await app.chat.reset(principal, session_key="s11")
    emptied = await app.chat.history(principal, session_key="s11")
    assert emptied["messages"] == []


async def test_ai_action_log_written(app, principal):
    app.llm.push(
        {"reply": "ok", "tool_calls": [{"name": "list_tasks", "args": {}}]}
    )
    app.llm.push({"reply": "查完了", "tool_calls": []})
    await app.chat.handle(principal, text="看看任务", session_key="s12")
    rows = await app.db.fetch_all(
        "SELECT tool_name, ok FROM ai_action_log WHERE owner_principal_id = ?", (principal.id,)
    )
    assert rows and rows[0]["tool_name"] == "list_tasks"
    assert rows[0]["ok"] == 1


async def test_non_json_reply_is_treated_as_text(app, principal):
    app.llm.push("这是一段普通文本，不是 JSON")
    result = await app.chat.handle(principal, text="随便聊聊", session_key="s13")
    assert result["reply"].startswith("这是一段普通文本")
