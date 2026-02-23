# Printify MCP Server Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a standalone Printify MCP server with full API coverage, deployable to Cloud Run.

**Architecture:** 3-layer design — Auth middleware → MCP Server (official SDK FastMCP) → PrintifyService (httpx async). Single codebase supports both Streamable HTTP (remote) and stdio (local) transports.

**Tech Stack:** Python 3.12+, `mcp[cli]` (official SDK), `httpx`, `pydantic-settings`, `pytest` + `respx`, Docker, Cloud Run.

---

## Task 1: Project Scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `src/__init__.py`
- Create: `src/config.py`
- Create: `.env.example`
- Create: `.gitignore`
- Create: `tests/__init__.py`

**Step 1: Create pyproject.toml**

```toml
[project]
name = "printify-mcp-server"
version = "0.1.0"
description = "Printify MCP server for Claude Desktop / Claude Web"
requires-python = ">=3.12"
dependencies = [
    "mcp[cli]>=1.9.0",
    "httpx>=0.28.0",
    "pydantic-settings>=2.7.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.25.0",
    "respx>=0.22.0",
    "ruff>=0.9.0",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.ruff]
target-version = "py312"
line-length = 100
```

**Step 2: Create src/config.py**

```python
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    printify_api_key: str
    printify_shop_id: str | None = None
    mcp_auth_token: str | None = None
    port: int = 8080
    transport: str = "streamable-http"

    model_config = {"env_file": ".env"}


settings = Settings()
```

**Step 3: Create .env.example**

```
PRINTIFY_API_KEY=your_printify_api_key_here
PRINTIFY_SHOP_ID=
MCP_AUTH_TOKEN=your_secret_token_here
PORT=8080
TRANSPORT=streamable-http
```

**Step 4: Create .gitignore**

```
__pycache__/
*.pyc
.env
.venv/
dist/
*.egg-info/
.pytest_cache/
.ruff_cache/
```

**Step 5: Create empty __init__.py files**

```python
# src/__init__.py — empty
# tests/__init__.py — empty
```

**Step 6: Initialize project**

Run: `cd /c/Users/nouph/Dropbox/dev/PrintifyMCP/printify-mcp-server && uv sync`
Expected: Dependencies installed, `.venv` created.

**Step 7: Commit**

```bash
git add -A
git commit -m "chore: project scaffolding with pyproject.toml and config"
```

---

## Task 2: PrintifyService — Base Client + Error Handling

**Files:**
- Create: `src/services/__init__.py`
- Create: `src/services/printify.py`
- Create: `tests/conftest.py`
- Create: `tests/test_printify_service.py`

**Step 1: Write the failing test**

`tests/conftest.py`:
```python
import pytest
import httpx
import respx

from src.services.printify import PrintifyService


@pytest.fixture
def printify_api():
    return respx.mock(base_url="https://api.printify.com/v1")


@pytest.fixture
def service():
    return PrintifyService(api_key="test-key", shop_id="12345")
```

`tests/test_printify_service.py`:
```python
import httpx
import respx

from src.services.printify import PrintifyService


class TestPrintifyServiceInit:
    def test_creates_client_with_auth_header(self, service: PrintifyService):
        assert service._client.headers["authorization"] == "Bearer test-key"

    def test_creates_client_with_user_agent(self, service: PrintifyService):
        assert "printify-mcp-server" in service._client.headers["user-agent"]

    def test_stores_shop_id(self, service: PrintifyService):
        assert service.shop_id == "12345"


class TestPrintifyServiceRequest:
    @respx.mock(base_url="https://api.printify.com/v1")
    async def test_get_returns_json(self, service: PrintifyService):
        respx.get("/v1/shops.json").mock(
            return_value=httpx.Response(200, json=[{"id": 1, "title": "My Shop"}])
        )
        result = await service._get("/v1/shops.json")
        assert result == [{"id": 1, "title": "My Shop"}]

    @respx.mock(base_url="https://api.printify.com/v1")
    async def test_get_raises_on_401(self, service: PrintifyService):
        respx.get("/v1/shops.json").mock(
            return_value=httpx.Response(401, json={"error": "Unauthorized"})
        )
        try:
            await service._get("/v1/shops.json")
            assert False, "Should have raised"
        except httpx.HTTPStatusError as e:
            assert e.response.status_code == 401

    @respx.mock(base_url="https://api.printify.com/v1")
    async def test_retry_on_429(self, service: PrintifyService):
        route = respx.get("/v1/shops.json")
        route.side_effect = [
            httpx.Response(429, headers={"Retry-After": "0"}),
            httpx.Response(200, json=[{"id": 1}]),
        ]
        result = await service._get("/v1/shops.json")
        assert result == [{"id": 1}]
        assert route.call_count == 2
```

