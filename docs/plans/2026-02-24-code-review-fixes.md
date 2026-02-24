# コードレビュー残件（I1・I2）修正 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** コードレビューで指摘された I1（構造化エラーレスポンス）と I2（プロアクティブレート制限）を実装する

**Architecture:** I1 は共通デコレータ `handle_errors` でツール層の例外を構造化JSONに変換する。I2 は `PrintifyService._request()` にレスポンスヘッダー解析を追加し、残りリクエスト数が閾値以下の場合にスリープを入れる。

**Tech Stack:** Python 3.12, httpx, pytest, respx, functools

---

### Task 1: エラーハンドラーデコレータ — テスト作成

**Files:**
- Create: `src/tools/_error_handler.py`
- Create: `tests/test_error_handler.py`

**Step 1: テストファイル作成**

`tests/test_error_handler.py`:

```python
import httpx
import pytest

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

    async def test_value_error_returns_structured_response(self):
        @handle_errors
        async def failing_tool():
            raise ValueError("shop_id is required. Set PRINTIFY_SHOP_ID or call list_shops first.")

        result = await failing_tool()
        assert result["error"] is True
        assert result["status_code"] == 400
        assert "shop_id" in result["message"]
```

**Step 2: テスト実行 — 失敗確認**

Run: `uv run pytest tests/test_error_handler.py -v`
Expected: FAIL（`_error_handler` モジュールが存在しない）

**Step 3: 最小実装**

`src/tools/_error_handler.py`:

```python
import functools

import httpx


def handle_errors(func):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except httpx.HTTPStatusError as e:
            details = {}
            content_type = e.response.headers.get("content-type", "")
            if content_type.startswith("application/json"):
                try:
                    details = e.response.json()
                except Exception:
                    pass
            return {
                "error": True,
                "status_code": e.response.status_code,
                "message": str(e),
                "details": details,
            }
        except ValueError as e:
            return {
                "error": True,
                "status_code": 400,
                "message": str(e),
                "details": {},
            }

    return wrapper
```

**Step 4: テスト実行 — パス確認**

Run: `uv run pytest tests/test_error_handler.py -v`
Expected: 4 PASSED

**Step 5: コミット**

```bash
git add src/tools/_error_handler.py tests/test_error_handler.py
git commit -m "feat: 構造化エラーレスポンス用デコレータ追加 (I1-1/2)"
```

---

### Task 2: 全ツールにデコレータ適用 + 統合テスト

**Files:**
- Modify: `src/tools/shops.py`
- Modify: `src/tools/products.py`
- Modify: `src/tools/catalog.py`
- Modify: `src/tools/images.py`
- Modify: `src/tools/orders.py`
- Modify: `tests/test_products.py`（統合テスト追加）

**Step 1: 統合テスト追加**

`tests/test_products.py` の末尾に追加:

```python
class TestProductErrorHandling:
    @respx.mock
    async def test_create_product_returns_structured_error_on_422(self, service: PrintifyService):
        respx.post(f"{API}/v1/shops/{SHOP_ID}/products.json").mock(
            return_value=httpx.Response(
                422,
                json={"title": ["is required"]},
            )
        )
        result = await service.create_product({"blueprint_id": 6})
        assert result["error"] is True
        assert result["status_code"] == 422
        assert result["details"] == {"title": ["is required"]}
```

**Step 2: テスト実行 — 失敗確認**

Run: `uv run pytest tests/test_products.py::TestProductErrorHandling -v`
Expected: FAIL（`httpx.HTTPStatusError` が raise される）

**Step 3: 全ツールファイルにデコレータ適用**

各ツールファイルに以下の変更を適用:

