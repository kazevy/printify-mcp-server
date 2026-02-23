# Printify MCP Server — Design Document

Date: 2026-02-23
Status: Approved

## Overview

Standalone Printify MCP server for Claude Desktop / Claude Web. Provides full Printify API coverage as MCP tools, deployed on Cloud Run with Streamable HTTP transport.

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Approach | B-2b: Python new | Clean design, Kazevy tech stack alignment (Python/httpx) |
| Framework | Official MCP Python SDK (`mcp[cli]`) | Minimal deps, best MCP spec compliance, long-term maintainability |
| HTTP client | `httpx` (async) | Kazevy patterns reusable, async-native |
| Hosting | Cloud Run | Min 0 / Max 1, Startup CPU Boost, ~$0/month |
| Transport | Streamable HTTP (production) / stdio (local) | Single codebase, both supported by SDK |
| Auth (MCP server) | Bearer Token via ASGI middleware | Simple, sufficient for personal use |
| Auth (Printify API) | API key via environment variable | Standard Printify auth |

## Architecture

```
┌─────────────────────────────────────────┐
│ Claude Desktop / Claude Web             │
│  (MCP Client)                           │
└──────────────┬──────────────────────────┘
               │ Streamable HTTP / stdio
┌──────────────▼──────────────────────────┐
│ printify-mcp-server                     │
│  ┌────────────────────────────────────┐ │
│  │ Auth Middleware (Bearer Token)     │ │
│  ├────────────────────────────────────┤ │
│  │ MCP Server (mcp[cli] SDK)         │ │
│  │  - Tool definitions               │ │
│  │  - Schema validation (Pydantic)   │ │
│  ├────────────────────────────────────┤ │
│  │ PrintifyService (httpx)           │ │
│  │  - Shops / Products / Catalog     │ │
│  │  - Orders / Images                │ │
│  │  - Rate limiting / Retry          │ │
│  └────────────────────────────────────┘ │
└──────────────┬──────────────────────────┘
               │ HTTPS (Bearer Token)
┌──────────────▼──────────────────────────┐
│ Printify REST API                       │
│  api.printify.com/v1/                   │
└─────────────────────────────────────────┘
```

### Layers

1. **Auth Middleware** — ASGI middleware that validates Bearer token on incoming requests. Bypassed in stdio mode.
2. **MCP Server** — Tool definitions with Pydantic input schemas. Routes tool calls to PrintifyService.
3. **PrintifyService** — Async httpx client wrapping Printify REST API. Handles rate limiting (exponential backoff + `X-RateLimit-*` headers), error formatting, and response normalization.

## MCP Tools (16 tools)

### Shop Management (2)

| Tool | Printify API | Description |
|------|-------------|-------------|
| `list_shops` | `GET /v1/shops.json` | List all shops |
| `get_shop` | `GET /v1/shops/{shop_id}.json` | Get shop details |

### Product Management (6)

| Tool | Printify API | Description |
|------|-------------|-------------|
| `list_products` | `GET /v1/shops/{shop_id}/products.json` | List products (paginated) |
| `get_product` | `GET /v1/shops/{shop_id}/products/{id}.json` | Get product details (includes mockup image URLs) |
| `create_product` | `POST /v1/shops/{shop_id}/products.json` | Create product with variants and print areas |
| `update_product` | `PUT /v1/shops/{shop_id}/products/{id}.json` | Update product |
| `delete_product` | `DELETE /v1/shops/{shop_id}/products/{id}.json` | Delete product |
| `publish_product` | `POST /v1/shops/{shop_id}/products/{id}/publish.json` | Publish to sales channel |

### Catalog (4)

| Tool | Printify API | Description |
|------|-------------|-------------|
| `list_blueprints` | `GET /v1/catalog/blueprints.json` | List all blueprints |
| `get_blueprint` | `GET /v1/catalog/blueprints/{id}.json` | Get blueprint details |
| `get_print_providers` | `GET /v1/catalog/blueprints/{id}/print_providers.json` | List providers for blueprint |
| `get_variants` | `GET /v1/catalog/blueprints/{id}/print_providers/{pid}/variants.json` | List variants for blueprint+provider |

