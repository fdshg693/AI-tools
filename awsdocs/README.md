# awsdocs — fastmcp で自作した AWS Knowledge MCP CLI ラッパー

**関連スキル: `claude-plugins/my-tools/skills/aws-docs`**

AWS 公式のリモート MCP サーバー **AWS Knowledge MCP Server**(`https://knowledge-mcp.global.api.aws`、
認証不要・無料・GA)を、Python の `fastmcp` クライアントで叩いて CLI にしたもの。
[`tools/mslearn`](../mslearn/README.md) と同じ設計(1呼び出し1フォルダ・1件1ファイル＋`index.md`、
`--json`、`tools`/`call` パススルー)を AWS 向けに移植している。

設計意図とセットアップはこのファイルに、AI に読ませる判断フロー・引数・出力形式・終了コードは
`claude-plugins/my-tools/skills/aws-docs/SKILL.md` を正本とする。ツール選定の経緯と
サーバーの実測挙動は [`memo/`](memo/00-overview.md) を参照。

## 前提条件

- Python 3.11+ / uv
- `fastmcp` パッケージ(下記インストール手順で入る)
- 認証不要(API キー・AWS アカウント不要。`.env` も無い)

## インストール

```bash
uv tool install --editable tools/awsdocs
```

インストール後は `awsdocs` コマンドが PATH 上でどこからでも使える。

## 使い方

```bash
awsdocs search "S3 lifecycle rule transition to Glacier"
awsdocs search "Lambda throttling errors" --topic troubleshooting --limit 5
awsdocs fetch https://docs.aws.amazon.com/AmazonS3/latest/userguide/lifecycle-configuration-examples.html --all
awsdocs fetch <url> --start-index 18024 --max-length 5000   # 切り詰め時の TOC の文字範囲へジャンプ
awsdocs regions
awsdocs availability --type product --region ap-northeast-1 --region us-east-1 --filter "AWS Lambda"
awsdocs skill securing-s3-buckets
awsdocs tools
awsdocs call search_documentation --args '{"search_phrase": "...", "limit": 3}'
```

| コマンド       | MCP ツール                        | 出力                               |
| -------------- | --------------------------------- | ---------------------------------- |
| `search`       | `aws___search_documentation`      | フォルダ(1件1ファイル＋`index.md`) |
| `fetch`        | `aws___read_documentation`        | フォルダ                           |
| `regions`      | `aws___list_regions`              | 標準出力(Markdown 表)              |
| `availability` | `aws___get_regional_availability` | 標準出力(Markdown 表)              |
| `skill`        | `aws___retrieve_skill`            | フォルダ(1ファイル)                |
| `tools`        | `list_tools`                      | 標準出力                           |
| `call`         | 任意ツール(`aws___` は省略可)     | 標準出力(生 JSON)                  |

共通オプション: `--json`(ファイルを書かず単一 JSON を標準出力)、`--endpoint`
(既定は環境変数 `AWSDOCS_MCP_ENDPOINT`、なければ上記 URL)、`--timeout`(既定 60 秒)。
出力先は環境変数 `AWSDOCS_MCP_OUTPUT_DIR`(未設定時 `temp/awsdocs_mcp`)。

終了コード: 0 成功 / 1 実行時エラー(接続失敗・空レスポンス・レート制限) / 2 引数エラー /
3 ツールエラー(対象外 URL・フィルタ名誤り・不明 skill 等) / 4 空結果(`regions`・`availability`・
`skill` が本当に空のときだけ。`search` は無意味なクエリでも何か返すので実質出ない)。

## 設計メモ

### 出力(`mslearn` との共通点と差分)

- `search` / `fetch` / `skill` は `NNNN-<スラッグ>/` フォルダに1件1ファイルで書き、標準出力には
  `index.md` のパスだけを出す。`index.md` の各行にはファイルの文字数を付ける。連番の採番は
  ファイルロックで直列化しているので並列起動しても衝突しない(ここまで `mslearn` と同じ)。
- 検索結果は docs / Blog / What's New / re:Post / AWS Agent Skill が1つのランキングに混ざって返る
  (既定トピック `general` では Blog が上位に来やすい)。URL で分類し `blog/`・`whats-new/`・
  `repost/`・`skills/` に分ける(`mslearn` の `qa/` 分離の拡張)。ファイル番号は全区分通しの
  連番なので、元の順位はファイル名に残る。skill エントリは URL を持たないので `URL:` 行の代わりに
  `Skill: <name>` 行を書く(本文は `awsdocs skill <name>` で取る)。
- 各ファイルは先頭付近に `URL:` 行を持つ(`aim --parallel` での出典転記用)。切り詰められたページは
  サーバーが先頭に「見出しごとの文字範囲付き TOC」を付けるので、H1＋`URL:` 行を前置きして
  TOC はそのまま残す(`--start-index` でジャンプする手がかり)。

### `fetch` の分割取得

- サーバー既定は1回 10000 字。`truncated` のときはファイル先頭と `index.md` の Warnings に
  「何字目で切れたか・続きの `--start-index`」を書く。
