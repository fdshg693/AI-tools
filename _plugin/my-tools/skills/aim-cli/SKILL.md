---
name: aim-cli
description: OpenRouter経由でAIモデルを単発呼び出しする`aim` CLIツールの使い方を説明する。プロンプトをAIモデルに投げて応答を得たい、プロンプト内の`@path`でファイルやディレクトリの内容を取り込みたい、複数ファイルやスキルフォルダへ同じ質問（要約・バグ指摘など）を`--parallel`で一括したい、利用可能なモデル一覧を確認したい、タスクの難易度に応じてどのモデルを使うか選定したい場合に使う。
# 前提条件: `aim`コマンドがPATH上にインストール済み（`uv tool install --editable tools/aim`）であり、OPENROUTER_API_KEYが設定済みであること。このスキルはインストール・セットアップは一切行わない
# このスキルの設計意図・前提条件の背景は同階層のREADME.md参照（人間のメンテナ向け）
meta:
  tag: []
  requires_repo_tools: aim
  requires_env: OPENROUTER_API_KEY
  dependencies: none
  requires_install: uv tool install --editable tools/aim
  requires_hooks: none
  requires_skills: none
  status: stable
  description: no description
  version: 1.0.9
---

# aim CLI の使い方

`aim`はエージェント機能を持たない、AIモデルへの単発呼び出し専用CLI。system プロンプトやマルチターンは扱わない。`--format`未指定かつ`--parallel`なしのときは、ユーザーメッセージ1件を投げて応答テキストのみを標準出力に返す。`--parallel`や`--format`指定時はプロンプトごとの応答を対応付きで返す。

## エントリポイント: `aim` コマンド

使い方・利用可能なモデル・各モデルの説明・`@path`/`--parallel`の正本は `aim --ai-help`。人間向けは `aim --help`。オプション表やモデル表はこのスキルに転記しない。呼び出す前に次を実行して読む。

```!
aim --ai-help
```

## ファイル取り込みと並列

位置引数でパスを並べる書き方は無い。`--parallel`と`@path`は独立した機能。

- `--parallel`なし: `--prompt`は1件。全`@path`をその場に展開して**1回**呼び出す。複数ファイルの突き合わせ・差分向き
- `--parallel`あり: `--prompt`を複数渡すと各プロンプトが1ジョブ。`@path`は各プロンプト内でファイル内容に展開するだけ（ジョブの区切りではない）。失敗はプロンプト単位で記録し、他ジョブは継続する
- ディレクトリ`@path`で一部ファイルだけ本文が欲しいときは`--full-content-names`

```bash
aim --prompt "@src/foo.py を要約して"
aim --prompt "@a.py と @b.py の差分を説明して"
aim --parallel --prompt "@a.py 要約して" "@b.py 要約して"
aim --parallel --format json --prompt "@a.py 要約して" --prompt "@b.py 要約して"
```

## 前提条件

- `aim`コマンドが既にインストールされ、PATH上で実行可能であること
- `OPENROUTER_API_KEY`が環境変数または`tools/aim/.env`で設定済みであること
- 未インストール・未設定の場合はこのスキルでは対処しない。エラーが出た場合はユーザーに`tools/aim/README.md`のセットアップ手順を案内する

モデルの入力・出力単価を見てから選びたいときは`aim --cost`（`--model`で略記。省略時はデフォルト）。`pricing`のベース値と`overrides`の最大値（最悪ケース）を`$/M tokens`で出す。`:free`は0。Models APIは認証不要なのでAPIキーは要らない。

## ログ

呼び出しごとに`tools/aim/logs/<trace.tool>/<YYYY-MM-DD>.jsonl`（JSON Lines）へ1行追記される。`trace.tool`（`aim-cli`等。無ければ`unknown`）でフォルダ分けし、日付でファイル分割することで1ファイルへの際限ない肥大化を防いでいる。CLIのソースディレクトリ基準の絶対パスを使うため、実行時のカレントディレクトリには依存しない。`cost`・`*_tokens`・`generation_id`はOpenRouterレスポンスの`usage`/`id`フィールドからそのまま転記される。応答本文（completion）はログに含めない。`--parallel`の各ジョブも`trace.tool`は`aim-cli`のまま、`prompt_index`を付与する（`@path`があれば先頭を`file_path`にも付ける）。

各呼び出しには`trace.trace_id`（32桁hexのOTel準拠trace id）が自動付与される。OpenRouterのGrafana Cloud連携（Broadcast機能、任意設定）を有効化している場合、このtrace_idがGrafana Cloud側のTrace IDと一致するため、ログの`trace.trace_id`をGrafana CloudのTempoで検索すれば対応するトレースを特定できる（詳細は`tools/aim/README.md`の「Grafana Cloudへのログ配信」参照）。

## エラー時の挙動

APIキー未設定・モデルID誤り・OpenRouter側エラー（401/402/429など）が発生した場合、エラーメッセージを標準エラー出力に表示し、非ゼロで終了する。`--parallel`時の個別プロンプト失敗は全体を止めず、そのプロンプトの結果として記録される。
