import asyncio
import logging

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://api.printify.com"
MAX_RETRIES = 3
RATE_LIMIT_THRESHOLD = 5


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

    # --- Shops ---

    async def list_shops(self) -> list[dict]:
        return await self._get("/v1/shops.json")

    async def get_shop(self, shop_id: str) -> dict | None:
        shops = await self.list_shops()
        return next((s for s in shops if str(s["id"]) == str(shop_id)), None)

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