- `--all` は `end_index` を次の `start_index` にして追い読みし、1ファイルに連結する。2回目以降の
  チャンクにも TOC が付くが、本文スライスは `end_index - start_index` 字ちょうどなので末尾から
  切り出して連結する(最初のチャンクの TOC だけ残る)。単発の大きな `--max-length` 取得と
  本文が一致することを確認済み。
- 複数 URL を渡せる。サーバー上限の5件ずつに分けて送り、追い読みも含めて1回の MCP セッション内で
  行う(接続ごとに `initialize` ハンドシェイクが走り、レート制限に近づくため)。

### MCP 応答の正規化

MCP の `is_error` は常に `False` で、本文は常に `content[0].text` の JSON 文字列1つ。CLI 側で判定する
(`awsdocs_core/responses.py`、根拠は [memo/01-knowledge-mcp-server.md](memo/01-knowledge-mcp-server.md)):

| 状況                                                  | 判定                                | 扱い                                                            |
| ----------------------------------------------------- | ----------------------------------- | --------------------------------------------------------------- |
| 引数・対象外 URL・フィルタ名誤り・不明 skill          | トップレベル `errorMessage`         | exit 3、メッセージを stderr へ                                  |
| `fetch` バッチ内の個別失敗                            | 要素の `status: ERROR`/`error_code` | 成功分は書き出し、失敗は stderr と `index.md` の Errors、exit 3 |
| 存在しない docs URL(ガイドトップへ黙ってリダイレクト) | `redirected_url` が非 null          | exit 0 のまま stderr・`index.md`・ファイル先頭に警告            |
| 空レスポンス(長いページの特定範囲で断続的に発生)      | content ブロック無し/本文が空       | exit 1、範囲を変えるか `.md` を直接取得するよう案内             |
| レート制限                                            | HTTP 429 / `-32004` / `throttled`   | 3 秒待って1回だけ再試行、だめなら exit 1                        |

レート制限は公式クォータで未認証 5 req/s/IP だが、過去に大きく絞られた事例がある(memo 参照)。

### その他

- `search --topic` は argparse の `choices` で検証する(サーバーは不正トピックを黙って無視するため)。
  サーバー側でトピックが増えたら `awsdocs_core/config.py` の `SEARCH_TOPICS` に足す。それまでは
  `call` で直接渡せる。
- ツール名(`aws___` プレフィックス込み)は `config.py` に集約。`tools` はサーバーの一覧を都度取得し、
  `call` はプレフィックスを補って任意ツールを呼ぶ(未ラップのツールや改名への逃げ道)。
- `availability` の応答形状は単一/複数リージョンで異なるため、`rendering.availability_rows` で
  「名前 × リージョン」の表に揃える。複数リージョンは `--filter` 必須(サーバー仕様)、
  `--next-token` は単一リージョン・フィルタ無しのときだけ使える。
- `mslearn_core` のコードは共通ライブラリ化せずコピーして調整している(2ツールの段階では早い)。
  `release: true` のため、workspace 内の兄弟パッケージには依存しない。公開関数の形
  (`client.call_tool`/`list_tools`/`content_text`、`output.write_query_results`、
  `rendering.render_*`)は `tools/my-agents` からの将来利用に備えて `mslearn_core` に揃えてある。

## ファイル構成

```text
tools/awsdocs/
├── README.md              ← このファイル(設計意図・セットアップ)
├── pyproject.toml          ← `awsdocs` コンソールコマンドのパッケージング
├── awsdocs_cli.py           ← エントリポイント。argparse サブコマンド定義 + main()
├── awsdocs_core/
│   ├── config.py             ← 定数(終了コード・エンドポイント・ツール名・トピック・上限値)
│   ├── client.py              ← `fastmcp.Client` のラッパー(1実行1セッション・429 再試行)
│   ├── responses.py           ← MCP 応答の正規化(errorMessage/空応答 → 型付き例外、チャンク本文の切り出し)
│   ├── rendering.py           ← 生の結果1件 → `(category, title, markdown)`、regions/availability の表
│   └── output.py              ← 連番フォルダ書き出し(区分サブフォルダ + `index.md`)
├── tests/                  ← オフライン unittest(分類・index.md・採番・応答正規化・追い読み連結)
└── memo/                   ← 事前調査メモ(Knowledge MCP の実測、代替手段の比較)
```

## 動作確認

オフラインテスト:

```bash
uv run pytest tools/awsdocs
```

実サーバーでの手動確認(ネットワーク必須):

```bash
awsdocs --version
awsdocs tools                                   # aws___ 付き5ツールが出る
awsdocs search "S3 lifecycle rule transition to Glacier"      # Docs / Blog に分かれた index.md
awsdocs fetch https://docs.aws.amazon.com/AmazonS3/latest/userguide/lifecycle-configuration-examples.html --all
                                                # 24460 字が1ファイルに連結される
awsdocs fetch https://example.com/x             # exit 3(対象外 URL)
awsdocs fetch https://docs.aws.amazon.com/AmazonS3/latest/userguide/nope-does-not-exist.html
                                                # exit 0 + リダイレクト警告
awsdocs search "lambda" --topic nonsense        # exit 2
awsdocs availability --type product --region ap-northeast-1 --region us-east-1 --filter Lambda
                                                # exit 3 + did you mean
```
