---
name: interactive-cli-wrapper
description: Drive an interactive (TTY-only, REPL-style) CLI process from an AI agent one Bash-tool call per turn — start it as a background session, send one line of input, wait for the turn to settle, get the accumulated output back. Use when a CLI has no non-interactive/print flag and must be operated as a live REPL (e.g. Cursor CLI's `agent` run without `-p`). Not for one-shot non-interactive delegation to Cursor CLI (use cursor-cli-use for `agent -p`) and not for CLIs that already support a scriptable non-interactive mode.
allowed-tools: Bash(icw *), Bash(agent *)
disable-model-invocation: true
# 前提条件: `icw`コマンドがPATH上にインストール済み（`uv tool install --editable tools/interactive-cli-wrapper`）であること。
# このスキルはインストール・セットアップは一切行わない。実体は tools/interactive-cli-wrapper/ を参照。
# disable-model-invocation: 対話CLI(特にagentのような課金・副作用のあるエージェントCLI)を
# バックグラウンドセッションとして起動・駆動する副作用があるため、cursor-cli-useと同様に
# ユーザーの明示呼び出し（/interactive-cli-wrapper）に限定する
# このスキルの意図・スコープは同階層のREADME.md参照（人間のメンテナ向け）
meta:
  tag: []
  requires_repo_tools: icw
  requires_env: none
  dependencies: pywinpty, pyte
  requires_install: uv tool install --editable tools/interactive-cli-wrapper
  requires_hooks: none
  requires_skills: none
  status: stable
  description: no description
  version: 1.1.2
---

# interactive-cli-wrapper (`icw`) の使い方

`icw`は、TTY前提でREPLとして動く対話的CLI(非対話フラグを持たない、または非対話フラグでは目的を果たせないCLI)を、AIエージェントの「1アクション=1回のBashツール呼び出し」の制約の中で駆動するための**汎用**ラッパー。特定のCLIに依存しない。PTY(ConPTY)越しに対象CLIを起動し、`write → そのターンが落ち着くまで待つ → 蓄積出力を返す`を1回のCLI呼び出しに凝縮する。

## いつ使うか

- 対象CLIに`-p`/`--print`のような非対話実行フラグが**無い**、またはあっても目的(対話履歴を保った複数ターンのやり取り、スラッシュコマンド操作等)を果たせない場合。
- 逆に、対象CLIが非対話フラグを持ち単発の一撃実行で済むなら、このスキルは使わない。Cursor CLI(`agent`)の単発委譲は**cursor-cli-use**スキル(`agent -p --force ...`)を使う。両者の使い分けは下記「cursor-cli-useとの使い分け」参照。

## 基本の使い方: `start` → `send`(繰り返し) → `stop`

対象コマンドをバックグラウンドデーモンとして起動し、以後は`--session`名で指定して1ターンずつやり取りする。プロセスハンドルを呼び出し間で保持する必要はない(デーモン側が保持する)。

```bash
# セッション起動。最初のプロンプトまでの出力(バナー等)を返す
icw start --session <name> [--idle-timeout <秒>] [--overall-timeout <秒>] [--ready-pattern '<正規表現>'] -- <対象コマンド...>

# 1行入力を書き込み、ターンが落ち着くまで待って、蓄積出力を返す(1呼び出し=1ターン)
icw send --session <name> [--idle-timeout <秒>] [--overall-timeout <秒>] [--ready-pattern '<正規表現>'] "<入力テキスト>"

# セッション一覧(生死判定込み)
icw list

# セッションを終了する
icw stop --session <name>
```

- `--`より前が`icw start`自身のオプション、後ろが対象コマンドの`argv`(対象コマンド側のオプションと衝突しないよう手動split)。
- 対象コマンドは**シェルが解決するコマンド名ではなく実行ファイルの実体**を渡すのが安全(bashラッパー越しだと対象が`stdin is not a tty`になることがある)。

## `ready`判定の仕組み(idle-timeoutが基礎、ready-patternは任意の上乗せ)

`send`/`start`の戻り値には`ready`/`alive`/`matched_pattern`/`elapsed_seconds`が含まれる(`icw`の標準エラー出力に1行で要約される)。

- **idle-timeout**(一定時間新規出力が無ければ「入力待ちに戻った」とみなす)が必須の基礎ロジック。対象CLIの出力が途中で途切れがちなら長めに設定する。
- **ready-pattern**(正規表現、現在画面をnewline結合した文字列に対して`search`)は任意の上乗せで、マッチすればidle-timeoutを待ち切る前に短絡して返る。**対象CLI固有のUI文字列に依存するため、CLIごとに実地検証してから使うこと**(入力欄の固定プレースホルダ文字列のような「生成完了」を意味しない文字列を安易に`ready_pattern`にすると、生成中に誤って`ready=True`を返すことがある — 詳細は[cursor-agent.md](cursor-agent.md)の実例参照)。
- `ready=False`で返ってきた場合(`overall_timeout`到達)は、呼び出し側が同じ`--session`に対して(空文字列や無害な入力で)再度`send`し、待ち直す運用にする。

## 送信方式のチューニング(`--submit-separately`)

一部の対話CLI(特に生キー入力を自前処理するTUI)は、入力テキストと改行を1回の書き込みにまとめて送ると「複数行の貼り付け」とみなし、Enterとして扱わないことがある。`icw send --submit-separately`は、テキストと送信キー(既定`--submit-key`はCRのみ)を**別々の`write()`呼び出し**として`--submit-delay`秒(既定0.3秒)空けて送る。対象CLIで`send`が反応しない(入力欄にテキストが残ったまま無反応になる)場合はまずこのオプションを試す。

## 対象CLIごとの既知の癖

対象CLIごとの実地検証で判明した個別の癖・チューニング値は、CLIごとに別ファイルへ切り出す(このファイルは汎用の使い方だけに留める)。

- **Cursor CLI(`agent`対話モード)** — [cursor-agent.md](cursor-agent.md)。起動直後の初期化グレース期間、`--submit-separately`が必須になる理由、確実な`ready_pattern`が無いこと、具体的なコマンド例を記載。

他の対象CLIを繋いだ場合も、同様に`<cli-name>.md`として知見を追記していく。

## セッションが死んでいた場合の挙動

`send`/`stop`/`list`はメタデータファイルが見つかった後に必ず実接続を試み、失敗すれば「デーモンがクラッシュ/強制終了して死んでいる」とみなしてメタデータを削除してからエラーを返す(または`list`ならそのセッションを一覧から除いて片付ける)。`send`が非ゼロ終了した場合、対象セッションはもう存在しない可能性があるので、まず`icw list`で生死を確認してから`icw start`でセッションを取り直す。
