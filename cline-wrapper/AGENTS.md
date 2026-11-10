# Cline SDK を使った、カスタマイズした Cline 利用 CLI ツール

`@cline/sdk` の `Agent` から、ClinePass の `minimax-m3` を呼び出すツール群です。

- `main.mjs` — `Agent` + カスタムツールの動作確認用の最小サンプル。SDKの使い方を確認したいときに読む。
- `repo-search.mjs` — 実用ツール本体。2段階のリポジトリ検索フローで根拠付きの回答を返す（詳細は後述）。

## セットアップ

```powershell
npm install --prefix tools\cline-wrapper
```

APIキーは Cline の Settings > API Keys で作成します。ClinePassのサブスクリプション（初月 $4.99、以降 $9.99/月）が前提です。

- `main.mjs` と `repo-search.mjs` はどちらも `tools/cline-wrapper/.env` の `CLINE_API_KEY` を読む。`.env.example` を `.env` にコピーして値を設定する。既に環境変数に設定されていればそちらを優先する。

## main.mjs の実行

リポジトリルートから実行します。

```powershell
npm start --prefix tools\cline-wrapper
npm start --prefix tools\cline-wrapper -- "TypeScriptを一文で説明して"
```

## repo-search.mjs — 2段階リポジトリ検索フロー

質問を受け取り、2段階でリポジトリを検索して根拠のある回答を返すフローです。`@cline/sdk` の `Agent`（stateless・ビルトインファイル/検索ツール無し）を使い、ファイル検索・読み取りは自前のカスタムツール（純Node実装・外部依存なし）で行います。

- **モデル**: 既定は [lib/config.mjs](lib/config.mjs) の `DEFAULT_MODEL_ID`（`cline-pass/minimax-m3`）。`--model` / `-m` で切替可（フル id または短い名前）
- **APIキー**: `tools/cline-wrapper/.env` の `CLINE_API_KEY` から読み込む
- **構成の意図**: 最初のエージェントでコンテキストを気にせず網羅的に探索して抜け漏れをなくし、後続エージェントで関連ファイルだけを読み込むことでコンテキストを汚さず質の高い回答を出す。
- **共有モジュール**: `lib/agent-runner.mjs`（Agent 実行）、`lib/completing-tool.mjs`（`completesRun` ツール）、`lib/config.mjs`（provider/model）

### フロー

1. **エージェント1（探索）**: `grep_search` / `read_file` / `list_files` で網羅的に探索し、`submit_findings`（`completesRun: true`）で「関連ファイルパス+重要度+理由 / 有効だったGrepキーワード / 概要」のみを確定する。生のファイル内容は出力に含めない。
2. **エージェント2（回答）**: エージェント1の出力（JSON）をプロンプトに注入し、`grep_search` / `read_file` で関連ファイルを実際に読み、`submit_answer`（`completesRun: true`）でファイルパス・行番号を根拠とする回答を確定する。
3. いずれの完了ツールも呼ばれなかった場合は `outputText` にフォールバックする。

### 実行

```powershell
npm run search --prefix tools\cline-wrapper -- "このリポジトリでaim CLIのエントリポイントはどこですか"
# 検索対象リポジトリを明示的に指定する場合
npm run search --prefix tools\cline-wrapper -- --repo C:\CodeRoot\AI "フックの仕組みを説明して"
# モデルを切り替える場合
npm run search --prefix tools\cline-wrapper -- --model minimax-m3 "質問"
```

オプション: `--repo / -r <path>`（検索対象リポジトリルート、既定はカレントディレクトリ）、`--model / -m <id>`（モデル。既定は `lib/config.mjs`）。

進捗（ツール呼び出し・ストリーミング）は標準エラー出力、最終回答は標準出力へ出力します。

### 探索が打ち切られた場合のフォールバック

エージェント1（探索）は `maxIterations`（14）以内に `submit_findings` を呼べないと、その回のexplorer実行は結果を確定せずに打ち切られます。この場合、`findings` は空リスト（`relevantFiles: []`）＋その時点の出力テキストのみの簡易版にフォールバックし、エージェント2（回答）に渡されます。標準エラー出力に `[explorer] submit_findings was not called; falling back to output text.` と出るので、回答の根拠が薄い場合はこのログを確認してください。エージェント2は渡された情報が乏しくても自力でファイルを探して回答を試みますが、探索の網羅性は本来より落ちます。

### ツールの単体テスト（APIキー不要）

`lib/repo-tools.mjs` の検索ロジック（grep / read_file / list_files）は実際のリポジトリに対するスモークテストで検証できます。

```powershell
npm test --prefix tools\cline-wrapper
```

## 関連ファイル

コードの編集・作成・デバッグ時は必ず以下のファイルを参照してください。

- `.cline\skills\cline-sdk-docs\`
  - Cline SDK のドキュメントを Markdown 形式でまとめたものです。
- [NEXT.md](NEXT.md) — 今後の機能追加アイデア。
- [REFACTOR.md](REFACTOR.md) — リファクタ候補。
