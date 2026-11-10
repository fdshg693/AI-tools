# textgraph スキルについて

`tools/textgraph/` の `textgraph` CLI（テキストファイルのローカルリンクグラフ）を、Claude が会話の中からすぐ判断・実行できるようにするためのスキル。このファイルは人間のメンテナ向けで、設計意図と前提条件を説明する。Claude が実行時に読むのは [SKILL.md](SKILL.md) であり、こちらは参照しない。

## なぜこのスキルがあるか

[tool-companion-skills](../../../../../maintenance/docs/tool-companion-skills.md) の併設判断基準（フラグの選び方、誤ると後続が壊れる意味論）に該当するため併設した。

- `status` / `files` / `impact` / `check` / `fix` のどれを先に叩くかは `--help` だけでは割れる。件数確認と切れ検出と inbound 照会を取り違えると、広い grep に落ちるか、無関係なファイルを `--apply` する
- 既定の走査はドキュメント拡張子だけ。スクリプトコメントの同じ構文を見るかは `check --scripts` の判断であり、`--help` の有無だけでは「いつ付けるか」は決まらない
- `--apply` してよい信頼度は `unique-suffix` と `git-rename` だけ。`unique-basename` は一意でも誤ることがある、という運用は CLI の `--help` に出てこない
- CodeGraph との役割分担（コードの流れ vs テキストのローカル参照）と、YAML/import を grep に落とす条件も、ツール README のコマンド説明だけでは固定されない

## 前提条件（重要）

- `textgraph` コマンドは事前にインストール済みであること（`uv tool install --editable tools/textgraph`）。このスキルはインストール処理を一切行わず、CLI 本体も同梱しない
- API キーは不要。索引は対象リポジトリ直下の `.textgraph/`（gitignore）
- 上記が満たされていない環境でこのスキルが呼ばれた場合、Claude はこのスキルではエラーに対処せず、`tools/textgraph/README.md` のセットアップ手順をユーザーに案内する

## 情報源と保守

- CLI オプション・抽出対象・解決カスケード・終了コードの一次情報は `tools/textgraph/README.md`
- SKILL.md は判断基準だけを持ち、`--help` のフラグ表を複製しない
- `impact` vs `check` vs grep、`--apply` 可否の判断基準はこのスキル固有の運用方針であり、ツール README には（コマンドの意味としては書かれていても、エージェント向けの分岐としては）置かない

二重化した内容のドリフトを防ぐため、CLI 仕様を変更するときは次の順で確認する。

1. `tools/textgraph/README.md` を正本として、CLI 本体と仕様を更新する
2. SKILL.md の「どれを使うか」「`fix --apply` してよいか」「grep に落とす条件」が同じ変更に追従しているか確認する（フラグ表は復活させない）。`--scripts` を付ける判断もスキル側。