**Step 2: Run tests to verify they fail**

Run: `cd /c/Users/nouph/Dropbox/dev/PrintifyMCP/printify-mcp-server && uv run pytest tests/test_printify_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.services.printify'`

**Step 3: Write PrintifyService implementation**

`src/services/__init__.py` — empty

`src/services/printify.py`:
```python
import asyncio
import logging

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://api.printify.com/v1"
MAX_RETRIES = 3


class PrintifyService:
    def __init__(self, api_key: str, shop_id: str | None = None):
        self.shop_id = shop_id
        self._client = httpx.AsyncClient(
            base_url=BASE_URL,
            headers={
                "authorization": f"Bearer {api_key}",
                "user-agent": "printify-mcp-server/0.1.0",
                "content-type": "application/json",
            },
            timeout=30.0,
        )

    async def close(self):
        await self._client.aclose()

    async def _request(
        self, method: str, path: str, **kwargs
    ) -> dict | list:
        last_exc = None
        for attempt in range(MAX_RETRIES):
            try:
                response = await self._client.request(method, path, **kwargs)
                response.raise_for_status()
                if response.status_code == 204:
                    return {}
                return response.json()
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    wait = float(e.response.headers.get("Retry-After", 2 ** attempt))
                    logger.warning(f"Rate limited. Retrying in {wait}s (attempt {attempt + 1})")
                    await asyncio.sleep(wait)
                    last_exc = e
                    continue
                raise
        raise last_exc

    async def _get(self, path: str, **params) -> dict | list:
        return await self._request("GET", path, params=params)

    async def _post(self, path: str, data: dict | None = None) -> dict:
        return await self._request("POST", path, json=data)

    async def _put(self, path: str, data: dict) -> dict:
        return await self._request("PUT", path, json=data)

    async def _delete(self, path: str) -> dict:
        return await self._request("DELETE", path)

    def _shop_path(self, suffix: str) -> str:
        if not self.shop_id:
            raise ValueError("shop_id is required. Set PRINTIFY_SHOP_ID or call list_shops first.")
        return f"/v1/shops/{self.shop_id}/{suffix}"
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_printify_service.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/services/ tests/conftest.py tests/test_printify_service.py
git commit -m "feat: add PrintifyService base client with retry logic"
```

---

## Task 3: Shop Tools

**Files:**
- Create: `src/tools/__init__.py`
- Create: `src/tools/shops.py`
- Create: `tests/test_shops.py`

**Step 1: Write failing test**

`tests/test_shops.py`:
```python
import httpx
import respx

from src.services.printify import PrintifyService


class TestListShops:
    @respx.mock(base_url="https://api.printify.com/v1")
    async def test_returns_shop_list(self, service: PrintifyService):
        respx.get("/v1/shops.json").mock(
            return_value=httpx.Response(200, json=[
                {"id": 12345, "title": "My Etsy Shop", "sales_channel": "etsy"},
            ])
        )
        result = await service.list_shops()
        assert len(result) == 1
        assert result[0]["title"] == "My Etsy Shop"


class TestGetShop:
    @respx.mock(base_url="https://api.printify.com/v1")
    async def test_returns_single_shop(self, service: PrintifyService):
        respx.get("/v1/shops.json").mock(
            return_value=httpx.Response(200, json=[
                {"id": 12345, "title": "My Etsy Shop", "sales_channel": "etsy"},
                {"id": 67890, "title": "Other Shop", "sales_channel": "custom"},
            ])
        )
        result = await service.get_shop("12345")
        assert result["title"] == "My Etsy Shop"

    @respx.mock(base_url="https://api.printify.com/v1")
    async def test_shop_not_found(self, service: PrintifyService):
        respx.get("/v1/shops.json").mock(
            return_value=httpx.Response(200, json=[])
        )
        result = await service.get_shop("99999")
        assert result is None
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_shops.py -v`
Expected: FAIL — `AttributeError: 'PrintifyService' has no attribute 'list_shops'`

**Step 3: Add shop methods to PrintifyService**

