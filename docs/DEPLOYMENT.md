# デプロイガイド

## ホスティング構成

**Google Cloud Run**（Kazevyバックエンドとは完全分離の独立コンテナ）

| 項目 | 値 |
|------|-----|
| リージョン | asia-northeast1 |
| 最小インスタンス | 0 |
| 最大インスタンス | 1 |
| CPU | 1 vCPU |
| メモリ | 512MB |
| Startup CPU Boost | 有効 |
| CPU割当 | リクエスト処理中のみ |
| 月額概算 | ~$0.01〜0.05 |
| コールドスタート | 1〜2秒（Boost有効時） |

MCPセッション中はツール呼び出しが数分間隔でもウォーム維持されるため、コールドスタートは初回のみ。

## 環境変数

| 変数名 | 必須 | 説明 |
|--------|:---:|------|
| `PRINTIFY_API_KEY` | Yes | Printify APIトークン |
| `PRINTIFY_SHOP_ID` | No | デフォルトショップID |
| `MCP_AUTH_TOKEN` | Yes | MCP接続用Bearer Token（16文字以上）。HTTP モードでは `MCP_AUTH_TOKEN` も `OAUTH_ISSUER_URL` も無いと起動を拒否する |
| `OAUTH_ISSUER_URL` | No | 公開URL（例: `https://xxx.run.app`）。設定すると OAuth（DCR + 同意画面）を有効化 |
| `OAUTH_OWNER_PASSWORD` | No | OAuth 同意画面の合言葉（16文字以上）。未設定なら `MCP_AUTH_TOKEN` を合言葉として使う |
| `OAUTH_ALLOWED_REDIRECT_URIS` | No | DCR で追加許可する redirect_uri（カンマ区切り・完全一致）。claude.ai / claude.com のコールバックとループバックは既定で許可 |
| `PORT` | No | リッスンポート（デフォルト: 8080） |
| `TRANSPORT` | No | トランスポート（デフォルト: streamable-http） |

## デプロイ手順

### 初回デプロイ

```bash
# 1. サービス作成 & デプロイ
gcloud run deploy printify-mcp-server \
  --region asia-northeast1 \
  --source . \
  --port 8080 \
  --memory 512Mi \
  --cpu 1 \
  --min-instances 0 \
  --max-instances 1 \
  --cpu-boost \
  --cpu-throttling \
  --set-env-vars "TRANSPORT=streamable-http" \
  --set-secrets "PRINTIFY_API_KEY=printify-api-key:latest,MCP_AUTH_TOKEN=printify-mcp-auth-token:latest" \
  --allow-unauthenticated

# 2. ヘルスチェック確認
curl https://<SERVICE_URL>/health
```

### Secret Manager に機密情報を登録

```bash
# Printify APIキー
echo -n "YOUR_PRINTIFY_API_KEY" | \
  gcloud secrets create printify-api-key --data-file=-

# MCP認証トークン（任意の安全な文字列を生成）
python -c "import secrets; print(secrets.token_urlsafe(32))" | \
  gcloud secrets create printify-mcp-auth-token --data-file=-
```

### 更新デプロイ

```bash
gcloud run deploy printify-mcp-server \
  --region asia-northeast1 \
  --source .
```

## ローカル開発

```bash
# .env ファイルを作成
cp .env.example .env
# .env に PRINTIFY_API_KEY を設定

# stdio モード（Claude Code用）
uv run python -m src.server --transport stdio

# HTTP モード（リモートMCPテスト用）
uv run python -m src.server
# → http://localhost:8080/mcp
```

## MCP接続設定

### Claude Code（stdio）

`.mcp.json`:
```json
{
  "printify": {
    "type": "stdio",
    "command": "uv",
    "args": ["run", "python", "-m", "src.server"],
    "cwd": "/path/to/printify-mcp-server",
    "env": {
      "PRINTIFY_API_KEY": "your-api-key",
      "TRANSPORT": "stdio"
    }
  }
}
```

### Claude Desktop / TypingMind（リモート）

URL: `https://<SERVICE_URL>/mcp`
認証: Bearer Token（`MCP_AUTH_TOKEN` に設定した値）

### OAuth クライアント（Claude.ai カスタムコネクタ / Claude Code / Codex の OAuth 接続）

`OAUTH_ISSUER_URL` を設定している場合、接続時にブラウザでサーバーの同意画面が開く。
要求元アプリ名（自己申告）と redirect_uri を確認し、合言葉（`OAUTH_OWNER_PASSWORD`、未設定なら `MCP_AUTH_TOKEN`）を入力して Approve する。
合言葉なしでは認可コードは発行されない。同意画面の要求は 5 分で失効し、1 要求あたり 5 回、全体で 15 分に 20 回失敗するとロックする（ロック中も静的 Bearer Token は使える）。
クライアント・トークンはインメモリのため、再デプロイ・インスタンス再起動のたびに再認可が必要。
