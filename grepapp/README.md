# grepapp — fastmcp で自作した grep.app MCP CLI ラッパー

**関連スキル: `claude-plugins/my-tools/skills/grep-app`**

Vercel が公開している grep.app MCP サーバー(`https://mcp.grep.app`、紹介記事:
https://vercel.com/blog/grep-a-million-github-repositories-via-mcp )を、
`tools/mslearn` と同じパターンで **Python の `fastmcp` ライブラリで MCP クライアントを
自前で立て、CLI でラップする**。CLI 経由にすることで、結果を他の CLI ツール(`jq` など)に
流し込んで柔軟にカスタマイズできる点が、ホストにMCPプロトコルを隠蔽させる使い方にはない
利点になる。

設計意図とセットアップはこのファイルに、AI に読ませる判断フロー・引数・出力形式は
`claude-plugins/my-tools/skills/grep-app/SKILL.md` を参照。

## 前提条件

- Python 3.11+ / uv
- `fastmcp` パッケージ(下記インストール手順で入る)
- 認証不要(grep.app MCP サーバーは公開エンドポイント、API キー不要。公開GitHubリポジトリ
  のみが検索対象)

## インストール

グローバルCLIとして使う場合は `uv tool install --editable`(`pip install -e` の代替)で
エディタブルインストールする。リポジトリルートから実行可能。

```bash
uv tool install --editable tools/grepapp
```

インストール後は `grepapp` コマンドが PATH 上でどこからでも使える。

## 使い方

```bash
grepapp search "useState(" --language TypeScript
grepapp search "useEffect(" --repo vercel/next.js --language TypeScript
grepapp search "(?s)class .+ extends React.Component" --use-regexp
grepapp tools
grepapp call searchGitHub --args '{"query": "useState("}'
```

サブコマンド・オプション・出力形式・終了コードの詳細は
`claude-plugins/my-tools/skills/grep-app/SKILL.md` を正本とする(AIが実行時に読む前提で
自己完結して書かれている)。

## このツールの目的

- `fastmcp.Client` で Streamable HTTP の MCP サーバーに接続し、`tools/list` / `tools/call`
  を直接叩く経験を積む(`tools/mslearn` と同じ動機)
- grep.app が公開しているツールは `searchGitHub` の1つだけだが、サーバー側でツールが
  増減・改名されても詰まないよう `call <tool_name>` という汎用パススルーと、
  ハードコードに頼らず `tools/list` を都度呼ぶ `tools` サブコマンドを持たせる
- `--json` で全サブコマンドの出力を単一 JSON にでき、`jq` や他スクリプトへパイプできる
  ようにする

## 実装メモ(動作確認済みの実際のレスポンス形状)

`searchGitHub` を実際に叩いて確認した戻り値の形(詳細な調査ログは `memo/00-findings.md`
参照)。

- `CallToolResult` は `structured_content` も `data` も常に `None`。中身はすべて
  `content`(TextContent のリスト)に入る。
- **ヒットありの場合**: 1マッチ(1ファイル)につき1つの TextContent ブロック。
  1クエリあたり最大10ブロック固定(ページング手段がスキーマに無い)。各ブロックは
  `Repository: <owner/repo>` / `Path: <file path>` / `URL: ...` / `License: ...` の
  ヘッダー行に続けて `Snippets:` セクションを持つ。
- **ヒット0件の場合**: ブロックが1つだけで、本文は
  `"No results found for your query."`(実測)。`is_error` は `False` のまま。
  CLI 側の空判定はこの固定文言の完全一致には頼らず、「ブロックが1つだけで、かつ
  `"Repository: "` から始まらない」という構造で判定する(サーバー側の文言変更に対して
  頑健にするため)。
- 初回呼び出しで `timeout=20` 秒だと `504 Gateway Timeout` が発生した実測があり(2回目
  以降 `timeout=40` 秒では成功)、既定タイムアウトは mslearn の30秒より長い45秒にしている。
- レート制限は公式ブログ記事に明記が無い。CLI側で特別なリトライ・バックオフは実装しない。
- `microsoft_docs_search` の `maxTokenBudget` に相当するレスポンスサイズ制御パラメータは
  `searchGitHub` のスキーマに存在しない。ページング用パラメータも存在しない。

## `mslearn` との違い

- 提供ツールが `searchGitHub` の1つだけなので、サブコマンドは `search`/`tools`/`call` の
  3つのみ(`fetch` 相当は無い — grep.app はページ取得ではなくコード検索専用)
- `search` の結果は `structured_content["results"]` ではなく `result.content` の
  TextContent ブロックを1件=1ファイルとしてそのまま書き出す(`microsoft_docs_fetch` と
  同じ形だが、`search` 系コマンドでこの形になるのは mslearn には無いパターン)
- Q&A相当の分離(`qa/` サブフォルダ)は無い。`category` は常に `""`

## ファイル構成

薄い CLI エントリポイント(`grepapp_cli.py`)と、責務ごとに分けた実装パッケージ
(`grepapp_core/`)に分離する構成は `tools/mslearn` と同じ。

```text
tools/grepapp/
├── README.md              ← このファイル(設計意図・セットアップ)
├── pyproject.toml          ← `grepapp` コンソールコマンドのパッケージング
├── grepapp_cli.py           ← エントリポイント。argparse サブコマンド定義 + main()
├── grepapp_core/
│   ├── config.py             ← 定数(終了コード・既定エンドポイント・出力先 env var)
│   ├── client.py              ← `fastmcp.Client` のラッパー(接続・tools/call・tools/list)
│   ├── rendering.py           ← 生の TextContent ブロック1件 →
│   │                            `(category, title, markdown)` への変換(空応答判定・
│   │                            `Repository:`/`Path:` ヘッダー抽出を集約)
│   └── output.py              ← `(category, title, markdown)` のリスト →
│                                  クエリごとの連番フォルダ書き出し + `index.md` 生成 +
│                                  「index.md のパスだけ」の標準出力サマリ
└── memo/                   ← 事前調査メモ(実測したエンドポイント仕様・レスポンス形状)
```

`claude-plugins/my-tools/skills/grep-app/` 側には `SKILL.md`(AI が実行時に読む判断フロー・
使い方)と `README.md`(スキルの設計意図)だけが残る。CLI 本体はこのライブラリ依存として
明示的に切り出してあり、スキル側から `grepapp_cli.py` を直接叩くことはしない。
