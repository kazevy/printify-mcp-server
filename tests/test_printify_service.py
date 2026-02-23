import httpx
import respx

from src.services.printify import PrintifyService

API = "https://api.printify.com"


class TestPrintifyServiceInit:
    def test_creates_client_with_auth_header(self, service: PrintifyService):
        assert service._client.headers["authorization"] == "Bearer test-key"

    def test_creates_client_with_user_agent(self, service: PrintifyService):
        assert "printify-mcp-server" in service._client.headers["user-agent"]

    def test_stores_shop_id(self, service: PrintifyService):
        assert service.shop_id == "12345"


class TestPrintifyServiceRequest:
    @respx.mock
    async def test_get_returns_json(self, service: PrintifyService):
        respx.get(f"{API}/v1/shops.json").mock(
            return_value=httpx.Response(200, json=[{"id": 1, "title": "My Shop"}])
        )
        result = await service._get("/v1/shops.json")
        assert result == [{"id": 1, "title": "My Shop"}]

    @respx.mock
    async def test_get_raises_on_401(self, service: PrintifyService):
        respx.get(f"{API}/v1/shops.json").mock(
            return_value=httpx.Response(401, json={"error": "Unauthorized"})
        )
        try:
            await service._get("/v1/shops.json")
            assert False, "Should have raised"
        except httpx.HTTPStatusError as e:
            assert e.response.status_code == 401

    @respx.mock
    async def test_retry_on_429(self, service: PrintifyService):
        route = respx.get(f"{API}/v1/shops.json")
        route.side_effect = [
            httpx.Response(429, headers={"Retry-After": "0"}),
            httpx.Response(200, json=[{"id": 1}]),
        ]
        result = await service._get("/v1/shops.json")
        assert result == [{"id": 1}]
        assert route.call_count == 2
