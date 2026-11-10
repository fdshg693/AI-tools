# todo_runner — todo.json / NEXT.md 駆動の自律実行ループ

エージェントの記憶を「システムプロンプト + 目標 + NEXT.md + todo.json 等の実ファイル」だけに限定し、TODO が全完了するまで **1 呼び出し = 1 タスク** で新規セッションを繰り返す。`resume` / `continue_conversation` は使わない。セットアップは親の [`../AGENTS.md`](../AGENTS.md) を参照。

`--model` は [`../util/models.json`](../util/models.json) のカタログ id。省略時はカタログの `default`。分割・detail モードが要る変種は [`../todo_detail_runner/AGENTS.md`](../todo_detail_runner/AGENTS.md)。

## ファイル

- `todo_runner.py` — エントリ。システムプロンプト、TODO 検査、エージェント呼び出し、停滞検出がすべてここ
- `todo.json.example` — `{"tasks": [{"id", "title", "status"}]}` の見本。実行時の実体は `--workdir` 側（gitignore 対象）

作業ディレクトリに実行中生成されるもの:

- `todo.json` — エージェントが作成・更新する。status は `pending` / `in_progress` / `done`
- `NEXT.md` — 1 タスク完了時の引継ぎ。次イテレーション開始時にアプリが読んで空にする

## 仕組み

1. エージェントは目標をタスク分割して `todo.json` を作成する。
2. 1 回の呼び出しでは未完了のうち **id 最小の 1 件**だけを完了させ、`NEXT.md` に引継ぎを書いて終了する。
3. アプリは終了ごとに `todo.json` を検査し、全 `done` でなければ `query()` の新規セッションで再呼び出しする。
4. 全タスク `done` で exit 0。完了数が増えない連続回数が `--max-stagnant`、呼び出し回数が `--max-iterations` を超えたら中断。

Haiku は `cwd` を絶対パスへ解決できず `/work/...` へ迷走することがある。対策として、プロンプト双方に作業ディレクトリの絶対パスを埋め、「`/` 始まり・相対パス禁止」と明示している。

### Haiku での実測（2026-07-19）

4 タスクの俳句作成目標を 4 イテレーション（各 8〜11 ターン、計約 $0.18）で完走。迷走対策を入れる前は、作業ディレクトリ外へ書き込んで「完了」と誤報することがあった。

## 実行

```powershell
cd tools\claude-wrapper
python todo_runner\todo_runner.py "達成したい目標" --workdir <作業ディレクトリ> --model haiku
```

主なオプション: `--max-iterations`（既定 20）、`--max-turns`（既定 15）、`--max-stagnant`（既定 3）。`--workdir` 既定は `./todo_workspace`。`--model` はカタログ id（[`../util/AGENTS.md`](../util/AGENTS.md)）。PowerShell では `sonnet[1m]` のような括弧付き id を `"sonnet[1m]"` と引用すること。
