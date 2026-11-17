"""鉴权：令牌、绑定码、设备吊销、限流。"""

from __future__ import annotations

import pytest

from core.errors import ApiError
from core.principal import create_bind_code, issue_token, get_or_create

pytestmark = pytest.mark.asyncio


async def test_health_needs_no_token(client):
    response = await client.get("/api/study/health")
    assert response.status == 200
    payload = await response.json()
    assert payload["ok"] is True
    assert payload["data"]["name"] == "astrbot_plugin_study_bridge"


async def test_health_leaks_nothing(client):
    response = await client.get("/api/study/health")
    payload = await response.json()
    assert set(payload["data"].keys()) == {"name", "version", "status"}


async def test_protected_requires_token(client):
    response = await client.get("/api/study/tasks")
    assert response.status == 401
    payload = await response.json()
    assert payload["ok"] is False
    assert payload["error"]["code"] == "UNAUTHORIZED"


async def test_wrong_token_rejected(client):
    response = await client.get(
        "/api/study/tasks", headers={"Authorization": "Bearer " + "x" * 43}
    )
    assert response.status == 401


async def test_valid_token_works(auth_client):
    response = await auth_client.get("/api/study/tasks")
    assert response.status == 200
    payload = await response.json()
    assert payload["ok"] is True


async def test_bind_code_flow(app, client):
    created = await client.post("/api/study/auth/bind-code")
    assert created.status == 201 or created.status == 200
    data = (await created.json())["data"]
    code = data["code"]
    assert len(code) == 6 and code.isdigit()

    status_before = await client.get(f"/api/study/auth/bind-status?code={code}")
    assert (await status_before.json())["data"]["bound"] is False

    principal = await get_or_create(app.db, kind="user", external_id="777")
    result, key = await app.auth.claim_from_qq(principal, code)
    assert result == "ok"
    assert key == "cmd.bind.ok"

    status_after = await client.get(f"/api/study/auth/bind-status?code={code}")
    assert (await status_after.json())["data"]["bound"] is True

    exchanged = await client.post("/api/study/auth/token", json={"code": code})
    payload = await exchanged.json()
    assert payload["ok"] is True
    assert len(payload["data"]["token"]) > 20
    assert payload["data"]["principal"]["id"] == principal.id

    # 一次性：第二次兑换 401
    again = await client.post("/api/study/auth/token", json={"code": code})
    assert again.status == 401


async def test_bind_code_expired(app, client):
    principal = await get_or_create(app.db, kind="user", external_id="888")
    created = await app.auth.create_bind_code()
    code = created["code"]
    await app.db.execute(
        "UPDATE bind_code SET expires_at = ? WHERE code = ?",
        ("2000-01-01T00:00:00+00:00", code),
    )
    status = await client.get(f"/api/study/auth/bind-status?code={code}")
    assert (await status.json())["data"]["bound"] is False
    result, key = await app.auth.claim_from_qq(principal, code)
    assert result == "expired"
    assert key == "cmd.bind.expired"


async def test_bind_code_used_twice(app):
    principal = await get_or_create(app.db, kind="user", external_id="999")
    created = await create_bind_code(app.db)
    code = created["code"]
    first, _ = await app.auth.claim_from_qq(principal, code)
    assert first == "ok"
    token_data = await app.auth.exchange(code)
    assert token_data["token"]
    # 一次性：再次兑换必须 401
    with pytest.raises(ApiError) as exc:
        await app.auth.exchange(code)
    assert exc.value.code == "UNAUTHORIZED"


async def test_bind_code_wrong_attempts_invalidate(app):
    principal = await get_or_create(app.db, kind="user", external_id="1024")
    codes = [await app.auth.create_bind_code() for _ in range(3)]
    blocked = False
    for _ in range(5):
        status, _key = await app.auth.claim_from_qq(principal, "000000")
        if status == "blocked":
            blocked = True
            break
    assert blocked is True
    # 封禁期间即使码正确也不能绑定
    status, _key = await app.auth.claim_from_qq(principal, codes[0]["code"])
    assert status == "blocked"


async def test_revoke_device_immediately_401(app, client):
    principal = await get_or_create(app.db, kind="user", external_id="2001")
    token, token_id = await issue_token(app.db, principal_id=principal.id, label="phone")
    headers = {"Authorization": f"Bearer {token}"}
    ok_response = await client.get("/api/study/auth/me", headers=headers)
    assert ok_response.status == 200

    revoked = await client.post(
        "/api/study/auth/revoke", json={"token_id": token_id}, headers=headers
    )
    assert (await revoked.json())["ok"] is True

    after = await client.get("/api/study/auth/me", headers=headers)
    assert after.status == 401


async def test_revoke_other_principal_token_is_404(app, client):
    owner = await get_or_create(app.db, kind="user", external_id="3001")
    other = await get_or_create(app.db, kind="user", external_id="3002")
    _token, other_token_id = await issue_token(app.db, principal_id=other.id, label="x")
    token, _ = await issue_token(app.db, principal_id=owner.id, label="mine")
    response = await client.post(
        "/api/study/auth/revoke",
        json={"token_id": other_token_id},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status == 404


async def test_rate_limit_returns_429(app):
    from aiohttp.test_utils import TestClient, TestServer

    from core.http_server import HttpServer
    from core.principal import RateLimiter

    server = HttpServer(app)
    server._ip_limiter = RateLimiter(limit=2)
    async with TestClient(TestServer(server.build())) as test_client:
        statuses = [(await test_client.get("/api/study/health")).status for _ in range(3)]
    assert statuses == [200, 200, 429]


async def test_auth_failures_lock_the_ip(app):
    from aiohttp.test_utils import TestClient, TestServer

    from core.http_server import HttpServer
    from core.principal import AttemptLimiter

    server = HttpServer(app)
    server._auth_fail = AttemptLimiter(max_attempts=3, window_seconds=60, block_seconds=600)
    async with TestClient(TestServer(server.build())) as test_client:
        for _ in range(3):
            response = await test_client.get("/api/study/tasks")
            assert response.status == 401
        blocked = await test_client.get(
            "/api/study/tasks", headers={"Authorization": "Bearer " + "y" * 43}
        )
        assert blocked.status == 429
        payload = await blocked.json()
    assert payload["error"]["code"] == "RATE_LIMITED"


async def test_bind_status_is_minimal(client):
    response = await client.get("/api/study/auth/bind-status?code=123456")
    payload = await response.json()
    assert payload["data"] == {"bound": False}


async def test_invalid_json_body_returns_400(auth_client):
    response = await auth_client.post(
        "/api/study/tasks", data="{not json", headers={"Content-Type": "application/json"}
    )
    assert response.status == 400
    payload = await response.json()
    assert payload["error"]["code"] == "VALIDATION_ERROR"


async def test_api_error_shapes():
    error = ApiError("NOT_FOUND", "x")
    assert error.status == 404
    assert error.to_dict()["code"] == "NOT_FOUND"
    with pytest.raises(ApiError):
        raise ApiError("QUOTA_EXCEEDED", "full")
