# todo_detail_runner — detail モード付き TODO 駆動ループ

[`../todo_runner/AGENTS.md`](../todo_runner/AGENTS.md) と同じ「1 呼び出し = 1 タスク、終了ごとに新規セッション」だが、各タスクに `detail` を持ち、エージェントが必要なら TODO を詳細化できる。セットアップは親の [`../AGENTS.md`](../AGENTS.md) を参照。

`todo.json` はアプリが所有する。エージェントには今回の 1 アイテムだけを JSON で渡し、結果は `RESULT.json`（`complete` / `split` / 初回のみ `plan`）で受け取る。`todo.json` への Read/Write/Edit は PreToolUse フックで拒否する。分割時もアプリが当該アイテムだけを差し替え、id / status はアプリが振る。各タスクの `model` は [`../util/models.json`](../util/models.json) のカタログ id のみ。plan / split 時はカタログ（id + 評価）をエージェントへ渡し、返ってきた id を検証してから todo.json に書く。

パッケージ化せず、同じフォルダのモジュールを `import todo_state` のように読む。共有カタログは `_paths.py` で親を `sys.path` に入れてから `from util.models import ...`。

## ファイル

- `todo_detail_runner.py` — ループと CLI。テスト公開面もここから re-export
- `todo_state.py` — todo.json の読み書きと complete / split / plan の差し替え
- `result.py` — RESULT.json の契約解釈と NEXT.md / RESULT.json の読み書き
- `prompts.py` — システムプロンプトと 1 件（または初回 plan）向けプロンプト
- `agent.py` — PreToolUse フックと SDK の 1 回実行
- `_paths.py` — `claude-wrapper` ルートを `sys.path` に入れ、`util` を import 可能にする
- `constants.py` — `todo.json` / `NEXT.md` / `RESULT.json` のファイル名定数
- `todo.json.example` — `detail` / `model` 付きスキーマ見本。実行時の実体は `--workdir` 側（gitignore 対象）
- `test_todo_detail_runner.py` — 差し替え・RESULT 契約の単体テスト（SDK 不要）

作業ディレクトリに実行中生成されるもの:

- `todo.json` — アプリだけが書く。エージェントは触らない
- `NEXT.md` — 引継ぎ。次イテレーション開始時にアプリが読んで空にする
- `RESULT.json` — エージェントが書く。適用後にアプリが消す

## `detail` の 3 モード

| 値    | JSON                            | エージェントの動作                                                                    |
| ----- | ------------------------------- | ------------------------------------------------------------------------------------- |
| false | boolean `false`（省略時もこれ） | 作業して `{"action": "complete"}`。分割禁止                                           |
| true  | boolean `true`                  | 作業せず `{"action": "split", "tasks": [...]}`。アプリが当該 1 件を子タスクへ差し替え |
| auto  | 文字列 `"auto"`                 | complete か split を一方だけ。両方は拒否                                              |

分割時の書き換え規則（アプリ側）: 対象 1 件をリストから外し、同じ位置に 2 件以上の子タスクを挿入する。新しい id は既存最大値 + 1 から振る。他タスクは触らない。エージェントが付けた id / status は捨てる。`model` はカタログ id なら残し、省略時は親タスク（plan では `--model`）を入れる。分割も「前進」とみなし停滞検出の対象。

## タスクごとの `model`

各タスクは任意で `model` を持てる。値は [`../util/models.json`](../util/models.json) の `id` だけ。SDK の `ClaudeAgentOptions.model` にそのまま渡り、CLI の `--model` と同じエイリアスとして解決される。カタログのフィールド・許可 id・編集方法は [`../util/AGENTS.md`](../util/AGENTS.md)。

| 場面                        | 使うモデル                                         |
| --------------------------- | -------------------------------------------------- |
| タスクに `model` がある     | その id                                            |
| タスクに `model` がない     | CLI `--model`（カタログの `default: true` が既定） |
| split の子が `model` を省略 | 親タスクの model                                   |
| plan の子が `model` を省略  | CLI `--model`                                      |
| カタログに無い id           | 起動時 / RESULT 適用時に拒否                       |

## 実行

```powershell
cd tools\claude-wrapper
python todo_detail_runner\todo_detail_runner.py "達成したい目標" --model haiku
```

`--workdir` は CWD 基準（既定 `./todo_detail_workspace`）。オプションは `todo_runner` と同じ（`--max-iterations` 20、`--max-turns` 15、`--max-stagnant` 3）。`--model` はカタログ id。PowerShell では `sonnet[1m]` のような括弧付き id を `"sonnet[1m]"` と引用すること。

スキーマ判定の単体テスト:

```powershell
cd tools\claude-wrapper\todo_detail_runner
python -m unittest test_todo_detail_runner
```

カタログ本体のテストは [`../util/AGENTS.md`](../util/AGENTS.md)。
