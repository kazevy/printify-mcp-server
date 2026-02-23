import contextlib
import logging
import os

from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from src.auth import BearerAuthMiddleware
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

    mcp = FastMCP(
        "Printify MCP Server",
        json_response=True,
        stateless_http=True,
    )

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
    if settings.mcp_auth_token:
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
