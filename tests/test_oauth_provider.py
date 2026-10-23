import time
from urllib.parse import parse_qs, urlparse

import pytest
from pydantic import AnyUrl

from src.oauth_provider import ConsentError, InMemoryOAuthProvider

from mcp.server.auth.provider import AuthorizationParams
from mcp.shared.auth import OAuthClientInformationFull


OWNER_SECRET = "owner-secret-0123456789"


@pytest.fixture
def provider():
    return InMemoryOAuthProvider(
        static_bearer_token="static-secret",
        owner_secret=OWNER_SECRET,
        consent_url="https://mcp.example/oauth/consent",
    )


def _request_id(consent_url: str) -> str:
    return parse_qs(urlparse(consent_url).query)["req"][0]


async def _obtain_code(provider, client_info, auth_params) -> str:
    """authorize → 同意画面でオーナー承認 → 認可コード"""
    consent_url = await provider.authorize(client_info, auth_params)
    req_id = _request_id(consent_url)
    pending = provider.get_pending(req_id)
    redirect_url = provider.approve(req_id, pending.csrf_token, OWNER_SECRET)
    return parse_qs(urlparse(redirect_url).query)["code"][0]


@pytest.fixture
def client_info():
    return OAuthClientInformationFull(
        client_id="test-client",
        redirect_uris=[AnyUrl("http://localhost:3000/callback")],
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        token_endpoint_auth_method="none",
    )


@pytest.fixture
def auth_params():
    return AuthorizationParams(
        state="test-state",
        scopes=["read"],
        code_challenge="challenge123",
        redirect_uri=AnyUrl("http://localhost:3000/callback"),
        redirect_uri_provided_explicitly=True,
        resource="https://mcp.example/mcp",
    )


class TestClientRegistration:
    async def test_register_and_get_client(self, provider, client_info):
        await provider.register_client(client_info)
        result = await provider.get_client("test-client")
        assert result is not None
        assert result.client_id == "test-client"

    async def test_get_unknown_client_returns_none(self, provider):
        result = await provider.get_client("unknown")
        assert result is None

    async def test_auto_assigns_client_id(self, provider):
        info = OAuthClientInformationFull(
            redirect_uris=[AnyUrl("http://localhost/cb")],
            token_endpoint_auth_method="none",
        )
        await provider.register_client(info)
        assert info.client_id is not None
        assert len(info.client_id) > 0


class TestAuthorize:
    async def test_authorize_returns_consent_url_not_code(self, provider, client_info, auth_params):
        await provider.register_client(client_info)
        url = await provider.authorize(client_info, auth_params)
        assert url.startswith("https://mcp.example/oauth/consent?req=")
        assert "code=" not in url
        assert provider._auth_codes == {}

    async def test_approve_with_owner_secret_issues_code(self, provider, client_info, auth_params):
        await provider.register_client(client_info)
        req_id = _request_id(await provider.authorize(client_info, auth_params))
        pending = provider.get_pending(req_id)
        redirect_url = provider.approve(req_id, pending.csrf_token, OWNER_SECRET)
        assert redirect_url.startswith("http://localhost:3000/callback")
        assert "code=" in redirect_url
        assert "state=test-state" in redirect_url

    async def test_wrong_secret_raises_401(self, provider, client_info, auth_params):
        await provider.register_client(client_info)
        req_id = _request_id(await provider.authorize(client_info, auth_params))
        pending = provider.get_pending(req_id)
        with pytest.raises(ConsentError) as e:
            provider.approve(req_id, pending.csrf_token, "wrong")
        assert e.value.status_code == 401
        assert provider._auth_codes == {}

    async def test_wrong_csrf_raises_403(self, provider, client_info, auth_params):
        await provider.register_client(client_info)
        req_id = _request_id(await provider.authorize(client_info, auth_params))
        with pytest.raises(ConsentError) as e:
            provider.approve(req_id, "forged", OWNER_SECRET)
        assert e.value.status_code == 403

    async def test_pending_is_single_use(self, provider, client_info, auth_params):
        await provider.register_client(client_info)
        req_id = _request_id(await provider.authorize(client_info, auth_params))
        pending = provider.get_pending(req_id)
        provider.approve(req_id, pending.csrf_token, OWNER_SECRET)
        assert provider.get_pending(req_id) is None
        with pytest.raises(ConsentError) as e:
            provider.approve(req_id, pending.csrf_token, OWNER_SECRET)
        assert e.value.status_code == 400

    async def test_expired_pending_rejected(self, provider, client_info, auth_params):
        await provider.register_client(client_info)
        req_id = _request_id(await provider.authorize(client_info, auth_params))
        pending = provider.get_pending(req_id)
        pending.expires_at = time.time() - 1
        assert provider.get_pending(req_id) is None
        with pytest.raises(ConsentError) as e:
            provider.approve(req_id, pending.csrf_token, OWNER_SECRET)
        assert e.value.status_code == 400

    async def test_no_owner_secret_fails_closed(self, client_info, auth_params):
        provider = InMemoryOAuthProvider(static_bearer_token=None, owner_secret=None)
        await provider.register_client(client_info)
        req_id = _request_id(await provider.authorize(client_info, auth_params))
        pending = provider.get_pending(req_id)
        with pytest.raises(ConsentError):
            provider.approve(req_id, pending.csrf_token, "")

    async def test_pending_store_is_bounded(self, provider, client_info, auth_params):
        await provider.register_client(client_info)
        for _ in range(150):
            await provider.authorize(client_info, auth_params)
        assert len(provider._pending) <= 100


