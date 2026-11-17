"""HTTP 服务（aiohttp）：路由、鉴权中间件、限流、静态托管。

为什么自建而不是挂在 AstrBot Dashboard 上：见 docs/RESEARCH.md §1.6 ——
插件的 ``register_web_api`` 只能挂在 Dashboard 且强制 Dashboard 鉴权，
App 只持有本插件的绑定令牌，无法访问。因此这里自带一个服务，
同源托管 ``/study/`` 静态页与 ``/api/study/*`` 接口。

安全要点：
- 令牌只认 ``Authorization: Bearer``；
- ``/health`` 与 ``/auth/bind-status`` 免鉴权且只返回最少信息；
- 单 IP 限流 120/min，鉴权失败 20/min 后封 10 分钟；
- 任何异常都转成统一 JSON 信封，绝不返回堆栈。
"""

from __future__ import annotations

import ipaddress
import json
import time
from pathlib import Path
from typing import Any

from aiohttp import web

from .app import StudyApp
from .errors import ApiError, unauthorized
from .principal import AttemptLimiter, RateLimiter
from .util import iso, utcnow

API_PREFIX = "/api/study"
PUBLIC_PATHS = {
    f"{API_PREFIX}/health",
    f"{API_PREFIX}/auth/bind-status",
    f"{API_PREFIX}/auth/bind-code",
    f"{API_PREFIX}/auth/token",
}


def ok(data: Any = None, *, status: int = 200) -> web.Response:
    return web.json_response({"ok": True, "data": data}, status=status)


def fail(error: ApiError) -> web.Response:
    return web.json_response({"ok": False, "error": error.to_dict()}, status=error.status)


