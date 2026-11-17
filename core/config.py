"""配置读取：把 ``_conf_schema.json`` 对应的 dict 包成带默认值的只读视图。

特点：
- 支持点号路径 ``cfg.get("http.port")``；
- 默认值与 ``_conf_schema.json`` 保持一致；
- 不认识的值不会让插件崩溃（类型不对就退回默认值）；
- 不 import astrbot。
"""

from __future__ import annotations

import copy
from typing import Any

DEFAULTS: dict[str, Any] = {
    "http.enabled": True,
    "http.host": "0.0.0.0",
    "http.port": 6188,
    "http.public_base_url": "",
    "http.allowed_origins": ["*"],
    "http.rate_limit_per_minute": 120,
    "http.auth_fail_limit_per_minute": 20,
    "http.max_body_bytes": 262144,
    "scope.allowed_qq": [],
    "scope.allowed_groups": [],
    "scope.group_mode": "per_user",
    "language": "zh-CN",
    "default_timezone": "Asia/Shanghai",
    "notify.early_brief_time": "08:00",
    "notify.plan_nudge_time": "21:00",
    "notify.weekly_report_weekday": 1,
    "notify.weekly_report_time": "09:00",
    "notify.retry_max": 3,
    "notify.default_remind_offsets": [30, 0],
    "ai.mode": "astrbot",
    "ai.provider_id": "",
    "ai.timeout_seconds": 60,
    "ai.max_tool_rounds": 6,
    "ai.allow_principal_ai": True,
    "memory.adapter_order": ["generic_tool", "livingmemory", "none"],
    "memory.sync_mode": "upload_only",
    "memory.budget_tokens": 1500,
    "memory.source_tag_prefix": "[src:study:",
    "memory.file_adapter_path": "",
    "memory.generic_tool.write_tool": "remember",
    "memory.generic_tool.search_tool": "recall",
    "memory.generic_tool.write_arg": "text",
    "memory.generic_tool.search_arg": "query",
    "memory.livingmemory.allow_private_attrs": True,
    "memory.livingmemory.persona_id": "",
    "quota.max_tasks": 2000,
    "quota.max_plans": 200,
    "quota.max_notifications": 5000,
    "data_dir_override": "",
}


def _flatten(raw: Any, prefix: str, out: dict[str, Any]) -> None:
    """把嵌套 dict 展平成点号键；只展开 dict，其它原样保留。"""
    if not isinstance(raw, dict):
        return
    for key, value in raw.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict) and not any(
            isinstance(v, (dict,)) for v in value.values()
        ):
            out[path] = copy.deepcopy(value)
            _flatten(value, path, out)
        elif isinstance(value, dict):
            _flatten(value, path, out)
        else:
            out[path] = value


class Settings:
    """插件配置的只读视图。"""

    def __init__(self, raw: dict[str, Any] | None = None) -> None:
        self._raw: dict[str, Any] = copy.deepcopy(DEFAULTS)
        if raw:
            flat: dict[str, Any] = {}
            _flatten(raw, "", flat)
            for key, value in flat.items():
                if value is None:
                    continue
                self._raw[key] = value

    # ------------------------------------------------------------ 通用读取
    def get(self, path: str, default: Any = None) -> Any:
        if path in self._raw:
            return self._raw[path]
        return DEFAULTS.get(path, default)

    def get_str(self, path: str, default: str = "") -> str:
        value = self.get(path, default)
        return value if isinstance(value, str) else default

    def get_bool(self, path: str, default: bool = False) -> bool:
        value = self.get(path, default)
        return bool(value) if isinstance(value, (bool, int)) else default

    def get_int(self, path: str, default: int = 0) -> int:
        value = self.get(path, default)
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def get_list(self, path: str, default: list | None = None) -> list:
        value = self.get(path, default or [])
        return list(value) if isinstance(value, (list, tuple)) else list(default or [])

    # ------------------------------------------------------------ 便捷属性
    @property
    def language(self) -> str:
        lang = self.get_str("language", "zh-CN")
        return lang if lang in ("zh-CN", "en-US") else "zh-CN"

    @property
    def timezone(self) -> str:
        return self.get_str("default_timezone", "Asia/Shanghai") or "Asia/Shanghai"

    @property
    def group_mode(self) -> str:
        mode = self.get_str("scope.group_mode", "per_user")
        return mode if mode in ("per_user", "per_group") else "per_user"

    @property
    def source_tag_prefix(self) -> str:
        prefix = self.get_str("memory.source_tag_prefix", "[src:study:")
        return prefix or "[src:study:"

    def as_dict(self) -> dict[str, Any]:
        return copy.deepcopy(self._raw)