`src/tools/shops.py`:
```python
from mcp.server.fastmcp import FastMCP

from src.services.printify import PrintifyService
from src.tools._error_handler import handle_errors


def register(mcp: FastMCP, service: PrintifyService):
    @mcp.tool()
    @handle_errors
    async def list_shops() -> list[dict]:
        """List all Printify shops in your account."""
        return await service.list_shops()

    @mcp.tool()
    @handle_errors
    async def get_shop(shop_id: str) -> dict | str:
        """Get details for a specific shop by ID."""
        result = await service.get_shop(shop_id)
        if result is None:
            return f"Shop {shop_id} not found"
        return result
```

`src/tools/products.py`:
```python
from mcp.server.fastmcp import FastMCP

from src.services.printify import PrintifyService
from src.tools._error_handler import handle_errors


def register(mcp: FastMCP, service: PrintifyService):
    @mcp.tool()
    @handle_errors
    async def list_products(page: int = 1, limit: int = 10) -> dict:
        """List products in the current shop. Supports pagination."""
        return await service.list_products(page=page, limit=limit)

    @mcp.tool()
    @handle_errors
    async def get_product(product_id: str) -> dict:
        """Get detailed product info including mockup image URLs."""
        return await service.get_product(product_id)

    @mcp.tool()
    @handle_errors
    async def create_product(data: dict) -> dict:
        """Create a new product. Requires title, blueprint_id, print_provider_id, variants, and print_areas."""
        return await service.create_product(data)

    @mcp.tool()
    @handle_errors
    async def update_product(product_id: str, data: dict) -> dict:
        """Update an existing product's properties."""
        return await service.update_product(product_id, data)

    @mcp.tool()
    @handle_errors
    async def delete_product(product_id: str) -> dict:
        """Delete a product from the shop."""
        return await service.delete_product(product_id)

    @mcp.tool()
    @handle_errors
    async def publish_product(product_id: str, data: dict) -> dict:
        """Publish a product to sales channels. Data should specify which fields to publish (title, description, images, variants, tags)."""
        return await service.publish_product(product_id, data)
```

`src/tools/catalog.py`:
```python
from mcp.server.fastmcp import FastMCP

from src.services.printify import PrintifyService
from src.tools._error_handler import handle_errors


def register(mcp: FastMCP, service: PrintifyService):
    @mcp.tool()
    @handle_errors
    async def list_blueprints() -> list[dict]:
        """List all available product blueprints (templates) from Printify catalog."""
        return await service.list_blueprints()

    @mcp.tool()
    @handle_errors
    async def get_blueprint(blueprint_id: int) -> dict:
        """Get details for a specific blueprint including available images and description."""
        return await service.get_blueprint(blueprint_id)

    @mcp.tool()
    @handle_errors
    async def get_print_providers(blueprint_id: int) -> list[dict]:
        """List print providers available for a specific blueprint."""
        return await service.get_print_providers(blueprint_id)

    @mcp.tool()
    @handle_errors
    async def get_variants(blueprint_id: int, provider_id: int) -> dict:
        """List variants (sizes, colors) for a blueprint and print provider combination."""
        return await service.get_variants(blueprint_id, provider_id)
```

`src/tools/images.py`:
```python
from mcp.server.fastmcp import FastMCP

from src.services.printify import PrintifyService
from src.tools._error_handler import handle_errors


def register(mcp: FastMCP, service: PrintifyService):
    @mcp.tool()
    @handle_errors
    async def upload_image(
        file_name: str, url: str | None = None, contents: str | None = None
    ) -> dict:
        """Upload an image to Printify. Provide either a URL or base64-encoded contents."""
        return await service.upload_image(
            file_name=file_name, url=url, contents=contents
        )
```

`src/tools/orders.py`:
```python
from mcp.server.fastmcp import FastMCP

from src.services.printify import PrintifyService
from src.tools._error_handler import handle_errors


def register(mcp: FastMCP, service: PrintifyService):
    @mcp.tool()
    @handle_errors
    async def list_orders(page: int = 1, limit: int = 10) -> dict:
        """List orders in the current shop. Supports pagination."""
        return await service.list_orders(page=page, limit=limit)

    @mcp.tool()
    @handle_errors
    async def get_order(order_id: str) -> dict:
        """Get detailed order information including line items and shipping status."""
        return await service.get_order(order_id)

    @mcp.tool()
    @handle_errors
    async def submit_order(order_id: str) -> dict:
        """Send an order to production. This action cannot be undone."""
        return await service.submit_order(order_id)
```

