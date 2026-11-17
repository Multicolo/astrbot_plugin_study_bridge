"""脚本化 LLM：按顺序返回预设输出，其余逻辑走真实实现（prompt 渲染、JSON 解析、重试）。"""

from __future__ import annotations

import json
from typing import Any

from core.llm import LLMClient, LLMError


class ScriptedLLM(LLMClient):
    def __init__(self, app: Any, script: list[Any] | None = None) -> None:
        super().__init__(app)
        self.script: list[Any] = list(script or [])
        self.prompts: list[str] = []
        self.systems: list[str | None] = []
        self.available_flag = True
        self.default_reply = json.dumps(
            {"reply": "好的", "tool_calls": []}, ensure_ascii=False
        )

    # ------------------------------------------------------------ 覆盖
    async def available(self) -> bool:
        return self.available_flag

    async def reload(self) -> None:
        # 必须走父类：它会清掉 llm_config 的读取缓存
        await super().reload()

    async def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        timeout: int | None = None,
        json_mode: bool = False,
    ) -> str:
        self.prompts.append(prompt)
        self.systems.append(system)
        if not self.script:
            return self.default_reply
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, dict):
            return json.dumps(item, ensure_ascii=False)
        return str(item)

    # ------------------------------------------------------------ 便捷
    def push(self, *items: Any) -> None:
        self.script.extend(items)

    def push_llm_error(self) -> None:
        self.script.append(LLMError("上游超时"))
