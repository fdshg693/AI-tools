@./README.md

## このフォルダだけを開いたとき

アンブレラ（fdshg693/AI）の `tools/` として clone されている前提。共通の手順（Junction・フックの作り方、`_umbrella/` の扱い、2 段階コミット）は [repo-layout](../maintenance/docs/repo-layout.md#サブモジュールを単体で開く)。

- CLI を登録・公開するかは `_umbrella/registry/repo-tools.yaml`、`_plugin/my-tools` の公開は `_umbrella/registry/ai-tools.yaml` で決まる。ツールを足す・消すときはアンブレラ側で先にそこを更新する。
- `_plugin/my-tools` のスキルを書くときの手引きは `writing-skill` スキル（Junction で見えている）。
- `uv run` はアンブレラの uv workspace を使う。このフォルダ直下に `pyproject.toml` を置かない。単体 clone ではツールごとに `uv run --project <name>` で動かす。
