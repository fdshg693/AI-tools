# inspecting-python-libraries スキルについて

`tools/pyinspect/` の `pyinspect` CLI を、Claude が会話の中からすぐ使えるようにするためのスキル。このファイルは人間のメンテナ向けで、設計意図と前提条件を説明する。Claude が実行時に読むのは [SKILL.md](SKILL.md) であり、こちらは参照しない。

## なぜこのスキルがあるか

- `use-context`（Context7）と web-lookup の `ctx` はドキュメント索引。配布物に入っている実装・公開面・wheel のファイルツリーは対象外。その穴を埋める。
- CLI の `--help` だけでは「いつ `use-context` / `grep-app` ではなくこちらか」「非 0 終了でも索引を Read するか」が固定されない。スキルは判断だけを持つ。
- 初版は Claude Code の `my-tools` だけ。他 AI ツールへはポートしない。

## 前提条件（重要）

- `pyinspect` コマンドは事前にインストール済みであること
  (`uv tool install --editable tools/pyinspect`)。このスキルはインストール処理を一切
  行わず、CLI 本体も同梱しない
- 起動はリポジトリルート。stdout のパスは cwd 相対なので、印字パスをそのまま Read する
- API キー不要
- `PYINSPECT_MAX_BYTES` は任意上書き（未設定でも動く。既定と意味は `tools/pyinspect/README.md`）
- 未インストールでこのスキルが呼ばれた場合、Claude はこのスキルではエラーに対処せず、
  `tools/pyinspect/README.md` のセットアップ手順をユーザーに案内する

## `use-context` / `grep-app` との境界

| 欲しいもの                                                     | 使うもの      |
| -------------------------------------------------------------- | ------------- |
| 公式ドキュメント・セットアップ・移行ガイドの文章               | `use-context` |
| 他リポジトリでの実使用例                                       | `grep-app`    |
| 配布物の中身・実装・実際の公開モジュール（シグネチャ確認含む） | このスキル    |

## 情報源と保守

- CLI 本体の設計意図・フラグ・終了コードの一次情報は `tools/pyinspect/README.md` と `pyinspect --help`
- SKILL.md はルーター。オプション表・終了コード表は転記しない。CLI が変わってもスキル本文は判断フローだけ直せばよい
- `skills/CATALOG.md` / `.claude-plugin/skill-catalog.json` は手編集しない（コミット時 lefthook）
