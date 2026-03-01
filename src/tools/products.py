from mcp.server.fastmcp import FastMCP

from src.services.printify import PrintifyService
from src.tools._error_handler import handle_errors


def register(mcp: FastMCP, service: PrintifyService):
    @mcp.tool()
    @handle_errors
    async def list_products(
        page: int = 1, limit: int = 10, shop_id: str | None = None
    ) -> dict:
        """List products in a shop. Supports pagination. If shop_id is omitted, uses the default shop.

        Note on publish status: There is no 'is_published' field. To determine if a product is published
        to a sales channel, check: (1) 'external' object exists and has an 'id' = listed on the channel,
        (2) 'visible' = true means the listing is active/visible on the channel."""
        return await service.list_products(page=page, limit=limit, shop_id=shop_id)

    @mcp.tool()
    @handle_errors
    async def get_product(product_id: str, shop_id: str | None = None) -> dict:
        """Get detailed product info including mockup image URLs.

        Key fields: 'visible' (active on channel), 'external' (sales channel reference with listing id),
        'is_locked' (locked during publish). A product with 'external.id' is published to the channel."""
        return await service.get_product(product_id, shop_id=shop_id)

    @mcp.tool()
    @handle_errors
    async def create_product(data: dict, shop_id: str | None = None) -> dict:
        """Create a new product. Requires title, blueprint_id, print_provider_id, variants, and print_areas."""
        return await service.create_product(data, shop_id=shop_id)

    @mcp.tool()
    @handle_errors
    async def update_product(
        product_id: str, data: dict, shop_id: str | None = None
    ) -> dict:
        """Update an existing product's properties."""
        return await service.update_product(product_id, data, shop_id=shop_id)

    @mcp.tool()
    @handle_errors
    async def delete_product(product_id: str, shop_id: str | None = None) -> dict:
        """Delete a product from the shop."""
        return await service.delete_product(product_id, shop_id=shop_id)

    @mcp.tool()
    @handle_errors
    async def publish_product(
        product_id: str, data: dict, shop_id: str | None = None
    ) -> dict:
        """Publish a product to sales channels. Data should specify which fields to publish (title, description, images, variants, tags)."""
        return await service.publish_product(product_id, data, shop_id=shop_id)
