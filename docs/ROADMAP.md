# Printify MCP Server — ロードマップ

## 完了済み

### Phase 1: 設計・調査 (2026-02-23)
- [x] Notion調査ドキュメント作成（既存MCP候補の比較、アプローチ選定）
- [x] GitHub Organization `kazevy` 作成
- [x] リポジトリ `kazevy/printify-mcp-server` 作成（public）
- [x] アプローチ決定: B-2b Python新規（公式MCP Python SDK）
- [x] フレームワーク比較（SDK vs FastMCP vs FastAPI+MCP）→ 公式SDK選定
- [x] 設計書作成・承認 → `docs/plans/2026-02-23-printify-mcp-server-design.md`
- [x] 実装計画作成 → `docs/plans/2026-02-23-printify-mcp-server-plan.md`

### Phase 2: 初期実装 (2026-02-23) — PR #1
- [x] プロジェクトスキャフォールディング（pyproject.toml, config, .gitignore等）
- [x] PrintifyService基盤クライアント + 429リトライ（指数バックオフ）
- [x] MCP ツール全16種実装（shops/products/catalog/images/orders）
- [x] Bearer Token認証ミドルウェア
- [x] MCPサーバーエントリーポイント（Streamable HTTP + stdio対応）
- [x] Cloud Run用 Dockerfile
- [x] テスト30件 全パス、Ruff lint クリーン

### Phase 3: コードレビュー修正 (2026-02-24) — PR #2
- [x] C1: `__main__` でのService/MCP二重生成バグ解消
- [x] C2: `config.py` モジュールレベル `Settings()` 削除（遅延初期化）
- [x] C3: 認証トークン比較を `hmac.compare_digest` に変更（タイミング攻撃対策）
- [x] I1: 構造化エラーレスポンス（`handle_errors` デコレータで全ツールに適用）
- [x] I2: プロアクティブレート制限（`X-RateLimit-Remaining` ヘッダー解析）
- [x] I3: `service.close()` を `try/finally` で確実に実行
- [x] I5: `uv.lock` を `.gitignore` から除外しコミット
- [x] I6: Dockerfile CMD修正 + 非rootユーザー追加
- [x] Settings に `extra="ignore"` 追加（.env未定義フィールド対応）
- [x] テスト39件 全パス、Docker ローカルビルド + ヘルスチェック確認

## 残タスク

### Phase 4: Cloud Run デプロイ
- [ ] GCPプロジェクト設定（Artifact Registry有効化）
- [ ] DockerイメージをArtifact Registryにpush
- [ ] Cloud Runサービスデプロイ（min 0 / max 1, Startup CPU Boost）
- [ ] 環境変数設定（PRINTIFY_API_KEY, MCP_AUTH_TOKEN）
- [ ] ヘルスチェック + MCP接続テスト

### Phase 5: Claude統合テスト
- [ ] Claude Desktop からstdioモードで接続・動作確認
- [ ] Cloud Run経由で Streamable HTTP モードの接続・動作確認
- [ ] 全16ツールの実API呼び出しテスト

### Phase 6: 運用改善（優先度低）
- [ ] S1: エラーパスのテスト追加（422, 204, auth edge cases等）
- [ ] S2: `get_shop` をダイレクトAPI呼び出しに変更（可能であれば）
- [ ] S5: BaseHTTPMiddleware → 純粋ASGIミドルウェアへの移行（SSE対応強化）
- [ ] CI/CD（GitHub Actions: テスト + lint + Docker build）
- [ ] Printify Webhook対応（注文ステータス変更通知等）