Append to `src/services/printify.py`:
```python
    # --- Shops ---

    async def list_shops(self) -> list[dict]:
        return await self._get("/v1/shops.json")

    async def get_shop(self, shop_id: str) -> dict | None:
        shops = await self.list_shops()
        return next((s for s in shops if str(s["id"]) == str(shop_id)), None)
```

**Step 4: Write MCP tool wrappers**

`src/tools/__init__.py` — empty

`src/tools/shops.py`:
```python
from mcp.server.fastmcp import FastMCP

from src.services.printify import PrintifyService


def register(mcp: FastMCP, service: PrintifyService):
    @mcp.tool()
    async def list_shops() -> list[dict]:
        """List all Printify shops in your account."""
        return await service.list_shops()

    @mcp.tool()
    async def get_shop(shop_id: str) -> dict | str:
        """Get details for a specific shop by ID."""
        result = await service.get_shop(shop_id)
        if result is None:
            return f"Shop {shop_id} not found"
        return result
```

**Step 5: Run tests**

Run: `uv run pytest tests/test_shops.py -v`
Expected: All PASS

**Step 6: Commit**

```bash
git add src/tools/ src/services/printify.py tests/test_shops.py
git commit -m "feat: add shop tools (list_shops, get_shop)"
```

---

## Task 4: Product Tools

**Files:**
- Create: `src/tools/products.py`
- Create: `tests/test_products.py`

**Step 1: Write failing tests**

`tests/test_products.py`:
```python
import httpx
import respx

from src.services.printify import PrintifyService

SHOP_ID = "12345"


class TestListProducts:
    @respx.mock(base_url="https://api.printify.com/v1")
    async def test_returns_products(self, service: PrintifyService):
        respx.get(f"/v1/shops/{SHOP_ID}/products.json").mock(
            return_value=httpx.Response(200, json={
                "current_page": 1,
                "data": [{"id": "prod_1", "title": "T-Shirt"}],
            })
        )
        result = await service.list_products()
        assert result["data"][0]["title"] == "T-Shirt"

    @respx.mock(base_url="https://api.printify.com/v1")
    async def test_pagination(self, service: PrintifyService):
        respx.get(f"/v1/shops/{SHOP_ID}/products.json", params__contains={"page": "2"}).mock(
            return_value=httpx.Response(200, json={"current_page": 2, "data": []})
        )
        result = await service.list_products(page=2)
        assert result["current_page"] == 2


class TestGetProduct:
    @respx.mock(base_url="https://api.printify.com/v1")
    async def test_returns_product_detail(self, service: PrintifyService):
        respx.get(f"/v1/shops/{SHOP_ID}/products/prod_1.json").mock(
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
    @respx.mock(base_url="https://api.printify.com/v1")
    async def test_creates_product(self, service: PrintifyService):
        respx.post(f"/v1/shops/{SHOP_ID}/products.json").mock(
            return_value=httpx.Response(200, json={"id": "prod_new", "title": "New Product"})
        )
        result = await service.create_product({"title": "New Product", "blueprint_id": 6})
        assert result["id"] == "prod_new"


class TestUpdateProduct:
    @respx.mock(base_url="https://api.printify.com/v1")
    async def test_updates_product(self, service: PrintifyService):
        respx.put(f"/v1/shops/{SHOP_ID}/products/prod_1.json").mock(
            return_value=httpx.Response(200, json={"id": "prod_1", "title": "Updated"})
        )
        result = await service.update_product("prod_1", {"title": "Updated"})
        assert result["title"] == "Updated"


class TestDeleteProduct:
    @respx.mock(base_url="https://api.printify.com/v1")
    async def test_deletes_product(self, service: PrintifyService):
        respx.delete(f"/v1/shops/{SHOP_ID}/products/prod_1.json").mock(
            return_value=httpx.Response(200, json={})
        )
        result = await service.delete_product("prod_1")
        assert result == {}


class TestPublishProduct:
    @respx.mock(base_url="https://api.printify.com/v1")
    async def test_publishes_product(self, service: PrintifyService):
        respx.post(f"/v1/shops/{SHOP_ID}/products/prod_1/publish.json").mock(
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
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_products.py -v`
Expected: FAIL — `AttributeError: 'PrintifyService' has no attribute 'list_products'`

**Step 3: Add product methods to PrintifyService**

