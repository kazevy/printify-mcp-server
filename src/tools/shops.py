from mcp.server.fastmcp import FastMCP

from src.services.printify import PrintifyService
from src.tools._error_handler import handle_errors


def register(mcp: FastMCP, service: PrintifyService):
    @mcp.tool()
    @handle_errors
    async def list_shops() -> list[dict]:
        """List all Printify shops in your account."""
        return await service.list_shops()

    @mcp.tool()
    @handle_errors
    async def get_shop(shop_id: str) -> dict | str:
        """Get details for a specific shop by ID."""
        result = await service.get_shop(shop_id)
        if result is None:
            return f"Shop {shop_id} not found"
        return result