**注意:** 統合テストで `service.create_product()` を直接呼ぶと `_request()` が例外を raise するため、テストはツール経由で呼ぶか、あるいはサービス層で直接呼びつつ結果の形式を確認する必要がある。

ツール層のテストは MCP サーバー経由になり複雑すぎるため、以下のようにサービス層のメソッドをデコレータでラップした関数をテストする:

`tests/test_products.py` の統合テストを修正:

```python
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
```

**Step 4: テスト実行 — パス確認**

Run: `uv run pytest -v`
Expected: 全テスト PASSED（既存30 + 新規テスト）

**Step 5: Ruff チェック**

Run: `uv run ruff check src/ tests/`
Expected: All checks passed!

**Step 6: コミット**

```bash
git add src/tools/ tests/test_products.py
git commit -m "feat: 全ツールに構造化エラーレスポンスを適用 (I1-2/2)"
```

---

### Task 3: プロアクティブレート制限 — テスト作成

**Files:**
- Modify: `src/services/printify.py:28-47`
- Modify: `tests/test_printify_service.py`

**Step 1: テスト追加**

`tests/test_printify_service.py` に追加:

```python
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
```

**Step 2: テスト実行 — 失敗確認**

Run: `uv run pytest tests/test_printify_service.py::TestProactiveRateLimit -v`
Expected: FAIL（スリープが呼ばれない）

**Step 3: 実装**

`src/services/printify.py` の `_request()` メソッドを修正:

```python
RATE_LIMIT_THRESHOLD = 5

async def _request(
    self, method: str, path: str, **kwargs
) -> dict | list:
    last_exc = None
    for attempt in range(MAX_RETRIES):
        try:
            response = await self._client.request(method, path, **kwargs)
            response.raise_for_status()

            # プロアクティブレート制限
            remaining = response.headers.get("X-RateLimit-Remaining")
            if remaining is not None and int(remaining) < RATE_LIMIT_THRESHOLD:
                reset = float(response.headers.get("X-RateLimit-Reset", "1"))
                logger.info(f"Rate limit low ({remaining} remaining). Sleeping {reset}s")
                await asyncio.sleep(reset)

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
```

**Step 4: テスト実行 — パス確認**

Run: `uv run pytest tests/test_printify_service.py -v`
Expected: 全テスト PASSED

**Step 5: コミット**

```bash
git add src/services/printify.py tests/test_printify_service.py
git commit -m "feat: プロアクティブレート制限を追加 (I2)"
```

---

### Task 4: 全テスト実行 + Ruff + Docker ローカルビルド確認

**Files:** なし（検証のみ）

**Step 1: 全テスト実行**

Run: `uv run pytest -v`
Expected: 全テスト PASSED（30 + 4 + 2 + 3 = 39）

**Step 2: Ruff チェック**

Run: `uv run ruff check src/ tests/`
Expected: All checks passed!

**Step 3: Docker ビルド**

Run: `docker build -t printify-mcp-server .`
Expected: ビルド成功

**Step 4: Docker 起動テスト**

```bash
docker run --rm -p 8080:8080 \
  -e PRINTIFY_API_KEY=<.envから取得> \
  -e MCP_AUTH_TOKEN=test-local-token \
  printify-mcp-server
```

別ターミナルでヘルスチェック:

```bash
curl http://localhost:8080/health
```

Expected: `{"status":"ok"}`

**Step 5: コミット（最終整理があれば）**

```bash
git add -A
git commit -m "chore: コードレビュー残件(I1・I2)完了"
```
