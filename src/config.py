from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    printify_api_key: str
    printify_shop_id: str | None = None
    mcp_auth_token: str | None = None
    oauth_issuer_url: str | None = None  # OAuth有効化: サーバーの公開URL（例: https://xxx.run.app）
    port: int = 8080
    transport: str = "streamable-http"

    model_config = {"env_file": ".env", "extra": "ignore"}
