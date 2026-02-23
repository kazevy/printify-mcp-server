from mcp.server.fastmcp import FastMCP

from src.services.printify import PrintifyService


def register(mcp: FastMCP, service: PrintifyService):
    @mcp.tool()
    async def list_products(page: int = 1, limit: int = 10) -> dict:
        """List products in the current shop. Supports pagination."""
        return await service.list_products(page=page, limit=limit)

    @mcp.tool()
    async def get_product(product_id: str) -> dict:
        """Get detailed product info including mockup image URLs."""
        return await service.get_product(product_id)

    @mcp.tool()
    async def create_product(data: dict) -> dict:
        """Create a new product. Requires title, blueprint_id, print_provider_id, variants, and print_areas."""
        return await service.create_product(data)

    @mcp.tool()
    async def update_product(product_id: str, data: dict) -> dict:
        """Update an existing product's properties."""
        return await service.update_product(product_id, data)

    @mcp.tool()
    async def delete_product(product_id: str) -> dict:
        """Delete a product from the shop."""
        return await service.delete_product(product_id)

    @mcp.tool()
    async def publish_product(product_id: str, data: dict) -> dict:
        """Publish a product to sales channels. Data should specify which fields to publish (title, description, images, variants, tags)."""
        return await service.publish_product(product_id, data)
