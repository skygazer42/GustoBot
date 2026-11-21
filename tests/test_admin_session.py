"""Verify the admin session through the production FastAPI routing."""

from datetime import datetime, timezone
from http.cookies import SimpleCookie

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from jose import jwt
from pydantic import SecretStr

from gustobot.config import settings
from gustobot.config.settings import Settings
from gustobot.interfaces.http.admin_session import AUDIENCE, COOKIE_NAME, _session_key
from gustobot.main import application

SESSION_PATH = "/api/v1/admin/session"
SOURCES_PATH = "/api/v1/knowledge/admin/sources"
PASSWORD = "测试-admin-password"
TEST_SIGNING_KEY = "independent-signing-key-for-tests"
ORIGIN = "https://admin.example.test"
SAME_ORIGIN = {"Origin": ORIGIN, "Sec-Fetch-Site": "same-origin"}


pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def client(monkeypatch):
    monkeypatch.setenv("GUSTOBOT_ADMIN_PASSWORD", PASSWORD)
    monkeypatch.setenv("SECRET_KEY", TEST_SIGNING_KEY)
    config = Settings().model_dump(include={"GUSTOBOT_ADMIN_PASSWORD", "SECRET_KEY"})
    for name, value in config.items():
        monkeypatch.setattr(settings, name, value)
    async with AsyncClient(transport=ASGITransport(app=application), base_url=ORIGIN) as client:
        yield client


async def test_status_login_and_logout(client):
    status = await client.get(SESSION_PATH)
    assert status.status_code == 200
    assert status.json() == {"authenticated": False, "configured": True}
    assert status.headers["cache-control"] == "no-store"

    rejected = await client.post(SESSION_PATH, json={"password": "wrong"}, headers=SAME_ORIGIN)
    assert rejected.status_code == 401
    assert "set-cookie" not in rejected.headers
    assert rejected.headers["cache-control"] == "no-store"

    login = await client.post(SESSION_PATH, json={"password": PASSWORD}, headers=SAME_ORIGIN)
    assert login.status_code == 204
    cookie = login.headers["set-cookie"].lower()
    assert "; httponly" in cookie
    assert "; secure" in cookie
    assert "; samesite=strict" in cookie
    assert "; path=/api/v1" in cookie
    assert "max-age=28800" in cookie
    status = await client.get(SESSION_PATH)
    assert status.json() == {"authenticated": True, "configured": True}

    logout = await client.delete(SESSION_PATH, headers=SAME_ORIGIN)
    assert logout.status_code == 204
    assert "max-age=0" in logout.headers["set-cookie"].lower()
    status = await client.get(SESSION_PATH)
    assert status.json() == {"authenticated": False, "configured": True}
    assert (await client.get(SOURCES_PATH)).status_code == 401


@pytest.mark.parametrize(
    ("method", "route"),
    [
        ("GET", "/admin/conversations"),
        ("GET", "/admin/conversations/example/messages"),
        ("GET", "/sessions/"),
        ("GET", "/sessions/example"),
        ("POST", "/sessions/"),
        ("GET", "/chat/history/example"),
        ("GET", "/knowledge/admin/sources"),
        ("GET", "/knowledge/admin/source"),
        ("GET", "/knowledge/admin/document"),
        ("PUT", "/knowledge/admin/document"),
        ("DELETE", "/knowledge/admin/source"),
        ("GET", "/knowledge/admin/chunk"),
        ("POST", "/knowledge/admin/retry"),
        ("GET", "/ontology/admin/source-facts"),
        ("POST", "/ontology/admin/extract"),
        ("POST", "/ontology/admin/validate"),
        ("POST", "/ontology/admin/facts"),
        ("POST", "/knowledge/documents"),
        ("POST", "/knowledge/recipes"),
        ("POST", "/knowledge/recipes/batch"),
        ("GET", "/knowledge/jobs/example"),
        ("DELETE", "/knowledge/sources/example"),
        ("POST", "/ontology/extract"),
        ("POST", "/ontology/facts"),
    ],
)
async def test_configured_admin_endpoints_reject_anonymous_requests(client, method, route):
    response = await client.request(method, f"/api/v1{route}")
    assert response.status_code == 401


