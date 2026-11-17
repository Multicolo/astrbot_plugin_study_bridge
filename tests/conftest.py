"""pytest 公共夹具。

设计要点：
- 每个测试用独立临时数据目录，互不影响；
- LLM 一律用 ``ScriptedLLM``（绝不真调外部 API）；
- HTTP 用 aiohttp 的 ``TestClient`` 直连 ASGI 应用，不起真实端口。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import pytest_asyncio

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.app import StudyApp  # noqa: E402
from core.config import Settings  # noqa: E402
from core.principal import get_or_create, issue_token  # noqa: E402

from tests.harness.fake_astrbot import FakeContext, FakeEvent  # noqa: E402
from tests.harness.fake_llm import ScriptedLLM  # noqa: E402


def make_settings(overrides: dict | None = None) -> Settings:
    base = {
        "http": {
            "enabled": False,
            "allowed_origins": ["*"],
            "rate_limit_per_minute": 120,
            "auth_fail_limit_per_minute": 20,
        },
        "scope": {"allowed_qq": [], "allowed_groups": [], "group_mode": "per_user"},
        "language": "zh-CN",
        "default_timezone": "Asia/Shanghai",
        "memory": {"adapter_order": ["generic_tool", "livingmemory", "none"], "sync_mode": "upload_only"},
        "ai": {"allow_principal_ai": True, "max_tool_rounds": 6},
        "notify": {"retry_max": 3},
    }
    if overrides:
        _deep_update(base, overrides)
    return Settings(base)


def _deep_update(target: dict, patch: dict) -> None:
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_update(target[key], value)
        else:
            target[key] = value


@pytest_asyncio.fixture
async def app(tmp_path):
    settings = make_settings()
    application = StudyApp(data_dir=tmp_path, cfg=settings, context=None)
    application.llm = ScriptedLLM(application)
    await application.startup()
    yield application
    await application.shutdown()


@pytest_asyncio.fixture
async def app_with_context(tmp_path):
    """带假 AstrBot Context 的实例（用于适配器 / provider 测试）。"""
    context = FakeContext()
    settings = make_settings()
    application = StudyApp(data_dir=tmp_path, cfg=settings, context=context)
    application.llm = ScriptedLLM(application)
    await application.startup()
    yield application, context
    await application.shutdown()


@pytest_asyncio.fixture
async def principal(app):
    return await get_or_create(app.db, kind="user", external_id="10001", display_name="小明")


@pytest_asyncio.fixture
async def token(app, principal):
    value, _token_id = await issue_token(app.db, principal_id=principal.id, label="pytest")
    return value


@pytest_asyncio.fixture
async def client(app):
    from aiohttp.test_utils import TestClient, TestServer

    from core.http_server import HttpServer

    server = TestServer(HttpServer(app).build())
    async with TestClient(server) as test_client:
        yield test_client


@pytest_asyncio.fixture
async def auth_client(client, token):
    class _Authed:
        def __init__(self, inner, bearer: str) -> None:
            self._inner = inner
            self._headers = {"Authorization": f"Bearer {bearer}"}

        async def get(self, path, **kwargs):
            headers = {**self._headers, **kwargs.pop("headers", {})}
            return await self._inner.get(path, headers=headers, **kwargs)

        async def post(self, path, **kwargs):
            headers = {**self._headers, **kwargs.pop("headers", {})}
            return await self._inner.post(path, headers=headers, **kwargs)

        async def put(self, path, **kwargs):
            headers = {**self._headers, **kwargs.pop("headers", {})}
            return await self._inner.put(path, headers=headers, **kwargs)

        async def patch(self, path, **kwargs):
            headers = {**self._headers, **kwargs.pop("headers", {})}
            return await self._inner.patch(path, headers=headers, **kwargs)

        async def delete(self, path, **kwargs):
            headers = {**self._headers, **kwargs.pop("headers", {})}
            return await self._inner.delete(path, headers=headers, **kwargs)

    return _Authed(client, token)


@pytest.fixture
def event_factory():
    def _make(**kwargs):
        return FakeEvent(**kwargs)

    return _make
