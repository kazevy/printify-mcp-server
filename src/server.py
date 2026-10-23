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

    oauth_provider = None
    if settings.oauth_issuer_url:
        # OAuth モード: Claude Web/Mobile + 静的Bearer Token（Claude Code/TypingMind）
        from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions

        from src.config import MIN_SECRET_LENGTH
        from src.consent import CONSENT_PATH
        from src.oauth_provider import InMemoryOAuthProvider

        # 同意画面の合言葉が無ければ誰でも承認できてしまうため起動を拒否する（PMCP-1）
        owner_secret = settings.oauth_owner_password or settings.mcp_auth_token
        if not owner_secret:
            raise RuntimeError(
                "OAUTH_ISSUER_URL is set but neither OAUTH_OWNER_PASSWORD nor MCP_AUTH_TOKEN is "
                "configured; refusing to start an OAuth server without owner authentication."
            )
        if len(owner_secret) < MIN_SECRET_LENGTH:
            raise RuntimeError(
                "The OAuth owner secret (OAUTH_OWNER_PASSWORD, or MCP_AUTH_TOKEN if unset) must be "
                f"at least {MIN_SECRET_LENGTH} characters."
            )

        issuer = settings.oauth_issuer_url.rstrip("/")
        oauth_provider = InMemoryOAuthProvider(
            static_bearer_token=settings.mcp_auth_token,
            owner_secret=owner_secret,
            consent_url=f"{issuer}{CONSENT_PATH}",
            allowed_redirect_uris=settings.extra_allowed_redirect_uris,
        )
        mcp_kwargs["auth_server_provider"] = oauth_provider
        mcp_kwargs["auth"] = AuthSettings(
            issuer_url=issuer,
            resource_server_url=f"{issuer}/mcp",
            client_registration_options=ClientRegistrationOptions(
                enabled=True,  # DCR有効化（Claude Webが自動登録。redirect_uriは許可リストで制限）
            ),
            # 静的 Bearer Token とリフレッシュ後のトークンは resource を持たないため検証しない
            validate_token_resource=False,
        )
        logger.info(f"OAuth enabled (issuer: {issuer})")
    else:
        logger.info("OAuth disabled (no OAUTH_ISSUER_URL set)")

    mcp = FastMCP("Printify MCP Server", **mcp_kwargs)

    shops.register(mcp, service)
    products.register(mcp, service)
    catalog.register(mcp, service)
    images.register(mcp, service)
    orders.register(mcp, service)

    if oauth_provider is not None:
        from src.consent import CONSENT_PATH, make_consent_endpoint

        mcp.custom_route(CONSENT_PATH, methods=["GET", "POST"])(
            make_consent_endpoint(oauth_provider)
        )

    return settings, service, mcp


async def health(request):
    return JSONResponse({"status": "ok"})


def create_app() -> Starlette:
    from src.config import MIN_SECRET_LENGTH, Settings

    # HTTP で公開するのに認証設定が無い場合は起動を拒否する（PMCP-2: fail-closed）
    settings = Settings()
    if not settings.oauth_issuer_url and not settings.mcp_auth_token:
        raise RuntimeError(
            "Refusing to start the HTTP server without authentication: set MCP_AUTH_TOKEN "
            "(and optionally OAUTH_ISSUER_URL). Use TRANSPORT=stdio for local unauthenticated use."
        )
    if settings.mcp_auth_token and len(settings.mcp_auth_token) < MIN_SECRET_LENGTH:
        raise RuntimeError(f"MCP_AUTH_TOKEN must be at least {MIN_SECRET_LENGTH} characters.")

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

    # OAuth無効時は旧ミドルウェアでBearer Token認証（上の検査で mcp_auth_token は必ずある）
    if not settings.oauth_issuer_url:
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
