# interactive-cli-wrapper — 対話型CLI用PTY駆動コア(Python実装)

このディレクトリは、対話的(TTY前提でREPLとして動く)CLIプロセスを、AIエージェントから「入力を書き込む → そのターンの操作が落ち着くまで待つ → 出力を返す」という単位(1ターン)で駆動するための **PTY駆動コア** の実体です。特定CLIに依存させない汎用ラッパーとして設計しており、検証・実運用の題材はCursor CLI(`agent`コマンド)の対話モード([cursor-cli-use](../../cursor-plugins/meta/skills/cursor-cli-use/SKILL.md)スキルが非対話`-p`実行のみを対象とし、意図的に対象外としているREPL利用)です。

Step2でコアドライバ(`icw_core/session.py` / `icw_core/screen.py`)とトイ対話CLI(`toy_repl.py`)を用意し、Step3で「1アクション=1回のCLI呼び出し」で使えるセッション永続化つきコンソールコマンド `icw`(`start`/`send`/`stop`/`list`)を追加、Step4で実CLI(Cursor CLIの`agent`対話モード)への接続を実地検証しました。実CLI固有のチューニング内容は[カスタマイズ箇所](#カスタマイズ箇所)の下にある「`agent`対話モードへの接続で判明した癖」を参照してください。AIエージェント向けの使い方は[claude-plugins/my-tools/skills/interactive-cli-wrapper/SKILL.md](../../claude-plugins/my-tools/skills/interactive-cli-wrapper/SKILL.md)にまとめてあります。

## 前提条件

- Python 3.11+ / uv
- Windows(ConPTY)。`pywinpty`はWindows専用ライブラリで、他OS向けバックエンドは無い(このリポジトリ自体がWindows環境前提のため、この制約は許容している)。

## セットアップ

リポジトリルートの uv workspace メンバーなので、`uv sync`(リポジトリルートで実行)で共有devベンチへ依存(`pywinpty` / `pyte`)が解決され、`icw`コンソールコマンドも編集可能インストールされる。

```bash
uv run pytest tools/interactive-cli-wrapper
```

グローバルCLIとして使う場合は `uv tool install --editable tools/interactive-cli-wrapper` でエディタブルインストールする(他の `tools/` 配下のツールと同じ手順)。

## なぜPTY駆動が必要か

生の`subprocess`パイプや、Git Bash同梱の`winpty` CLI経由では対象の対話CLI(`agent`)を駆動できないことを、実装前の調査で確認済み。

- 対話モードのまま`stdin=/dev/null`、標準出力/エラーをファイルへリダイレクトして起動 → **出力0バイトのままタイムアウト**(非tty検出時にフルバッファリングされ、対話モードは何も返さないと推測される)
- Git Bash同梱の`winpty`経由で起動 → **`stdin is not a tty`**で失敗。`winpty`CLIは「winptyを呼び出したプロセス自身が対話端末に接続されている」ことを前提にしており、Bashツール等の非対話呼び出しからは使えない

このため、**呼び出し元プロセスのtty状態に依存せず、Python内で新規に疑似コンソール(ConPTY)を生成して子プロセスへ接続する**方式が必要と判断し、`pywinpty`(ConPTYを直接扱うPythonライブラリ)を採用した。実機検証では、`pywinpty`経由なら上記の`stdin is not a tty`エラーは発生せず正常にTUIが起動することを確認している。

## コアドライバの設計(`icw_core/`)

### `icw_core/screen.py` — 端末画面の再構成

対話TUIは同じ行をカーソル移動・再描画で更新することが多く、生バイト列への正規表現でのANSIエスケープ除去だけでは重複・破損したテキストになりうる。`TerminalScreen`は`pyte.Screen` + `pyte.Stream`で「現在の画面内容」をバッファとして再構成し、`snapshot()`で現在の非空白行のリストを返す。末尾の空行はスクリーンの未使用行にすぎないため`rstrip`する(=各行末尾の意図的な空白と未使用列のパディングは、スクリーンバッファ上は区別できない。テストで固定プロンプト文字列を照合する際は、この制約を踏まえて末尾空白を含めずに照合すること)。

### `icw_core/session.py` — 1ターンの往復

`InteractiveSession`が中核クラス。

- `write(text)` — 生テキストをそのまま書き込む(改行の正規化はしない)
- `send(text, *, idle_timeout, ready_pattern=None, overall_timeout=30.0, submit_separately=False, submit_key="\r", submit_delay=0.3)` — 既定(`submit_separately=False`)では`text`の末尾に`\r\n`が無ければ付与して1回の`write()`で書き込み、`wait_until_ready`を呼ぶ(=1ターン)。`submit_separately=True`にすると、`text`と`submit_key`(既定はCRのみ)を**別々の`write()`呼び出し**として`submit_delay`秒空けて送る(実CLI接続時に必要になった経緯は下記「`agent`対話モードへの接続で判明した癖」参照)
- `wait_until_ready(*, idle_timeout, ready_pattern=None, overall_timeout=30.0)` — 「入力待ちに戻ったこと」の検知ループ本体。**idle-timeout(一定時間新規出力が無ければ確定)を必須の基礎ロジックとし、`ready_pattern`(正規表現、現在画面をnewline結合した文字列に対して`search`)は任意の上乗せ**にしてある(idle-timeoutだけだと生成が遅いCLIで誤検知しうる一方、pattern はCLIのUIに依存し汎用性を損なうため。両対応にすることで、トイCLI検証はidle-timeoutのみで完結し、実CLI接続時はpattern追加で精度を上げられる)
- `close(*, force_after=2.0)` — Ctrl-C送信 → 猶予時間待機 → 生きていればforce-terminate

読み出しループは、`pywinpty`の`PtyProcess.read()`が内部でブロッキングする実装であるため、`proc.fileobj.settimeout(...)`でポーリング可能にする方式を採用(`blocking=False`のような引数はpywinptyに無い。Step1で確認済み)。タイムアウトによる`OSError`は「このポーリングでは新規データ無し」として継続扱いにし、`EOFError`はプロセス終了として扱う。

## トイ対話CLI(`toy_repl.py`)

コアドライバの検証専用の、起動が速く・出力タイミングを制御できるダミーREPL(実運用には使わない)。実CLI(`agent`)は起動・応答が遅く出力タイミングもぶれるため、コア機構(特に「入力待ちに戻ったことの検知」ヒューリスティック)は先にこのトイCLI相手で固める。

`--startup-delay` / `--chunk-delay` / `--chunks-per-turn` で、起動直後の遅延・1ターンあたりの出力チャンク数と各チャンク間の遅延を制御できる。1行入力を受け取るたびに`echo[N]: <入力>`をN行出力してから、固定のプロンプト文字列(`toy> `)を再表示する。

`[sys.executable, "-u", "<path to toy_repl.py>", ...]`という形でspawnする(シェルが解決するコマンド名ではなく、実行ファイルのフルパスを渡す。実CLI`agent`がbashラッパー越しだと`stdin is not a tty`になった教訓と同種の注意点。トイCLIの場合は`sys.executable`が最初から実体パスなので問題にならない)。`-u`は出力バッファリングを避けるため。

## セッション永続化つきCLI(`icw`)

AIエージェントは1アクション=1回のCLI呼び出し(Bashツール経由)になるため、プロセスハンドルを呼び出しの間で持ち続けることができない。そこで`start`は対象コマンドを**バックグラウンドデーモン**として起動し、以後の`send`/`stop`/`list`は標準ライブラリの`multiprocessing.connection`(Windows: named pipe / POSIX: unix socket)でそのデーモンに接続する。

```bash
# 対象コマンドを新規セッションとして起動し、最初のプロンプトまでの出力を返す
icw start --session mysession --ready-pattern 'toy>\s*$' -- python -u toy_repl.py

# 1行書き込み、ターンが落ち着くまで待って、蓄積出力を返す(1呼び出し=1ターン)
icw send --session mysession "hello"

# セッション一覧(生死判定込み)
icw list

# セッションを終了する
icw stop --session mysession
```

### 構成要素

- `icw_core/registry.py` — セッションメタデータ(`SessionMetadata`: 起動コマンド`argv`、IPCアドレス、認証キー、デーモンPID、起動時刻、最初の`wait_until_ready`結果)を、システムの一時ディレクトリ配下(`<tempdir>/icw-sessions/<name>.json`)に1セッション1JSONファイルとして永続化する。**生死判定はこのファイルの存在では行わない**(後述)。
- `icw_core/ipc.py` — IPCアドレスの決定(`session_address`: Windowsは名前付きパイプ、POSIXはUnixドメインソケット)と、「1回つないで1リクエスト送り1レスポンス受けて切断する」`call()`ヘルパー。認証キーは`start`時に`secrets.token_bytes`でセッションごとに生成する。
- `icw_core/daemon.py` — `start`から検知不要なバックグラウンドプロセスとして起動される本体(`python -m icw_core.daemon`)。対象コマンドをPTYでspawnして最初の`wait_until_ready`を済ませてからメタデータを書き込み(=`start`側はこのファイルが現れるのをポーリングして初回出力として返す)、以後`Listener`で1接続=1リクエストのRPCループに入る。`stop`を受けるか対象プロセスが自発的に終了したら、メタデータを削除してから自分自身も終了する。
- `icw_cli.py` — コンソールコマンド本体(`argparse`)。`start -- <対象コマンド...>`はこの`--`より前をラッパー自身のオプション、後ろを対象コマンドの`argv`として手動split(argparseの`REMAINDER`だと対象コマンド側のオプション風トークンと衝突しうるため)。

### 生死判定はメタデータの存在ではなく実接続で行う

`send`/`stop`/`list`はいずれも、メタデータファイルが見つかった後に必ず`icw_core.ipc.call()`で実際に接続を試み、失敗したら「デーモンがクラッシュ/強制終了して死んでいる」とみなしてメタデータを削除する(`list`は全セッションに対してこの生死確認を行い、死んでいたものは表示前にメタデータを片付ける)。`list`用の生死確認だけを目的に、待機を伴わない`ping`アクション(即座に`{"alive": ...}`を返すだけ)をIPCプロトコルに用意してある(`send`アクションで生死確認を兼ねると、その分レスポンスを待つあいだサーバ側スレッドがブロックしたままになるため)。

### 落とし穴: 同じメタデータファイルへの競合削除・書き込み中の読み取り

Step3実装中に実機で再現した2つの競合状態と対処:

- **メタデータ削除の競合** — セッション終了時、CLIコマンド側(`send`/`stop`が「死んでいる/終了した」と判定して削除)とデーモン自身(`serve()`の終了処理で自己クリーンアップ)がほぼ同時に同じファイルを削除しにいく。Windowsでは片方が`FileNotFoundError`、もう片方が`PermissionError`(削除処理中のファイルへの同時アクセス)になりうる。`registry.delete()`はこれらの`OSError`を握りつぶすベストエフォート実装にしてある(どちらか一方が消せれば十分で、両者削除できることを主張する契約ではない)。
- **書き込み中のメタデータの読み取り** — `list`はシステム共有の一時ディレクトリを丸ごとglobするため、他セッションのデーモンが`SessionMetadata.save()`(非アトミックな`write_text`)で書き込んでいる最中のファイルや、過去の異常終了で壊れたまま残っているファイルを掴むことがある。`registry.load_if_exists()`は`OSError`/`ValueError`/`TypeError`を「メタデータ無し」と同じ`None`として扱い、1つのセッションの読み取り失敗で`list`全体が落ちないようにしてある。

## テスト(`tests/`)

- `test_screen.py` — プロセスを一切spawnせず、Step1調査で実際にキャプチャしたANSI混じりの生バイト列を`TerminalScreen`に食わせて、スナップショットが破損・重複しないことを確認するオフラインテスト
- `test_session.py` — トイCLI相手に`InteractiveSession`をspawnし、以下を確認する(`pywinpty`がWindows専用のため`sys.platform != "win32"`ではスキップ):
  - 1ターン往復(`test_single_turn_round_trip`)
  - 複数ターン連続往復(`test_multiple_consecutive_turns_round_trip`)
  - **出力が複数チャンクに分かれて遅延して届く場合に、チャンク間の空白時間をidle-timeoutが「入力待ちに戻った」と誤検知しないこと**(`test_trickling_output_is_not_misdetected_as_ready`)— 各チャンク間隔をidle_timeoutより短く設定し、全チャンクが揃うまで待ってから返ることを検証する
  - `ready_pattern`が一致した場合、idle_timeoutを待ち切る前に短絡して返ること(`test_ready_pattern_short_circuits_idle_timeout`)
  - `close()`でプロセスが確実に終了すること
- `test_cli_session_lifecycle.py` — `icw_cli.main()`をトイCLI相手に直接呼び出す統合テスト(同じくWindows専用でスキップ):
  - `start`が最初のプロンプトまで到達すること・メタデータが書かれること(`test_start_reaches_ready_prompt`)
  - `send`を複数回連続で呼び出せること(`test_send_multiple_consecutive_turns`)
  - `stop`後は`send`が失敗し、メタデータが削除されていること(`test_stop_then_send_fails`)
  - トイCLIが`exit`で自発的に終了した場合も、`stop`を呼ばずにメタデータが片付くこと(`test_child_exit_cleans_up_metadata`)
  - `list`が生存中は`alive`と表示し、`stop`後は一覧から消えること(`test_list_reports_alive_then_removes_after_stop`)

## ファイル構成

```text
tools/interactive-cli-wrapper/
├── README.md              ← このファイル(設計意図・セットアップ)
├── AGENTS.md / CLAUDE.md  ← リポジトリ規約に合わせたエージェント向け入口(実体はこのREADME)
├── pyproject.toml          ← uv workspaceメンバー。依存は pywinpty / pyte。`icw`コンソールコマンドを公開
├── icw_cli.py               ← コンソールコマンド本体(`argparse`: start/send/stop/list)
├── icw_core/
│   ├── __init__.py           ← 公開シンボルの再エクスポート(`from icw_core import ...`の窓口)
│   ├── screen.py              ← pyteベースの端末画面再構成(`TerminalScreen`)
│   ├── session.py             ← PTY起動・1ターン往復・入力待ち検知(`InteractiveSession` / `ReadyResult`)
│   ├── ipc.py                  ← IPCアドレス決定・認証キー生成・1往復の`call()`ヘルパー
│   ├── registry.py             ← セッションメタデータの永続化(`SessionMetadata`)・生死判定は含まない
│   └── daemon.py                ← バックグラウンドデーモン本体(`python -m icw_core.daemon`)
├── toy_repl.py              ← テスト専用のダミー対話REPL(実運用には使わない)
└── tests/
    ├── conftest.py            ← sys.path調整(未インストールでも`uv run pytest tools/interactive-cli-wrapper`が通るように)
    ├── test_screen.py          ← 端末再構成のオフラインテスト(プロセス起動なし)
    ├── test_session.py         ← トイCLI相手のPTY往復・入力待ち検知テスト
    └── test_cli_session_lifecycle.py ← `icw`のstart/send/stop/list統合テスト(トイCLI相手)
```

## `agent`対話モードへの接続で判明した癖

Cursor CLI(`agent`)を対話モードで実地駆動して初めて分かった、トイCLI検証だけでは見えなかった実CLI固有の挙動。コア(`icw_core/`)には`agent`固有の値をハードコードせず、以下は`icw send`のオプション・呼び出し側の運用として吸収している。

- **起動直後の初期化猶予期間が必要** — `icw start`が返す最初の画面(バナー+入力欄プレースホルダ)は見た目上「入力待ち」に見えるが、実際にはこの直後(目安15秒未満)に`send`しても入力がまったく反映されない(テキストが入力欄に残ったまま無反応)。実測では起動から**15〜20秒程度**待ってから最初の`send`を行うと安定して送信できた。以後のターンではこの猶予は不要(1回だけのコスト)。原因は未確定だが、MCP接続やワークスペース解析等の非同期初期化がEnterキーのハンドラ登録より先に完了していないことが疑われる。
- **Enterキーはテキストと同じ`write()`に含めると送信されない** — `send()`の既定動作(`text + "\r\n"`を1回の`write()`で書き込む)は、トイCLI(行バッファ的な標準入力読み取り)には有効だが、`agent`の生キー入力ハンドリングには効かない。埋め込まれた改行を含む1回の書き込みを「(複数行の)貼り付け」とみなし、Enterとして扱わない(通常の複数行貼り付けはこのCLIでも改行挿入として振る舞う仕様のため、区別できていないと考えられる)。`icw send --submit-separately`(既定`--submit-key`はCRのみ、`--submit-delay`既定0.3秒)でテキストとEnterを別の`write()`呼び出しに分けると送信できることを確認した。**この2条件(起動猶予・separate submit)がどちらも揃わないと送信は成立しない**(delay長を0.3〜3秒の範囲で変えても、猶予期間なしでは常に失敗した)。
- **確実な`ready_pattern`はまだ見つかっていない** — 入力欄が空のとき常時表示されるプレースホルダ文字列(初回は`Plan, search, build anything`、2ターン目以降は`Add a follow-up`)は、生成が完了していなくても表示され続ける(生成中を示す`Working`スピナー行と同時に出現することを実機確認済み)。これをそのまま`ready_pattern`にすると誤って早期return(まだ生成中なのに`ready=True`)になるため、**`agent`向けには`ready_pattern`を使わずidle-timeoutのみに頼る**(idle-timeoutは長めの`overall_timeout`と組み合わせ、ツール呼び出しを伴う複雑なターンでは応答が数十秒単位になりうることを見込んでおく)。
- 上記はCursor CLI `2026.07.23-e383d2b`での実地検証結果。CLIのアップデートで挙動が変わった場合は再検証が必要。切り分け過程(否定された仮説含む)は[claude-plugins/my-tools/skills/interactive-cli-wrapper/cursor-agent.md](../../claude-plugins/my-tools/skills/interactive-cli-wrapper/cursor-agent.md)を参照。

## カスタマイズ箇所

| 変えたいこと                                              | 編集場所                                                                                                                                              |
| --------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| PTYの既定サイズ・読み出しチャンクサイズ・ポーリング間隔   | `icw_core/session.py`の`DEFAULT_DIMENSIONS` / `DEFAULT_READ_CHUNK_BYTES` / `DEFAULT_READ_POLL_SECONDS`                                                |
| 「入力待ち」検知のidle-timeout/ready-patternの意味付け    | `icw_core/session.py`の`InteractiveSession.wait_until_ready`                                                                                          |
| 端末画面再構成(pyteの扱い)                                | `icw_core/screen.py`                                                                                                                                  |
| トイCLIの起動遅延・出力チャンク数・チャンク間遅延         | `toy_repl.py`の`argparse`引数(`--startup-delay`等)                                                                                                    |
| セッションメタデータの置き場所                            | `icw_core/registry.py`の`sessions_dir()`(既定: システム一時ディレクトリ配下`icw-sessions/`)                                                           |
| IPCアドレスの決定方式・認証キー生成                       | `icw_core/ipc.py`の`session_address()` / `new_authkey()`                                                                                              |
| `send`/`start`初回待機・`ping`/`stop`のタイムアウト既定値 | `icw_cli.py`冒頭の`DEFAULT_IDLE_TIMEOUT` / `DEFAULT_OVERALL_TIMEOUT` / `PING_TIMEOUT_SECONDS` / `STOP_TIMEOUT_SECONDS` / `DAEMON_START_GRACE_SECONDS` |
| デーモンが処理できるIPCアクション(`send`/`stop`/`ping`)   | `icw_core/daemon.py`の`handle_request()`                                                                                                              |
