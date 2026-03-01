import contextlib
import logging
import os

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.server import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from src.services.printify import PrintifyService
from src.tools import shops, products, catalog, images, orders

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def _create_service_and_mcp():
    from src.config import Settings

    settings = Settings()
    service = PrintifyService(
        api_key=settings.printify_api_key,
        shop_id=settings.printify_shop_id,
    )

    # OAuth / Bearer Token 認証の設定
    mcp_kwargs = {
        "json_response": True,
        "stateless_http": True,
        "transport_security": TransportSecuritySettings(
            enable_dns_rebinding_protection=False,
        ),
    }

    if settings.oauth_issuer_url:
        # OAuth モード: Claude Web/Mobile + 静的Bearer Token（Claude Code/TypingMind）
        from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions

        from src.oauth_provider import InMemoryOAuthProvider

        oauth_provider = InMemoryOAuthProvider(
            static_bearer_token=settings.mcp_auth_token,
        )
        mcp_kwargs["auth_server_provider"] = oauth_provider
        mcp_kwargs["auth"] = AuthSettings(
            issuer_url=settings.oauth_issuer_url,
            resource_server_url=f"{settings.oauth_issuer_url}/mcp",
            client_registration_options=ClientRegistrationOptions(
                enabled=True,  # DCR有効化（Claude Webが自動登録）
            ),
        )
        logger.info(f"OAuth enabled (issuer: {settings.oauth_issuer_url})")
    else:
        logger.info("OAuth disabled (no OAUTH_ISSUER_URL set)")

    mcp = FastMCP("Printify MCP Server", **mcp_kwargs)

    shops.register(mcp, service)
    products.register(mcp, service)
    catalog.register(mcp, service)
    images.register(mcp, service)
    orders.register(mcp, service)

    return settings, service, mcp


async def health(request):
    return JSONResponse({"status": "ok"})


def create_app() -> Starlette:
    settings, service, mcp = _create_service_and_mcp()

    @contextlib.asynccontextmanager
    async def lifespan(app):
        logger.info("Printify MCP Server starting")
        try:
            async with contextlib.AsyncExitStack() as stack:
                await stack.enter_async_context(mcp.session_manager.run())
                yield
        finally:
            await service.close()
            logger.info("Printify MCP Server stopped")

    app = Starlette(
        routes=[
            Route("/health", health),
            Mount("/", app=mcp.streamable_http_app()),
        ],
        lifespan=lifespan,
    )

    # OAuth無効時のみ旧ミドルウェアでBearer Token認証
    if not settings.oauth_issuer_url and settings.mcp_auth_token:
        from src.auth import BearerAuthMiddleware

        app.add_middleware(BearerAuthMiddleware, token=settings.mcp_auth_token)

    return app


if __name__ == "__main__":
    transport = os.environ.get("TRANSPORT", "streamable-http")
    if transport == "stdio":
        _, _, mcp = _create_service_and_mcp()
        mcp.run(transport="stdio")
    else:
        import uvicorn

        from src.config import Settings

        app = create_app()
        uvicorn.run(app, host="0.0.0.0", port=Settings().port)
