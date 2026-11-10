# ona-run — リポジトリ+タスク指定でOnaにAIエージェント作業を委任するCLI

**関連スキル: `claude-plugins/my-tools/skills/ona-run`**

「リポジトリURL（またはOnaプロジェクトID）」と「タスク内容（自然文プロンプト）」を指定すると、Onaの環境（コンテナ）を作成/起動し、その中でタスク（既定はAIエージェントCLIのheadless実行）を実行し、完了後に環境を停止する。Ona公式CLI（`ona environment create`/`get`/`exec`/`stop`/`delete`）をsubprocessでラップするだけで、Connect-RPC APIの再実装はしない。

## 前提条件

- Ona公式CLI（`ona`）がインストール済み、かつ`ona login`で認証済みであること
- コンテナ内でAIエージェントを動かす場合（`--agent claude`/`--agent codex`）、対象リポジトリのDev Container側にそのCLIが導入済みであること（このツールはその導入までは面倒を見ない）

## インストール

グローバルCLIとして使う場合は `uv tool install --editable`（`pip install -e` の代替）でエディタブルインストールする。リポジトリルートから実行可能。

```bash
uv tool install --editable tools/ona-run
```

インストール後は `ona-run` コマンドが PATH 上でどこからでも使える。

## 使い方

```bash
# --agent: 簡易テンプレート（claude/codex のheadless実行コマンドを組み立てる）
ona-run https://github.com/example/repo "READMEのtypoを直してPRを作って" --agent claude

# タスクは省略時、標準入力から読み込む
echo "READMEのtypoを直してPRを作って" | ona-run https://github.com/example/repo --agent claude

# --command: コンテナ内で実行する完全なコマンドをargvのトークン列として指定する
# （{task}はタスク文字列に置換される。他のオプションより後ろ・末尾に置くこと）
ona-run https://github.com/example/repo "タスク内容" --cleanup delete \
  --command claude -p "{task}" --dangerously-skip-permissions

# クリーンアップをdelete（環境ごと削除）にする
ona-run https://github.com/example/repo "タスク内容" --agent codex --cleanup delete
```

### オプション

| オプション        | 必須 | 説明                                                                                                                                                                                          |
| ----------------- | ---- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `repo_or_project` | ○    | 位置引数。リポジトリURL、またはOnaプロジェクトID                                                                                                                                              |
| `task`            | △    | 位置引数。タスク内容（自然文プロンプト）。省略時は標準入力から読み込む（`--agent`/`--command`のテンプレートが`{task}`を使わない場合は不要）                                                   |
| `--agent`         | △    | `claude`/`codex`。コンテナ内実行コマンドの簡易テンプレート（`--command`と同時指定不可、どちらか一方が必須）                                                                                   |
| `--command`       | △    | コンテナ内で実行する完全なコマンド（argvのトークン列）。`--agent`と同時指定不可、どちらか一方が必須。以降の全トークンをそのままコマンドとして扱うため、他のオプションより後ろ・末尾に置くこと |
| `--cleanup`       | -    | `stop`/`delete`/`keep`。タスク終了後の環境の扱い（既定: `stop`）                                                                                                                              |
| `--class-id`      | -    | 環境クラスID（省略時はまずクラス指定なしで作成を試み、失敗時のみ`ona environment list-classes`で解決した既定クラスで自動リトライ）                                                            |
| `--start-timeout` | -    | 環境がRUNNINGになるまでの待機タイムアウト秒（既定: 300）                                                                                                                                      |
| `--task-timeout`  | -    | タスク実行（`ona environment exec`）のタイムアウト秒（既定: 1800）                                                                                                                            |

### `--agent`テンプレートの中身

| `--agent` | 組み立てるコマンド                                               |
| --------- | ---------------------------------------------------------------- |
| `claude`  | `claude -p "<task>" --dangerously-skip-permissions`              |
| `codex`   | `codex exec --dangerously-bypass-approvals-and-sandbox "<task>"` |

いずれも「Onaのコンテナ自体が外部サンドボックスである」ことを前提に、確認プロンプトなしで自律実行するフラグを付けている。対象CLIのバージョンによってフラグが変わりうるため、`--command`で独自のコマンドに差し替えられるようにしてある。

## 終了コード・エラー時の挙動

`--command`で渡す任意のコマンドは0〜255のどの終了コードでも返しうるため、終了コード単体では「タスク失敗」と「Ona側インフラ失敗（環境作成・起動待ちの失敗）」を100%区別できない。呼び出し元が確実に判別したい場合は、標準エラー出力に必ず出力される`ona-run: status=...`の1行を一次情報として使う。

| 状況                                   | 終了コード                   | stderrマーカー                |
| -------------------------------------- | ---------------------------- | ----------------------------- |
| 環境作成・起動待ち自体が失敗           | 固定`64`                     | `ona-run: status=infra_error` |
| タスク（`ona environment exec`）が失敗 | タスクの終了コードをそのまま | `ona-run: status=task_failed` |
| 成功                                   | `0`                          | `ona-run: status=success`     |

クリーンアップ（`stop`/`delete`）自体の失敗は警告をstderrに出すのみで、上記の戻り値は上書きしない（クリーンアップ失敗によってタスク成功が握りつぶされるのを防ぐため）。

## ログ

実行ごとに `tools/ona-run/logs/runs.jsonl`（JSON Lines）へ1行追記される。CLIのソースディレクトリ基準の絶対パスを使うため、実行時のカレントディレクトリには依存しない。

```json
{
  "timestamp": "2026-08-12T22:22:34+09:00",
  "env_id": "env_abc123",
  "repo": "https://github.com/example/repo",
  "agent": "claude",
  "exit_code": 0,
  "duration_seconds": 128.4
}
```

- タスク本文・stdout/stderrは含めない
- `repo`にトークン付きURL（`https://<token>@github.com/...`等）を渡した場合、そのトークンを含む文字列がログに平文で残る点に注意
- `logs/runs.jsonl` はプロンプト由来の情報を含み得るため Git管理対象外（`.gitignore` 参照）。ディレクトリ自体は `.gitkeep` で追跡

## ファイル構成

```
tools/ona-run/
├── README.md            # 本ファイル
├── AGENTS.md / CLAUDE.md  # 参照チェーン（中身は本ファイルへのリンクのみ）
├── pyproject.toml          # パッケージ定義 + console script (ona-run)
├── ona_run_cli.py           # CLI本体
├── .gitignore
├── logs/
│   ├── .gitkeep
│   └── runs.jsonl          # gitignore対象
└── tests/
    └── test_command_building.py  # argv組み立てロジックのユニットテスト
```
