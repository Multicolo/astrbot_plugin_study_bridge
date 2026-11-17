"""测试替身：没有 AstrBot 运行时也能验证插件逻辑。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FakeMessage:
    text: str

    def __repr__(self) -> str:  # pragma: no cover
        return f"FakeMessage({self.text!r})"


class FakeEvent:
    """模拟 AstrMessageEvent 的最小面（UMO / 发送者 / 群 / 权限）。"""

    def __init__(
        self,
        *,
        sender_id: str = "10001",
        umo: str = "qq:FriendMessage:10001",
        group_id: str = "",
        is_admin: bool = False,
        sender_name: str = "tester",
        message: str = "",
    ) -> None:
        self.unified_msg_origin = umo
        self._sender_id = sender_id
        self._group_id = group_id
        self._is_admin = is_admin
        self._sender_name = sender_name
        self.message_str = message

    def get_sender_id(self) -> str:
        return self._sender_id

    def get_group_id(self) -> str:
        return self._group_id

    def is_private_chat(self) -> bool:
        return not self._group_id

    def is_admin(self) -> bool:
        return self._is_admin

    def get_sender_name(self) -> str:
        return self._sender_name

    def get_message_str(self) -> str:
        return self.message_str

    def plain_result(self, text: str) -> FakeMessage:
        return FakeMessage(text)


@dataclass
class FakeTool:
    """模拟 AstrBot 注册给 LLM 的 FunctionTool。"""

    name: str
    description: str = ""
    calls: list[dict[str, Any]] = field(default_factory=list)
    handler: Any = None

    def __post_init__(self) -> None:
        base = self

        async def _handler(*args: Any, **kwargs: Any) -> str:
            base.calls.append({"args": args, "kwargs": kwargs})
            return f"stored:{kwargs.get('text') or kwargs.get('query') or ''}"

        if self.handler is None:
            self.handler = _handler


class FakeToolManager:
    def __init__(self, tools: list[FakeTool] | None = None) -> None:
        self.func_list = list(tools or [])

    def get_func(self, name: str) -> FakeTool | None:
        for tool in self.func_list:
            if tool.name == name:
                return tool
        return None


@dataclass
class FakeProvider:
    provider_id: str = "prov-openai"
    model: str = "gpt-4o-mini"
    provider_type: str = "openai"

    def meta(self):
        class _Meta:
            id = self.provider_id
            model = self.model
            type = self.provider_type

        return _Meta()

    async def text_chat(self, prompt: str | None = None, system_prompt: str | None = None, **_: Any):
        class _Resp:
            completion_text = "ok"

        return _Resp()


class FakeContext:
    """模拟 AstrBot 的 ``Context``：provider 列表、工具注册表、插件注册表。"""

    def __init__(
        self,
        *,
        providers: list[FakeProvider] | None = None,
        tools: list[FakeTool] | None = None,
        stars: dict[str, Any] | None = None,
        send_result: bool = True,
    ) -> None:
        self.providers = providers if providers is not None else [FakeProvider()]
        self.tool_manager = FakeToolManager(tools)
        self.stars = stars or {}
        self.sent: list[tuple[str, str]] = []
        self.send_result = send_result

    def get_all_providers(self):
        return list(self.providers)

    def get_provider_by_id(self, provider_id: str):
        for provider in self.providers:
            if provider.meta().id == provider_id:
                return provider
        return None

    def get_using_provider(self, umo: str | None = None):
        return self.providers[0] if self.providers else None

    def get_llm_tool_manager(self):
        return self.tool_manager

    def get_registered_star(self, name: str):
        return self.stars.get(name)

    async def send_message(self, umo: str, message_chain: Any) -> bool:
        text = ""
        for component in getattr(message_chain, "chain", []):
            text += getattr(component, "text", "")
        self.sent.append((umo, text))
        return self.send_result


@dataclass
class FakeStarMetadata:
    """模拟 StarMetadata（`star_cls` 即插件实例）。"""

    name: str
    version: str
    star_cls: Any = None


class FakeMemoryEngine:
    """模拟 LivingMemory 的 MemoryEngine（只看我们用到的方法）。"""

    def __init__(self) -> None:
        self.added: list[dict[str, Any]] = []
        self.deleted: list[int] = []
        self._next = 100

    async def add_memory(self, content: str, session_id=None, persona_id=None, importance=0.5, metadata=None, **kwargs):
        self._next += 1
        self.added.append(
            {
                "id": self._next,
                "content": content,
                "session_id": session_id,
                "importance": importance,
                "metadata": metadata,
            }
        )
        return self._next

    async def delete_memory(self, memory_id: int) -> bool:
        self.deleted.append(memory_id)
        self.added = [item for item in self.added if item["id"] != memory_id]
        return True

    async def search_memories(self, query: str, k: int = 5, **kwargs):
        return [{"id": 1, "content": f"hit:{query}"}][:k]

    async def list_memories_page(self, offset: int = 0, limit: int = 50):
        return [{"id": 7, "content": "from bot: 下周三有高数考试", "importance": 0.8}]


class FakeLivingMemoryPlugin:
    def __init__(self) -> None:
        self.initializer = type("Init", (), {"memory_engine": FakeMemoryEngine()})()
        self.engine = self.initializer.memory_engine
