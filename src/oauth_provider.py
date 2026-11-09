"""軽量インメモリ OAuth プロバイダー（個人利用向け）

Claude Web/Mobile が MCP SDK の OAuth フローで接続できるようにする。
同時に、既存の静的 Bearer Token 認証（Claude Code / TypingMind）も維持する。

認可コードは、オーナーが同意画面（src/consent.py）で合言葉を入力して
承認した場合にだけ発行する。/authorize は保留中の認可要求を作って
同意画面へリダイレクトするだけで、コードは出さない。
"""

import hashlib
import hmac
import logging
import secrets
import time
import uuid
from collections import OrderedDict, deque
from dataclasses import dataclass
from urllib.parse import urlencode, urlparse, urlunparse, parse_qs

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    RegistrationError,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import AnyUrl

logger = logging.getLogger(__name__)

TOKEN_TTL = 3600  # 1時間
REFRESH_TOKEN_TTL = 86400 * 30  # 30日
AUTH_CODE_TTL = 600  # 10分

# 同意画面（オーナー確認）の制限
PENDING_TTL = 300  # 保留中の認可要求の有効期限: 5分
MAX_PENDING = 100  # 保留中の認可要求の上限（メモリ枯渇対策）
MAX_CLIENTS = 200  # 登録クライアントの上限（超えたら古い順に破棄）
MAX_ATTEMPTS_PER_REQUEST = 5  # 1つの認可要求で許す失敗回数
GLOBAL_FAILURE_LIMIT = 20  # 全体で許す失敗回数（ウィンドウ内）
GLOBAL_FAILURE_WINDOW = 900  # 全体失敗カウントのウィンドウ: 15分

# DCR で登録を許す redirect_uri（完全一致）。ループバックは別途許可する
DEFAULT_ALLOWED_REDIRECT_URIS = (
    "https://claude.ai/api/mcp/auth_callback",
    "https://claude.com/api/mcp/auth_callback",
)
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


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


def _secure_equals(a: str, b: str) -> bool:
    """定数時間比較。非 ASCII を含む文字列でも例外を出さないよう bytes で比べる"""
    return hmac.compare_digest(a.encode("utf-8", "surrogatepass"), b.encode("utf-8", "surrogatepass"))


def is_allowed_redirect_uri(uri: str, extra_allowed: tuple[str, ...] = ()) -> bool:
    """DCR で登録できる redirect_uri か判定する

    - ループバック（http://localhost / 127.0.0.1 / [::1]、ポート・パス任意）: CLI クライアント用
    - claude.ai / claude.com のコールバック、および環境変数で追加した URI（完全一致）
    """
    if uri in DEFAULT_ALLOWED_REDIRECT_URIS or uri in extra_allowed:
        return True
    parsed = urlparse(uri)
    return parsed.scheme == "http" and parsed.hostname in _LOOPBACK_HOSTS


class ConsentError(Exception):
    """同意画面での承認失敗（HTTP ステータスとメッセージを持つ）"""

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


@dataclass
class PendingAuthorization:
    """オーナーの承認待ちの認可要求（使い捨て・短命）"""

    client: OAuthClientInformationFull
    params: AuthorizationParams
    csrf_token: str
    expires_at: float
    failed_attempts: int = 0


