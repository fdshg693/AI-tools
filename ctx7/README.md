# ctx7 — Context7 REST API の薄い CLI ラッパー(Python 実装)

**関連スキル: `claude-plugins/my-tools/skills/use-context`**

このディレクトリは、[Context7](https://context7.com/)(外部ライブラリ・フレームワークの最新ドキュメントをコードスニペット付きで返すサービス)の REST API を **`requests` で直接叩く** CLI の実体です。Context7 は公式に MCP サーバーと Node 製 CLI(`npx ctx7`)を配布していますが、このツールはそれとは別に、Python から素の REST API(`https://context7.com/api/v2/...`)を叩く自前実装です。

設計意図はこのファイルに、AI に読ませる利用判断・ワークフローは [claude-plugins/my-tools/skills/use-context/](../../claude-plugins/my-tools/skills/use-context/) の memo を参照してください。

## 前提条件

- Python 3.11+ / uv
- `requests` / `python-dotenv`(下記インストール手順で入る)
- Context7 の API キー(`CONTEXT7_API_KEY`)— **任意**。実機確認済みで、キー無しでも両エンドポイントとも 200 が返る。キー無しは低いレート制限、キー有りは高いレート制限という位置づけ(詳細は後述「認証」)。

## インストール

グローバル CLI として使う場合は `uv tool install --editable`(`pip install -e` の代替)でエディタブルインストールする。リポジトリルートから実行可能。

```bash
uv tool install --editable tools/ctx7
```

インストール後は `ctx7` コマンドが PATH 上でどこからでも使える(依存の `requests` / `python-dotenv` も一緒に入る。リポジトリ共通のテスト用 venv に入れるだけなら `uv sync` でも可)。

## セットアップ(APIキー、任意)

```bash
cp tools/ctx7/.env.example tools/ctx7/.env
# .env を編集して CONTEXT7_API_KEY=... を設定(空のままでも動く)
```

`--api-key` オプションでその場だけ上書きもできる。

## 使い方

```bash
# ライブラリ候補を検索(GET /api/v2/libs/search)
ctx7 library react "react hooks"

# 選んだ library ID でドキュメント取得(GET /api/v2/context)
ctx7 docs /react/react "useEffect cleanup"
```

PowerShell の場合も同じ(バッククォート改行のみ異なる)。

```powershell
ctx7 library react "react hooks"
ctx7 docs /react/react "useEffect cleanup"
```

`--json` を付けると自己記述 JSON エンベロープ(後述)を stdout に出す(`jq` 等へのパイプ用途)。付けない場合は `library` は候補の簡易一覧、`docs` は API の生レスポンス(`type=txt` ならプレーンテキストそのもの、`type=json` なら整形 JSON)をそのまま stdout に出す。

各サブコマンドの引数詳細は `--help` で確認できる。

```bash
ctx7 --help
ctx7 library --help
ctx7 docs --help
```

## 実装方針

### なぜ mslearn 型のフォルダ出力ではなく stdout 直接出力にしたか

`tools/mslearn` は MCP 経由で取得した本文をフォルダ + `index.md` に書き出す設計だが、これは Microsoft Learn のページ本文が大きくなりがちなことが理由。Context7 の実機レスポンスはそれよりずっと小さく、`type=txt` で 5.8KB、`type=json` で 7.0KB 前後(実測)。この分量なら 1 回の呼び出し結果をそのまま stdout に流しても後段のコンテキストを圧迫しないため、`tools/tav-cli` の「`--topic` 未指定時」と同じ **stdout 直接出力のみ** の設計にした。トピックフォルダ・`index.md` 書き出し機構(`tav_core/topic_layout.py` 相当)は実装していない。

### 認証

`Authorization: Bearer <CONTEXT7_API_KEY>` ヘッダーを付与するが、キーが空でもリクエストは送る(必須にしない)。両エンドポイントとも無認証で 200 が返ることを実機で確認済み。`.env` の `CONTEXT7_API_KEY` を読むか、`--api-key` で都度上書きできる(`ctx7_core/environment.py`)。

### エラー処理・リトライ(`ctx7_core/client.py`)

Context7 REST API のステータスコード別の扱い:

| ステータス                                                              | 対応                                                                                                                                                             |
| ----------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `200`                                                                   | 成功。`docs --type txt` のときだけ本文はプレーンテキスト、それ以外(検索結果・`--type json`・エラー全般)は JSON                                                   |
| `202`(`docs` のみ)                                                      | ライブラリがまだインデックス中。`POLL_INTERVAL_SECONDS` 間隔で `MAX_202_POLLS` 回まで再試行し、それでも 202 なら「インデックス中」として返す(エラー扱いにしない) |
| `301`(`docs` のみ)                                                      | レスポンスの `redirectUrl` が新しい `libraryId`。1 回だけ追従して再試行。2 回連続で 301 なら終端エラー扱い                                                       |
| `429`                                                                   | `Retry-After` ヘッダーがあれば尊重、無ければ指数バックオフ(`BACKOFF_BASE_SECONDS * 2**attempt`)。`MAX_429_RETRIES` 回まで再試行し、尽きたらエラー                |
| それ以外の非 200(`400`/`401`/`403`/`404`/`409`/`422`/`500`/`503`/`504`) | `Context7ApiError` を送出。ペイロードは `{"error", "message"}`                                                                                                   |

定数(`MAX_429_RETRIES` / `BACKOFF_BASE_SECONDS` / `MAX_202_POLLS` / `POLL_INTERVAL_SECONDS`)は `ctx7_core/client.py` 冒頭に置いてあり、そこを編集すれば挙動を変えられる。

### 実行結果(終了コード)

`mslearn_core/config.py` と同じ番号体系に揃えている(既存の小さな CLI 群と混同しないため)。

| code | 定数                 | 意味                                                      |
| ---- | -------------------- | --------------------------------------------------------- |
| `0`  | `EXIT_SUCCESS`       | 正常完了                                                  |
| `1`  | `EXIT_RUNTIME_ERROR` | 接続失敗・タイムアウト・予期しない例外                    |
| `3`  | `EXIT_API_ERROR`     | Context7 が 4xx/5xx を返した(429 リトライ枯渇も含む)      |
| `4`  | `EXIT_EMPTY_RESULT`  | `library` の検索結果が 0 件                               |
| `5`  | `EXIT_INCOMPLETE`    | `docs` が 202(インデックス中)のままポーリングを使い切った |

`--json` 出力の形は次の自己記述エンベロープ(`ctx7_cli.build_envelope`):

```json
{
  "command": "library",
  "exit_code": 0,
  "result": {
    "...": "API の生レスポンス、またはエラー時は {\"error\", \"message\"}"
  }
}
```

`tav-cli` の `ResultEnvelope`(`script` / `result_kind` / `exit_code` / `result`)を参考にしているが、ファイル出力が無く `result_kind` で分岐すべき出力形式も 2 種類(検索結果 / ドキュメント本文)しか無いため、`result_kind` 判別子や `OutputChannel` のような重い抽象化は持たない。

## ファイル構成

```text
tools/ctx7/
├── README.md              ← このファイル(設計意図・セットアップ)
├── AGENTS.md / CLAUDE.md  ← リポジトリ規約に合わせたエージェント向け入口(実体はこのREADME)
├── pyproject.toml          ← `ctx7` コンソールコマンドのパッケージング
├── .env / .env.example     ← Context7 API キー(.env はgitignore対象、キー無しでも動く)
├── ctx7_cli.py              ← エントリポイント。argparse サブコマンド(library/docs)+ main()
├── ctx7_core/
│   ├── __init__.py           ← 公開シンボルの再エクスポート(`from ctx7_core import ...` の窓口)
│   ├── client.py              ← requests での Context7 API 呼び出し・429/301/202 の処理・ApiResult/Context7ApiError
│   ├── environment.py         ← .env 読込・CONTEXT7_API_KEY 取得(空文字許容)
│   └── result_contract.py     ← 終了コード定数(EXIT_SUCCESS 等)
└── tests/
    ├── conftest.py            ← sys.path 調整(未インストールでも `uv run pytest tools/ctx7` が通るように)
    ├── test_client.py          ← ネットワークを叩かない client.py の純粋関数テスト(FakeSession でモック)
    └── test_cli.py             ← ctx7_cli.py の純粋関数テスト(エンベロープ組み立て・APIキー解決の優先順位)
```

## カスタマイズ箇所

| 変えたいこと                                    | 編集場所                                                                    |
| ----------------------------------------------- | --------------------------------------------------------------------------- |
| ベース URL・エンドポイントパス                  | `ctx7_core/client.py` の `BASE_URL` / `SEARCH_PATH` / `CONTEXT_PATH`        |
| 429 リトライ回数・バックオフ                    | `ctx7_core/client.py` の `MAX_429_RETRIES` / `BACKOFF_BASE_SECONDS`         |
| 202 ポーリング回数・間隔                        | `ctx7_core/client.py` の `MAX_202_POLLS` / `POLL_INTERVAL_SECONDS`          |
| タイムアウト既定値                              | `ctx7_core/client.py` の `DEFAULT_TIMEOUT`(CLI からは `--timeout` で上書き) |
| `.env` 読み込み挙動・APIキー env var 名         | `ctx7_core/environment.py`                                                  |
| 終了コード体系                                  | `ctx7_core/result_contract.py`                                              |
| `--json` エンベロープの形・非 JSON 時の表示整形 | `ctx7_cli.py` の `build_envelope` / `render_library_results`                |
