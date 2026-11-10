# aws-docs スキルについて

`tools/awsdocs/`の`awsdocs` CLI(fastmcpで自作した、公式AWS Knowledge MCP Serverの
ラッパー)を、Claudeが会話の中からすぐ使えるようにするためのスキル。このファイルは
人間のメンテナ向けで、設計意図と前提条件を説明する。Claudeが実行時に読むのは
[SKILL.md](SKILL.md)であり、こちらは参照しない。

## なぜこのスキルがあるか

- `awsdocs`は`search`/`fetch`/`regions`/`availability`/`skill`/`tools`/`call`の7サブコマンドを
  持つが、「リージョン可用性なら`availability`」「目的に応じて`--topic`を1つ選ぶ」
  「searchのチャンクで答えられるなら`fetch`しない」といった**使い分けの判断フロー**は
  `tools/awsdocs/README.md`には書かれておらず、それを固定化するためにスキル化した
- Knowledge MCPの罠(トピック未指定だとBlogが上位に来る、無意味なクエリでもゼロ件に
  ならない、存在しないURLが黙ってガイドトップにリダイレクトされる)への対処や、
  `ms-learn`/`use-context`/`tav-cli`との使い分けも、CLI自体の仕様ではなく運用上の
  ノウハウなのでスキル側に持たせている

## 前提条件(重要)

- `awsdocs`コマンドは事前にインストール済みであること
  (`uv tool install --editable tools/awsdocs`)。このスキルはインストール処理を
  一切行わず、CLI本体も同梱しない
- 認証は不要(AWS Knowledge MCP Serverは公開エンドポイント、AWSアカウント・APIキー不要)。
  未認証はソースIPごとにレート制限がある
- 上記が満たされていない環境(未インストール)でこのスキルが呼ばれた場合、Claudeは
  このスキルではエラーに対処せず、`tools/awsdocs/README.md`のセットアップ手順を
  ユーザーに案内する

## 情報源と保守

- CLI本体の設計意図・実装メモ・ファイル構成の一次情報は`tools/awsdocs/README.md`、
  サーバーの実測挙動は`tools/awsdocs/memo/01-knowledge-mcp-server.md`
- サブコマンド・オプション・出力形式・終了コードの一次情報も`tools/awsdocs/`配下
  (`awsdocs_cli.py`本体)だが、SKILL.mdはClaudeが実行時に外部ファイルへジャンプしなくて
  済むよう、意図的に自己完結する形で複製している
- 判断フロー・クエリのコツ・罠・他スキルとの使い分けはこのスキル固有の運用方針であり、
  `tools/awsdocs/README.md`には存在しない。「クエリのコツ・罠」には実測で確認したものだけを
  書き、推測は書かない

二重化した内容のドリフトを防ぐため、CLI仕様を変更するときは次の順で確認する
(`tools/awsdocs/AGENTS.md`にも同じ規約がある)。

1. `tools/awsdocs/README.md`および`awsdocs_cli.py`を正本として、CLI本体と仕様を更新する
2. `SKILL.md`の「サブコマンド」「出力形式」「終了コード」を同じ変更内容に更新する
3. オプション名・出力形式・終了条件を両ファイルで突き合わせる

## スコープ外にしたもの

- `ms-digest`相当の並列抽出スキル(`aws-digest`)は作っていない。`aws-docs`の結果ファイルの
  読み込みが実際に重いと分かってから別途作る。それまではSKILL.mdで`aim --parallel`での
  抽出を案内するに留める
- AWS API の実行・デプロイは扱わない(ドキュメント参照専用)

## 実装の背景(なぜ自作したか)

公式には`claude-plugins-official`の`aws-core`等(Agent Toolkit for AWS。AWS MCP Server＋
スキル一式、AWS API実行・デプロイまで含む)や`awslabs/agent-plugins`(MCPとして
`awsknowledge`を同梱)があり、それを直接使うのが最短ルートではある。それでもあえて
`fastmcp`でMCPクライアントを自前で立ててCLIでラップしたのは次の理由による
(`ms-learn`と同じ論点)。

- 結果を1呼び出し1フォルダ・1件1ファイルに書き出し、会話コンテキストに直接流さない
- `--json`で`jq`パイプラインや`aim --parallel`での抽出に流せる
- MCPの罠(`is_error`が常にFalse、存在しないURLの黙ったリダイレクト、空レスポンス)を
  CLI側で終了コードに正規化できる
- 公式プラグインはAWS API実行まで含む大きな束で、「ドキュメントを引くだけ」には重い

比較の詳細は`tools/awsdocs/memo/03-alternatives-and-existing-assets.md`を参照。
