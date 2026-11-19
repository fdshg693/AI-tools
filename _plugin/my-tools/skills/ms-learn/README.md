# ms-learn スキルについて

`tools/web-research/mslearn/`の`mslearn` CLI(fastmcpで自作した、公式Microsoft Learn MCPサーバーの
ラッパー)を、Claudeが会話の中からすぐ使えるようにするためのスキル。このファイルは
人間のメンテナ向けで、設計意図と前提条件を説明する。Claudeが実行時に読むのは
[SKILL.md](SKILL.md)と、そこから分岐する同階層の目的別ファイルであり、こちらは参照しない。

## ファイル構成

- `SKILL.md` — 薄いエントリ。`mslearn --help` の埋め込み、判断フロー、目的別ファイルへの分岐表、`tav-cli`との使い分けだけを持つ
- `queries.md` — クエリの具体性を上げるコツ
- `output.md` — サブコマンド・共通オプション・出力形式・終了コード
- `digest.md` — 結果ファイルを`aim --parallel`で並列AI抽出する手順(旧`ms-digest`スキルを統合)

`digest.md`がある理由: `search`/`code-search`は最大10件前後を1件1ファイルに書き出し、素直に
やるとClaudeが1件ずつReadすることになる。件数が多い・大きいファイルが複数あるとコンテキストを
無関係な抜粋で消費するため、この読むフェーズを`aim --parallel`に置き換え、関連する内容だけを
抜き出させる。どのファイルを渡すかは`index.md`を見て呼び出し側が決める。

## なぜこのスキルがあるか

- `mslearn`は`search`/`code-search`/`fetch`/`tools`/`call`の5サブコマンドを持つが、
  「まずURLが分かっているかで分岐する」「`search`の抜粋が浅ければ`fetch`で深掘りする」
  といった**使い分けの判断フロー**は`tools/web-research/mslearn/README.md`には書かれておらず、
  それを固定化するためにスキル化した
- クエリの具体化のコツ(製品名だけでなく機能名・バージョン・症状まで含める、英語の方が
  一致率が高い、ARM リソース型名は ARM スキーマ参照に結果を占領される等)や
  `tav-cli`との使い分けも、CLI自体の仕様ではなく運用上のノウハウなので
  スキル側に持たせている

## 前提条件(重要)

- `mslearn`コマンドは事前にインストール済みであること
  (`uv tool install --editable tools/web-research/mslearn`)。このスキルはインストール処理を
  一切行わず、CLI本体も同梱しない
- 認証は不要(Microsoft Learn MCP サーバーは公開エンドポイント、APIキー不要)
- 上記が満たされていない環境(未インストール)でこのスキルが呼ばれた場合、Claudeは
  このスキルではエラーに対処せず、`tools/web-research/mslearn/README.md`のセットアップ手順を
  ユーザーに案内する

## 情報源と保守

- CLI本体の設計意図・実装メモ・ファイル構成の一次情報は`tools/web-research/mslearn/README.md`
- サブコマンド・オプション・出力形式・終了コードの一次情報も`tools/web-research/mslearn/`配下
  (`mslearn_cli.py`本体)だが、スキルはClaudeが実行時にリポジトリ外のファイルへジャンプしなくて
  済むよう、意図的にスキル内で自己完結する形で複製している。CLIのオプション名・出力形式・終了コード
  が変わった場合は`output.md`も合わせて更新すること
- 判断フロー・クエリの具体化のコツ・`tav-cli`との使い分けはこのスキル固有の運用方針
  であり、`tools/web-research/mslearn/README.md`には存在しない

二重化した内容のドリフトを防ぐため、CLI仕様を変更するときは次の順で確認する。

1. `tools/web-research/mslearn/README.md`および`mslearn_cli.py`を正本として、CLI本体と仕様を更新する
2. `output.md`の「サブコマンド」「出力形式」「終了コード」を同じ変更内容に更新する
3. オプション名・出力形式・終了条件を両ファイルで突き合わせる

## 実装の背景(なぜ自作したか)

公式が Microsoft Learn MCP サーバー本体と `microsoft-docs` / `microsoft-code-reference`
の Agent Skill 一式を配布しており(`/plugin install microsoft-docs@claude-plugins-official`)、
それを直接使うのが最短ルートではある。それでもあえて`fastmcp`でMCPクライアントを自前で
立ててCLIでラップしたのは学習目的、かつCLI経由にすることで結果を`jq`等の他CLIツールに
流し込める柔軟性が公式スキルにはない利点になるため。実装の詳細(レスポンス形状の実測、
ファイル構成、`tav-cli`との違いなど)や事前調査メモは`tools/web-research/mslearn/README.md`および
`tools/web-research/mslearn/memo/`を参照。
