# textgraph

**関連スキル: `claude-plugins/my-tools/skills/textgraph`**

テキストファイルのローカルファイルリンクを索引し、参照関係をクエリするための CLI。索引の作成・更新・健康確認、索引済みファイル一覧・1 hop の impact、リンク切れの報告と一意候補の書き換えを提供する（`init` / `sync` / `status` / `files` / `impact` / `check` / `fix`）。

CodeGraph がソースコードの呼び出し関係を索引するのと同じ役割を、Markdown 等のローカルリンクに対して持つ。API キーは不要。追加の Python 依存もない。

## インストール

グローバル CLI として使う場合は `uv tool install --editable`（`pip install -e` の代替）でエディタブルインストールする。リポジトリルートから実行可能。

```powershell
uv tool install --editable tools/textgraph
```

`docs/integrations/justfile` からも入れられる。

```powershell
just -f docs/integrations/justfile textgraph-local
just -f docs/integrations/justfile textgraph-git
```

インストール後は `textgraph` コマンドが PATH 上でどこからでも使える。テストはリポジトリルート、またはツールディレクトリから実行できる。

```powershell
uv run pytest tools/textgraph/tests
uv run --directory tools/textgraph pytest
```

## 使い方

カレントディレクトリが git リポジトリの外でも、親へ `.git` を辿る。Cursor 等が cwd をプロジェクトルートにしないことがあるため、`--path` でルートを明示できる。`--path` は `.git` があるディレクトリそのものを指す。

```powershell
textgraph --version
textgraph --path C:\src\project init
textgraph --path C:\src\project sync
textgraph --path C:\src\project sync --force
textgraph --path C:\src\project status
textgraph --path C:\src\project files
textgraph --path C:\src\project files --max-depth 2 --filter docs
textgraph --path C:\src\project files --json
textgraph --path C:\src\project impact docs/guide.md
textgraph --path C:\src\project impact guide.md --json
textgraph --path C:\src\project check
textgraph --path C:\src\project check --scripts
textgraph --path C:\src\project fix
textgraph --path C:\src\project fix --apply
textgraph --path C:\src\project fix --scripts --apply
```

- `init` — `.textgraph/` を作り、初回索引を構築する。既にある場合は拒否して `sync` を案内する。
- `sync` — 内容 hash が変わったテキストファイルだけ再抽出する。削除されたファイルは索引から落とす。`--force` は全件再抽出。
- `status` — ファイル数・リンク数・`unresolved` 数・最終 sync 時刻。壊れたリンクの一覧は出さない。
- `files` — 索引上のテキストファイルをリポジトリ相対で出す。`--filter` は前方一致。`--max-depth` は人間向けの木を途中で畳む（`--json` は flat な配列のまま）。
- `impact` — あるファイルの inbound（誰が指しているか）を先に、outbound を次に出す。1 hop のみ。未解決の outbound は末尾。`<path>` はリポジトリ相対・絶対・basename。複数ヒットなら候補を出して非 0。
- `check` — outbound のリンク切れを報告する。切れは索引上 `unresolved`、または resolved 先が今の git ファイル集合に無いもの。候補が1件なら `suggested`、2件以上は `ambiguous`、0件は `unresolved`。http(s) 等は索引に載らないので触れない。`--scripts` は索引に入れず、スクリプトをその場で同じ構文で走査する（コメント判定はしない）。終了コードは問題なし 0、切れ/曖昧あり 1、索引なし/stale/I/O 失敗 2。
- `fix` — 既定は dry-run。適用予定の hunk 要約だけ出す。`--apply` は一意の `unique-suffix` と `git-rename` だけ本文のリンク先パスを書き換える。リンクテキストと `@./` 構文は維持する。`unique-basename` と `ambiguous` は suggested に出しても適用しない。`--scripts` は `check` と同じ範囲。`--apply` 後も残りがあれば 1。
- `--version` — マニフェストの版数を1行出す。`.git` も索引も触らない。

`files` / `impact` / `check` / `fix` は索引が無い、またはソースが索引より新しい（未索引のドキュメント追加を含む）ときは `sync` を案内して非 0（`files`/`impact` は 1、`check`/`fix` は 2）。クエリ側で自動 sync はしない。ソース本文は出さない。`fix --apply` のあと索引は古くなるので、直したドキュメントを確認するなら `sync` してから `check` する。`--scripts` で直したスクリプトは索引に無いので、確認も `check --scripts`。

索引はリポジトリ直下の `.textgraph/graph.db`（SQLite）。パスは POSIX 相対で保存する。`.textgraph/` は gitignore 対象で、ソースには置かない。無い・古いときは `init` / `sync` で作り直す。

## 対象と抽出

走査対象は `git ls-files --cached --others --exclude-standard` のうち、既定拡張子 `.md` / `.mdc` / `.txt` / `.rst`。これらだけを索引する。スクリプトの変更では索引は stale にならない。

`check --scripts` / `fix --scripts` は索引には入れず、スクリプトをその場で同じリンク構文で走査する。コメントとコードの区別はしない（`[text](url)` や `@./` が実行コードに現れることはほぼ無いため）。対象は `.py` / `.ts` / `.js` / `.ps1` / `.sh` などのソース拡張子と、basename が `justfile` / `makefile` のもの。YAML / JSON は対象外。その場で再解決するため、今も unique-suffix で当たるリンクは切れではない。索引に残った古い解決先をきっかけにする書き換えはドキュメント側の話で、スクリプトでは今解決できないリンクと `git-rename` が対象になる。

抽出するリンク:

- Markdown インライン `[text](url)`、画像 `![alt](url)`、参照定義 `[label]: url`
- wiki `[[path]]` / `[[path|label]]`
- `@./` と `@../` のローカルパス（行頭でも行中でも）

http(s) / mailto / アンカーのみは無視する。フェンスコードとインラインバッククォートの中は走査しない。

解決順: ソースディレクトリ相対 → リポジトリルート相対 → 大小文字無視 → 拡張子なしなら `.md` を補う → 一意 basename → 一意 path suffix。ディレクトリリンクは `README.md` / `AGENTS.md` / `index.md` をこの順で `exact` とみなす。`check` / `fix` だけ、それでも決まらないリンクにコミット済みの git rename を足す。

## ファイル構成

- `textgraph/cli.py` — エントリポイント
- `textgraph/extract.py` — リンク抽出
- `textgraph/resolve.py` — 解決カスケード
- `textgraph/scan.py` — git 走査と増分 sync
- `textgraph/store.py` — SQLite 索引
- `textgraph/query.py` — `files` / `impact` の読み取り
- `textgraph/check.py` — `check` / `fix` と git rename 候補
- `tests/` — 抽出・解決・init/sync/status・files/impact・check/fix
