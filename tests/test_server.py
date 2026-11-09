import os

os.environ.setdefault("PRINTIFY_API_KEY", "test-key")

from starlette.testclient import TestClient

from src.server import create_app


class TestHealthEndpoint:
    def test_health_returns_ok(self, monkeypatch):
        monkeypatch.setenv("MCP_AUTH_TOKEN", "test-bearer-token")
        monkeypatch.delenv("OAUTH_ISSUER_URL", raising=False)
        app = create_app()
        client = TestClient(app)
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


INIT_BODY = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "0"},
    },
}
MCP_HEADERS = {"Accept": "application/json, text/event-stream"}


class TestMcpGetRejected:
    """GET /mcp（サーバーからの通知を待つ接続）は張らせず 405 を返す。

    Claude Code は GET /mcp を張りっぱなしにし、Cloud Run のインスタンスが 1 日中起き続けて
    課金されていた（2026-11-08 に 1 日 24 時間・接続時間の合計 441 時間）。
    このサーバーのツールはクライアントへ通知しないので、この接続は要らない。
    """

    def test_get_mcp_returns_405_with_bearer(self, monkeypatch):
        monkeypatch.setenv("MCP_AUTH_TOKEN", "test-bearer-token")
        monkeypatch.delenv("OAUTH_ISSUER_URL", raising=False)
        with TestClient(create_app()) as client:
            resp = client.get(
                "/mcp",
                headers={"Authorization": "Bearer test-bearer-token", "Accept": "text/event-stream"},
            )
        assert resp.status_code == 405
        assert resp.headers["allow"] == "POST"

    def test_get_mcp_returns_405_in_oauth_mode(self, monkeypatch):
        monkeypatch.setenv("MCP_AUTH_TOKEN", "test-bearer-token")
        monkeypatch.setenv("OAUTH_ISSUER_URL", "https://printify-mcp.example.com")
        with TestClient(create_app()) as client:
            resp = client.get("/mcp", headers={"Accept": "text/event-stream"})
            # OAuth の開始は認証なしの POST /mcp の 401 から始まる。こちらは変えない
            post = client.post("/mcp", json=INIT_BODY, headers=MCP_HEADERS)
        assert resp.status_code == 405
        assert resp.headers["allow"] == "POST"
        assert post.status_code == 401
        assert "resource_metadata" in post.headers["www-authenticate"]

    def test_post_mcp_still_works(self, monkeypatch):
        monkeypatch.setenv("MCP_AUTH_TOKEN", "test-bearer-token")
        monkeypatch.delenv("OAUTH_ISSUER_URL", raising=False)
        with TestClient(create_app()) as client:
            resp = client.post(
                "/mcp",
                json=INIT_BODY,
                headers={"Authorization": "Bearer test-bearer-token", **MCP_HEADERS},
            )
        assert resp.status_code == 200
        assert resp.json()["result"]["serverInfo"]["name"] == "Printify MCP Server"