### Images (1)

| Tool | Printify API | Description |
|------|-------------|-------------|
| `upload_image` | `POST /v1/uploads/images.json` | Upload image (URL or base64) |

### Orders (3)

| Tool | Printify API | Description |
|------|-------------|-------------|
| `list_orders` | `GET /v1/shops/{shop_id}/orders.json` | List orders (paginated) |
| `get_order` | `GET /v1/shops/{shop_id}/orders/{id}.json` | Get order details |
| `submit_order` | `POST /v1/shops/{shop_id}/orders/{id}/send_to_production.json` | Send order to production |

## Project Structure

```
printify-mcp-server/
├── src/
│   ├── __init__.py
│   ├── server.py              # MCP Server entry point, transport setup
│   ├── auth.py                # Bearer Token ASGI middleware
│   ├── config.py              # Environment config (Pydantic Settings)
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── shops.py           # list_shops, get_shop
│   │   ├── products.py        # list/get/create/update/delete/publish
│   │   ├── catalog.py         # blueprints, providers, variants
│   │   ├── images.py          # upload_image
│   │   └── orders.py          # list/get/submit orders
│   └── services/
│       ├── __init__.py
│       └── printify.py        # PrintifyService (httpx async client)
├── tests/
│   ├── conftest.py            # Shared fixtures (mock httpx)
│   ├── test_shops.py
│   ├── test_products.py
│   ├── test_catalog.py
│   ├── test_images.py
│   └── test_orders.py
├── Dockerfile                 # Multi-stage build
├── pyproject.toml             # Dependencies, scripts, tool config
├── .env.example               # Template for environment variables
└── docs/
    └── plans/
        └── 2026-02-23-printify-mcp-server-design.md
```

## Configuration

Environment variables:

| Variable | Required | Description |
|----------|----------|-------------|
| `PRINTIFY_API_KEY` | Yes | Printify API token |
| `PRINTIFY_SHOP_ID` | No | Default shop ID (auto-selects first shop if omitted) |
| `MCP_AUTH_TOKEN` | Yes (remote) | Bearer token for MCP server auth |
| `PORT` | No | Server port (default: 8080, Cloud Run standard) |
| `TRANSPORT` | No | `streamable-http` (default) or `stdio` |

## Rate Limiting Strategy

- Parse `X-RateLimit-Remaining` and `X-RateLimit-Reset` headers from Printify responses
- When remaining < 5: add delay before next request
- On 429 response: exponential backoff (1s, 2s, 4s, max 3 retries)
- Printify limit: 600 requests / 5 minutes

## Error Handling

All tools return structured error responses:

```json
{
  "error": true,
  "status_code": 422,
  "message": "Validation failed",
  "details": { "title": ["is required"] }
}
```

## Cloud Run Configuration

- **Image**: Multi-stage Dockerfile (python:3.12-slim)
- **Min instances**: 0
- **Max instances**: 1
- **CPU**: 1 vCPU (request-time only)
- **Memory**: 256MB
- **Startup CPU Boost**: Enabled
- **Secrets**: PRINTIFY_API_KEY, MCP_AUTH_TOKEN via Secret Manager
- **Health check**: `GET /health` endpoint

## Effort Estimate

| Task | Days |
|------|------|
| Project setup (pyproject.toml, Docker, config) | 0.25 |
| MCP server base (Streamable HTTP + stdio) | 0.5 |
| Auth middleware | 0.5 |
| Health check | 0.25 |
| PrintifyService (httpx, rate limiting) | 2.5 |
| Tools: Shops + Products + Catalog + Images + Orders | 1 |
| Cloud Run (Dockerfile, Secret Manager) | 0.5 |
| Tests | 1.5 |
| Deploy & verification | 0.5 |
| **Total** | **7.5** |
