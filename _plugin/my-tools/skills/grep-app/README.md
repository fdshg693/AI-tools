# grep-app スキルについて

`tools/grepapp/`の`grepapp` CLI(fastmcpで自作した、Vercelが公開しているgrep.app MCP
サーバーのラッパー)を、Claudeが会話の中からすぐ使えるようにするためのスキル。このファイルは
人間のメンテナ向けで、設計意図と前提条件を説明する。Claudeが実行時に読むのは
[SKILL.md](SKILL.md)であり、こちらは参照しない。

## なぜこのスキルがあるか

- `searchGitHub`ツールの`query`は「キーワードではなく実際にコードに現れるリテラルな
  パターンを渡す」という、他の検索ツール(`ms-learn`のセマンティック検索等)とは異なる
  特有の制約を持つ。この制約はツール自体のdescriptionには書かれているが、CLIの
  `--help`だけでは伝わらないため、スキル側の判断フロー・クエリの書き方セクションの
  冒頭で固定化している
- `tools/mslearn`と同じ構成(薄いCLIエントリポイント + `*_core/`パッケージ)で実装した
  ことで、`ms-learn`スキルとほぼ同じ判断フローの型(判断フロー→出力形式→終了コード→
  他スキルとの使い分け)を踏襲できる

## 前提条件(重要)

- `grepapp`コマンドは事前にインストール済みであること
  (`uv tool install --editable tools/grepapp`)。このスキルはインストール処理を
  一切行わず、CLI本体も同梱しない
- 認証は不要(grep.app MCP サーバーは公開エンドポイント、APIキー不要。検索対象は
  公開GitHubリポジトリのみ)
- 上記が満たされていない環境(未インストール)でこのスキルが呼ばれた場合、Claudeは
  このスキルではエラーに対処せず、`tools/grepapp/README.md`のセットアップ手順を
  ユーザーに案内する

## 情報源と保守

- CLI本体の設計意図・実装メモ・ファイル構成の一次情報は`tools/grepapp/README.md`
- サブコマンド・オプション・出力形式・終了コードの一次情報も`tools/grepapp/`配下
  (`grepapp_cli.py`本体)だが、SKILL.mdはClaudeが実行時に外部ファイルへジャンプしなくて
  済むよう、意図的に自己完結する形で複製している。CLIのオプション名・出力形式・終了コード
  が変わった場合はSKILL.mdも合わせて更新すること
- 判断フロー・クエリの書き方の制約・`ms-learn`/`tav-cli`との使い分けはこのスキル固有の
  運用方針であり、`tools/grepapp/README.md`には存在しない

二重化した内容のドリフトを防ぐため、CLI仕様を変更するときは次の順で確認する。

1. `tools/grepapp/README.md`および`grepapp_cli.py`を正本として、CLI本体と仕様を更新する
2. `SKILL.md`の「サブコマンド」「出力形式」「終了コード」を同じ変更内容に更新する
3. オプション名・出力形式・終了条件を両ファイルで突き合わせる

## 実装の背景(なぜ自作したか)

grep.appはVercelが公開しているMCPサーバー(`https://mcp.grep.app`)で、公式のAgent Skill
配布は行っていない(紹介記事:
https://vercel.com/blog/grep-a-million-github-repositories-via-mcp )。`tools/mslearn`と
同じ理由で、`fastmcp`でMCPクライアントを自前で立ててCLIでラップした
(学習目的、かつCLI経由にすることで結果を`jq`等の他CLIツールに流し込める柔軟性のため)。
提供ツールが`searchGitHub`の1つだけであることを含む実測結果は`tools/grepapp/README.md`
および`tools/grepapp/memo/`を参照。
