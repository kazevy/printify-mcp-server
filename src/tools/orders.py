from mcp.server.fastmcp import FastMCP

from src.services.printify import PrintifyService


def register(mcp: FastMCP, service: PrintifyService):
    @mcp.tool()
    async def list_orders(page: int = 1, limit: int = 10) -> dict:
        """List orders in the current shop. Supports pagination."""
        return await service.list_orders(page=page, limit=limit)

    @mcp.tool()
    async def get_order(order_id: str) -> dict:
        """Get detailed order information including line items and shipping status."""
        return await service.get_order(order_id)

    @mcp.tool()
    async def submit_order(order_id: str) -> dict:
        """Send an order to production. This action cannot be undone."""
        return await service.submit_order(order_id)
