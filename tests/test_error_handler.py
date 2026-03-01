import httpx

from src.tools._error_handler import handle_errors


class TestHandleErrors:
    async def test_success_passes_through(self):
        @handle_errors
        async def ok_tool():
            return {"id": "prod_1", "title": "T-Shirt"}

        result = await ok_tool()
        assert result == {"id": "prod_1", "title": "T-Shirt"}

    async def test_http_error_returns_structured_response(self):
        @handle_errors
        async def failing_tool():
            response = httpx.Response(
                422,
                json={"title": ["is required"]},
                request=httpx.Request("POST", "https://api.printify.com/v1/products.json"),
            )
            raise httpx.HTTPStatusError("422 Unprocessable", response=response, request=response.request)

        result = await failing_tool()
        assert result["error"] is True
        assert result["status_code"] == 422
        assert "422" in result["message"]
        assert result["details"] == {"title": ["is required"]}

    async def test_http_error_non_json_body(self):
        @handle_errors
        async def failing_tool():
            response = httpx.Response(
                500,
                text="Internal Server Error",
                request=httpx.Request("GET", "https://api.printify.com/v1/shops.json"),
            )
            raise httpx.HTTPStatusError("500 Internal", response=response, request=response.request)

        result = await failing_tool()
        assert result["error"] is True
        assert result["status_code"] == 500
        assert result["details"] == {}

    async def test_http_error_with_broken_json_body(self):
        @handle_errors
        async def failing_tool():
            response = httpx.Response(
                502,
                text="{broken json",
                headers={"content-type": "application/json"},
                request=httpx.Request("GET", "https://api.printify.com/v1/shops.json"),
            )
            raise httpx.HTTPStatusError("502 Bad Gateway", response=response, request=response.request)

        result = await failing_tool()
        assert result["error"] is True
        assert result["status_code"] == 502
        assert result["details"] == {}

    async def test_value_error_returns_structured_response(self):
        @handle_errors
        async def failing_tool():
            raise ValueError("shop_id is required. Set PRINTIFY_SHOP_ID or call list_shops first.")

        result = await failing_tool()
        assert result["error"] is True
        assert result["status_code"] == 400
        assert "shop_id" in result["message"]