Append to `src/services/printify.py`:
```python
    # --- Products ---

    async def list_products(self, page: int = 1, limit: int = 10) -> dict:
        return await self._get(
            self._shop_path("products.json"), page=page, limit=limit
        )

    async def get_product(self, product_id: str) -> dict:
        return await self._get(self._shop_path(f"products/{product_id}.json"))

    async def create_product(self, data: dict) -> dict:
        return await self._post(self._shop_path("products.json"), data=data)

    async def update_product(self, product_id: str, data: dict) -> dict:
        return await self._put(self._shop_path(f"products/{product_id}.json"), data=data)

    async def delete_product(self, product_id: str) -> dict:
        return await self._delete(self._shop_path(f"products/{product_id}.json"))

    async def publish_product(self, product_id: str, data: dict) -> dict:
        return await self._post(
            self._shop_path(f"products/{product_id}/publish.json"), data=data
        )
```

**Step 4: Write MCP tool wrappers**

`src/tools/products.py`:
```python
from mcp.server.fastmcp import FastMCP

from src.services.printify import PrintifyService


def register(mcp: FastMCP, service: PrintifyService):
    @mcp.tool()
    async def list_products(page: int = 1, limit: int = 10) -> dict:
        """List products in the current shop. Supports pagination."""
        return await service.list_products(page=page, limit=limit)

    @mcp.tool()
    async def get_product(product_id: str) -> dict:
        """Get detailed product info including mockup image URLs."""
        return await service.get_product(product_id)

    @mcp.tool()
    async def create_product(data: dict) -> dict:
        """Create a new product. Requires title, blueprint_id, print_provider_id, variants, and print_areas."""
        return await service.create_product(data)

    @mcp.tool()
    async def update_product(product_id: str, data: dict) -> dict:
        """Update an existing product's properties."""
        return await service.update_product(product_id, data)

    @mcp.tool()
    async def delete_product(product_id: str) -> dict:
        """Delete a product from the shop."""
        return await service.delete_product(product_id)

    @mcp.tool()
    async def publish_product(product_id: str, data: dict) -> dict:
        """Publish a product to sales channels. Data should specify which fields to publish (title, description, images, variants, tags)."""
        return await service.publish_product(product_id, data)
```

**Step 5: Run tests**

Run: `uv run pytest tests/test_products.py -v`
Expected: All PASS

**Step 6: Commit**

```bash
git add src/tools/products.py src/services/printify.py tests/test_products.py
git commit -m "feat: add product tools (CRUD + publish)"
```

---

## Task 5: Catalog Tools

**Files:**
- Create: `src/tools/catalog.py`
- Create: `tests/test_catalog.py`

**Step 1: Write failing tests**

`tests/test_catalog.py`:
```python
import httpx
import respx

from src.services.printify import PrintifyService


class TestListBlueprints:
    @respx.mock(base_url="https://api.printify.com/v1")
    async def test_returns_blueprints(self, service: PrintifyService):
        respx.get("/v1/catalog/blueprints.json").mock(
            return_value=httpx.Response(200, json=[
                {"id": 6, "title": "Unisex Heavy Cotton Tee", "brand": "Gildan"},
            ])
        )
        result = await service.list_blueprints()
        assert result[0]["title"] == "Unisex Heavy Cotton Tee"


class TestGetBlueprint:
    @respx.mock(base_url="https://api.printify.com/v1")
    async def test_returns_blueprint_detail(self, service: PrintifyService):
        respx.get("/v1/catalog/blueprints/6.json").mock(
            return_value=httpx.Response(200, json={
                "id": 6,
                "title": "Unisex Heavy Cotton Tee",
                "images": ["https://images.printify.com/bp6.png"],
            })
        )
        result = await service.get_blueprint(6)
        assert result["id"] == 6


class TestGetPrintProviders:
    @respx.mock(base_url="https://api.printify.com/v1")
    async def test_returns_providers(self, service: PrintifyService):
        respx.get("/v1/catalog/blueprints/6/print_providers.json").mock(
            return_value=httpx.Response(200, json=[
                {"id": 3, "title": "DJ"},
            ])
        )
        result = await service.get_print_providers(6)
        assert result[0]["title"] == "DJ"


class TestGetVariants:
    @respx.mock(base_url="https://api.printify.com/v1")
    async def test_returns_variants(self, service: PrintifyService):
        respx.get("/v1/catalog/blueprints/6/print_providers/3/variants.json").mock(
            return_value=httpx.Response(200, json={
                "id": 3,
                "variants": [{"id": 17390, "title": "S / White", "options": {}}],
            })
        )
        result = await service.get_variants(6, 3)
        assert result["variants"][0]["title"] == "S / White"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_catalog.py -v`
