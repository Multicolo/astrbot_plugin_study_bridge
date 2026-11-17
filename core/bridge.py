"""兼容层：真 AstrBot 运行时用官方 API，独立运行/单测时用最小替身。

这样做的好处：
- ``core/commands.py`` 只有一份代码，真机与测试走同一条路径；
- 独立运行（``python -m core.standalone``）不需要安装 AstrBot；
- 假 ``filter`` 的装饰器是空操作，handler 依旧是普通方法，测试可直接调用。
"""

from __future__ import annotations

from typing import Any

try:  # pragma: no cover - 真机分支
    from astrbot.api.event import AstrMessageEvent, MessageChain, filter
    from astrbot.api.message_components import Plain
    from astrbot.api.star import Context, Star

    HAS_ASTRBOT = True
except Exception:  # noqa: BLE001 - 独立运行/AstrBot 不可用
    HAS_ASTRBOT = False

    class Star:  # type: ignore[no-redef]
        """最小替身：只保留插件会用到的字段。"""

        def __init__(self, context: Any = None, config: Any = None) -> None:
            self.context = context
            self.config = config

        async def initialize(self) -> None:  # pragma: no cover - 由子类覆盖
            return None

        async def terminate(self) -> None:  # pragma: no cover
            return None

    class Context:  # type: ignore[no-redef]
        ...

    class AstrMessageEvent:  # type: ignore[no-redef]
        """最小替身：测试里用 FakeEvent 代替。"""

    class MessageChain:  # type: ignore[no-redef]
        def __init__(self, chain: list[Any] | None = None) -> None:
            self.chain = chain or []

    class Plain:  # type: ignore[no-redef]
        def __init__(self, text: str) -> None:
            self.text = text

    class _FilterStub:
        """所有装饰器都是空操作，返回原函数。"""

        def __getattr__(self, name: str):
            def decorator(*args: Any, **kwargs: Any):
                def wrap(func):
                    return func

                return wrap

            return decorator

    filter = _FilterStub()  # type: ignore[assignment]

__all__ = [
    "HAS_ASTRBOT",
    "AstrMessageEvent",
    "Context",
    "MessageChain",
    "Plain",
    "Star",
    "filter",
]
