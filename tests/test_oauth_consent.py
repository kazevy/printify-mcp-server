"""OAuth 認可エンドポイントの本人確認（同意画面）と起動時の認証必須化のテスト

PMCP-1: /authorize だけでは認可コードが出ず、オーナーの合言葉 + CSRF トークンを
        通した場合にだけコードが発行されることを HTTP レベルで確認する。
PMCP-2: 認証設定が無い HTTP サーバーは起動を拒否する。
"""

import base64
import hashlib
import re
import secrets
from urllib.parse import parse_qs, urlparse

import pytest
from starlette.testclient import TestClient

from src.server import create_app

OWNER_SECRET = "owner-secret-for-tests-0123456789"
ISSUER = "http://localhost"
REDIRECT_URI = "http://127.0.0.1:33418/callback"


@pytest.fixture
def oauth_env(monkeypatch):
    monkeypatch.setenv("PRINTIFY_API_KEY", "test-key")
    monkeypatch.setenv("OAUTH_ISSUER_URL", ISSUER)
    monkeypatch.setenv("MCP_AUTH_TOKEN", OWNER_SECRET)
    monkeypatch.delenv("OAUTH_OWNER_PASSWORD", raising=False)
    monkeypatch.delenv("OAUTH_ALLOWED_REDIRECT_URIS", raising=False)


@pytest.fixture
def client(oauth_env):
    with TestClient(create_app(), follow_redirects=False) as c:
        yield c


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    return verifier, challenge


def _register(client: TestClient, redirect_uri: str = REDIRECT_URI):
    return client.post(
        "/register",
        json={
            "redirect_uris": [redirect_uri],
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "client_name": "<script>alert(1)</script>",
        },
    )


def _start_authorize(client: TestClient):
    """クライアント登録 → /authorize。同意画面へのリダイレクト応答と付随情報を返す"""
    reg = _register(client)
    assert reg.status_code == 201, reg.text
    client_id = reg.json()["client_id"]
    verifier, challenge = _pkce()
    resp = client.get(
        "/authorize",
        params={
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": "xyz-state",
        },
    )
    return resp, client_id, verifier


def _open_consent(client: TestClient):
    resp, client_id, verifier = _start_authorize(client)
    location = resp.headers["location"]
    parsed = urlparse(location)
    page = client.get(f"{parsed.path}?{parsed.query}")
    assert page.status_code == 200
    req_id = parse_qs(parsed.query)["req"][0]
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
    return req_id, csrf, client_id, verifier, parsed.path


def _submit(client, path, req_id, csrf, secret, action="approve"):
    return client.post(
        path,
        data={"req": req_id, "csrf_token": csrf, "owner_secret": secret, "action": action},
    )


class TestAuthorizeRequiresOwner:
    def test_unauthenticated_authorize_does_not_yield_code(self, client):
        resp, _, _ = _start_authorize(client)
        assert resp.status_code == 302
        location = resp.headers["location"]
        # 登録済み redirect_uri ではなく自サーバーの同意画面へ飛ぶ
        assert location.startswith(f"{ISSUER}/oauth/consent?")
        assert "code=" not in location
        assert not location.startswith(REDIRECT_URI)

    def test_consent_page_escapes_client_name_and_sets_headers(self, client):
        resp, _, _ = _start_authorize(client)
        parsed = urlparse(resp.headers["location"])
        page = client.get(f"{parsed.path}?{parsed.query}")
        assert page.status_code == 200
        assert "<script>alert(1)</script>" not in page.text
        assert "&lt;script&gt;" in page.text
        assert REDIRECT_URI in page.text
        assert page.headers["cache-control"] == "no-store"
        assert page.headers["x-frame-options"] == "DENY"
        assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
        assert page.headers["referrer-policy"] == "no-referrer"

    def test_wrong_secret_rejected(self, client):
        req_id, csrf, _, _, path = _open_consent(client)
        resp = _submit(client, path, req_id, csrf, "wrong-secret")
        assert resp.status_code == 401
        assert "location" not in resp.headers
        assert "code=" not in resp.text

    def test_missing_csrf_rejected(self, client):
        req_id, _, _, _, path = _open_consent(client)
        resp = _submit(client, path, req_id, "forged-csrf", OWNER_SECRET)
        assert resp.status_code == 403
        assert "location" not in resp.headers

    def test_correct_secret_and_csrf_yields_code_and_token(self, client):
        req_id, csrf, client_id, verifier, path = _open_consent(client)
        resp = _submit(client, path, req_id, csrf, OWNER_SECRET)
        assert resp.status_code == 303
        location = resp.headers["location"]
        assert location.startswith(REDIRECT_URI)
        query = parse_qs(urlparse(location).query)
        assert query["state"] == ["xyz-state"]
        code = query["code"][0]

        token = client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
                "client_id": client_id,
                "code_verifier": verifier,
            },
        )
        assert token.status_code == 200, token.text
        assert token.json()["access_token"]

    def test_replayed_pending_state_rejected(self, client):
        req_id, csrf, _, _, path = _open_consent(client)
        first = _submit(client, path, req_id, csrf, OWNER_SECRET)
        assert first.status_code == 303
        replay = _submit(client, path, req_id, csrf, OWNER_SECRET)
        assert replay.status_code == 400
        assert "location" not in replay.headers
        # 使用済みの同意画面も再表示できない
        page = client.get(f"{path}?req={req_id}")
        assert page.status_code == 400

    def test_too_many_wrong_attempts_invalidate_pending(self, client):
        req_id, csrf, _, _, path = _open_consent(client)
        for _ in range(5):
            assert _submit(client, path, req_id, csrf, "wrong").status_code == 401
        # 5 回失敗した要求は正しい合言葉でも通らない
        resp = _submit(client, path, req_id, csrf, OWNER_SECRET)
        assert resp.status_code == 400

    def test_global_lockout_after_repeated_failures(self, client):
        for _ in range(4):
            req_id, csrf, _, _, path = _open_consent(client)
            for _ in range(5):
                _submit(client, path, req_id, csrf, "wrong")
        req_id, csrf, _, _, path = _open_consent(client)
        resp = _submit(client, path, req_id, csrf, OWNER_SECRET)
        assert resp.status_code == 429

    def test_deny_redirects_with_access_denied(self, client):
        req_id, csrf, _, _, path = _open_consent(client)
        resp = _submit(client, path, req_id, csrf, "", action="deny")
        assert resp.status_code == 303
        query = parse_qs(urlparse(resp.headers["location"]).query)
        assert query["error"] == ["access_denied"]
        assert "code" not in query

    def test_separate_owner_password_takes_precedence(self, oauth_env, monkeypatch):
        monkeypatch.setenv("OAUTH_OWNER_PASSWORD", "separate-owner-password-xyz")
        with TestClient(create_app(), follow_redirects=False) as c:
            req_id, csrf, _, _, path = _open_consent(c)
            assert _submit(c, path, req_id, csrf, OWNER_SECRET).status_code == 401
            req_id, csrf, _, _, path = _open_consent(c)
            assert _submit(c, path, req_id, csrf, "separate-owner-password-xyz").status_code == 303