class TestRedirectUriPolicy:
    async def test_non_allowlisted_redirect_rejected(self, provider):
        from mcp.server.auth.provider import RegistrationError

        info = OAuthClientInformationFull(
            redirect_uris=[AnyUrl("https://attacker.example/cb")],
            token_endpoint_auth_method="none",
        )
        with pytest.raises(RegistrationError):
            await provider.register_client(info)

    async def test_client_store_is_bounded(self, provider):
        for i in range(250):
            await provider.register_client(
                OAuthClientInformationFull(
                    client_id=f"c{i}",
                    redirect_uris=[AnyUrl("http://localhost/cb")],
                    token_endpoint_auth_method="none",
                )
            )
        assert len(provider._clients) <= 200
        assert await provider.get_client("c249") is not None

    async def test_authorized_client_survives_registration_flood(
        self, provider, client_info, auth_params
    ):
        # トークン発行済みの正規クライアントは DCR の大量登録で追い出されない
        await provider.register_client(client_info)
        await _obtain_code(provider, client_info, auth_params)
        for i in range(300):
            await provider.register_client(
                OAuthClientInformationFull(
                    client_id=f"flood{i}",
                    redirect_uris=[AnyUrl("http://localhost/cb")],
                    token_endpoint_auth_method="none",
                )
            )
        assert await provider.get_client("test-client") is not None
        assert len(provider._clients) <= 200

    async def test_extra_allowlist_is_normalized(self):
        provider = InMemoryOAuthProvider(
            owner_secret=OWNER_SECRET, allowed_redirect_uris=("https://example.com",)
        )
        await provider.register_client(
            OAuthClientInformationFull(
                redirect_uris=[AnyUrl("https://example.com")],
                token_endpoint_auth_method="none",
            )
        )

    async def test_failure_log_is_bounded(self, provider, client_info, auth_params):
        await provider.register_client(client_info)
        for _ in range(100):
            req_id = _request_id(await provider.authorize(client_info, auth_params))
            with pytest.raises(ConsentError):
                provider.approve(req_id, "forged", OWNER_SECRET)
        assert len(provider._failures) <= 20


class TestTokenExchange:
    async def test_full_auth_code_flow(self, provider, client_info, auth_params):
        await provider.register_client(client_info)

        # 認可コード取得（同意画面でオーナー確認を通す）
        code = await _obtain_code(provider, client_info, auth_params)

        # 認可コードのロード
        ac = await provider.load_authorization_code(client_info, code)
        assert ac is not None
        assert ac.client_id == "test-client"

        # トークン交換
        token = await provider.exchange_authorization_code(client_info, ac)
        assert token.access_token
        assert token.refresh_token
        assert token.token_type == "Bearer"

        # アクセストークンの検証
        at = await provider.load_access_token(token.access_token)
        assert at is not None
        assert at.client_id == "test-client"

    async def test_auth_code_is_single_use(self, provider, client_info, auth_params):
        await provider.register_client(client_info)
        code = await _obtain_code(provider, client_info, auth_params)

        ac = await provider.load_authorization_code(client_info, code)
        await provider.exchange_authorization_code(client_info, ac)

        # 2回目はロードできない
        ac2 = await provider.load_authorization_code(client_info, code)
        assert ac2 is None

    async def test_expired_auth_code_returns_none(self, provider, client_info, auth_params):
        await provider.register_client(client_info)
        code = await _obtain_code(provider, client_info, auth_params)

        # 有効期限を過去に設定
        from src.oauth_provider import _hash
        provider._auth_codes[_hash(code)].expires_at = time.time() - 1

        ac = await provider.load_authorization_code(client_info, code)
        assert ac is None


class TestRefreshToken:
    async def test_refresh_token_rotation(self, provider, client_info, auth_params):
        await provider.register_client(client_info)
        code = await _obtain_code(provider, client_info, auth_params)
        ac = await provider.load_authorization_code(client_info, code)
        token = await provider.exchange_authorization_code(client_info, ac)

        # リフレッシュトークンでトークン更新
        rt = await provider.load_refresh_token(client_info, token.refresh_token)
        assert rt is not None

        new_token = await provider.exchange_refresh_token(client_info, rt, ["read"])
        assert new_token.access_token != token.access_token
        assert new_token.refresh_token != token.refresh_token

        # resource（RFC 8707）はリフレッシュ後のトークンにも引き継がれる
        at = await provider.load_access_token(new_token.access_token)
        assert at.resource == auth_params.resource

        # 古いリフレッシュトークンは無効
        old_rt = await provider.load_refresh_token(client_info, token.refresh_token)
        assert old_rt is None


class TestStaticBearerFallback:
    async def test_static_bearer_token_accepted(self, provider):
        at = await provider.load_access_token("static-secret")
        assert at is not None
        assert at.client_id == "static-bearer"

    async def test_invalid_token_rejected(self, provider):
        at = await provider.load_access_token("wrong-token")
        assert at is None

    async def test_no_static_token_configured(self):
        provider = InMemoryOAuthProvider(static_bearer_token=None)
        at = await provider.load_access_token("any-token")
        assert at is None


class TestRevocation:
    async def test_revoke_access_token(self, provider, client_info, auth_params):
        await provider.register_client(client_info)
        code = await _obtain_code(provider, client_info, auth_params)
        ac = await provider.load_authorization_code(client_info, code)
        token = await provider.exchange_authorization_code(client_info, ac)

        at = await provider.load_access_token(token.access_token)
        assert at is not None
        await provider.revoke_token(at)

        at2 = await provider.load_access_token(token.access_token)
        assert at2 is None
