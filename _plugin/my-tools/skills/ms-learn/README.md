# ms-learn スキルについて

`tools/mslearn/`の`mslearn` CLI(fastmcpで自作した、公式Microsoft Learn MCPサーバーの
ラッパー)を、Claudeが会話の中からすぐ使えるようにするためのスキル。このファイルは
人間のメンテナ向けで、設計意図と前提条件を説明する。Claudeが実行時に読むのは
[SKILL.md](SKILL.md)であり、こちらは参照しない。

## なぜこのスキルがあるか

- `mslearn`は`search`/`code-search`/`fetch`/`tools`/`call`の5サブコマンドを持つが、
  「まずURLが分かっているかで分岐する」「`search`の抜粋が浅ければ`fetch`で深掘りする」
  といった**使い分けの判断フロー**は`tools/mslearn/README.md`には書かれておらず、
  それを固定化するためにスキル化した
- クエリの具体化のコツ(製品名だけでなく機能名・バージョン・症状まで含める、英語の方が
  一致率が高い、ARM リソース型名は ARM スキーマ参照に結果を占領される等)や
  `tav-cli`との使い分けも、CLI自体の仕様ではなく運用上のノウハウなので
  スキル側に持たせている

## 前提条件(重要)

- `mslearn`コマンドは事前にインストール済みであること
  (`uv tool install --editable tools/mslearn`)。このスキルはインストール処理を
  一切行わず、CLI本体も同梱しない
- 認証は不要(Microsoft Learn MCP サーバーは公開エンドポイント、APIキー不要)
- 上記が満たされていない環境(未インストール)でこのスキルが呼ばれた場合、Claudeは
  このスキルではエラーに対処せず、`tools/mslearn/README.md`のセットアップ手順を
  ユーザーに案内する

## 情報源と保守

- CLI本体の設計意図・実装メモ・ファイル構成の一次情報は`tools/mslearn/README.md`
- サブコマンド・オプション・出力形式・終了コードの一次情報も`tools/mslearn/`配下
  (`mslearn_cli.py`本体)だが、SKILL.mdはClaudeが実行時に外部ファイルへジャンプしなくて
  済むよう、意図的に自己完結する形で複製している。CLIのオプション名・出力形式・終了コード
  が変わった場合はSKILL.mdも合わせて更新すること
- 判断フロー・クエリの具体化のコツ・`tav-cli`との使い分けはこのスキル固有の運用方針
  であり、`tools/mslearn/README.md`には存在しない

二重化した内容のドリフトを防ぐため、CLI仕様を変更するときは次の順で確認する。

1. `tools/mslearn/README.md`および`mslearn_cli.py`を正本として、CLI本体と仕様を更新する
2. `SKILL.md`の「サブコマンド」「出力形式」「終了コード」を同じ変更内容に更新する
3. オプション名・出力形式・終了条件を両ファイルで突き合わせる

## 実装の背景(なぜ自作したか)

公式が Microsoft Learn MCP サーバー本体と `microsoft-docs` / `microsoft-code-reference`
の Agent Skill 一式を配布しており(`/plugin install microsoft-docs@claude-plugins-official`)、
それを直接使うのが最短ルートではある。それでもあえて`fastmcp`でMCPクライアントを自前で
立ててCLIでラップしたのは学習目的、かつCLI経由にすることで結果を`jq`等の他CLIツールに
流し込める柔軟性が公式スキルにはない利点になるため。実装の詳細(レスポンス形状の実測、
ファイル構成、`tav-cli`との違いなど)や事前調査メモは`tools/mslearn/README.md`および
`tools/mslearn/memo/`を参照。
