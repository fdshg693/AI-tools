---
name: inspecting-python-libraries
description: "Downloads a PyPI wheel and writes a local file-tree index so the agent can read a Python library's distribution as a primary source. Use when you need to inspect shipped files, public module surface, or implementation — not docs. Triggers: wheel をダウンロードする, 配布物の中身を読む, inspect a published package, read the actual source of a PyPI library. Prefer `use-context` for official docs, setup, and migration guides; `grep-app` for how other repos use the library."

# 前提条件: `pyinspect` が PATH 上にインストール済み
# (`uv tool install --editable tools/pyinspect`)であること。このスキルはインストール・
# セットアップは一切行わない。API キー不要。`PYINSPECT_MAX_BYTES` は任意上書き
# （未設定でも動く。requires_env には書かない）。
# このスキルの設計意図・前提条件の背景は同階層の README.md 参照（人間のメンテナ向け）。
allowed-tools: "Bash(pyinspect *)"
meta:
  tag: []
  requires_repo_tools: pyinspect
  requires_env: none
  dependencies: none
  requires_install: uv tool install --editable tools/pyinspect
  requires_hooks: none
  requires_skills: none
  status: experimental
  description: no description
  version: 1.0.5
---

## エントリポイント: `pyinspect` コマンド

フラグの正本は `--help`。オプション表は転記しない。毎回実行しなくてよい。
未インストール確認やフラグ確認が必要なときだけ `pyinspect --help` を実行する。

未インストール・エラーが出た場合はこのスキルでは対処しない。ユーザーに
`tools/pyinspect/README.md` のセットアップ手順を案内する。

## 最初に見るべき判断フロー

```text
1. 欲しいのは公式ドキュメント・セットアップ・移行ガイドの文章か?
   Yes -> use-context（このスキルは使わない）
   No  -> 2へ

2. 欲しいのは他リポジトリでの実使用例か?
   Yes -> grep-app（このスキルは使わない）
   No  -> 3へ

3. 欲しいのは配布物の中身・実装・実際の公開モジュールか?
   Yes -> pyinspect（このスキル）
   No  -> 通常の知識または別ツール
```

シグネチャや実装の確認は 3。Microsoft/Azure 公式ドキュメントは `ms-learn`。一般 Web は `tav-cli` / `tav-lit`。

入力は PyPI 名と任意バージョンだけ。extras / URL / git+ は対象外。lockfile / `pyproject.toml` のパスを specifier に渡さない。

このリポジトリで使っている版なら `uv.lock` / `pyproject.toml`（無ければ `pip` lock 等）を読んで `name==version` にする。分からなければ latest。

## 起動

リポジトリルートで実行する。stdout のパスは cwd 相対なので、印字されたパスをそのまま Read する。

```text
pyinspect <name>
pyinspect <name>==<version>
```

版を省略したら毎回 latest を解決し、確定版でキャッシュする。同じ版でも CLI を再実行してよい。キャッシュヒットでも数秒かかることがある（進捗は出ない）。ハングと決めつけず、キャッシュディレクトリを手で探して省略しない。取得自体をスキル読み込み時に走らせない。`--help` 以外の動的注入はしない。

最初は `--import` なしで起動する。公開面は索引の File tree と `__init__.py` / `__all__` で足りることが多い。`--import` はそれらで足りないときだけ付ける。`--module` は `--import` 必須。

`--import` は依存を入れないため、依存のあるパッケージでは失敗（exit 5）が本線。stdout にパスがあれば索引を Read する。Import 欄は末尾の例外行だけ見ればよい。`pass --module` なら一度だけ付けて再実行する。`ModuleNotFoundError` など依存欠落なら再実行せず `__init__.py` / `__all__` を読む。

## 結果の読み方

stdout は `index.md` のパスだけ。中身は出ない。

1. 終了コードが非 0 でも、stdout にパスがあれば Read する（wheel 無し・サイズ超過・import 失敗でも索引は成果物）。パスが無いとき（パッケージ/版が 404 など）だけ諦める。
2. 必ず `index.md` を先に Read する。Recommended paths はヒントであり完全リストではない。先頭を盲信せず File tree から選ぶ。単一ファイルモジュールは Recommended が METADATA だけになることがある。`_` 始まり・空ファイル・複数トップレベルも File tree を見る。Status の wheel 名に `.pyd` / `.so` があれば隣の `.py` を読む。
3. File tree が truncated、または個別 `.py` が大きいときは Grep / `aim --parallel`（`aim-cli`）。通常は Read。
4. 索引本文も個別ファイルもチャットに貼らない。必要なパスだけ Read する。
5. 解釈・要約は CLI もスキルもやらない。エージェントがファイルを読む。
