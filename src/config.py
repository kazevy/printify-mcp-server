from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    printify_api_key: str
    printify_shop_id: str | None = None
    mcp_auth_token: str | None = None
    port: int = 8080
    transport: str = "streamable-http"

    model_config = {"env_file": ".env"}
