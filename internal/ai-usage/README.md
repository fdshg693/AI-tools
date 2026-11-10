# ai-usage — AIコーディングツールの使用量をターミナルで一覧表示

Claude Code / Codex の「5時間ウィンドウ」「週間ウィンドウ」相当のレート制限消費率(%)を、
1コマンドでターミナルに一覧表示するCLI。

## スコープ

- **Claude Code**: 対応。`statusLine`フック経由でのみ値が取れる(pull型のAPIが無いため)。
- **Codex**: 対応。`codex app-server`をJSON-RPCで都度呼び出すpull型。
- **Cursor**: `--cursor`オプトインで対応。`cursor-agent`にはpull型API・JSON出力とも無く、
  `/usage`は対話TUI内のスラッシュコマンドとしてしか存在しない。そのため実際に
  `cursor-agent --trust`をConPTY(`pywinpty`)上で起動し、`/usage`を打鍵→Enterした後の
  画面を仮想端末(`pyte`)で再生してテキストとして取得する。5h/週/月のウィンドウ消費率には
  分解できないリッチなUIの生画面なので、表形式には混ぜず`show`実行時の追加ブロックとして
  別出力する。実プロセス起動を伴うため数十秒かかり、既定では実行されない。詳細は
  `ai_usage_core/collectors/cursor.py`参照。
- **Cline**: 見送り。`/api/v1/users/{id}/usages`は個々のAPI呼び出し単位の生トークン消費履歴
  のみを返し、5h/週/月のウィンドウ消費率を含まないことを実地検証で確認した
  (詳細: `.claude/plans/ai-cost-usage-visualization/04-cline-collector-and-cli.md`)。
- **Antigravity**: 対象外。公式にスクリプトから読む手段が無い(非公開内部APIのハックは採用しない)。

## インストール

```bash
uv tool install --editable tools/internal/ai-usage
```

`ai-usage` コマンドがPATH上でどこからでも使えるようになる。

## Claude Codeの使用量を有効にする(統計線フックの登録)

Claude Codeにはレート制限をこちらから取得できるpull型APIが無いため、`statusLine`フックが
呼ばれた際にpushされてくる`rate_limits`の値をログファイル(`~/.ai-usage/claude-code-rate-limits.jsonl`)
に溜めておき、`ai-usage show`実行時にその最終行を読む。そのため、`~/.claude/settings.json`
(ユーザーのグローバル設定。プロジェクト単位ではなく、日常のClaude Code利用全体を拾うため)
に以下を登録しておく必要がある:

```json
{
  "statusLine": {
    "type": "command",
    "command": "python C:/CodeRoot/AI/tools/internal/ai-usage/statusline_hook.py"
  }
}
```

パスはこのリポジトリの実際の配置に合わせて調整すること(Windows/Git Bash環境ではフォワード
スラッシュ表記が必要)。登録後、次のClaude Codeとのやり取りで自動的に反映される。

表示されるのは最後にログが書かれた時点のスナップショットであり、ライブの値ではない
(セッションを常時起動しておく必要はない、という前提でユーザー確認済み)。

## 使い方

```bash
ai-usage show
```

各コレクタは個別にtry/exceptされており、1ツールが未導入・未認証でも他のツールの結果は
表示される(例: `codex`コマンドが無い環境では`codex`行が空欄になるだけ)。

Cursorの使用量も見たい場合は`--cursor`を付ける(`cursor-agent`を実際に起動して`/usage`を
実行するため数十秒かかる。既定では実行されない):

```bash
ai-usage show --cursor
```

`cursor-agent`が未インストール、または`pywinpty`/`pyte`が無い環境では
`(unavailable: ...)`とだけ表示され、他の行には影響しない。

## ファイル構成

```text
tools/internal/ai-usage/
├── README.md                          ← このファイル
├── pyproject.toml                      ← `ai-usage` コンソールコマンドのパッケージング
├── ai_usage_cli.py                      ← エントリポイント。argparse `show` サブコマンド
├── statusline_hook.py                    ← Claude Code `statusLine` フック本体
│                                            (ログ追記 + ステータスライン表示テキスト生成)
└── ai_usage_core/
    ├── config.py                          ← ログファイルパスなどの定数
    ├── rendering.py                        ← コレクタ結果 → ターミナル向けテーブル整形
    └── collectors/
        ├── claude_code.py                    ← ログファイルの最終行を読むコレクタ
        ├── codex.py                           ← `codex app-server` をJSON-RPCで叩くコレクタ
        └── cursor.py                          ← `cursor-agent`をConPTYで操作し`/usage`画面を
                                                    テキストとして取得するコレクタ(`--cursor`時のみ)
```

`claude_code`/`codex`コレクタは `{"tool": <name>, "windows": [{"name", "used_percent",
"resets_at"}, ...]}` という共通形式を返す(詳細は `ai_usage_core/collectors/__init__.py`)。
`cursor`コレクタのみ、この形式に載らない生テキストの画面スナップショット(`str | None`)を
返す。