async def test_session_rejects_cross_origin_even_on_same_site(client):
    login = await client.post(SESSION_PATH, json={"password": PASSWORD}, headers=SAME_ORIGIN)
    assert login.status_code == 204

    foreign_origin = {"Origin": "https://other.example.test", "Sec-Fetch-Site": "same-site"}
    assert (await client.delete(SESSION_PATH, headers=foreign_origin)).status_code == 403
    assert (await client.get(SOURCES_PATH, headers=foreign_origin)).status_code == 403
    login = await client.post(SESSION_PATH, json={"password": PASSWORD}, headers=foreign_origin)
    assert login.status_code == 403
    assert (await client.delete(SESSION_PATH, headers={"Origin": "null"})).status_code == 403
    assert (await client.get(SESSION_PATH)).json()["authenticated"] is True


async def test_invalid_login_does_not_echo_password(client):
    invalid_password = PASSWORD * 1024
    response = await client.post(SESSION_PATH, json={"password": invalid_password})
    assert response.status_code == 422
    assert response.headers["cache-control"] == "no-store"
    assert PASSWORD not in response.text


async def test_unconfigured_admin_preserves_local_mode(client, monkeypatch):
    monkeypatch.setattr(settings, "GUSTOBOT_ADMIN_PASSWORD", None)
    assert (await client.get(SESSION_PATH)).json() == {"authenticated": False, "configured": False}
    assert (await client.post(SESSION_PATH, json={"password": PASSWORD})).status_code == 503
    assert (await client.post("/api/v1/knowledge/recipes", json={})).status_code == 422


async def test_missing_signing_key_fails_closed_without_blocking_public_routes(client, monkeypatch):
    monkeypatch.setattr(settings, "SECRET_KEY", None)
    assert (await client.get(SESSION_PATH)).status_code == 503
    assert (await client.get(SOURCES_PATH)).status_code == 503
    assert (await client.get("/api/v1/ontology/domain")).status_code == 200


async def test_tampered_cookie_is_rejected(client):
    login = await client.post(SESSION_PATH, json={"password": PASSWORD})
    assert login.status_code == 204
    cookies = SimpleCookie(login.headers["set-cookie"])
    name, cookie = next(iter(cookies.items()))
    content, signature = cookie.value.rsplit(".", 1)
    wrong_signature = ("A" if signature[0] != "A" else "B") + signature[1:]
    client.cookies.clear()
    invalid_cookie = {"Cookie": f"{name}={content}.{wrong_signature}"}
    assert (await client.get(SESSION_PATH, headers=invalid_cookie)).json()["authenticated"] is False
    assert (await client.get(SOURCES_PATH, headers=invalid_cookie)).status_code == 401


async def test_expired_cookie_and_password_rotation_are_rejected(client, monkeypatch):
    now = int(datetime.now(timezone.utc).timestamp())
    expired = jwt.encode(
        {"sub": "administrator", "aud": AUDIENCE, "iss": AUDIENCE, "iat": now - 10, "exp": now - 1},
        _session_key(),
        algorithm="HS256",
    )
    response = await client.get(SOURCES_PATH, headers={"Cookie": f"{COOKIE_NAME}={expired}"})
    assert response.status_code == 401
    assert (await client.post(SESSION_PATH, json={"password": PASSWORD})).status_code == 204
    monkeypatch.setattr(settings, "GUSTOBOT_ADMIN_PASSWORD", SecretStr("changed-admin-password"))
    assert (await client.get(SOURCES_PATH)).status_code == 401


async def test_signed_in_request_reaches_protected_validation(client):
    assert (await client.post(SESSION_PATH, json={"password": PASSWORD})).status_code == 204
    response = await client.post("/api/v1/knowledge/recipes", json={})
    assert response.status_code == 422


@pytest.mark.parametrize("path", ["/api/v1/chat/", "/api/v1/chat/stream"])
async def test_public_chat_generation_remains_independent_of_admin_login(client, path):
    response = await client.post(path, json={})
    assert response.status_code == 422


async def test_blank_admin_password_disables_local_login():
    config = Settings(_env_file=None, GUSTOBOT_ADMIN_PASSWORD="")
    assert config.GUSTOBOT_ADMIN_PASSWORD is None
