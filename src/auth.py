import hmac

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
        # 定数時間比較。非 ASCII ヘッダーで例外（500）にならないよう bytes で比べる
        expected = f"Bearer {self.token}".encode("utf-8")
        if not hmac.compare_digest(auth.encode("utf-8", "surrogatepass"), expected):
            return JSONResponse(
                {"error": "Unauthorized"}, status_code=401
            )
        return await call_next(request)
