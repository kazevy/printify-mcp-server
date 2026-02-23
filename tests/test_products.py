import httpx
import respx

from src.services.printify import PrintifyService

API = "https://api.printify.com"
SHOP_ID = "12345"


class TestListProducts:
    @respx.mock
    async def test_returns_products(self, service: PrintifyService):
        respx.get(f"{API}/v1/shops/{SHOP_ID}/products.json").mock(
            return_value=httpx.Response(200, json={
                "current_page": 1,
                "data": [{"id": "prod_1", "title": "T-Shirt"}],
            })
        )
        result = await service.list_products()
        assert result["data"][0]["title"] == "T-Shirt"

    @respx.mock
    async def test_pagination(self, service: PrintifyService):
        respx.get(f"{API}/v1/shops/{SHOP_ID}/products.json").mock(
            return_value=httpx.Response(200, json={"current_page": 2, "data": []})
        )
        result = await service.list_products(page=2)
        assert result["current_page"] == 2


class TestGetProduct:
    @respx.mock
    async def test_returns_product_detail(self, service: PrintifyService):
        respx.get(f"{API}/v1/shops/{SHOP_ID}/products/prod_1.json").mock(
            return_value=httpx.Response(200, json={
                "id": "prod_1",
                "title": "T-Shirt",
                "images": [{"src": "https://images.printify.com/mock.png"}],
            })
        )
        result = await service.get_product("prod_1")
        assert result["title"] == "T-Shirt"
        assert len(result["images"]) == 1


class TestCreateProduct:
    @respx.mock
    async def test_creates_product(self, service: PrintifyService):
        respx.post(f"{API}/v1/shops/{SHOP_ID}/products.json").mock(
            return_value=httpx.Response(200, json={"id": "prod_new", "title": "New Product"})
        )
        result = await service.create_product({"title": "New Product", "blueprint_id": 6})
        assert result["id"] == "prod_new"


class TestUpdateProduct:
    @respx.mock
    async def test_updates_product(self, service: PrintifyService):
        respx.put(f"{API}/v1/shops/{SHOP_ID}/products/prod_1.json").mock(
            return_value=httpx.Response(200, json={"id": "prod_1", "title": "Updated"})
        )
        result = await service.update_product("prod_1", {"title": "Updated"})
        assert result["title"] == "Updated"


class TestDeleteProduct:
    @respx.mock
    async def test_deletes_product(self, service: PrintifyService):
        respx.delete(f"{API}/v1/shops/{SHOP_ID}/products/prod_1.json").mock(
            return_value=httpx.Response(200, json={})
        )
        result = await service.delete_product("prod_1")
        assert result == {}


class TestPublishProduct:
    @respx.mock
    async def test_publishes_product(self, service: PrintifyService):
        respx.post(f"{API}/v1/shops/{SHOP_ID}/products/prod_1/publish.json").mock(
            return_value=httpx.Response(200, json={})
        )
        publish_data = {
            "title": True,
            "description": True,
            "images": True,
            "variants": True,
            "tags": True,
        }
        result = await service.publish_product("prod_1", publish_data)
        assert result == {}


class TestProductErrorHandling:
    @respx.mock
    async def test_returns_structured_error_on_422(self, service: PrintifyService):
        from src.tools._error_handler import handle_errors

        @handle_errors
        async def wrapped_create():
            return await service.create_product({"blueprint_id": 6})

        respx.post(f"{API}/v1/shops/{SHOP_ID}/products.json").mock(
            return_value=httpx.Response(422, json={"title": ["is required"]})
        )
        result = await wrapped_create()
        assert result["error"] is True
        assert result["status_code"] == 422
        assert result["details"] == {"title": ["is required"]}

    async def test_returns_structured_error_when_shop_id_missing(self):
        from src.tools._error_handler import handle_errors

        no_shop_service = PrintifyService(api_key="test-key", shop_id=None)

        @handle_errors
        async def wrapped_list():
            return await no_shop_service.list_products()

        result = await wrapped_list()
        assert result["error"] is True
        assert result["status_code"] == 400
        assert "shop_id" in result["message"]
