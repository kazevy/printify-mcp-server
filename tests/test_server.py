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
