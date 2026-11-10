# schedule — 設定ファイル駆動のWindowsタスクスケジューラ同期CLI

設定ファイル(YAML)に登録済みPowerShellスクリプトの定期実行内容を宣言し、`ai-schedule sync` を実行すると
Windowsタスクスケジューラの状態がその内容に一致するよう同期される(作成・更新・削除)。

- ジョブの有効/無効・スケジュール変更は設定ファイル(`config/jobs.yaml`)の編集のみで行う。
- 実際にタスクスケジューラへ反映するには、編集後に `ai-schedule sync` を実行する。
- 設定ファイルが唯一の正(source of truth): `enabled: false` にしたジョブ、または設定ファイルから
  削除したジョブは、次回 `sync` 実行時にタスクスケジューラからも削除される。
- タスクは Windows タスクスケジューラの `\AI-Schedule\<job名>` フォルダ配下にまとめて登録される
  (このフォルダ配下だけを対象に同期するため、他のツールが登録したタスクには影響しない)。
- 内部実装は `schtasks.exe` を `subprocess` 経由で呼び出すだけで、pywin32等の追加依存は使わない。

## セットアップ

リポジトリルートで `uv sync` 済みであること(ルートの `pyproject.toml` のworkspace memberとして本パッケージが含まれる)。

```bash
cp tools/schedule/config/jobs.example.yaml tools/schedule/config/jobs.yaml
# config/jobs.yaml を編集(登録したいPowerShellスクリプトとスケジュールを記述)
```

## 使い方

CLIは[Typer](https://typer.tiangolo.com/)製。

```bash
# コマンド一覧・ヘルプを表示
uv run ai-schedule --help
uv run ai-schedule help

# 設定ファイルの内容にタスクスケジューラを同期する(作成/更新/削除)
uv run ai-schedule sync tools/schedule/config/jobs.yaml

# 実際には変更せず、実行予定の操作だけ確認する
uv run ai-schedule sync tools/schedule/config/jobs.yaml --dry-run

# 設定ファイルのジョブ一覧と、タスクスケジューラへの現在の登録状況を表示する
uv run ai-schedule list tools/schedule/config/jobs.yaml
```

グローバルCLIとして使う場合は `uv tool install --editable tools/schedule` でエディタブルインストールする。

`sync` はWindows標準の `schtasks.exe` を呼び出すため、対象スクリプトを実行できる権限を持つユーザーで
実行すること(管理者権限のスクリプトを登録する場合は管理者権限のシェルから `sync` を実行する)。

## 設定ファイル(`config/jobs.yaml`)のフォーマット

```yaml
jobs:
  - name: example-daily-job # タスク名(パス区切り文字不可、jobs内で一意)
    enabled: true # false にすると sync 実行時にタスクスケジューラから削除される
    script: C:\path\to\script.ps1 # 実行するPowerShellスクリプトの絶対パス
    args: ["-Foo", "bar"] # スクリプトへの引数(省略可)
    schedule:
      type: daily # daily | weekly | interval
      time: "09:00" # daily/weekly で必須(HH:MM, 24時間制)

  - name: example-weekly-job
    script: C:\path\to\weekly-script.ps1
    schedule:
      type: weekly
      time: "22:30"
      days: [MON, WED, FRI] # weekly で必須

  - name: example-interval-job
    script: C:\path\to\interval-script.ps1
    schedule:
      type: interval
      minutes: 30 # interval で必須(N分ごとに実行)
```

`schedule.type` ごとの必須/禁止フィールドは `ai_schedule/config.py` の `JobSchedule` でバリデーションされる
(例: `daily` に `minutes` を指定するとエラー)。

## ファイル構成

```
tools/schedule/
├── README.md                  # 概要(ローカル/クラウドでの定期実行方針)
├── AGENTS.md / CLAUDE.md        # 本ファイル
├── pyproject.toml                 # パッケージ定義 + console script (ai-schedule)
├── config/
│   ├── jobs.example.yaml            # 設定ファイルのサンプル(コピーして使う)
│   └── jobs.yaml                     # 実際の設定ファイル(gitignore対象)
├── ai_schedule/
│   ├── __init__.py
│   ├── config.py                       # 設定YAMLの読み込み・バリデーション(pydantic)
│   ├── windows_task.py                  # schtasks.exe とのやり取り(作成/更新/削除/一覧取得)
│   └── cli.py                            # CLIエントリポイント(Typer製。sync/list/help)
└── tests/
    ├── test_config.py
    └── test_windows_task.py               # subprocess.run をmonkeypatchしてschtasks呼び出しを検証
```
