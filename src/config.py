from pydantic_settings import BaseSettings

# 合言葉・静的 Bearer Token の最小長（/mcp の静的 Bearer 照合には試行回数制限が無いため）
MIN_SECRET_LENGTH = 16


class Settings(BaseSettings):
    printify_api_key: str
    printify_shop_id: str | None = None
    mcp_auth_token: str | None = None
    oauth_issuer_url: str | None = None  # OAuth有効化: サーバーの公開URL（例: https://xxx.run.app）
    # OAuth 同意画面でオーナーが入力する合言葉。未設定なら MCP_AUTH_TOKEN を使う
    oauth_owner_password: str | None = None
    # DCR で追加許可する redirect_uri（カンマ区切り・完全一致）。
    # claude.ai / claude.com のコールバックとループバックは既定で許可済み
    oauth_allowed_redirect_uris: str | None = None
    port: int = 8080
    transport: str = "streamable-http"

    # 空欄の環境変数（例: `OAUTH_OWNER_PASSWORD=`）は未設定として扱う
    model_config = {"env_file": ".env", "extra": "ignore", "env_ignore_empty": True}

    @property
    def extra_allowed_redirect_uris(self) -> tuple[str, ...]:
        if not self.oauth_allowed_redirect_uris:
            return ()
        return tuple(u.strip() for u in self.oauth_allowed_redirect_uris.split(",") if u.strip())
