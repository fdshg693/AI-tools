# tav-cli スキルについて

`tools/tav-cli/`の`tav` CLI(Tavily SDK をプロジェクト固有のデフォルト引数で固定した
Python ラッパー)を、Claudeが会話の中からすぐ使えるようにするためのスキル。このファイルは
人間のメンテナ向けで、設計意図と前提条件を説明する。Claudeが実行時に読むのは
[SKILL.md](SKILL.md)であり、こちらは参照しない。

## なぜこのスキルがあるか

- `tav`は`search`/`search-extract`/`research`/`extract`/`map`/`map-extract`/`crawl`の
  7サブコマンドを持つが、「まずURLが分かっているかで分岐する」「詳細度プリセット
  (`quick`/`balanced`/`max`)をどう選ぶか」「`--topic`のトピックフォルダ運用」といった
  **使い分けの判断フロー**は`tools/tav-cli/README.md`には書かれておらず、それを固定化
  するためにスキル化した
- クエリ言語・ドメインフィルタの実務ルールや、並列実行・レート・コストの扱いも、
  CLI自体の仕様ではなく運用上のノウハウなのでスキル側に持たせている

## 前提条件(重要)

- `tav`コマンドは事前にインストール済みであること
  (`uv tool install --editable tools/tav-cli`)。このスキルはインストール処理を
  一切行わず、CLI本体も同梱しない(以前は`src/`配下にPythonスクリプト本体を同梱して
  直接叩く運用だったが、`tools/tav-cli/`へ切り出した上で廃止した)
- 実行前に`TAVILY_API_KEY`を環境変数、またはグローバル設定`~/.config/tav/config.toml`の`api_key`に設定していること
- 上記が満たされていない環境(未インストール・APIキー未設定)でこのスキルが呼ばれた
  場合、Claudeはこのスキルではエラーに対処せず、`tools/tav-cli/README.md`の
  セットアップ手順をユーザーに案内する

## 情報源と保守

- CLI本体の設計意図・実装メモ・ファイル構成の一次情報は`tools/tav-cli/README.md`
- サブコマンド・オプション・出力形式・終了コードの一次情報も`tools/tav-cli/`配下
  (各スクリプト本体・`tav_core/result_contract.py`)だが、SKILL.mdはClaudeが実行時に
  外部ファイルへジャンプしなくて済むよう、意図的に自己完結する形で複製している。
  CLIのオプション名・出力形式・終了コードが変わった場合はSKILL.mdも合わせて更新すること
- 判断フロー・クエリの具体化のコツ・並列実行やコストの目安はこのスキル固有の運用方針
  であり、`tools/tav-cli/README.md`には存在しない

二重化した内容のドリフトを防ぐため、CLI仕様を変更するときは次の順で確認する。

1. `tools/tav-cli/README.md`および各スクリプト本体を正本として、CLI本体と仕様を更新する
2. `SKILL.md`の「エントリポイント」「`--detail`プリセット早見表」「出力先と`--topic`
   レイアウト」「出力エンベロープと終了コード」を同じ変更内容に更新する
3. オプション名・出力形式・終了条件を両ファイルで突き合わせる

## 実装の背景(なぜPythonラッパーをCLI化したか)

- AI が WEB 調査をするとき、毎回パラメータがブレて品質と費用が読めなくなる問題を
  解決するため、Tavily SDK の細かいオプションを **スクリプト側のプリセットでロック** し、
  AI には「目的」と「詳細度」だけ選ばせる設計にした
- 検索結果を `<TAVILY_OUTPUT_DIR>/<topic>/` 配下(既定 `temp/web/<topic>/`)に
  **トピック単位のレイアウトで** 蓄積し、後段のスクリプトやサブエージェントが拾える
  ようにしている
- 実装の詳細(戻り値契約・共通モジュール構成・型の実測確定など)は
  `tools/tav-cli/README.md`、`tools/tav-cli/experiments/README.md`、
  `tools/tav-cli/tests/README.md` を参照

## 関連スキル

- [tav-lit](../../../../../skills/plugins/web-lookup/skills/tav-lit/README.md): 1 URL・その場限りで読むだけの用途に絞った軽量版
  (ライブラリの前提条件は共有するが、`tav-cli`本体には依存しない独立スクリプト)
- [ms-learn](../ms-learn/README.md): Microsoft/Azure公式ドキュメントが対象ならこちらを優先
- `zenn`(`skills/plugins/others/skills/zenn`): 記事執筆時の外部調査を`tav-cli`経由に
  固定する上位スキル
