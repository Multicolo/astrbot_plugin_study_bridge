"""应用容器：把 config/db/llm/adapters/services 组装起来。

不 import astrbot：``context``、``sender``、``current_event`` 由 ``main.py``（真机）
或 ``core/standalone.py``（调试）注入。这样 services 可以在无 AstrBot 环境完整跑测试。
"""

from __future__ import annotations

import contextvars
import logging
from pathlib import Path
from typing import Any, Awaitable, Callable

try:  # 作为 AstrBot 插件包导入（真机）
    from ..adapters import MemoryManager
except ImportError:  # 顶层导入（独立运行 / 单元测试）
    from adapters import MemoryManager  # type: ignore[no-redef]

from . import principal as principal_mod
from .commands import StudyCommands
from .config import Settings
from .db import Database
from .i18n import I18n, set_default
from .llm import LLMClient
from .services.auth_service import AuthService
from .services.chat_service import ChatService
from .services.export_service import ExportService
from .services.material_service import MaterialService
from .services.memory_service import MemoryService
from .services.notify_service import NotifyService
from .services.plan_service import PlanService
from .services.settings_service import SettingsService
from .services.stats_service import StatsService
from .services.task_service import TaskService
from .scheduler import Scheduler
from .util import iso, utcnow

PLUGIN_NAME = "astrbot_plugin_study_bridge"
PLUGIN_VERSION = "1.1.5"
MIN_ASTRBOT_VERSION = "4.24.2"

_current_event: contextvars.ContextVar[Any] = contextvars.ContextVar(
    "study_bridge_event", default=None
)

Sender = Callable[[str, str], Awaitable[bool]]


class StudyApp:
    def __init__(
        self,
        *,
        data_dir: str | Path,
        cfg: Settings | None = None,
        context: Any = None,
        logger: logging.Logger | None = None,
        astrbot_version: str = "",
    ) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.cfg = cfg or Settings()
        self.context = context
        self.logger = logger or logging.getLogger("astrbot.plugin.study_bridge")
        self.astrbot_version = astrbot_version
        self.plugin_version = PLUGIN_VERSION
        self.sender: Sender | None = None
        self.i18n = I18n(self.cfg.language)
        set_default(self.i18n)

        self.db = Database(self.data_dir / "study.db")
        self.llm = LLMClient(self)
        self.memory_manager = MemoryManager(self)
        self.scheduler = Scheduler(self)

        self.settings = SettingsService(self)
        self.auth = AuthService(self)
        self.tasks = TaskService(self)
        self.plans = PlanService(self)
        self.stats = StatsService(self)
        self.materials = MaterialService(self)
        self.notify = NotifyService(self)
        self.memories = MemoryService(self)
        self.chat = ChatService(self)
        self.export = ExportService(self)
        self.commands = StudyCommands(self)

        self.ready = False
        self.warnings: list[str] = []

    # ------------------------------------------------------------ 生命周期
    async def startup(self, *, migrate: bool = True) -> None:
        await self.db.open(migrate=migrate)
        await self.memory_manager.start()
        await self.llm.reload()
        self._check_version()
        self.ready = True
        self.logger.info(
            "学习桥梁已启动：data_dir=%s schema=v%s adapter=%s",
            self.data_dir,
            self.db.version,
            self.memory_manager.active.name,
        )

    async def shutdown(self) -> None:
        await self.db.close()
        self.ready = False

    def _check_version(self) -> None:
        version = (self.astrbot_version or "").strip()
        if not version:
            return
        try:
            parsed = tuple(int(part) for part in version.split(".")[:3] if part.isdigit())
        except ValueError:
            return
        minimum = tuple(int(part) for part in MIN_ASTRBOT_VERSION.split("."))
        if parsed and parsed < minimum:
            message = (
                f"当前 AstrBot 版本 {version} 低于本插件要求的 {MIN_ASTRBOT_VERSION}，"
                "部分接口可能不可用（插件仍会加载，但请升级）。"
            )
            self.warnings.append(message)
            self.logger.warning(message)

    # ------------------------------------------------------------ 工具
    @property
    def lang(self) -> str:
        return self.cfg.language

    def t(self, key: str, /, **kwargs: Any) -> str:
        """取本地化文案；``key`` 为位置参数，模板里的 ``{key}`` 占位符不冲突。"""
        return self.i18n.t(key, **kwargs)

    def current_event(self) -> Any:
        return _current_event.get()

    def set_current_event(self, event: Any) -> contextvars.Token:
        return _current_event.set(event)

    def reset_current_event(self, token: contextvars.Token) -> None:
        _current_event.reset(token)

    async def principal_by_id(self, principal_id: str) -> principal_mod.Principal | None:
        return await principal_mod.get_by_id(self.db, principal_id)

    async def principal_for_event(self, event: Any) -> principal_mod.Principal:
        """从事件对象解析主体；UMO/群号/发送者一律取自事件，绝不手工拼接。"""
        sender_id = _event_str(event, "get_sender_id") or _event_str(event, "get_session_id")
        group_id = _event_str(event, "get_group_id")
        is_private = _event_bool(event, "is_private_chat")
        is_admin = _event_bool(event, "is_admin")
        display = _event_str(event, "get_sender_name") or None
        if group_id and not is_private and self.cfg.group_mode == "per_group":
            return await principal_mod.get_or_create(
                self.db, kind="group", external_id=str(group_id), display_name=display
            )
        kind = "owner" if is_admin else "user"
        external = str(sender_id or "unknown")
        return await principal_mod.get_or_create(
            self.db, kind=kind, external_id=external, display_name=display
        )

    async def info(self) -> dict[str, Any]:
        """``GET /api/study/info`` 与 ``/study/setup`` 自检页的数据源。"""
        devices = int(
            await self.db.scalar("SELECT COUNT(*) FROM auth_token WHERE revoked_at IS NULL", default=0)
        )
        tasks = int(
            await self.db.scalar(
                "SELECT COUNT(*) FROM task WHERE deleted_at IS NULL", default=0
            )
        )
        return {
            "name": PLUGIN_NAME,
            "plugin_version": self.plugin_version,
            "astrbot_version": self.astrbot_version or "未知（独立运行）",
            "min_astrbot_version": MIN_ASTRBOT_VERSION,
            "schema_version": self.db.version,
            "timezone": self.cfg.timezone,
            "language": self.lang,
            "http": {
                "enabled": self.cfg.get_bool("http.enabled", True),
                "host": self.cfg.get_str("http.host", "0.0.0.0"),
                "port": self.cfg.get_int("http.port", 6188),
            },
            "memory": self.memory_manager.describe(),
            "ai": {
                "mode": self.llm.mode,
                "provider_id": self.llm.provider_id,
                "model": self.llm.model,
                "available": await self.llm.available(),
            },
            "capabilities": {
                "chat": True,
                "plan": True,
                "push": self.sender is not None,
                "memory_sync": self.cfg.get_str("memory.sync_mode", "upload_only"),
            },
            "counts": {"devices": devices, "tasks": tasks},
            "warnings": list(self.warnings),
            "generated_at": iso(utcnow()),
        }


def _event_str(event: Any, method: str) -> str:
    fn = getattr(event, method, None)
    if callable(fn):
        try:
            value = fn()
            return str(value) if value else ""
        except Exception:  # noqa: BLE001 - 平台差异不能让指令崩
            return ""
    return ""


def _event_bool(event: Any, method: str) -> bool:
    fn = getattr(event, method, None)
    if callable(fn):
        try:
            return bool(fn())
        except Exception:  # noqa: BLE001
            return False
    return False
