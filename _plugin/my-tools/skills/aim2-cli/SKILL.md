---
name: aim2-cli
description: 複数プロバイダ（OpenAI, Anthropic, Google Gemini, OpenRouter, Ollama等）に直接対応したAIモデルCLIツール`aim2`の使い方を説明する。プロンプトをAIモデルに投げて応答を得たい、`--session-id`（互換`--thread-id`）でローカル会話継続したい、プロンプト内の`@path`でファイルやディレクトリの内容を取り込みたい、複数プロンプトを`--parallel`で一括並列実行したい、利用可能なモデル一覧を確認したい場合に使う。
# 前提条件: `aim2`コマンドがPATH上にインストール済み（`cd tools/aim2 && pnpm add -g .`）であり、利用するプロバイダのAPIキーまたはOllamaが設定済みであること。このスキルはインストール・セットアップは一切行わない
# このスキルの設計意図・前提条件の背景は同階層のREADME.md参照（人間のメンテナ向け）
meta:
  tag: []
  requires_repo_tools: tools/aim2
  requires_env: none
  dependencies: none
  requires_install: cd tools/aim2 && pnpm add -g .
  requires_hooks: none
  requires_skills: none
  status: stable
  description: 複数プロバイダ対応 AI モデル単発呼び出し CLI ツールの使い方
  version: 1.0.3
---

# aim2 CLI の使い方

`aim2`はエージェント機能を持たない軽量CLI。複数プロバイダ（OpenAI, Anthropic, Google Gemini, OpenRouter, Ollama）に直接接続し、system プロンプトは扱わない。既定では user prompt 1件を投げて応答本文を返すが、`--session-id`（互換エイリアス: `--thread-id`）を指定するとローカルログから過去の user/assistant ターンを再送して継続できる。`--format`未指定かつ`--parallel`なしのときは応答テキストのみを標準出力に返し、`--parallel`や`--format`指定時はプロンプトごとの応答を対応付きで返す。

## エントリポイント: `aim2` コマンド

使い方・利用可能なモデル・各モデルの説明・`@path`/`--parallel`の正本は `aim2 --ai-help`。人間向けは `aim2 --help`。オプション表やモデル表はこのスキルに転記しない。呼び出す前に次を実行して確認する。

```!
aim2 --ai-help
```

## ファイル取り込みと並列

位置引数でパスを並べる書き方は無い。`--parallel`と`@path`は独立した機能。

- `--parallel`なし: `--prompt`は1件。全`@path`をその場に展開して**1回**呼び出す。複数ファイルの突き合わせ・差分向き
- `--parallel`あり: `--prompt`を複数渡すと各プロンプトが1ジョブ。`@path`は各プロンプト内でファイル内容に展開するだけ（ジョブの区切りではない）。失敗はプロンプト単位で記録し、他ジョブは継続する。各ジョブには別の`session_id`が自動発行され、標準エラーに`session_id[1]: ...`形式で表示される
- ディレクトリ`@path`で一部ファイルだけ本文が欲しいときは`--full-content-names`

```bash
aim2 --prompt "@src/cli.ts を要約して"
aim2 --prompt "@a.py と @b.py の差分を説明して"
aim2 --session-id feature-abc --prompt "前回の続きで要点だけまとめて"
aim2 --parallel --prompt "@a.py 要約して" "@b.py 要約して"
aim2 --parallel --format json --prompt "@a.py 要約して" --prompt "@b.py 要約して"
```

## 会話継続（`--session-id`）

- `--session-id` を省略してプロンプト実行すると、時刻情報を含む固定長のローカル継続 ID が自動発行され、`session_id: ...` が標準エラーへ表示される
- 同じ `session_id` を次回指定すると、`tools/aim2/logs/` から過去の成功ターンを再読込して user/assistant 履歴として送る
- `--thread-id` は `--session-id` の互換エイリアス。両方を同時に指定できない
- `--parallel` と `--session-id`/`--thread-id` は併用できない。並列ジョブを1本の会話へ混在させないため、ジョブごとに別IDを使う
- `session_id` は会話単位、`batch_id` は並列実行単位、`trace.trace_id` はモデル呼び出し単位の相関 ID である
- 継続履歴は自動要約しないため、長いスレッドはコンテキスト上限に達し得る
- 同じ `session_id` を複数プロセスから同時に使うと履歴が分岐し得る

## 前提条件

- `aim2`コマンドが既にインストールされ、PATH上で実行可能であること
- 利用対象のプロバイダに必要なAPIキー（`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `OPENROUTER_API_KEY`等）が環境変数または`tools/aim2/.env`で設定済みであること（Ollamaローカル実行の場合はAPIキー不要）
- 未インストール・未設定の場合はこのスキルでは対処しない。エラーが出た場合はユーザーに`tools/aim2/README.md`のセットアップ手順を案内する

モデルの入力・出力単価を見てから選びたいときは`aim2 --cost`（`--model`で略記。省略時はデフォルト。OpenRouter, Ollamaに対応）。

## ログ

新規の成功ログは`tools/aim2/logs/<trace_tool>/<YYYY-MM-DD>/<session-id>.jsonl`（JSON Lines）へ1行追記される。`trace_tool`（デフォルト: `aim2-cli`）と日付で分け、さらにセッション単位でファイルを分離する。CLIのソースディレクトリ基準の絶対パスを使うため、実行時のカレントディレクトリには依存しない。

- ログには `prompt` に加えて `response`、`session_id`、`batch_id`（`--parallel` のバッチ単位）、`trace.trace_id` が保存される
- 継続時の履歴抽出は新規セッションファイルを優先し、日付・`trace_tool` を横断して再読込する
- 旧フラット日次ログと未コミット版の `thread_id` レコードは読み取り互換として残る。応答がない旧レコードは履歴へ採用しない
- 応答本文もローカルログへ残るため、プロンプト同様に機微情報の扱いへ注意する
- 各呼び出しにはOTel準拠の128bit `trace.trace_id` が自動付与されるが、これは `session_id` とは別物

## エラー時の挙動

APIキー未設定・モデルID誤り・プロバイダ側エラー（401/404/429/500等）が発生した場合、正規化されたエラーメッセージ（`AimError`）を標準エラー出力に表示し、非ゼロで終了する。`--parallel`時の個別プロンプト失敗は全体を止めず、そのプロンプトの結果として記録される。