class TestRedirectUriAllowlist:
    def test_attacker_redirect_uri_rejected_at_registration(self, client):
        resp = _register(client, "https://attacker.example/cb")
        assert resp.status_code == 400
        assert resp.json()["error"] == "invalid_redirect_uri"

    @pytest.mark.parametrize(
        "uri",
        [
            "https://claude.ai/api/mcp/auth_callback",
            "https://claude.com/api/mcp/auth_callback",
            "http://localhost:51234/callback",
            "http://127.0.0.1:8976/oauth/callback",
        ],
    )
    def test_known_clients_allowed(self, client, uri):
        assert _register(client, uri).status_code == 201

    def test_extra_redirect_uri_from_env(self, oauth_env, monkeypatch):
        monkeypatch.setenv("OAUTH_ALLOWED_REDIRECT_URIS", "https://example.com/cb, https://x.test/a")
        with TestClient(create_app(), follow_redirects=False) as c:
            assert _register(c, "https://example.com/cb").status_code == 201
            assert _register(c, "https://example.com/other").status_code == 400


class TestStartupRequiresAuth:
    def test_http_app_without_any_auth_config_fails(self, monkeypatch):
        monkeypatch.setenv("PRINTIFY_API_KEY", "test-key")
        monkeypatch.delenv("MCP_AUTH_TOKEN", raising=False)
        monkeypatch.delenv("OAUTH_ISSUER_URL", raising=False)
        monkeypatch.delenv("OAUTH_OWNER_PASSWORD", raising=False)
        with pytest.raises(RuntimeError):
            create_app()

    def test_oauth_without_owner_secret_fails(self, monkeypatch):
        monkeypatch.setenv("PRINTIFY_API_KEY", "test-key")
        monkeypatch.setenv("OAUTH_ISSUER_URL", ISSUER)
        monkeypatch.delenv("MCP_AUTH_TOKEN", raising=False)
        monkeypatch.delenv("OAUTH_OWNER_PASSWORD", raising=False)
        with pytest.raises(RuntimeError):
            create_app()

    def test_short_owner_password_fails(self, oauth_env, monkeypatch):
        monkeypatch.setenv("OAUTH_OWNER_PASSWORD", "short")
        with pytest.raises(RuntimeError):
            create_app()

    def test_empty_owner_password_falls_back_to_auth_token(self, oauth_env, monkeypatch):
        # .env.example のように空欄で置いても起動でき、MCP_AUTH_TOKEN が合言葉になる
        monkeypatch.setenv("OAUTH_OWNER_PASSWORD", "")
        with TestClient(create_app(), follow_redirects=False) as c:
            req_id, csrf, _, _, path = _open_consent(c)
            assert _submit(c, path, req_id, csrf, OWNER_SECRET).status_code == 303

    def test_short_auth_token_fails(self, monkeypatch):
        monkeypatch.setenv("PRINTIFY_API_KEY", "test-key")
        monkeypatch.setenv("MCP_AUTH_TOKEN", "short")
        monkeypatch.delenv("OAUTH_ISSUER_URL", raising=False)
        with pytest.raises(RuntimeError):
            create_app()

    def test_bearer_mode_still_starts_and_protects_mcp(self, monkeypatch):
        monkeypatch.setenv("PRINTIFY_API_KEY", "test-key")
        monkeypatch.setenv("MCP_AUTH_TOKEN", OWNER_SECRET)
        monkeypatch.delenv("OAUTH_ISSUER_URL", raising=False)
        with TestClient(create_app()) as c:
            assert c.get("/health").status_code == 200
            assert c.post("/mcp", json={}).status_code == 401


class TestStaticBearerInOAuthMode:
    def test_static_bearer_still_accepted_on_mcp(self, client):
        resp = client.post(
            "/mcp",
            headers={
                "authorization": f"Bearer {OWNER_SECRET}",
                "accept": "application/json, text/event-stream",
            },
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
        assert resp.status_code == 200, resp.text

    def test_mcp_without_token_rejected(self, client):
        resp = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        assert resp.status_code == 401
