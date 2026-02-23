import httpx
import respx

from src.services.printify import PrintifyService

API = "https://api.printify.com"
SHOP_ID = "12345"


class TestListOrders:
    @respx.mock
    async def test_returns_orders(self, service: PrintifyService):
        respx.get(f"{API}/v1/shops/{SHOP_ID}/orders.json").mock(
            return_value=httpx.Response(200, json={
                "current_page": 1,
                "data": [{"id": "order_1", "status": "fulfilled"}],
            })
        )
        result = await service.list_orders()
        assert result["data"][0]["status"] == "fulfilled"


class TestGetOrder:
    @respx.mock
    async def test_returns_order_detail(self, service: PrintifyService):
        respx.get(f"{API}/v1/shops/{SHOP_ID}/orders/order_1.json").mock(
            return_value=httpx.Response(200, json={
                "id": "order_1",
                "status": "fulfilled",
                "line_items": [],
            })
        )
        result = await service.get_order("order_1")
        assert result["id"] == "order_1"


class TestSubmitOrder:
    @respx.mock
    async def test_sends_to_production(self, service: PrintifyService):
        respx.post(f"{API}/v1/shops/{SHOP_ID}/orders/order_1/send_to_production.json").mock(
            return_value=httpx.Response(200, json={})
        )
        result = await service.submit_order("order_1")
        assert result == {}
