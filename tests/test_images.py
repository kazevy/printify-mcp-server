import httpx
import respx

from src.services.printify import PrintifyService

API = "https://api.printify.com"


class TestUploadImage:
    @respx.mock
    async def test_uploads_image_from_url(self, service: PrintifyService):
        respx.post(f"{API}/v1/uploads/images.json").mock(
            return_value=httpx.Response(200, json={
                "id": "img_abc123",
                "file_name": "design.png",
                "height": 4000,
                "width": 4000,
                "preview_url": "https://images.printify.com/preview.png",
            })
        )
        result = await service.upload_image(
            file_name="design.png",
            url="https://example.com/design.png",
        )
        assert result["id"] == "img_abc123"

    @respx.mock
    async def test_uploads_image_from_base64(self, service: PrintifyService):
        respx.post(f"{API}/v1/uploads/images.json").mock(
            return_value=httpx.Response(200, json={"id": "img_def456"})
        )
        result = await service.upload_image(
            file_name="design.png",
            contents="iVBORw0KGgoAAAANS...",
        )
        assert result["id"] == "img_def456"