Expected: FAIL — `AttributeError`

**Step 3: Add catalog methods to PrintifyService**

Append to `src/services/printify.py`:
```python
    # --- Catalog ---

    async def list_blueprints(self) -> list[dict]:
        return await self._get("/v1/catalog/blueprints.json")

    async def get_blueprint(self, blueprint_id: int) -> dict:
        return await self._get(f"/v1/catalog/blueprints/{blueprint_id}.json")

    async def get_print_providers(self, blueprint_id: int) -> list[dict]:
        return await self._get(
            f"/v1/catalog/blueprints/{blueprint_id}/print_providers.json"
        )

    async def get_variants(self, blueprint_id: int, provider_id: int) -> dict:
        return await self._get(
            f"/v1/catalog/blueprints/{blueprint_id}/print_providers/{provider_id}/variants.json"
        )
```

**Step 4: Write MCP tool wrappers**

`src/tools/catalog.py`:
```python
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
```

**Step 5: Run tests**

Run: `uv run pytest tests/test_catalog.py -v`
Expected: All PASS

**Step 6: Commit**

```bash
git add src/tools/catalog.py src/services/printify.py tests/test_catalog.py
git commit -m "feat: add catalog tools (blueprints, providers, variants)"
```

---

## Task 6: Image Tools

**Files:**
- Create: `src/tools/images.py`
- Create: `tests/test_images.py`

**Step 1: Write failing test**

`tests/test_images.py`:
```python
import httpx
import respx

from src.services.printify import PrintifyService


class TestUploadImage:
    @respx.mock(base_url="https://api.printify.com/v1")
    async def test_uploads_image_from_url(self, service: PrintifyService):
        respx.post("/v1/uploads/images.json").mock(
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

    @respx.mock(base_url="https://api.printify.com/v1")
    async def test_uploads_image_from_base64(self, service: PrintifyService):
        respx.post("/v1/uploads/images.json").mock(
            return_value=httpx.Response(200, json={"id": "img_def456"})
        )
        result = await service.upload_image(
            file_name="design.png",
            contents="iVBORw0KGgoAAAANS...",
        )
        assert result["id"] == "img_def456"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_images.py -v`
Expected: FAIL

**Step 3: Add image method to PrintifyService**

Append to `src/services/printify.py`:
```python
    # --- Images ---

    async def upload_image(
        self, file_name: str, url: str | None = None, contents: str | None = None
    ) -> dict:
        data = {"file_name": file_name}
        if url:
            data["url"] = url
        elif contents:
            data["contents"] = contents
        else:
            raise ValueError("Either url or contents (base64) is required")
        return await self._post("/v1/uploads/images.json", data=data)
```

**Step 4: Write MCP tool wrapper**

`src/tools/images.py`:
```python
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
```

**Step 5: Run tests**

Run: `uv run pytest tests/test_images.py -v`
Expected: All PASS

**Step 6: Commit**

```bash
git add src/tools/images.py src/services/printify.py tests/test_images.py
git commit -m "feat: add image upload tool"
```

---

## Task 7: Order Tools

**Files:**
- Create: `src/tools/orders.py`
- Create: `tests/test_orders.py`

**Step 1: Write failing tests**

`tests/test_orders.py`:
```python
import httpx
import respx

from src.services.printify import PrintifyService

SHOP_ID = "12345"


class TestListOrders:
    @respx.mock(base_url="https://api.printify.com/v1")
    async def test_returns_orders(self, service: PrintifyService):
        respx.get(f"/v1/shops/{SHOP_ID}/orders.json").mock(
            return_value=httpx.Response(200, json={
                "current_page": 1,
                "data": [{"id": "order_1", "status": "fulfilled"}],
            })
        )
        result = await service.list_orders()
        assert result["data"][0]["status"] == "fulfilled"


class TestGetOrder:
    @respx.mock(base_url="https://api.printify.com/v1")
    async def test_returns_order_detail(self, service: PrintifyService):
        respx.get(f"/v1/shops/{SHOP_ID}/orders/order_1.json").mock(
            return_value=httpx.Response(200, json={
                "id": "order_1",
                "status": "fulfilled",
                "line_items": [],
            })
        )
        result = await service.get_order("order_1")
        assert result["id"] == "order_1"


class TestSubmitOrder:
    @respx.mock(base_url="https://api.printify.com/v1")
    async def test_sends_to_production(self, service: PrintifyService):
        respx.post(f"/v1/shops/{SHOP_ID}/orders/order_1/send_to_production.json").mock(
            return_value=httpx.Response(200, json={})
        )
        result = await service.submit_order("order_1")
        assert result == {}
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_orders.py -v`
Expected: FAIL

