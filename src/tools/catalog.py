from mcp.server.fastmcp import FastMCP

from src.services.printify import PrintifyService


def register(mcp: FastMCP, service: PrintifyService):
    @mcp.tool()
    async def list_blueprints() -> list[dict]:
        """List all available product blueprints (templates) from Printify catalog."""
        return await service.list_blueprints()

    @mcp.tool()
    async def get_blueprint(blueprint_id: int) -> dict:
        """Get details for a specific blueprint including available images and description."""
        return await service.get_blueprint(blueprint_id)

    @mcp.tool()
    async def get_print_providers(blueprint_id: int) -> list[dict]:
        """List print providers available for a specific blueprint."""
        return await service.get_print_providers(blueprint_id)

    @mcp.tool()
    async def get_variants(blueprint_id: int, provider_id: int) -> dict:
        """List variants (sizes, colors) for a blueprint and print provider combination."""
        return await service.get_variants(blueprint_id, provider_id)
