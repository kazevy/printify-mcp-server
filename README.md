# Printify MCP Server

A standalone MCP (Model Context Protocol) server that exposes the full Printify REST API as MCP tools. Manage shops, products, orders, and more directly from Claude Desktop or Claude Web.

[日本語版 README](README.ja.md)

## Features

16 MCP tools covering the entire Printify API:

| Category | Tools |
|----------|-------|
| Shop (2) | `list_shops`, `get_shop` |
| Product (6) | `list_products`, `get_product`, `create_product`, `update_product`, `delete_product`, `publish_product` |
| Catalog (4) | `list_blueprints`, `get_blueprint`, `get_print_providers`, `get_variants` |
| Image (1) | `upload_image` |
| Order (3) | `list_orders`, `get_order`, `submit_order` |

## Setup

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (package manager)
- Printify API key (get one at [Printify Settings](https://printify.com/app/account/api))

### Installation

```bash
git clone https://github.com/kazevy/printify-mcp-server.git
cd printify-mcp-server
cp .env.example .env
# Edit .env and set your PRINTIFY_API_KEY
uv sync
```

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `PRINTIFY_API_KEY` | Yes | Printify API key |
| `PRINTIFY_SHOP_ID` | No | Default shop ID (use `list_shops` to discover) |
| `MCP_AUTH_TOKEN` | No | Auth token for the MCP server (recommended for remote deployments) |
| `PORT` | No | Server port (default: 8080) |
| `TRANSPORT` | No | `streamable-http` or `stdio` (default: `streamable-http`) |

## Usage

### Claude Desktop (stdio mode)

Add to `claude_desktop_config.json`:

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

### HTTP Mode (local)

```bash
uv run python -m src.server
# Running at http://localhost:8080
```

Health check:

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

## Cloud Run Deployment (Production)

For deploying to Google Cloud Run, use Secret Manager to store credentials instead of environment variables directly.

### 1. Create secrets in Secret Manager

```bash
# Generate a secure auth token
python -c "import secrets; print(secrets.token_urlsafe(32))" | \
  gcloud secrets create printify-mcp-auth-token --data-file=-

# Store your Printify API key
echo -n "YOUR_PRINTIFY_API_KEY" | \
  gcloud secrets create printify-api-key --data-file=-
```

### 2. Grant Cloud Run access to secrets

```bash
PROJECT_NUM=$(gcloud projects describe $(gcloud config get-value project) --format="value(projectNumber)")
for SECRET in printify-api-key printify-mcp-auth-token; do
  gcloud secrets add-iam-policy-binding $SECRET \
    --member="serviceAccount:${PROJECT_NUM}-compute@developer.gserviceaccount.com" \
    --role="roles/secretmanager.secretAccessor"
done
```

### 3. Deploy

```bash
gcloud run deploy printify-mcp-server \
  --region asia-northeast1 \
  --source . \
  --port 8080 \
  --memory 512Mi \
  --cpu 1 \
  --min-instances 0 \
  --max-instances 1 \
  --cpu-boost \
  --set-secrets "PRINTIFY_API_KEY=printify-api-key:latest,MCP_AUTH_TOKEN=printify-mcp-auth-token:latest" \
  --allow-unauthenticated
```

See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for full details including update deployments and MCP client configuration.

### Security Best Practices

- **Never commit `.env` files** — already listed in `.gitignore`
- **Use Secret Manager for production** — avoid setting API keys directly as Cloud Run environment variables
- **Rotate `MCP_AUTH_TOKEN` periodically** — generate a new token and update the secret when needed
- **Set `PRINTIFY_SHOP_ID`** to restrict access to a specific shop when multi-shop access is not required

## Development

```bash
# Install dependencies (including dev)
uv sync --dev

# Run tests
uv run pytest -v

# Lint
uv run ruff check src/ tests/
```

## Architecture

```
Client → BearerAuthMiddleware → Starlette App
                                  ├── /health
                                  └── / (FastMCP streamable HTTP)
                                        └── 16 MCP Tools → PrintifyService → Printify API
```

- **Auth Middleware** — Bearer token authentication (`/health` is bypassed)
- **MCP Server** — Tool definitions via the official MCP Python SDK (FastMCP)
- **PrintifyService** — Async httpx client with 429 retry (exponential backoff) and proactive rate limiting

## Documentation

- [Design Document](docs/plans/2026-02-23-printify-mcp-server-design.md)
- [Roadmap](docs/ROADMAP.md)

## License

MIT
