"""Sign-in: session cookie, protected routes, and the failed-login limiter."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.auth import COOKIE_NAME, FAILURE_WINDOW_S, MAX_FAILURES, Auth
from app.core.config import Settings, get_settings
from app.main import create_app
from tests.conftest import FakeGeocoder, FakeLLM

USER, PASSWORD = "planner@example.com", "correct horse"


class FakePool:
    """Auth answers before any route touches the database."""

    async def close(self) -> None:
        pass


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("AUTH_USERNAME", USER)
    monkeypatch.setenv("AUTH_PASSWORD", PASSWORD)
    monkeypatch.setenv("AUTH_SECRET", "test-secret")
    get_settings.cache_clear()
    app = create_app(pool=FakePool(), llm=FakeLLM(), geocoder=FakeGeocoder())  # type: ignore[arg-type]
    with TestClient(app, base_url="https://testserver") as c:
        yield c
    get_settings.cache_clear()


def login(client, username=USER, password=PASSWORD):
    return client.post("/auth/login", json={"username": username, "password": password})


def test_routes_need_a_session(client):
    r = client.get("/projects")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthenticated"
    assert client.get("/search", params={"q": "FPL"}).status_code == 401
    assert client.post("/ask", json={"question": "hi"}).status_code == 401
    assert client.get("/samples/plan.pdf").status_code == 401  # source documents too
    assert client.get("/health").status_code == 200  # the deploy smoke test
    assert client.get("/auth/session").json() == {
        "required": True, "authenticated": False, "username": None,
    }


def test_login_sets_a_secure_http_only_cookie(client):
    r = login(client, username="  Planner@Example.com ")  # case and spaces don't matter
    assert r.status_code == 200
    assert r.json() == {"required": True, "authenticated": True, "username": USER}
    cookie = r.headers["set-cookie"]
    assert cookie.startswith(f"{COOKIE_NAME}=")
    for flag in ("HttpOnly", "Secure", "SameSite=lax", "Path=/", "Max-Age=43200"):
        assert flag in cookie
    assert client.get("/auth/session").json()["authenticated"] is True
    assert client.get("/health").status_code == 200


def test_session_opens_protected_routes(client):
    login(client)
    # Past the auth check: the fake pool fails the route itself, not with a 401.
    with pytest.raises(AttributeError):
        client.get("/projects")


@pytest.mark.parametrize("username,password", [(USER, "wrong"), ("someone@else.com", PASSWORD),
                                               (USER, ""), (USER, PASSWORD.upper())])
def test_wrong_credentials_are_rejected(client, username, password):
    r = login(client, username, password)
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "invalid_credentials"
    assert COOKIE_NAME not in r.headers.get("set-cookie", "")
    assert client.get("/projects").status_code == 401


def test_logout_ends_the_session(client):
    login(client)
    r = client.post("/auth/logout")
    assert r.status_code == 200 and f'{COOKIE_NAME}=""' in r.headers["set-cookie"]
    assert client.get("/projects").status_code == 401


def test_forged_or_tampered_cookies_are_rejected(client):
    login(client)
    token = client.cookies.get(COOKIE_NAME)
    client.cookies.clear()
    for bad in (token[:-1] + ("0" if token[-1] != "0" else "1"), "garbage", "a.b", ""):
        client.cookies.set(COOKIE_NAME, bad)
        assert client.get("/projects").status_code == 401, bad
    other_key = Auth(Settings(auth_username=USER, auth_password=PASSWORD, auth_secret="other"))
    client.cookies.set(COOKIE_NAME, other_key.issue())
    assert client.get("/projects").status_code == 401


def test_failed_logins_lock_the_client_out(client):
    for _ in range(MAX_FAILURES):
        assert login(client, password="guess").status_code == 401
    r = login(client)  # even the right password, until the window passes
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "too_many_attempts"
    # Another address (Caddy's X-Forwarded-For hop) is unaffected.
    r = client.post("/auth/login", json={"username": USER, "password": PASSWORD},
                    headers={"X-Forwarded-For": "203.0.113.9"})
    assert r.status_code == 200


def test_tokens_expire_and_failures_age_out():
    now = [1_000_000.0]
    auth = Auth(Settings(auth_username=USER, auth_password=PASSWORD, auth_secret="k",
                         auth_session_hours=1), clock=lambda: now[0])
    token = auth.issue()
    assert auth.verify(token) == USER
    now[0] += 3601
    assert auth.verify(token) is None

    for _ in range(MAX_FAILURES):
        auth.record_failure("1.2.3.4")
    assert auth.locked_out("1.2.3.4")
    now[0] += FAILURE_WINDOW_S + 1
    assert not auth.locked_out("1.2.3.4")


def test_open_when_credentials_are_not_configured(monkeypatch):
    monkeypatch.setenv("AUTH_USERNAME", "")
    monkeypatch.setenv("AUTH_PASSWORD", "")
    get_settings.cache_clear()
    app = create_app(pool=FakePool(), llm=FakeLLM(), geocoder=FakeGeocoder())  # type: ignore[arg-type]
    with TestClient(app) as c:
        assert c.get("/auth/session").json() == {
            "required": False, "authenticated": True, "username": None,
        }
        assert c.get("/samples/nope.pdf").status_code == 404  # reached the route: no gate
    get_settings.cache_clear()
    assert not Auth(Settings(auth_username="x", auth_password="")).enabled


def test_public_paths_work_when_mounted_under_api(client):
    """Production serves this app at /api (app/serve.py)."""
    outer = FastAPI()
    outer.mount("/api", client.app)
    with TestClient(outer, base_url="https://testserver") as c:
        assert c.get("/api/health").status_code == 200
        assert c.get("/api/auth/session").json()["authenticated"] is False
        assert c.get("/api/search", params={"q": "FPL"}).status_code == 401
        r = c.post("/api/auth/login", json={"username": USER, "password": PASSWORD})
        assert r.status_code == 200
        assert c.get("/api/auth/session").json()["authenticated"] is True
