import httpx
import respx

from src.services.printify import PrintifyService

API = "https://api.printify.com"


class TestListBlueprints:
    @respx.mock
    async def test_returns_blueprints(self, service: PrintifyService):
        respx.get(f"{API}/v1/catalog/blueprints.json").mock(
            return_value=httpx.Response(200, json=[
                {"id": 6, "title": "Unisex Heavy Cotton Tee", "brand": "Gildan"},
            ])
        )
        result = await service.list_blueprints()
        assert result[0]["title"] == "Unisex Heavy Cotton Tee"


class TestGetBlueprint:
    @respx.mock
    async def test_returns_blueprint_detail(self, service: PrintifyService):
        respx.get(f"{API}/v1/catalog/blueprints/6.json").mock(
            return_value=httpx.Response(200, json={
                "id": 6,
                "title": "Unisex Heavy Cotton Tee",
                "images": ["https://images.printify.com/bp6.png"],
            })
        )
        result = await service.get_blueprint(6)
        assert result["id"] == 6


class TestGetPrintProviders:
    @respx.mock
    async def test_returns_providers(self, service: PrintifyService):
        respx.get(f"{API}/v1/catalog/blueprints/6/print_providers.json").mock(
            return_value=httpx.Response(200, json=[
                {"id": 3, "title": "DJ"},
            ])
        )
        result = await service.get_print_providers(6)
        assert result[0]["title"] == "DJ"


class TestGetVariants:
    @respx.mock
    async def test_returns_variants(self, service: PrintifyService):
        respx.get(f"{API}/v1/catalog/blueprints/6/print_providers/3/variants.json").mock(
            return_value=httpx.Response(200, json={
                "id": 3,
                "variants": [{"id": 17390, "title": "S / White", "options": {}}],
            })
        )
        result = await service.get_variants(6, 3)
        assert result["variants"][0]["title"] == "S / White"