class HttpServer:
    def __init__(self, app: StudyApp, *, web_root: str | Path | None = None) -> None:
        self.app = app
        self.web_root = Path(web_root) if web_root else Path(__file__).resolve().parent.parent / "web"
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self._ip_limiter = RateLimiter(limit=app.cfg.get_int("http.rate_limit_per_minute", 120))
        self._auth_fail = AttemptLimiter(
            max_attempts=app.cfg.get_int("http.auth_fail_limit_per_minute", 20),
            window_seconds=60,
            block_seconds=600,
        )
        self.bound_port: int | None = None
        self.error: str | None = None

    # ------------------------------------------------------------ 应用
    def build(self) -> web.Application:
        app = web.Application(
            middlewares=[self._error_middleware, self._auth_middleware],
            client_max_size=self.app.cfg.get_int("http.max_body_bytes", 262144),
        )
        self._register_routes(app)
        return app

    def _register_routes(self, router: web.Application) -> None:
        p = API_PREFIX
        router.router.add_get(f"{p}/health", self.h_health)
        router.router.add_get(f"{p}/info", self.h_info)
        router.router.add_post(f"{p}/auth/bind-code", self.h_bind_code)
        router.router.add_get(f"{p}/auth/bind-status", self.h_bind_status)
        router.router.add_post(f"{p}/auth/token", self.h_auth_token)
        router.router.add_get(f"{p}/auth/me", self.h_me)
        router.router.add_get(f"{p}/auth/devices", self.h_devices)
        router.router.add_post(f"{p}/auth/revoke", self.h_revoke)

        router.router.add_get(f"{p}/tasks", self.h_tasks_list)
        router.router.add_post(f"{p}/tasks", self.h_tasks_create)
        router.router.add_get(f"{p}/tasks/today", self.h_tasks_today)
        router.router.add_post(f"{p}/tasks/parse", self.h_tasks_parse)
        router.router.add_get(f"{p}/tasks/{{task_id}}", self.h_task_get)
        router.router.add_put(f"{p}/tasks/{{task_id}}", self.h_task_update)
        router.router.add_delete(f"{p}/tasks/{{task_id}}", self.h_task_delete)
        router.router.add_patch(f"{p}/tasks/{{task_id}}/status", self.h_task_status)

        router.router.add_get(f"{p}/plans", self.h_plans_list)
        router.router.add_post(f"{p}/plans/generate", self.h_plans_generate)
        router.router.add_get(f"{p}/plans/{{plan_id}}", self.h_plan_get)
        router.router.add_patch(f"{p}/plans/{{plan_id}}", self.h_plan_patch)
        router.router.add_delete(f"{p}/plans/{{plan_id}}", self.h_plan_delete)
        router.router.add_post(f"{p}/plans/{{plan_id}}/apply", self.h_plan_apply)
        router.router.add_post(f"{p}/plans/{{plan_id}}/rollback", self.h_plan_rollback)

        router.router.add_get(f"{p}/materials", self.h_materials_list)
        router.router.add_post(f"{p}/materials", self.h_materials_create)
        router.router.add_delete(f"{p}/materials/{{material_id}}", self.h_material_delete)

        router.router.add_get(f"{p}/stats/overview", self.h_stats_overview)
        router.router.add_get(f"{p}/stats/daily", self.h_stats_daily)
        router.router.add_get(f"{p}/stats/plan-progress", self.h_stats_plan_progress)

        router.router.add_post(f"{p}/chat", self.h_chat)
        router.router.add_get(f"{p}/chat/history", self.h_chat_history)
        router.router.add_post(f"{p}/chat/reset", self.h_chat_reset)

        router.router.add_get(f"{p}/memory/notes", self.h_memory_notes)
        router.router.add_post(f"{p}/memory/notes", self.h_memory_note_create)
        router.router.add_patch(f"{p}/memory/notes/{{note_id}}", self.h_memory_note_patch)
        router.router.add_delete(f"{p}/memory/notes/{{note_id}}", self.h_memory_note_delete)
        router.router.add_get(f"{p}/memory/bot", self.h_memory_bot)
        router.router.add_post(f"{p}/memory/bot/{{remote_ref}}/adopt", self.h_memory_adopt)
        router.router.add_get(f"{p}/memory/sync-status", self.h_memory_sync_status)
        router.router.add_post(f"{p}/memory/compact", self.h_memory_compact)

        router.router.add_get(f"{p}/push-targets", self.h_push_list)
        router.router.add_post(f"{p}/push-targets", self.h_push_create)
        router.router.add_patch(f"{p}/push-targets/{{target_id}}", self.h_push_update)
        router.router.add_delete(f"{p}/push-targets/{{target_id}}", self.h_push_delete)
        router.router.add_post(f"{p}/push-targets/{{target_id}}/test", self.h_push_test)
        router.router.add_get(f"{p}/notifications", self.h_notifications)

        router.router.add_get(f"{p}/ai/providers", self.h_ai_providers)
        router.router.add_post(f"{p}/ai/select", self.h_ai_select)
        router.router.add_get(f"{p}/ai/manual", self.h_ai_manual_get)
        router.router.add_put(f"{p}/ai/manual", self.h_ai_manual_put)
        router.router.add_post(f"{p}/ai/test", self.h_ai_test)

        router.router.add_get(f"{p}/settings", self.h_settings_get)
        router.router.add_put(f"{p}/settings", self.h_settings_put)
        router.router.add_get(f"{p}/export", self.h_export)

        # 静态站点（SPA）
        router.router.add_get("/study", self.h_static_redirect)
        router.router.add_get("/study/", self.h_index)
        router.router.add_get("/", self.h_root_redirect)
        assets = self.web_root / "assets"
        if assets.is_dir():
            router.router.add_static("/study/assets", assets, show_index=False)
        router.router.add_get("/study/{path:.*}", self.h_spa)

    # ------------------------------------------------------------ 中间件
    @web.middleware
    async def _error_middleware(self, request: web.Request, handler):
        started = time.perf_counter()
        try:
            response = await handler(request)
            return response
        except ApiError as exc:
            return fail(exc)
        except web.HTTPException:
            raise
        except json.JSONDecodeError:
            return fail(ApiError("VALIDATION_ERROR", "请求体不是合法 JSON"))
        except Exception as exc:  # noqa: BLE001 - 兜底，绝不把堆栈返回给客户端
            self.app.logger.exception(
                "HTTP 处理异常 %s %s: %s", request.method, request.path, exc
            )
            return fail(ApiError("INTERNAL", "服务端内部错误，请查看 AstrBot 日志"))
        finally:
            _ = time.perf_counter() - started

    @web.middleware
    async def _auth_middleware(self, request: web.Request, handler):
        origin = request.headers.get("Origin")
        cors = self._cors_headers(origin)
        if request.method == "OPTIONS":
            response = web.Response(status=204)
            _apply_cors(response, cors)
            return response

        ip = self._client_ip(request)
        path = request.path
        is_api = path.startswith(API_PREFIX)
        if is_api and self._auth_fail.blocked(ip):
            response = fail(
                ApiError(
                    "RATE_LIMITED",
                    f"鉴权失败次数过多，请 {self._auth_fail.retry_after(ip) // 60 + 1} 分钟后再试",
                )
            )
            _apply_cors(response, cors)
            return response

        remaining = 0
        if is_api:
            # 限流只针对 API：静态资源（/study/*）不占用配额，否则一次页面加载就能打满
            allowed, remaining = self._ip_limiter.allow(ip)
            if not allowed:
                response = fail(ApiError("RATE_LIMITED", "请求过于频繁，请稍后再试"))
                response.headers["X-RateLimit-Remaining"] = "0"
                _apply_cors(response, cors)
                return response

        if path in PUBLIC_PATHS or path == "/" or path.startswith("/study"):
            request["principal"] = None
            response = await handler(request)
            _apply_cors(response, cors)
            return response

        auth = request.headers.get("Authorization", "")
        token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
        if not token:
            self._auth_fail.hit(ip)
            response = fail(unauthorized("缺少 Bearer 令牌"))
            _apply_cors(response, cors)
            return response
        principal = await self._resolve(token)
        if principal is None:
            self._auth_fail.hit(ip)
            response = fail(unauthorized("令牌无效或已被吊销"))
            _apply_cors(response, cors)
            return response
        request["principal"] = principal
        response = await handler(request)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        _apply_cors(response, cors)
        return response

    async def _resolve(self, token: str):
        from . import principal as principal_mod

        return await principal_mod.resolve_token(self.app.db, token)

    def _cors_headers(self, origin: str | None) -> dict[str, str]:
        allowed = [str(item) for item in self.app.cfg.get_list("http.allowed_origins", ["*"])]
        if not origin:
            return {}
        if "*" in allowed:
            return {
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "Authorization, Content-Type",
                "Access-Control-Allow-Methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
                "Access-Control-Max-Age": "600",
            }
        if origin in allowed:
            return {
                "Access-Control-Allow-Origin": origin,
                "Access-Control-Allow-Headers": "Authorization, Content-Type",
                "Access-Control-Allow-Methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
                "Vary": "Origin",
            }
        return {}

    def _client_ip(self, request: web.Request) -> str:
        peer = request.transport.get_extra_info("peername") if request.transport else None
        raw = peer[0] if isinstance(peer, tuple) and peer else (request.remote or "0.0.0.0")
        try:
            return str(ipaddress.ip_address(raw))
        except ValueError:
            return "0.0.0.0"

    # ------------------------------------------------------------ 工具
    def _principal(self, request: web.Request):
        principal = request.get("principal")
        if principal is None:
            raise unauthorized()
        return principal

    async def _json_body(self, request: web.Request) -> dict[str, Any]:
        if request.can_read_body:
            raw = await request.text()
            if raw.strip():
                try:
                    data = json.loads(raw)
                except ValueError as exc:
                    raise ApiError("VALIDATION_ERROR", "请求体不是合法 JSON") from exc
                if not isinstance(data, dict):
                    raise ApiError("VALIDATION_ERROR", "请求体必须是 JSON 对象")
                return data
        return {}

    # ------------------------------------------------------------ 公共接口
    async def h_health(self, request: web.Request) -> web.Response:
        return ok(
            {
                "name": "astrbot_plugin_study_bridge",
                "version": self.app.plugin_version,
                "status": "ok" if self.app.ready else "starting",
            }
        )

    async def h_info(self, request: web.Request) -> web.Response:
        return ok(await self.app.info())

    async def h_bind_code(self, request: web.Request) -> web.Response:
        data = await self.app.auth.create_bind_code()
        return ok(
            {
                "code": data["code"],
                "expires_in": data["expires_in"],
                "expires_at": data["expires_at"],
                "instruction": "在 QQ 私聊里发：/bind " + data["code"],
            }
        )

    async def h_bind_status(self, request: web.Request) -> web.Response:
        code = request.query.get("code", "")
        return ok(await self.app.auth.bind_status(code))

    async def h_auth_token(self, request: web.Request) -> web.Response:
        body = await self._json_body(request)
        code = str(body.get("code") or "")
        label = str(body.get("label") or request.headers.get("User-Agent") or "")[:60]
        return ok(await self.app.auth.exchange(code, label=label))

    # ------------------------------------------------------------ 鉴权后接口
    async def h_me(self, request: web.Request) -> web.Response:
        return ok(await self.app.auth.me(self._principal(request)))

    async def h_devices(self, request: web.Request) -> web.Response:
        principal = self._principal(request)
        return ok({"devices": await self.app.auth.devices(principal)})

    async def h_revoke(self, request: web.Request) -> web.Response:
        principal = self._principal(request)
        body = await self._json_body(request)
        return ok(await self.app.auth.revoke(principal, str(body.get("token_id") or "")))

    # ------------------------------------------------------------ 任务
    async def h_tasks_list(self, request: web.Request) -> web.Response:
        principal = self._principal(request)
        query = request.query
        tasks = await self.app.tasks.list(
            principal,
            date_from=query.get("from"),
            date_to=query.get("to"),
            status=query.get("status"),
            query=query.get("q"),
            limit=int(query.get("limit", "200")),
            offset=int(query.get("offset", "0")),
        )
        return ok({"tasks": tasks, "count": len(tasks)})

    async def h_tasks_create(self, request: web.Request) -> web.Response:
        principal = self._principal(request)
        body = await self._json_body(request)
        task = await self.app.tasks.create(principal, body, source=str(body.get("source") or "manual"))
        return ok(task, status=201)

    async def h_tasks_today(self, request: web.Request) -> web.Response:
        principal = self._principal(request)
        offset = int(request.query.get("offset", "0"))
        if offset not in (0, 1):
            offset = 0
        return ok(await self.app.tasks.day_view(principal, offset))

    async def h_tasks_parse(self, request: web.Request) -> web.Response:
        principal = self._principal(request)
        body = await self._json_body(request)
        return ok(await self.app.tasks.parse(principal, str(body.get("text") or "")))

    async def h_task_get(self, request: web.Request) -> web.Response:
        principal = self._principal(request)
        task = await self.app.tasks.get(principal, request.match_info["task_id"])
        if task is None:
            raise ApiError("NOT_FOUND", "任务不存在")
        return ok(task)

    async def h_task_update(self, request: web.Request) -> web.Response:
        principal = self._principal(request)
        body = await self._json_body(request)
        return ok(await self.app.tasks.update(principal, request.match_info["task_id"], body))

    async def h_task_delete(self, request: web.Request) -> web.Response:
        principal = self._principal(request)
        return ok(await self.app.tasks.delete(principal, request.match_info["task_id"]))

    async def h_task_status(self, request: web.Request) -> web.Response:
        principal = self._principal(request)
        body = await self._json_body(request)
        return ok(
            await self.app.tasks.set_status(
                principal, request.match_info["task_id"], str(body.get("status") or "")
            )
        )

    # ------------------------------------------------------------ 计划
    async def h_plans_list(self, request: web.Request) -> web.Response:
        principal = self._principal(request)
        plans = await self.app.plans.list(principal, status=request.query.get("status"))
        return ok({"plans": plans, "count": len(plans)})

    async def h_plans_generate(self, request: web.Request) -> web.Response:
        principal = self._principal(request)
        body = await self._json_body(request)
        plan = await self.app.plans.generate(
            principal,
            goal=str(body.get("goal") or ""),
            material_ids=[str(x) for x in (body.get("material_ids") or [])],
            daily_minutes=body.get("daily_minutes"),
            deadline=body.get("deadline"),
            title=body.get("title"),
        )
        return ok(plan, status=201)

    async def h_plan_get(self, request: web.Request) -> web.Response:
        principal = self._principal(request)
        plan = await self.app.plans.get(principal, request.match_info["plan_id"])
        if plan is None:
            raise ApiError("NOT_FOUND", "计划不存在")
        return ok(plan)

    async def h_plan_patch(self, request: web.Request) -> web.Response:
        principal = self._principal(request)
        body = await self._json_body(request)
        return ok(await self.app.plans.patch(principal, request.match_info["plan_id"], body))

    async def h_plan_delete(self, request: web.Request) -> web.Response:
        principal = self._principal(request)
        return ok(await self.app.plans.delete(principal, request.match_info["plan_id"]))

    async def h_plan_apply(self, request: web.Request) -> web.Response:
        principal = self._principal(request)
        return ok(await self.app.plans.apply(principal, request.match_info["plan_id"]))

    async def h_plan_rollback(self, request: web.Request) -> web.Response:
        principal = self._principal(request)
        return ok(await self.app.plans.rollback(principal, request.match_info["plan_id"]))

    # ------------------------------------------------------------ 资料
    async def h_materials_list(self, request: web.Request) -> web.Response:
        principal = self._principal(request)
        materials = await self.app.materials.list(principal)
        return ok({"materials": materials, "count": len(materials)})

    async def h_materials_create(self, request: web.Request) -> web.Response:
        principal = self._principal(request)
        content_type = request.headers.get("Content-Type", "")
        if content_type.startswith("multipart/"):
            reader = await request.multipart()
            name = ""
            text = ""
            async for part in reader:
                if part.name == "file" and part.filename:
                    name = part.filename
                    raw = await part.read(decode=True)
                    text = raw.decode("utf-8", errors="ignore")
                elif part.name == "text":
                    text = (await part.read(decode=True)).decode("utf-8", errors="ignore")
                elif part.name == "name":
                    name = (await part.read(decode=True)).decode("utf-8", errors="ignore")
            material = await self.app.materials.create(
                principal, name=name or None, kind="file", raw_text=text
            )
            return ok(material, status=201)
        body = await self._json_body(request)
        if body.get("url"):
            material = await self.app.materials.create(
                principal,
                name=body.get("name"),
                kind="url",
                url=str(body["url"]),
                raw_text=str(body.get("text") or ""),
            )
        else:
            material = await self.app.materials.create(
                principal, name=body.get("name"), kind="text", raw_text=str(body.get("text") or "")
            )
        return ok(material, status=201)

    async def h_material_delete(self, request: web.Request) -> web.Response:
        principal = self._principal(request)
        return ok(await self.app.materials.delete(principal, request.match_info["material_id"]))

    # ------------------------------------------------------------ 报表
    async def h_stats_overview(self, request: web.Request) -> web.Response:
        principal = self._principal(request)
        return ok(await self.app.stats.overview(principal, request.query.get("range", "week")))

    async def h_stats_daily(self, request: web.Request) -> web.Response:
        principal = self._principal(request)
        daily = await self.app.stats.daily(
            principal, request.query.get("from"), request.query.get("to")
        )
        return ok({"daily": daily})

    async def h_stats_plan_progress(self, request: web.Request) -> web.Response:
        principal = self._principal(request)
        return ok({"plans": await self.app.stats.plan_progress(principal)})

    # ------------------------------------------------------------ 对话
    async def h_chat(self, request: web.Request) -> web.Response:
        principal = self._principal(request)
        body = await self._json_body(request)
        result = await self.app.chat.handle(
            principal,
            text=str(body.get("text") or ""),
            session_key=str(body.get("session_key") or "default"),
            channel="app",
        )
        return ok(result)

    async def h_chat_history(self, request: web.Request) -> web.Response:
        principal = self._principal(request)
        return ok(
            await self.app.chat.history(
                principal,
                session_key=request.query.get("session_key", "default"),
                limit=int(request.query.get("limit", "30")),
            )
        )

    async def h_chat_reset(self, request: web.Request) -> web.Response:
        principal = self._principal(request)
        body = await self._json_body(request)
        return ok(
            await self.app.chat.reset(
                principal, session_key=str(body.get("session_key") or "default")
            )
        )

    # ------------------------------------------------------------ 记忆
    async def h_memory_notes(self, request: web.Request) -> web.Response:
        principal = self._principal(request)
        notes = await self.app.memories.list_notes(
            principal,
            kind=request.query.get("kind"),
            query=request.query.get("q"),
        )
        return ok({"notes": notes, "count": len(notes)})

    async def h_memory_note_create(self, request: web.Request) -> web.Response:
        principal = self._principal(request)
        body = await self._json_body(request)
        note = await self.app.memories.save_note(
            principal,
            kind=str(body.get("kind") or "fact"),
            content=str(body.get("content") or ""),
            tags=[str(tag) for tag in (body.get("tags") or [])],
            importance=int(body.get("importance") or 3),
            source="user",
        )
        return ok(note, status=201)

    async def h_memory_note_patch(self, request: web.Request) -> web.Response:
        principal = self._principal(request)
        body = await self._json_body(request)
        return ok(
            await self.app.memories.patch_note(principal, request.match_info["note_id"], body)
        )

    async def h_memory_note_delete(self, request: web.Request) -> web.Response:
        principal = self._principal(request)
        return ok(await self.app.memories.delete_note(principal, request.match_info["note_id"]))

    async def h_memory_bot(self, request: web.Request) -> web.Response:
        principal = self._principal(request)
        entries = await self.app.memories.list_bot_memory(principal)
        return ok({"entries": entries, "count": len(entries)})

    async def h_memory_adopt(self, request: web.Request) -> web.Response:
        principal = self._principal(request)
        return ok(await self.app.memories.adopt(principal, request.match_info["remote_ref"]))

    async def h_memory_sync_status(self, request: web.Request) -> web.Response:
        principal = self._principal(request)
        return ok(await self.app.memories.sync_status(principal))

    async def h_memory_compact(self, request: web.Request) -> web.Response:
        principal = self._principal(request)
        return ok(await self.app.memories.compact(principal))

    # ------------------------------------------------------------ 推送
    async def h_push_list(self, request: web.Request) -> web.Response:
        principal = self._principal(request)
        targets = await self.app.notify.list_targets(principal)
        return ok({"targets": targets, "count": len(targets)})

    async def h_push_create(self, request: web.Request) -> web.Response:
        principal = self._principal(request)
        body = await self._json_body(request)
        target = await self.app.notify.add_target(
            principal, umo=str(body.get("umo") or ""), alias=body.get("alias")
        )
        return ok(target, status=201)

    async def h_push_update(self, request: web.Request) -> web.Response:
        principal = self._principal(request)
        body = await self._json_body(request)
        return ok(
            await self.app.notify.update_target(principal, request.match_info["target_id"], body)
        )

    async def h_push_delete(self, request: web.Request) -> web.Response:
        principal = self._principal(request)
        return ok(await self.app.notify.delete_target(principal, request.match_info["target_id"]))

    async def h_push_test(self, request: web.Request) -> web.Response:
        principal = self._principal(request)
        return ok(await self.app.notify.test_target(principal, request.match_info["target_id"]))

    async def h_notifications(self, request: web.Request) -> web.Response:
        principal = self._principal(request)
        rows = await self.app.notify.list_notifications(
            principal,
            status=request.query.get("status"),
            limit=int(request.query.get("limit", "50")),
        )
        return ok({"notifications": rows, "count": len(rows)})

    # ------------------------------------------------------------ AI
    async def h_ai_providers(self, request: web.Request) -> web.Response:
        return ok(await self.app.llm.list_providers())

    async def h_ai_select(self, request: web.Request) -> web.Response:
        body = await self._json_body(request)
        return ok(
            await self.app.llm.select(
                str(body.get("provider_id") or ""), body.get("model")
            )
        )

    async def h_ai_manual_get(self, request: web.Request) -> web.Response:
        return ok(await self.app.llm.manual_info())

    async def h_ai_manual_put(self, request: web.Request) -> web.Response:
        body = await self._json_body(request)
        return ok(
            await self.app.llm.save_manual(
                str(body.get("base_url") or ""),
                body.get("api_key"),
                str(body.get("model") or ""),
            )
        )

    async def h_ai_test(self, request: web.Request) -> web.Response:
        return ok(await self.app.llm.test())

    # ------------------------------------------------------------ 设置 / 导出
    async def h_settings_get(self, request: web.Request) -> web.Response:
        principal = self._principal(request)
        return ok(await self.app.settings.get_all(principal))

    async def h_settings_put(self, request: web.Request) -> web.Response:
        principal = self._principal(request)
        body = await self._json_body(request)
        return ok(await self.app.settings.put_raw(principal, body))

    async def h_export(self, request: web.Request) -> web.Response:
        principal = self._principal(request)
        return ok(await self.app.export.dump(principal))

    # ------------------------------------------------------------ 静态
    def _index_response(self) -> web.Response:
        index = self.web_root / "index.html"
        if not index.is_file():
            return web.Response(
                text=(
                    "前端尚未构建：请在仓库根目录执行 `make build`（或 "
                    "`cd frontend && pnpm install && pnpm run build`）。\n"
                    f"期望目录：{self.web_root}"
                ),
                content_type="text/plain",
                charset="utf-8",
                status=503,
            )
        return web.FileResponse(index)

    async def h_index(self, request: web.Request) -> web.Response:
        return self._index_response()

    async def h_spa(self, request: web.Request) -> web.Response:
        path = request.match_info.get("path", "")
        candidate = (self.web_root / path).resolve()
        try:
            candidate.relative_to(self.web_root.resolve())
        except ValueError:
            raise ApiError("NOT_FOUND", "路径非法") from None
        if path and candidate.is_file():
            return web.FileResponse(candidate)
        return self._index_response()

    async def h_static_redirect(self, request: web.Request) -> web.Response:
        raise web.HTTPFound("/study/")

    async def h_root_redirect(self, request: web.Request) -> web.Response:
        raise web.HTTPFound("/study/")

    # ------------------------------------------------------------ 启停
    async def start(self) -> None:
        host = self.app.cfg.get_str("http.host", "0.0.0.0")
        port = self.app.cfg.get_int("http.port", 6188)
        application = self.build()
        self._runner = web.AppRunner(application, access_log=None)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, host, port)
        try:
            await self._site.start()
        except OSError as exc:
            self.error = (
                f"HTTP 服务启动失败：{host}:{port} 无法监听（{exc}）。"
                "请修改插件配置 http.port 后重载；本插件其余功能（QQ 指令/推送）不受影响。"
            )
            await self._runner.cleanup()
            self._runner = None
            self._site = None
            raise
        self.bound_port = port
        self.app.logger.info("学习桥梁 HTTP 服务已监听 http://%s:%s/study/", host, port)

    async def stop(self) -> None:
        if self._site is not None:
            await self._site.stop()
            self._site = None
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
        self.bound_port = None


def _apply_cors(response: web.StreamResponse, headers: dict[str, str]) -> None:
    for key, value in headers.items():
        response.headers[key] = value


_ = (iso, utcnow)