**Step 3: Add order methods to PrintifyService**

Append to `src/services/printify.py`:
```python
    # --- Orders ---

    async def list_orders(self, page: int = 1, limit: int = 10) -> dict:
        return await self._get(
            self._shop_path("orders.json"), page=page, limit=limit
        )

    async def get_order(self, order_id: str) -> dict:
        return await self._get(self._shop_path(f"orders/{order_id}.json"))

    async def submit_order(self, order_id: str) -> dict:
        return await self._post(
            self._shop_path(f"orders/{order_id}/send_to_production.json")
        )
```

**Step 4: Write MCP tool wrapper**

`src/tools/orders.py`:
```python
from mcp.server.fastmcp import FastMCP

from src.services.printify import PrintifyService


def register(mcp: FastMCP, service: PrintifyService):
    @mcp.tool()
    async def list_orders(page: int = 1, limit: int = 10) -> dict:
        """List orders in the current shop. Supports pagination."""
        return await service.list_orders(page=page, limit=limit)

    @mcp.tool()
    async def get_order(order_id: str) -> dict:
        """Get detailed order information including line items and shipping status."""
        return await service.get_order(order_id)

    @mcp.tool()
    async def submit_order(order_id: str) -> dict:
        """Send an order to production. This action cannot be undone."""
        return await service.submit_order(order_id)
```

**Step 5: Run tests**

Run: `uv run pytest tests/test_orders.py -v`
Expected: All PASS

**Step 6: Commit**

```bash
git add src/tools/orders.py src/services/printify.py tests/test_orders.py
git commit -m "feat: add order tools (list, get, submit)"
```

---

## Task 8: Auth Middleware

**Files:**
- Create: `src/auth.py`
- Create: `tests/test_auth.py`

**Step 1: Write failing tests**

`tests/test_auth.py`:
```python
from starlette.testclient import TestClient
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from src.auth import BearerAuthMiddleware


def _make_app(token: str | None):
    async def homepage(request):
        return JSONResponse({"ok": True})

    app = Starlette(routes=[Route("/", homepage)])
    if token:
        app.add_middleware(BearerAuthMiddleware, token=token)
    return app


class TestBearerAuthMiddleware:
    def test_allows_request_with_valid_token(self):
        app = _make_app("secret123")
        client = TestClient(app)
        resp = client.get("/", headers={"authorization": "Bearer secret123"})
        assert resp.status_code == 200

    def test_rejects_request_with_invalid_token(self):
        app = _make_app("secret123")
        client = TestClient(app)
        resp = client.get("/", headers={"authorization": "Bearer wrong"})
        assert resp.status_code == 401

    def test_rejects_request_without_token(self):
        app = _make_app("secret123")
        client = TestClient(app)
        resp = client.get("/")
        assert resp.status_code == 401

    def test_allows_health_check_without_token(self):
        app = _make_app("secret123")
        client = TestClient(app)
        resp = client.get("/health")
        assert resp.status_code == 404  # route doesn't exist, but NOT 401
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_auth.py -v`
Expected: FAIL

Note: Add `starlette` to dev dependencies if not already pulled in by `mcp[cli]`:
```bash
uv add --dev starlette httpx  # httpx needed for TestClient
```

**Step 3: Implement auth middleware**

`src/auth.py`:
```python
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


class BearerAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, token: str):
        super().__init__(app)
        self.token = token

    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/health":
            return await call_next(request)

        auth = request.headers.get("authorization", "")
        if auth != f"Bearer {self.token}":
            return JSONResponse(
                {"error": "Unauthorized"}, status_code=401
            )
        return await call_next(request)
```

**Step 4: Run tests**

Run: `uv run pytest tests/test_auth.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/auth.py tests/test_auth.py
git commit -m "feat: add Bearer token auth middleware"
```