class InMemoryOAuthProvider(
    OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]
):
    """インメモリ OAuth プロバイダー

    - DB不要（個人利用、インスタンス再起動でトークン無効化）
    - 認可コードはオーナーが同意画面で合言葉を入力して承認した場合だけ発行
    - DCR の redirect_uri は許可リスト（claude.ai / claude.com / ループバック）に限定
    - 静的 Bearer Token もフォールバックとして受け付ける
    """

    def __init__(
        self,
        static_bearer_token: str | None = None,
        owner_secret: str | None = None,
        consent_url: str = "/oauth/consent",
        allowed_redirect_uris: tuple[str, ...] = (),
    ):
        self._clients: OrderedDict[str, OAuthClientInformationFull] = OrderedDict()
        self._auth_codes: dict[str, AuthorizationCode] = {}
        self._access_tokens: dict[str, AccessToken] = {}
        self._refresh_tokens: dict[str, RefreshToken] = {}
        self._pending: OrderedDict[str, PendingAuthorization] = OrderedDict()
        self._failures: deque[float] = deque()
        self._static_bearer_token = static_bearer_token
        self._owner_secret = owner_secret
        self._consent_url = consent_url
        # DCR 側の redirect_uri は正規化済み AnyUrl の文字列なので、許可リストも同じ形に揃える
        self._allowed_redirect_uris = tuple(str(AnyUrl(u)) for u in allowed_redirect_uris)
        # 認可（トークン発行）まで済んだクライアント。上限超過時の破棄対象から外す
        self._authorized_client_ids: set[str] = set()

    # --- Client Registration (DCR) ---

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        return self._clients.get(client_id)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        for uri in client_info.redirect_uris or []:
            if not is_allowed_redirect_uri(str(uri), self._allowed_redirect_uris):
                logger.warning(f"OAuth client registration rejected (redirect_uri not allowed): {uri}")
                raise RegistrationError(
                    error="invalid_redirect_uri",
                    error_description="redirect_uri is not in the allowlist of this server",
                )
        if not client_info.client_id:
            client_info.client_id = str(uuid.uuid4())
        client_info.client_id_issued_at = int(time.time())
        self._clients[client_info.client_id] = client_info
        self._evict_clients()
        logger.info(f"OAuth client registered: {client_info.client_id}")

    def _evict_clients(self) -> None:
        """上限超過分を古い順に破棄する。未承認のクライアントから先に消す

        大量の DCR 登録で、承認済みの正規クライアント（claude.ai 等）が追い出され
        リフレッシュに失敗するのを防ぐ。
        """
        if len(self._clients) <= MAX_CLIENTS:
            return
        unauthorized = [cid for cid in self._clients if cid not in self._authorized_client_ids]
        for cid in unauthorized[: len(self._clients) - MAX_CLIENTS]:
            self._clients.pop(cid, None)
        while len(self._clients) > MAX_CLIENTS:
            cid, _ = self._clients.popitem(last=False)
            self._authorized_client_ids.discard(cid)

    # --- Authorization ---

    async def authorize(
        self,
        client: OAuthClientInformationFull,
        params: AuthorizationParams,
    ) -> str:
        """保留中の認可要求を作り、オーナー確認用の同意画面へリダイレクトさせる

        ここでは認可コードを発行しない（PMCP-1 対策）。
        """
        self._purge_expired_pending()
        request_id = secrets.token_urlsafe(32)
        self._pending[request_id] = PendingAuthorization(
            client=client,
            params=params,
            csrf_token=secrets.token_urlsafe(32),
            expires_at=time.time() + PENDING_TTL,
        )
        while len(self._pending) > MAX_PENDING:
            self._pending.popitem(last=False)
        logger.info(f"Authorization pending owner consent for client {client.client_id}")
        return f"{self._consent_url}?{urlencode({'req': request_id})}"

    # --- Owner consent ---

    def _purge_expired_pending(self) -> None:
        now = time.time()
        for key in [k for k, p in self._pending.items() if p.expires_at < now]:
            self._pending.pop(key, None)

    def get_pending(self, request_id: str) -> PendingAuthorization | None:
        """有効な保留中の認可要求を返す（期限切れ・使用済みは None）"""
        pending = self._pending.get(request_id)
        if pending is None:
            return None
        if time.time() > pending.expires_at:
            self._pending.pop(request_id, None)
            return None
        return pending

    def _prune_failures(self) -> None:
        cutoff = time.time() - GLOBAL_FAILURE_WINDOW
        while self._failures and self._failures[0] < cutoff:
            self._failures.popleft()

    def _is_locked_out(self) -> bool:
        self._prune_failures()
        return len(self._failures) >= GLOBAL_FAILURE_LIMIT

    def _record_failure(self, request_id: str, pending: PendingAuthorization) -> None:
        self._prune_failures()
        # ロック判定に必要な件数だけ保持する（メモリを無制限に使わない）
        if len(self._failures) < GLOBAL_FAILURE_LIMIT:
            self._failures.append(time.time())
        pending.failed_attempts += 1
        if pending.failed_attempts >= MAX_ATTEMPTS_PER_REQUEST:
            self._pending.pop(request_id, None)

    def _check_request(self, request_id: str, csrf_token: str) -> PendingAuthorization:
        pending = self.get_pending(request_id)
        if pending is None:
            raise ConsentError(400, "This authorization request is invalid or has expired.")
        if not _secure_equals(csrf_token, pending.csrf_token):
            self._record_failure(request_id, pending)
            logger.warning(f"OAuth consent CSRF mismatch for client {pending.client.client_id}")
            raise ConsentError(403, "Invalid form token. Reload the page and try again.")
        return pending

    def approve(self, request_id: str, csrf_token: str, owner_secret: str) -> str:
        """オーナーの合言葉を検証し、成功時のみ認可コードを発行してリダイレクト先を返す"""
        pending = self._check_request(request_id, csrf_token)
        if self._is_locked_out():
            logger.warning("OAuth consent locked out (too many failed attempts)")
            raise ConsentError(429, "Too many failed attempts. Try again later.")
        if not self._owner_secret or not _secure_equals(owner_secret, self._owner_secret):
            self._record_failure(request_id, pending)
            logger.warning(f"OAuth consent rejected (wrong secret) for client {pending.client.client_id}")
            raise ConsentError(401, "Incorrect owner secret.")

        # 使い捨て: 成功したら保留中の要求を破棄してからコードを発行する
        self._pending.pop(request_id, None)
        client, params = pending.client, pending.params
        self._authorized_client_ids.add(client.client_id)
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
        logger.info(f"Auth code issued after owner consent for client {client.client_id}")
        return _construct_redirect_uri(
            str(params.redirect_uri),
            code=code,
            state=params.state,
        )

    def deny(self, request_id: str, csrf_token: str) -> str:
        """オーナーが拒否した場合、access_denied でクライアントへ戻す"""
        pending = self._check_request(request_id, csrf_token)
        self._pending.pop(request_id, None)
        logger.info(f"OAuth consent denied for client {pending.client.client_id}")
        return _construct_redirect_uri(
            str(pending.params.redirect_uri),
            error="access_denied",
            state=pending.params.state,
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
            resource=authorization_code.resource,
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
            resource=refresh_token.resource,
        )
        self._refresh_tokens[_hash(new_refresh)] = RefreshToken(
            token=new_refresh,
            client_id=client.client_id,
            scopes=effective_scopes,
            expires_at=now + REFRESH_TOKEN_TTL,
            resource=refresh_token.resource,
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
        if self._static_bearer_token and _secure_equals(token, self._static_bearer_token):
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
