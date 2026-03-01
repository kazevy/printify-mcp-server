"""軽量インメモリ OAuth プロバイダー（個人利用向け）

Claude Web/Mobile が MCP SDK の OAuth フローで接続できるようにする。
同時に、既存の静的 Bearer Token 認証（Claude Code / TypingMind）も維持する。
"""

import hashlib
import logging
import secrets
import time
import uuid
from urllib.parse import urlencode, urlparse, urlunparse, parse_qs

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

logger = logging.getLogger(__name__)

TOKEN_TTL = 3600  # 1時間
REFRESH_TOKEN_TTL = 86400 * 30  # 30日
AUTH_CODE_TTL = 600  # 10分


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _construct_redirect_uri(redirect_uri: str, **params: str) -> str:
    """リダイレクトURIにクエリパラメータを追加する"""
    parsed = urlparse(redirect_uri)
    existing = parse_qs(parsed.query, keep_blank_values=True)
    for k, v in params.items():
        if v is not None:
            existing[k] = [v]
    new_query = urlencode(existing, doseq=True)
    return urlunparse(parsed._replace(query=new_query))


class InMemoryOAuthProvider(
    OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]
):
    """インメモリ OAuth プロバイダー

    - DB不要（個人利用、インスタンス再起動でトークン無効化）
    - 同意画面なし（authorize で即座にリダイレクト）
    - 静的 Bearer Token もフォールバックとして受け付ける
    """

    def __init__(self, static_bearer_token: str | None = None):
        self._clients: dict[str, OAuthClientInformationFull] = {}
        self._auth_codes: dict[str, AuthorizationCode] = {}
        self._access_tokens: dict[str, AccessToken] = {}
        self._refresh_tokens: dict[str, RefreshToken] = {}
        self._static_bearer_token = static_bearer_token

    # --- Client Registration (DCR) ---

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        return self._clients.get(client_id)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        if not client_info.client_id:
            client_info.client_id = str(uuid.uuid4())
        client_info.client_id_issued_at = int(time.time())
        self._clients[client_info.client_id] = client_info
        logger.info(f"OAuth client registered: {client_info.client_id}")

    # --- Authorization ---

    async def authorize(
        self,
        client: OAuthClientInformationFull,
        params: AuthorizationParams,
    ) -> str:
        """同意画面なしで即座に認可コードを発行しリダイレクト"""
        code = secrets.token_urlsafe(32)
        self._auth_codes[_hash(code)] = AuthorizationCode(
            code=code,
            scopes=params.scopes or [],
            expires_at=time.time() + AUTH_CODE_TTL,
            client_id=client.client_id,
            code_challenge=params.code_challenge,
            redirect_uri=params.redirect_uri,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            resource=params.resource,
        )
        logger.info(f"Auth code issued for client {client.client_id}")
        return _construct_redirect_uri(
            str(params.redirect_uri),
            code=code,
            state=params.state,
        )

    async def load_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: str,
    ) -> AuthorizationCode | None:
        ac = self._auth_codes.get(_hash(authorization_code))
        if ac is None:
            return None
        if ac.client_id != client.client_id:
            return None
        if time.time() > ac.expires_at:
            self._auth_codes.pop(_hash(authorization_code), None)
            return None
        return ac

    # --- Token Exchange ---

    async def exchange_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: AuthorizationCode,
    ) -> OAuthToken:
        # 認可コード消費（ワンタイム）
        self._auth_codes.pop(_hash(authorization_code.code), None)

        access_token = secrets.token_urlsafe(32)
        refresh_token = secrets.token_urlsafe(32)
        now = int(time.time())

        self._access_tokens[_hash(access_token)] = AccessToken(
            token=access_token,
            client_id=client.client_id,
            scopes=authorization_code.scopes,
            expires_at=now + TOKEN_TTL,
            resource=authorization_code.resource,
        )
        self._refresh_tokens[_hash(refresh_token)] = RefreshToken(
            token=refresh_token,
            client_id=client.client_id,
            scopes=authorization_code.scopes,
            expires_at=now + REFRESH_TOKEN_TTL,
        )

        logger.info(f"Tokens issued for client {client.client_id}")
        return OAuthToken(
            access_token=access_token,
            token_type="Bearer",
            expires_in=TOKEN_TTL,
            refresh_token=refresh_token,
            scope=" ".join(authorization_code.scopes) if authorization_code.scopes else None,
        )

    async def load_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: str,
    ) -> RefreshToken | None:
        rt = self._refresh_tokens.get(_hash(refresh_token))
        if rt is None:
            return None
        if rt.client_id != client.client_id:
            return None
        if rt.expires_at and time.time() > rt.expires_at:
            self._refresh_tokens.pop(_hash(refresh_token), None)
            return None
        return rt

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        # 古いトークンを無効化
        self._refresh_tokens.pop(_hash(refresh_token.token), None)

        # 新しいトークンを発行（トークンローテーション）
        new_access = secrets.token_urlsafe(32)
        new_refresh = secrets.token_urlsafe(32)
        now = int(time.time())
        effective_scopes = scopes if scopes else refresh_token.scopes

        self._access_tokens[_hash(new_access)] = AccessToken(
            token=new_access,
            client_id=client.client_id,
            scopes=effective_scopes,
            expires_at=now + TOKEN_TTL,
        )
        self._refresh_tokens[_hash(new_refresh)] = RefreshToken(
            token=new_refresh,
            client_id=client.client_id,
            scopes=effective_scopes,
            expires_at=now + REFRESH_TOKEN_TTL,
        )

        return OAuthToken(
            access_token=new_access,
            token_type="Bearer",
            expires_in=TOKEN_TTL,
            refresh_token=new_refresh,
            scope=" ".join(effective_scopes) if effective_scopes else None,
        )

    # --- Token Verification ---

    async def load_access_token(self, token: str) -> AccessToken | None:
        """OAuthトークンまたは静的Bearer Tokenを検証する

        1. OAuthで発行されたアクセストークンを検索
        2. 見つからなければ静的Bearer Token（MCP_AUTH_TOKEN）と照合
        """
        # OAuth トークン検証
        at = self._access_tokens.get(_hash(token))
        if at is not None:
            if at.expires_at and time.time() > at.expires_at:
                self._access_tokens.pop(_hash(token), None)
                return None
            return at

        # 静的 Bearer Token フォールバック
        if self._static_bearer_token and secrets.compare_digest(
            token, self._static_bearer_token
        ):
            return AccessToken(
                token=token,
                client_id="static-bearer",
                scopes=[],
                expires_at=None,
            )

        return None

    # --- Revocation ---

    async def revoke_token(
        self,
        token: AccessToken | RefreshToken,
    ) -> None:
        if isinstance(token, AccessToken):
            self._access_tokens.pop(_hash(token.token), None)
        elif isinstance(token, RefreshToken):
            self._refresh_tokens.pop(_hash(token.token), None)
