"""记忆适配器：null / generic_tool / livingmemory 探测与降级。"""

from __future__ import annotations

import pytest

from adapters import MemoryManager, NullAdapter
from adapters.generic_tool import GenericToolAdapter
from adapters.livingmemory import LivingMemoryAdapter

from tests.conftest import make_settings
from tests.harness.fake_astrbot import (
    FakeContext,
    FakeLivingMemoryPlugin,
    FakeStarMetadata,
    FakeTool,
)

pytestmark = pytest.mark.asyncio


async def test_null_adapter_is_always_ok(app):
    adapter = NullAdapter(app)
    assert await adapter.probe() is True
    assert adapter.status.ok is True
    assert adapter.status.degraded is True
    assert await adapter.upsert(source_ref="x", content="y") == ""
    assert await adapter.delete("x") is True
    assert await adapter.export(None) == ([], None)


async def test_default_order_falls_back_to_null(app):
    """没有 AstrBot Context / 工具注册表时，最终必须落到 none 且状态正常。"""
    names = [attempt["name"] for attempt in app.memory_manager.attempts]
    assert names[-1] == "none"
    assert app.memory_manager.active.name == "none"
    assert app.memory_manager.active.status.ok is True


async def test_generic_tool_probe_and_call(tmp_path):
    from core.app import StudyApp

    tool = FakeTool(name="remember")
    context = FakeContext(tools=[tool])
    settings = make_settings({"memory": {"adapter_order": ["generic_tool", "none"]}})
    application = StudyApp(data_dir=tmp_path, cfg=settings, context=context)
    await application.startup()
    try:
        assert application.memory_manager.active.name == "generic_tool"
        adapter = application.memory_manager.active
        ref = await adapter.upsert(
            source_ref="note-1", content="用户晚上八点后有空", tags=["时间"], importance=4
        )
        assert ref
        assert tool.calls[0]["kwargs"]["text"] == "用户晚上八点后有空"
        assert await adapter.delete("note-1") is False  # 未配置删除工具 -> 不支持
    finally:
        await application.shutdown()


async def test_generic_tool_missing_tool_degrades(tmp_path):
    context = FakeContext(tools=[])
    settings = make_settings({"memory": {"adapter_order": ["generic_tool", "none"]}})
    from core.app import StudyApp

    application = StudyApp(data_dir=tmp_path, cfg=settings, context=context)
    await application.startup()
    try:
        attempts = {item["name"]: item for item in application.memory_manager.attempts}
        assert attempts["generic_tool"]["ok"] is False
        assert "未找到写入工具" in attempts["generic_tool"]["reason"]
        assert application.memory_manager.active.name == "none"
    finally:
        await application.shutdown()


async def test_livingmemory_probe_success(tmp_path):
    from core.app import StudyApp

    plugin = FakeLivingMemoryPlugin()
    context = FakeContext(
        stars={
            "astrbot_plugin_livingmemory": FakeStarMetadata(
                name="astrbot_plugin_livingmemory", version="2.13.0", star_cls=plugin
            )
        }
    )
    settings = make_settings(
        {"memory": {"adapter_order": ["livingmemory", "none"], "sync_mode": "upload_only"}}
    )
    application = StudyApp(data_dir=tmp_path, cfg=settings, context=context)
    await application.startup()
    try:
        adapter = application.memory_manager.active
        assert isinstance(adapter, LivingMemoryAdapter)
        assert adapter.status.ok is True
        ref = await adapter.upsert(
            source_ref="note-2", content="用户准备考研", tags=["goal"], importance=5
        )
        engine = plugin.engine
        assert ref.isdigit()
        assert engine.added[0]["importance"] == pytest.approx(0.95)
        assert engine.added[0]["metadata"]["topics"] == ["goal"]
        assert "study:note-2" in engine.added[0]["session_id"]
    finally:
        await application.shutdown()


async def test_livingmemory_version_mismatch_degrades(tmp_path):
    from core.app import StudyApp

    context = FakeContext(
        stars={
            "astrbot_plugin_livingmemory": FakeStarMetadata(
                name="astrbot_plugin_livingmemory",
                version="1.9.0",
                star_cls=FakeLivingMemoryPlugin(),
            )
        }
    )
    settings = make_settings({"memory": {"adapter_order": ["livingmemory", "none"]}})
    application = StudyApp(data_dir=tmp_path, cfg=settings, context=context)
    await application.startup()
    try:
        attempts = {item["name"]: item for item in application.memory_manager.attempts}
        assert attempts["livingmemory"]["ok"] is False
        assert "版本不兼容" in attempts["livingmemory"]["reason"]
        assert application.memory_manager.active.name == "none"
    finally:
        await application.shutdown()


async def test_livingmemory_delete_uses_engine(tmp_path):
    from core.app import StudyApp

    plugin = FakeLivingMemoryPlugin()
    context = FakeContext(
        stars={
            "astrbot_plugin_livingmemory": FakeStarMetadata(
                name="astrbot_plugin_livingmemory", version="2.13.0", star_cls=plugin
            )
        }
    )
    settings = make_settings({"memory": {"adapter_order": ["livingmemory", "none"]}})
    application = StudyApp(data_dir=tmp_path, cfg=settings, context=context)
    await application.startup()
    try:
        adapter = application.memory_manager.active
        ref = await adapter.upsert(source_ref="n3", content="待删除", importance=3)
        assert await adapter.delete(ref) is True
        assert plugin.engine.deleted == [int(ref)]
        assert await adapter.delete("not-a-number") is False
    finally:
        await application.shutdown()


async def test_manager_order_and_failure_isolation(tmp_path):
    from core.app import StudyApp

    settings = make_settings({"memory": {"adapter_order": ["unknown_adapter", "none"]}})
    application = StudyApp(data_dir=tmp_path, cfg=settings)
    await application.startup()
    try:
        attempts = application.memory_manager.attempts
        assert attempts[0]["name"] == "unknown_adapter"
        assert attempts[0]["ok"] is False
        assert application.memory_manager.active.name == "none"
        describe = MemoryManager(application).describe()
        assert describe["sync_mode"] in ("off", "upload_only", "bidirectional")
    finally:
        await application.shutdown()


async def test_generic_tool_search_parses_results(tmp_path):
    from core.app import StudyApp

    class SearchTool(FakeTool):
        def __post_init__(self):
            base = self

            async def _handler(*args, **kwargs):
                base.calls.append({"kwargs": kwargs})
                return {"results": [{"content": "晚上有空", "id": 3}, "纯文本结果"]}

            self.handler = _handler

    tools = [FakeTool(name="remember"), SearchTool(name="recall")]
    context = FakeContext(tools=tools)
    settings = make_settings({"memory": {"adapter_order": ["generic_tool", "none"]}})
    application = StudyApp(data_dir=tmp_path, cfg=settings, context=context)
    await application.startup()
    try:
        adapter = application.memory_manager.active
        assert isinstance(adapter, GenericToolAdapter)
        entries = await adapter.search("我什么时候有空")
        assert len(entries) == 2
        assert entries[0]["content"] == "晚上有空"
        assert entries[1]["content"] == "纯文本结果"
    finally:
        await application.shutdown()
