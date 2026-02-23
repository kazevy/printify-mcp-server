import httpx
import respx

from src.services.printify import PrintifyService

API = "https://api.printify.com"


class TestListShops:
    @respx.mock
    async def test_returns_shop_list(self, service: PrintifyService):
        respx.get(f"{API}/v1/shops.json").mock(
            return_value=httpx.Response(200, json=[
                {"id": 12345, "title": "My Etsy Shop", "sales_channel": "etsy"},
            ])
        )
        result = await service.list_shops()
        assert len(result) == 1
        assert result[0]["title"] == "My Etsy Shop"


class TestGetShop:
    @respx.mock
    async def test_returns_single_shop(self, service: PrintifyService):
        respx.get(f"{API}/v1/shops.json").mock(
            return_value=httpx.Response(200, json=[
                {"id": 12345, "title": "My Etsy Shop", "sales_channel": "etsy"},
                {"id": 67890, "title": "Other Shop", "sales_channel": "custom"},
            ])
        )
        result = await service.get_shop("12345")
        assert result["title"] == "My Etsy Shop"

    @respx.mock
    async def test_shop_not_found(self, service: PrintifyService):
        respx.get(f"{API}/v1/shops.json").mock(
            return_value=httpx.Response(200, json=[])
        )
        result = await service.get_shop("99999")
        assert result is None
