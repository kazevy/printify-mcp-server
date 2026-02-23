from mcp.server.fastmcp import FastMCP

from src.services.printify import PrintifyService


def register(mcp: FastMCP, service: PrintifyService):
    @mcp.tool()
    async def upload_image(
        file_name: str, url: str | None = None, contents: str | None = None
    ) -> dict:
        """Upload an image to Printify. Provide either a URL or base64-encoded contents."""
        return await service.upload_image(
            file_name=file_name, url=url, contents=contents
        )
