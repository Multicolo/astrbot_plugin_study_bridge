"""学习桥梁 · AstrBot 插件入口。

职责只有一个：**编排**。
- 读取配置 → 组装 ``StudyApp``（core/app.py）
- 启动 HTTP 服务（core/http_server.py）与调度器（core/scheduler.py）
- 注册 QQ 指令（每个指令只做一层薄包装，逻辑在 core/commands.py）
- ``terminate()`` 时按 HTTP → 调度 → DB 的顺序优雅关闭

注意：指令装饰器必须写在**本模块**的类里 —— AstrBot 按
``handler_module_path == 插件 main 模块路径`` 精确匹配来激活 handler
（``astrbot/core/star/star_manager.py:1274-1279``），写在子模块里不会生效。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .core.app import MIN_ASTRBOT_VERSION, PLUGIN_NAME, PLUGIN_VERSION, StudyApp
from .core.bridge import HAS_ASTRBOT, MessageChain, Plain, Star, filter
from .core.commands import StudyCommands
from .core.config import Settings
from .core.http_server import HttpServer
from .core.scheduler import Scheduler

try:  # pragma: no cover - 运行在 AstrBot 内时，用官方代理日志器
    # AstrBot 4.29+ 的日志队列处理器只给已注册的 plugin logger 注入 plugin_tag 字段，
    # 自己 getLogger("astrbot.plugin.xxx") 产生的记录会让格式化抛
    # "Formatting field not found in record: 'plugin_tag'"，直接把插件加载打断。
    # astrbot.api.logger 会按调用方模块解析到本插件自己的日志器，规避这个问题。
    from astrbot.api import logger
except Exception:  # noqa: BLE001 - 独立运行 / 老版本没有该导出
    logger = logging.getLogger("astrbot.plugin.study_bridge")


class StudyBridgePlugin(Star):
    """学习桥梁：AI 学习计划 + 日程 + 早报 + 记忆同步（QQ 与 App 双端）。"""

    def __init__(self, context: Any = None, config: Any = None) -> None:
        try:
            super().__init__(context, config)
        except TypeError:  # pragma: no cover - 兼容只收 context 的老版本
            super().__init__(context)  # type: ignore[call-arg]
        self.context = context
        raw_config = dict(config or {}) if config is not None else {}
        self.cfg = Settings(raw_config)
        self.data_dir = self._resolve_data_dir()
        astrbot_version = ""
        try:  # pragma: no cover - 真机分支
            from astrbot.core.config.default import VERSION

            astrbot_version = str(VERSION)
        except Exception:  # noqa: BLE001
            astrbot_version = ""
        self.app = StudyApp(
            data_dir=self.data_dir,
            cfg=self.cfg,
            context=context,
            logger=logger,
            astrbot_version=astrbot_version,
        )
        self.app.sender = self._send_text
        self.commands = self.app.commands  # 与独立运行/测试共用同一套指令实现
        self.http = HttpServer(self.app)
        self.scheduler = self.app.scheduler
        self._started = False

    # ------------------------------------------------------------ 生命周期
    async def initialize(self) -> None:
        try:
            await self.app.startup()
        except Exception as exc:  # noqa: BLE001 - 启动失败必须给出明确原因
            logger.error("学习桥梁启动失败（数据库/迁移）：%s", exc)
            raise
        if self.cfg.get_bool("http.enabled", True):
            try:
                await self.http.start()
            except OSError as exc:
                # 端口被占：明确报错，不静默换端口，也不影响 QQ 侧功能
                logger.error(
                    "学习桥梁 HTTP 服务未能启动：%s。请修改插件配置 http.port 后重载插件；"
                    "QQ 指令/推送/计划拆解仍可正常使用。",
                    exc,
                )
        else:
            logger.info("http.enabled=false：纯 QQ 模式，网页与 App 不启动")
        self.scheduler.start()
        self._started = True
        logger.info(
            "学习桥梁已就绪：v%s（要求 AstrBot>=%s，当前 %s），数据目录 %s",
            PLUGIN_VERSION,
            MIN_ASTRBOT_VERSION,
            self.app.astrbot_version or "未知",
            self.data_dir,
        )

    async def terminate(self) -> None:
        logger.info("学习桥梁正在卸载：停止调度、关闭 HTTP 与数据库")
        try:
            await self.scheduler.stop()
        except Exception as exc:  # noqa: BLE001
            logger.warning("停止调度器失败：%s", exc)
        try:
            await self.http.stop()
        except Exception as exc:  # noqa: BLE001
            logger.warning("关闭 HTTP 服务失败：%s", exc)
        try:
            await self.app.shutdown()
        except Exception as exc:  # noqa: BLE001
            logger.warning("关闭数据库失败：%s", exc)
        self._started = False

    # ------------------------------------------------------------ 内部
    def _resolve_data_dir(self) -> Path:
        override = self.cfg.get_str("data_dir_override", "")
        if override:
            path = Path(override).expanduser()
            path.mkdir(parents=True, exist_ok=True)
            return path.resolve()
        try:
            from .core.bridge import HAS_ASTRBOT as _has

            if _has:
                from astrbot.api.star import StarTools

                return Path(StarTools.get_data_dir(PLUGIN_NAME)).resolve()
        except Exception as exc:  # noqa: BLE001 - 拿不到官方目录时降级到本地
            logger.warning("获取插件数据目录失败（%s），回退到插件目录下 data/", exc)
        fallback = Path(__file__).resolve().parent / "data" / "plugin_data" / PLUGIN_NAME
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback

    async def _send_text(self, umo: str, text: str) -> bool:
        if self.context is None:
            return False
        try:
            return bool(
                await self.context.send_message(umo, MessageChain([Plain(text)]))
            )
        except Exception as exc:  # noqa: BLE001 - 平台差异/断线不能让调度崩
            logger.warning("主动发送消息失败 umo=%s：%s", umo, exc)
            return False

    async def _run(self, event: Any, name: str, arg: str) -> str:
        token = self.app.set_current_event(event)
        try:
            return await self.commands.dispatch(event, name, arg)
        finally:
            self.app.reset_current_event(token)

    # ------------------------------------------------------------ 指令
    # 每个指令只做「取事件 → 交给 commands → 回消息」，业务逻辑全在 core/commands.py
    @filter.command("help")
    async def cmd_help(self, event: Any, arg: str = ""):
        yield event.plain_result(await self._run(event, "help", arg))

    @filter.command("bind")
    async def cmd_bind(self, event: Any, arg: str = ""):
        yield event.plain_result(await self._run(event, "bind", arg))

    @filter.command("whoami")
    async def cmd_whoami(self, event: Any, arg: str = ""):
        yield event.plain_result(await self._run(event, "whoami", arg))

    @filter.command("unbind")
    async def cmd_unbind(self, event: Any, arg: str = ""):
        yield event.plain_result(await self._run(event, "unbind", arg))

    @filter.command("addr")
    async def cmd_addr(self, event: Any, arg: str = ""):
        yield event.plain_result(await self._run(event, "addr", arg))

    @filter.command("umo")
    async def cmd_umo(self, event: Any, arg: str = ""):
        yield event.plain_result(await self._run(event, "umo", arg))

    @filter.command("settings")
    async def cmd_settings(self, event: Any, arg: str = ""):
        yield event.plain_result(await self._run(event, "settings", arg))

    @filter.command("today")
    async def cmd_today(self, event: Any, arg: str = ""):
        yield event.plain_result(await self._run(event, "today", arg))

    @filter.command("tomorrow")
    async def cmd_tomorrow(self, event: Any, arg: str = ""):
        yield event.plain_result(await self._run(event, "tomorrow", arg))

    @filter.command("week")
    async def cmd_week(self, event: Any, arg: str = ""):
        yield event.plain_result(await self._run(event, "week", arg))

    @filter.command("add")
    async def cmd_add(self, event: Any, arg: str = ""):
        yield event.plain_result(await self._run(event, "add", arg))

    @filter.command("done")
    async def cmd_done(self, event: Any, arg: str = ""):
        yield event.plain_result(await self._run(event, "done", arg))

    @filter.command("del")
    async def cmd_del(self, event: Any, arg: str = ""):
        yield event.plain_result(await self._run(event, "del", arg))

    @filter.command("plan")
    async def cmd_plan(self, event: Any, arg: str = ""):
        yield event.plain_result(await self._run(event, "plan", arg))

    @filter.command("apply")
    async def cmd_apply(self, event: Any, arg: str = ""):
        yield event.plain_result(await self._run(event, "apply", arg))

    @filter.command("report")
    async def cmd_report(self, event: Any, arg: str = ""):
        yield event.plain_result(await self._run(event, "report", arg))

    @filter.command("export")
    async def cmd_export(self, event: Any, arg: str = ""):
        yield event.plain_result(await self._run(event, "export", arg))

    @filter.command("memory")
    async def cmd_memory(self, event: Any, arg: str = ""):
        yield event.plain_result(await self._run(event, "memory", arg))

    @filter.command("forget")
    async def cmd_forget(self, event: Any, arg: str = ""):
        yield event.plain_result(await self._run(event, "forget", arg))

    @filter.command("reset")
    async def cmd_reset(self, event: Any, arg: str = ""):
        yield event.plain_result(await self._run(event, "reset", arg))

    @filter.command("study")
    async def cmd_study(self, event: Any, arg: str = ""):
        """``/study <sub> [args]``：与短指令等价的无冲突入口。"""
        parts = (arg or "").split(maxsplit=1)
        name = parts[0].lower() if parts else "help"
        rest = parts[1] if len(parts) > 1 else ""
        from .core.commands import COMMANDS

        if name not in COMMANDS:
            name, rest = "help", ""
        yield event.plain_result(await self._run(event, name, rest))


_ = HAS_ASTRBOT
