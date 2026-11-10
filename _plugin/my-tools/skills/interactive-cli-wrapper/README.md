# interactive-cli-wrapper スキルについて

`tools/interactive-cli-wrapper/`の`icw` CLI(PTY越しに対話的CLIを駆動する自作ラッパー)を、Claudeが会話の中からすぐ使えるようにするためのスキル。このファイルは人間のメンテナ向けで、設計意図と前提条件を説明する。Claudeが実行時に読むのは[SKILL.md](SKILL.md)(と、対象CLIに応じて追加で読む個別ファイル)であり、こちらは参照しない。

## なぜこのスキルがあるか

- 非対話フラグ(`-p`/`--print`)を持たない、またはそのフラグでは目的(対話履歴を保った複数ターンのやり取り、スラッシュコマンド操作等)を果たせない対話的CLIを、AIエージェントの「1アクション=1回のBashツール呼び出し」という制約の中で駆動する手段が無かった。`icw`(PTY駆動コア + セッション永続化つきCLI)はその汎用的な解決策として`tools/interactive-cli-wrapper/`に実装した。設計・実装の経緯全体は[tools/interactive-cli-wrapper/README.md](../../../../interactive-cli-wrapper/README.md)を参照。
- **cursor-cli-use**スキル(Cursor CLI `agent`の非対話`-p`単発実行)とはスコープが異なる。あちらは「他のCLIエージェントへの一撃タスク委譲」、こちらは「非対話フラグでは表現できない対話セッションの駆動」。両者の使い分けは[SKILL.md](SKILL.md)の「cursor-cli-useとの使い分け」節に書いてある(実行時にClaudeが参照する判断はそちらが正)。

## ファイル構成の設計判断: なぜSKILL.mdを薄いルーターにしたか

`icw`自体は特定のCLIに依存しない汎用ツールだが、実際に対象CLIを繋ぐと(Step4での`agent`接続がそうだったように)そのCLI固有の癖・チューニング値(起動待機時間、送信方式、ready-patternの可否等)が積み上がる。これを全部`SKILL.md`本体に書くと、

1. 汎用の使い方を知りたいだけの場面でも対象CLI固有の詳細を読み込むことになり本文が肥大化する
2. 別の対象CLIを繋ぐたびに`SKILL.md`本体が際限なく伸びる

という問題が出る。[writing-skill](../../../../../skills/plugins/cc-knowledge/skills/writing-skill/writing.md)の「同じスキルの中の観点違いなら、`SKILL.md`はルーターに徹する」方針に従い、**`SKILL.md`は汎用の使い方(start/send/stop/list、idle-timeout/ready-patternの考え方、cursor-cli-useとの使い分け)だけに留め、対象CLIごとの個別知見は`<cli-name>.md`として同階層に切り出す**構成にした。現時点では[cursor-agent.md](cursor-agent.md)(Cursor CLI `agent`対話モード)のみ存在する。今後別の対話CLIを繋いだ場合も、同じ形で`<cli-name>.md`を追加していく想定。

## 前提条件(重要)

- `icw`コマンドは事前にインストール済みであること(`uv tool install --editable tools/interactive-cli-wrapper`)。このスキルはインストール処理を一切行わず、CLI本体も同梱しない
- Windows(ConPTY)専用。`pywinpty`はWindows専用ライブラリで他OS向けバックエンドは無い(このリポジトリ自体がWindows環境前提のための制約。詳細は`tools/interactive-cli-wrapper/README.md`)
- 上記が満たされていない環境(未インストール)でこのスキルが呼ばれた場合、Claudeはこのスキルではエラーに対処せず、`tools/interactive-cli-wrapper/README.md`のセットアップ手順をユーザーに案内する
- 対話CLI(特に`agent`のような課金・副作用のあるエージェントCLI)をバックグラウンドセッションとして起動・駆動する副作用があるため、`SKILL.md`は`disable-model-invocation: true`にしてある(cursor-cli-useと同じ理由。ユーザーの明示呼び出し`/interactive-cli-wrapper`に限定)

## 情報源と保守

- CLI本体(`icw`)の設計意図・実装メモ・カスタマイズ箇所の一次情報は`tools/interactive-cli-wrapper/README.md`
- サブコマンド・オプションの一次情報も`tools/interactive-cli-wrapper/icw_cli.py`本体だが、`SKILL.md`はClaudeが実行時に外部ファイルへジャンプしなくて済むよう、意図的に自己完結する形で複製している。オプション名・出力形式が変わった場合は`SKILL.md`も合わせて更新すること
- `cursor-agent.md`の内容(起動グレース期間・`--submit-separately`が必要な理由・`ready_pattern`の非採用)は、Cursor CLIの特定バージョン(`2026.07.23-e383d2b`)での実地検証結果。CLIのアップデートで挙動が変わった場合は再検証が必要(否定された仮説を含む詳しい切り分け過程は`cursor-agent.md`の「詳しい調査過程」節参照)
- 判断フロー・cursor-cli-useとの棲み分けはこのスキル固有の運用方針であり、`tools/interactive-cli-wrapper/README.md`には存在しない

二重化した内容のドリフトを防ぐため、CLI仕様を変更するときは次の順で確認する。

1. `tools/interactive-cli-wrapper/README.md`および`icw_cli.py`を正本として、CLI本体と仕様を更新する
2. `SKILL.md`のサブコマンド・オプション説明を同じ変更内容に更新する
3. 対象CLI固有の癖(`cursor-agent.md`等)が変更の影響を受けていないか確認する
