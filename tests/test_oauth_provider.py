import time

import pytest
from pydantic import AnyUrl

from src.oauth_provider import InMemoryOAuthProvider

from mcp.server.auth.provider import AuthorizationCode, AuthorizationParams
from mcp.shared.auth import OAuthClientInformationFull


@pytest.fixture
def provider():
    return InMemoryOAuthProvider(static_bearer_token="static-secret")


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
    async def test_returns_redirect_url_with_code(self, provider, client_info, auth_params):
        await provider.register_client(client_info)
        redirect_url = await provider.authorize(client_info, auth_params)
        assert "code=" in redirect_url
        assert "state=test-state" in redirect_url
        assert redirect_url.startswith("http://localhost:3000/callback")


class TestTokenExchange:
    async def test_full_auth_code_flow(self, provider, client_info, auth_params):
        await provider.register_client(client_info)

        # 認可コード取得
        redirect_url = await provider.authorize(client_info, auth_params)
        code = redirect_url.split("code=")[1].split("&")[0]

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
        redirect_url = await provider.authorize(client_info, auth_params)
        code = redirect_url.split("code=")[1].split("&")[0]

        ac = await provider.load_authorization_code(client_info, code)
        await provider.exchange_authorization_code(client_info, ac)

        # 2回目はロードできない
        ac2 = await provider.load_authorization_code(client_info, code)
        assert ac2 is None

    async def test_expired_auth_code_returns_none(self, provider, client_info, auth_params):
        await provider.register_client(client_info)
        redirect_url = await provider.authorize(client_info, auth_params)
        code = redirect_url.split("code=")[1].split("&")[0]

        # 有効期限を過去に設定
        from src.oauth_provider import _hash
        provider._auth_codes[_hash(code)].expires_at = time.time() - 1

        ac = await provider.load_authorization_code(client_info, code)
        assert ac is None


class TestRefreshToken:
    async def test_refresh_token_rotation(self, provider, client_info, auth_params):
        await provider.register_client(client_info)
        redirect_url = await provider.authorize(client_info, auth_params)
        code = redirect_url.split("code=")[1].split("&")[0]
        ac = await provider.load_authorization_code(client_info, code)
        token = await provider.exchange_authorization_code(client_info, ac)

        # リフレッシュトークンでトークン更新
        rt = await provider.load_refresh_token(client_info, token.refresh_token)
        assert rt is not None

        new_token = await provider.exchange_refresh_token(client_info, rt, ["read"])
        assert new_token.access_token != token.access_token
        assert new_token.refresh_token != token.refresh_token

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
        redirect_url = await provider.authorize(client_info, auth_params)
        code = redirect_url.split("code=")[1].split("&")[0]
        ac = await provider.load_authorization_code(client_info, code)
        token = await provider.exchange_authorization_code(client_info, ac)

        at = await provider.load_access_token(token.access_token)
        assert at is not None
        await provider.revoke_token(at)

        at2 = await provider.load_access_token(token.access_token)
        assert at2 is None
