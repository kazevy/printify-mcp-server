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
