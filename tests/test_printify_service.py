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


class TestProactiveRateLimit:
    @respx.mock
    async def test_sleeps_when_remaining_below_threshold(self, service: PrintifyService, monkeypatch):
        sleep_calls = []

        async def mock_sleep(seconds):
            sleep_calls.append(seconds)

        monkeypatch.setattr("src.services.printify.asyncio.sleep", mock_sleep)

        respx.get(f"{API}/v1/shops.json").mock(
            return_value=httpx.Response(
                200,
                json=[{"id": 1}],
                headers={"X-RateLimit-Remaining": "3", "X-RateLimit-Reset": "2"},
            )
        )
        result = await service._get("/v1/shops.json")
        assert result == [{"id": 1}]
        assert sleep_calls == [2.0]

    @respx.mock
    async def test_no_sleep_when_remaining_above_threshold(self, service: PrintifyService, monkeypatch):
        sleep_calls = []

        async def mock_sleep(seconds):
            sleep_calls.append(seconds)

        monkeypatch.setattr("src.services.printify.asyncio.sleep", mock_sleep)

        respx.get(f"{API}/v1/shops.json").mock(
            return_value=httpx.Response(
                200,
                json=[{"id": 1}],
                headers={"X-RateLimit-Remaining": "50"},
            )
        )
        result = await service._get("/v1/shops.json")
        assert result == [{"id": 1}]
        assert sleep_calls == []

    @respx.mock
    async def test_no_sleep_when_no_ratelimit_header(self, service: PrintifyService, monkeypatch):
        sleep_calls = []

        async def mock_sleep(seconds):
            sleep_calls.append(seconds)

        monkeypatch.setattr("src.services.printify.asyncio.sleep", mock_sleep)

        respx.get(f"{API}/v1/shops.json").mock(
            return_value=httpx.Response(200, json=[{"id": 1}])
        )
        result = await service._get("/v1/shops.json")
        assert result == [{"id": 1}]
        assert sleep_calls == []
