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

    def test_rejects_non_bearer_auth_scheme(self):
        app = _make_app("secret123")
        client = TestClient(app)
        resp = client.get("/", headers={"authorization": "Basic dXNlcjpwYXNz"})
        assert resp.status_code == 401

    def test_rejects_bearer_prefix_only(self):
        app = _make_app("secret123")
        client = TestClient(app)
        resp = client.get("/", headers={"authorization": "Bearer "})
        assert resp.status_code == 401

    def test_error_response_body(self):
        app = _make_app("secret123")
        client = TestClient(app)
        resp = client.get("/")
        assert resp.json() == {"error": "Unauthorized"}

    def test_allows_health_check_without_token(self):
        app = _make_app("secret123")
        client = TestClient(app)
        resp = client.get("/health")
        assert resp.status_code == 404  # route doesn't exist, but NOT 401
