from mcp.server.fastmcp import FastMCP

from src.services.printify import PrintifyService
from src.tools._error_handler import handle_errors


def register(mcp: FastMCP, service: PrintifyService):
    @mcp.tool()
    @handle_errors
    async def list_orders(page: int = 1, limit: int = 10) -> dict:
        """List orders in the current shop. Supports pagination."""
        return await service.list_orders(page=page, limit=limit)

    @mcp.tool()
    @handle_errors
    async def get_order(order_id: str) -> dict:
        """Get detailed order information including line items and shipping status."""
        return await service.get_order(order_id)

    @mcp.tool()
    @handle_errors
    async def submit_order(order_id: str) -> dict:
        """Send an order to production. This action cannot be undone."""
        return await service.submit_order(order_id)