---

## Task 9: MCP Server Entry Point

**Files:**
- Create: `src/server.py`
- Create: `tests/test_server.py`

**Step 1: Write the server entry point**

`src/server.py`:
```python
import asyncio
import contextlib
import logging
import os

from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.routing import Mount, Route
from starlette.responses import JSONResponse

from src.auth import BearerAuthMiddleware
from src.config import settings
from src.services.printify import PrintifyService
from src.tools import shops, products, catalog, images, orders

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

service = PrintifyService(
    api_key=settings.printify_api_key,
    shop_id=settings.printify_shop_id,
)

mcp = FastMCP(
    "Printify MCP Server",
    json_response=True,
    stateless_http=True,
)

# Register all tools
shops.register(mcp, service)
products.register(mcp, service)
catalog.register(mcp, service)
images.register(mcp, service)
orders.register(mcp, service)


async def health(request):
    return JSONResponse({"status": "ok"})


@contextlib.asynccontextmanager
async def lifespan(app):
    logger.info("Printify MCP Server starting")
    async with contextlib.AsyncExitStack() as stack:
        await stack.enter_async_context(mcp.session_manager.run())
        yield
    await service.close()
    logger.info("Printify MCP Server stopped")


def create_app() -> Starlette:
    app = Starlette(
        routes=[
            Route("/health", health),
            Mount("/", app=mcp.streamable_http_app()),
        ],
        lifespan=lifespan,
    )
    if settings.mcp_auth_token:
        app.add_middleware(BearerAuthMiddleware, token=settings.mcp_auth_token)
    return app


if __name__ == "__main__":
    transport = os.environ.get("TRANSPORT", settings.transport)
    if transport == "stdio":
        mcp.run(transport="stdio")
    else:
        import uvicorn

        app = create_app()
        uvicorn.run(app, host="0.0.0.0", port=settings.port)
```

**Step 2: Write smoke test**

`tests/test_server.py`:
```python
import os
os.environ.setdefault("PRINTIFY_API_KEY", "test-key")

from starlette.testclient import TestClient

from src.server import create_app


class TestHealthEndpoint:
    def test_health_returns_ok(self):
        app = create_app()
        client = TestClient(app)
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
```

**Step 3: Run all tests**

Run: `uv run pytest -v`
Expected: All PASS

**Step 4: Commit**

```bash
git add src/server.py tests/test_server.py
git commit -m "feat: add MCP server entry point with health check"
```

---

## Task 10: Dockerfile + Cloud Run Config

**Files:**
- Create: `Dockerfile`

**Step 1: Create Dockerfile**

```dockerfile
FROM python:3.12-slim AS base

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY src/ src/

ENV PYTHONUNBUFFERED=1
EXPOSE 8080

CMD ["uv", "run", "src/server.py"]
```

**Step 2: Test Docker build locally**

Run: `cd /c/Users/nouph/Dropbox/dev/PrintifyMCP/printify-mcp-server && docker build -t printify-mcp-server .`
Expected: Build succeeds.

**Step 3: Commit**

```bash
git add Dockerfile
git commit -m "chore: add Dockerfile for Cloud Run deployment"
```

---

## Task 11: Final Verification + Push

**Step 1: Run full test suite**

Run: `uv run pytest -v --tb=short`
Expected: All tests PASS

**Step 2: Lint check**

Run: `uv run ruff check src/ tests/`
Expected: No errors

**Step 3: Create initial commit and push**

```bash
git push -u origin main
```

**Step 4: Verify on GitHub**

Visit: https://github.com/kazevy/printify-mcp-server
Expected: All files visible, README displays correctly.

---

## Summary

| Task | Description | Est. |
|------|-------------|------|
| 1 | Project scaffolding | 0.25d |
| 2 | PrintifyService base client + retry | 0.5d |
| 3 | Shop tools | 0.25d |
| 4 | Product tools | 0.5d |
| 5 | Catalog tools | 0.25d |
| 6 | Image tools | 0.25d |
| 7 | Order tools | 0.25d |
| 8 | Auth middleware | 0.25d |
| 9 | MCP server entry point | 0.5d |
| 10 | Dockerfile | 0.25d |
| 11 | Final verification + push | 0.25d |
| **Total** | | **3.5d** |

Note: This covers core implementation. Cloud Run deploy, integration testing with real Printify API, and README are separate follow-up tasks.
