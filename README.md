# Printify MCP Server

Printify REST API の全機能を MCP (Model Context Protocol) ツールとして提供するスタンドアロンサーバー。Claude Desktop / Claude Web から Printify のショップ管理、商品作成、注文処理などを直接操作できます。

## 機能

16の MCP ツールで Printify API をフルカバー:

| カテゴリ | ツール |
|----------|--------|
| Shop (2) | `list_shops`, `get_shop` |
| Product (6) | `list_products`, `get_product`, `create_product`, `update_product`, `delete_product`, `publish_product` |
| Catalog (4) | `list_blueprints`, `get_blueprint`, `get_print_providers`, `get_variants` |
| Image (1) | `upload_image` |
| Order (3) | `list_orders`, `get_order`, `submit_order` |

## セットアップ

### 必要なもの

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (パッケージマネージャー)
- Printify API キー ([Printify Settings](https://printify.com/app/account/api) で取得)

### インストール

```bash
git clone https://github.com/kazevy/printify-mcp-server.git
cd printify-mcp-server
cp .env.example .env
# .env を編集して PRINTIFY_API_KEY を設定
uv sync
```

### 環境変数

| 変数 | 必須 | 説明 |
|------|------|------|
| `PRINTIFY_API_KEY` | Yes | Printify API キー |
| `PRINTIFY_SHOP_ID` | No | デフォルトのショップID（省略時は `list_shops` で取得） |
| `MCP_AUTH_TOKEN` | No | MCP サーバーの認証トークン（リモートデプロイ時に設定推奨） |
| `PORT` | No | サーバーポート（デフォルト: 8080） |
| `TRANSPORT` | No | `streamable-http` or `stdio`（デフォルト: `streamable-http`） |

## 使い方

### Claude Desktop (stdio モード)

`claude_desktop_config.json` に追加:

```json
{
  "mcpServers": {
    "printify": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/printify-mcp-server", "python", "-m", "src.server"],
      "env": {
        "PRINTIFY_API_KEY": "your_api_key",
        "TRANSPORT": "stdio"
      }
    }
  }
}
```

### HTTP モード (ローカル)

```bash
uv run python -m src.server
# http://localhost:8080 で起動
```

ヘルスチェック:

```bash
curl http://localhost:8080/health
# {"status":"ok"}
```

### Docker

```bash
docker build -t printify-mcp-server .
docker run -p 8080:8080 \
  -e PRINTIFY_API_KEY=your_api_key \
  -e MCP_AUTH_TOKEN=your_secret_token \
  printify-mcp-server
```

## 開発

```bash
# 依存関係インストール (dev含む)
uv sync --dev

# テスト実行
uv run pytest -v

# Lint
uv run ruff check src/ tests/
```

## アーキテクチャ

```
Client → BearerAuthMiddleware → Starlette App
                                  ├── /health
                                  └── / (FastMCP streamable HTTP)
                                        └── 16 MCP Tools → PrintifyService → Printify API
```

- **Auth Middleware** — Bearer Token認証（`/health` はバイパス）
- **MCP Server** — 公式 MCP Python SDK (FastMCP) によるツール定義
- **PrintifyService** — httpx AsyncClient、429リトライ（指数バックオフ）、プロアクティブレート制限

## ドキュメント

- [設計書](docs/plans/2026-02-23-printify-mcp-server-design.md)
- [ロードマップ](docs/ROADMAP.md)

## ライセンス

MIT
