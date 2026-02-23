# Claude Code プロジェクト設定

このファイルはClaude Codeが会話開始時に自動的に読み込みます。

## 起動時ルール

会話開始時に必ず Skill ツールで `using-superpowers` スキルを呼び出すこと。タスクに応じて適切なスキルを確認・適用すること。

## 必読ドキュメント

開発作業を行う前に、以下のドキュメントを確認してください：

1. **設計書**: `docs/plans/2026-02-23-printify-mcp-server-design.md`
2. **実装計画**: `docs/plans/2026-02-23-printify-mcp-server-plan.md`

## 品質保証の原則（最重要）

> **「動かないコードはビジネス価値ゼロ」**

### 機能実装時の必須チェック

- [ ] ユニットテストを作成した
- [ ] テストが全てパスする（`uv run pytest -v`）
- [ ] 型チェック・リントが通る（`uv run ruff check src/ tests/`）
- [ ] エラーケースの動作も確認した

### やってはいけないこと

- テストなしで「完了」と報告する
- 手動テストのみで自動テストを省略する
- 既存のテストを壊したまま放置する

## 標準実行ワークフロー ⭐⭐⭐

> **実装計画策定後の「実行方法を選んでください」で常にこのパターンを選択肢に含めること。**

### フロー

1. **Agent Team + Git worktree + TDD** で実装
2. サブエージェント作業完了 → **PRレビュー** + **セキュリティチェック**（`make security-scan` → OWASP手動レビュー）
3. **マージ** → 統合テスト → **Chrome UAT**
4. **後片付け**: Git worktree削除、PRクローズ、**関連Issueクローズ**（全Phase完了時。部分完了の場合はIssue本文/コメントに進捗を記録してOpenのまま維持）
5. **ロードマップ確認**（完了項目あれば更新、Issue番号のリンクと✅マークを反映）
6. **コミット & プッシュ** → Dockerリビルド → **本番デプロイ**
7. **本番動作確認**（Chrome MCP → Playwright の2段構え） + **インフラセキュリティ確認**

### 実行方法の提示テンプレート

実装計画が完成したら、以下の選択肢を提示する:

```
実行方法を選んでください：

1. 標準ワークフロー（推奨）
   Agent Team + Git worktree + TDD → PRレビュー + セキュリティチェック → マージ → デプロイ → 本番確認 + インフラセキュリティ

2. Subagent-Driven（このセッション簡易版）
   worktreeなし、タスクごとにサブエージェント + レビュー

3. Parallel Session（別セッション）
   worktreeで新セッションを開き、バッチ実行
```

## 言語設定

- ドキュメント・会話: **日本語**
- コミットメッセージ: **日本語**
- コード内コメント: **日本語**

## 並行作業ルール（git worktree） ⭐⭐⭐

> **複数エージェントが同時に作業する場合、必ず git worktree を使うこと。同じディレクトリでブランチを切り替えない。**

### worktree の作成

> **重要: worktreeはDropbox外のディレクトリに作成すること。**
> Dropbox内に作成するとファイル同期によりパフォーマンスが大幅に低下する。

```bash
# メインリポジトリのルートで実行
git worktree add /c/dev/worktrees/printify-mcp-<作業名> -b <ブランチ名>

# 例
git worktree add /c/dev/worktrees/printify-mcp-feature -b feature/add-tools

# 重要: .envファイルをworktreeにコピー（git管理外のため自動コピーされない）
cp .env /c/dev/worktrees/printify-mcp-<作業名>/.env
```

### ルール

- **作業完了後**: `git worktree remove /c/dev/worktrees/printify-mcp-<作業名>` で削除

## ビルド・デプロイはバックグラウンドで実行 ⭐⭐⭐

> **時間のかかるビルド・デプロイコマンドは `run_in_background: true` で実行し、待機中に他の作業を継続すること。**

対象コマンド:
- `docker build`
- `gcloud run deploy`

## 環境

- OS: Windows (MSYS2/Git Bash)
- Language: Python 3.12+
- Package Manager: uv
- Framework: MCP Python SDK (`mcp[cli]`)
- HTTP Client: httpx (async)
- Test: pytest + pytest-asyncio + respx
- Deploy: Cloud Run (Docker)
- Repository: https://github.com/kazevy/printify-mcp-server
