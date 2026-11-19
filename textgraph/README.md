# textgraph

**関連スキル: `tools/_plugin/my-tools/skills/textgraph`**

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
textgraph --path C:\src\project check --external
textgraph --path C:\src\project check --json > before.json
textgraph --path C:\src\project check --baseline before.json
textgraph --path C:\src\project fix
textgraph --path C:\src\project fix --apply
textgraph --path C:\src\project fix --scripts --apply
```

- `init` — `.textgraph/` を作り、初回索引を構築する。既にある場合は拒否して `sync` を案内する。
- `sync` — 内容 hash が変わったテキストファイルだけ再抽出する。hash が同じでも索引の mtime はディスクに合わせる（内容を変えずに書き直したファイルで stale が抜けなくなるのを防ぐ）。削除されたファイルは索引から落とす。`--force` は全件再抽出。抽出の挙動が変わる版の textgraph に上げたら、内容の変わっていないファイルにも反映するため `sync --force` する。`init` と `sync` は `updated N, skipped N, removed N` を stdout に 1 行出す。
- `status` — ファイル数・リンク数・`unresolved` 数・最終 sync 時刻と、読み込んだ設定ファイル（`config: <絶対パス>` と `exclude`・`scripts_exclude` のパターン数。無ければ `config: (none)`）。壊れたリンクの一覧は出さない。
- `files` — 索引上のテキストファイルをリポジトリ相対で出す。`--filter` は前方一致。`--max-depth` は人間向けの木を途中で畳む（`--json` は flat な配列のまま）。
- `impact` — あるファイルの inbound（誰が指しているか）を先に、outbound を次に出す。1 hop のみ。未解決の outbound は末尾。`<path>` はリポジトリ相対・絶対・basename。複数ヒットなら候補を出して非 0。
- `check` — outbound のリンク切れと、書かれたパスのままでは当たらないリンクを報告する。対象は索引上 `unresolved`、resolved 先が今の git ファイル集合（とその親ディレクトリ）に無い、または `exact` 以外（`unique-suffix`・`unique-basename`）で解決したもの。wiki `[[name]]` は basename で引くのが本来の意味なので、`unique-basename` で解決しても報告しない。候補が1件なら `suggested`、2件以上は `ambiguous`、0件は `unresolved`。basename 由来の候補（同名ファイル・`git-rename-basename`）と `ambiguous` の候補は、リンクのディレクトリ部分の名前（`.`・`..` を除く）を 1 つ以上パスに含むものだけに絞る。絞って 0 件なら `unresolved`、1 件なら `suggested`（`unique-basename`、適用しない）。basename だけのリンクは絞らない。`impact <basename>` の候補表示は絞らない。http(s) 等は索引に載らないので触れない。`--scripts` は索引に入れず、スクリプトをその場で同じ構文で走査する（コメント判定はしない）。終了コードは問題なし 0、切れ/曖昧あり 1、索引なし/stale/I/O 失敗 2。
  - 索引（git ファイル集合）では exact に当たらないが、書かれたパスがディスク上にファイルかディレクトリとして実在するリンクは status `external`（confidence `on-disk`）。候補探し・git rename より先に判定する。サブモジュールの中のファイル（アンブレラから見た `tools/README.md` など）、`..` でリポジトリルートの外に出るファイル（サブモジュールから見たアンブレラのファイル）、gitignore された生成物がここに入る。見る順は解決順の exact の段と同じ（ソース相対 → ルート相対、拡張子なしなら `.md` を補う）だが、OS のパスで組み立てるのでルートより上も見る。
  - `external` は既定で一覧に出さず、終了コードにも数えない。1 件以上あれば stderr に `N links point outside the index (exist on disk); use --external to list` を 1 行出す。`--external`（`fix` も同じ）で一覧に含める。その場合も終了コードには数えない。
  - Windows のファイルシステムは大小文字を区別しないので、大小文字だけ違うリンクも実在扱いで `external` になることがある（git 集合内のファイルなら先に大小文字無視の exact で拾う）。Junction を辿った先も実在扱いになる。これはリンク 1 件ごとの存在確認で、リポジトリの走査ではない。
  - `--json` は `{"findings": [...], "external": N}` を stdout に出す。各 finding は `source`・`line`・`raw`・`kind`・`status`・`confidence`・`suggested`（配列）・`replacement`（候補が 1 件のときの書き換え後の raw、それ以外は `null`）。`external` は status `external` の件数で、`--external` を付けたときだけその finding も `findings` に入る。`version` キーは持たない（形は textgraph の版数で判断する）。非 ASCII は `files --json` と同じく `\uXXXX` にエスケープする。
  - `--baseline <file>` は以前の `check --json` の出力と比べ、新しく増えた finding だけを表（`--json` 付きなら同じ形の JSON）で出し、解消した件数を stderr に `N findings resolved since the baseline` と 1 行出す。比較キーは `(source, raw, status)` で、`line`・`confidence`・`suggested` は比べない（行番号は編集でずれ、候補は解決の変更でも変わる）。同じキーが複数あるときは件数で比べる。baseline の `source` が今の git ファイル集合に無く、git rename（stage 済みと履歴。`check` の候補と同じ一覧）で今のファイル 1 件に辿れるときは、今のパスに読み替える（ファイルを移動しても、その中の finding は新規にならない）。辿れなければそのままで、その finding は解消扱い。`--external` なしでは baseline 側の `external` も比べない。終了コードは新しい finding（`external` を除く）があれば 1、無ければ 0。baseline が読めない・JSON でない・`findings` の各要素に文字列の `source`/`raw`/`status` が無いときは 2。
  - 移動の手順: 移動前に `check --json > before.json`、`git mv` して `sync` したら `check --baseline before.json`。出た行が移動で増えた切れ。`--scripts`・`--external` は baseline を取ったときと揃える。
- `fix` — 既定は dry-run。適用予定の hunk 要約だけ出す。`--apply` は一意の `unique-suffix` と `git-rename` だけ本文のリンク先パスを書き換える。リンクテキストと `@./` 構文は維持する。`unique-basename`・`git-rename-basename`（旧パスが一致せず basename だけで当たった rename）・`ambiguous` は suggested に出しても適用しない。`external` は実在するリンクなので書き換えない。元の改行（LF / CRLF / 混在）は書き換えた行も含めてそのまま保つ。`--scripts` と `--external` は `check` と同じ範囲。`--apply` 後も残り（`external` を除く）があれば 1。
- `--version` — マニフェストの版数を1行出す。`.git` も索引も触らない。

`files` / `impact` / `check` / `fix` は索引が無い、またはソースが索引より新しい（未索引のドキュメント追加を含む）ときは `sync` を案内して非 0（`files`/`impact` は 1、`check`/`fix` は 2）。クエリ側で自動 sync はしない。ソース本文は出さない。`fix --apply` のあと索引は古くなるので、直したドキュメントを確認するなら `sync` してから `check` する。`--scripts` で直したスクリプトは索引に無いので、確認も `check --scripts`。

索引はリポジトリ直下の `.textgraph/graph.db`（SQLite）。パスは POSIX 相対で保存する。`.textgraph/` は gitignore 対象で、ソースには置かない。無い・古いときは `init` / `sync` で作り直す。

## 対象と抽出

走査対象は `git ls-files --cached --others --exclude-standard` のうち、既定拡張子 `.md` / `.mdc` / `.txt` / `.rst`。これらだけを索引する。スクリプトの変更では索引は stale にならない。`.textgraph.toml` の `exclude` に一致するファイルは索引しない（[設定](#設定)）。

`check --scripts` / `fix --scripts` は索引には入れず、スクリプトをその場で同じリンク構文で走査する。コメントとコードの区別はしない（`[text](url)` や `@./` が実行コードに現れることはほぼ無いため）。対象は `.py` / `.ts` / `.js` / `.ps1` / `.sh` などのソース拡張子と、basename が `justfile` / `makefile` のもの。YAML / JSON は対象外。`exclude`・`scripts_exclude` に一致するスクリプトは走査しない。抽出した raw のうち、`{`・`}`・`[`・`]`・`$`・`*` を含むもの（f-string・テンプレート・正規表現・glob の断片）、`\` を含むもの（エスケープ付きの文字列・正規表現。Windows のパス区切りも含む）、`/` も `.` も含まないもの（コード中の `FORMATTERS[fmt](results)` のような断片。拡張子なしのリンク・wiki `[[name]]`・`README#sec` も一緒に捨てる）はスクリプトでは常に捨てる。ドキュメントでは同じ raw を報告し続ける（`[x]({var})`・`[x](README)` はドキュメントなら本物の誤記）。`.` を含むコード中の `a[b](c)`（`FORMATTERS[x](self.results)` など）は捨てられずに誤検出として残りうるので、`scripts_exclude` で外すか、コメントならバッククォートで囲んで消す。その場で再解決し、判定はドキュメントと同じ（`exact` 以外の解決も報告する）。索引に残った古い解決先をきっかけにする書き換えはドキュメント側の話で、スクリプトでは今の解決結果と `git-rename` が対象になる。

抽出するリンク:

- Markdown インライン `[text](url)`、画像 `![alt](url)`、参照定義 `[label]: url`
- wiki `[[path]]` / `[[path|label]]`
- `@./` と `@../` のローカルパス（行頭でも行中でも）

http(s) / mailto / アンカーのみは無視する。フェンスコードとインラインのコードスパンの中は走査しない。コードスパンは CommonMark どおり、n 個連続するバッククォートで開き、ちょうど n 個の連続で閉じる（` ``[[name]]`` ` の中も走査しない）。閉じは同じ段落の中でだけ探す。段落の終わりは空行（空白だけの行を含む）で判定し、見出し・リスト・フェンスの開始では切らない。段落内の改行をまたぐコードスパンは隠す。スクリプト（`--scripts`）にも同じ規則を当てる。段落内に閉じが無ければ開きのバッククォートは通常の文字として扱う。

解決順: ソースディレクトリ相対 → リポジトリルート相対 → 大小文字無視 → 拡張子なしなら `.md` を補う → 一意 basename → 一意 path suffix。ディレクトリリンクは `README.md` / `AGENTS.md` / `index.md` をこの順で `exact` とみなし、どれも無ければ git ファイルの親として実在するディレクトリそのもの（末尾 `/` なしのパス）を `exact` で解決する（ディスクは見ない）。`impact` の inbound はファイル単位なので、ディレクトリそのものへのリンクは inbound に出ない。ソース相対・ルート相対で当たらない `../` 付きのリンクは、`..` より後ろの部分が一意 suffix で当たっても `unique-suffix`（非 exact）なので `check` が報告し、`fix --apply` で直せる。`check` / `fix` だけ、それでも決まらないリンクに git rename を足す。使うのは stage 済みの rename（`git diff --cached`、コミット前の `git mv` を含む）とコミット済みの rename（`git log` の全履歴）で、stage 済みを優先する。移動先がもう無ければ、その後の rename を辿って今あるファイルまで進む（A→B→C なら C）。rename の一覧は 1 回の実行で最初に必要になったときに 1 回だけ取り、切れが無ければ git を呼ばない。stage していない作業ツリーだけの移動（`mv`）は git が rename として検出できないので、`git mv` するか `git add -A` してから `check` する。

## 設定

`--path` で指すリポジトリルート（`.git` があるディレクトリ）の `.textgraph.toml` だけを読む。無ければ何も除外しない。記入例は [config.example.toml](config.example.toml)。

```toml
exclude = ["plugins/*/skills/*/output/**"]
scripts_exclude = ["**/tests/**"]
```

- `exclude` — 一致するパスを索引・stale 判定・`--scripts` の走査から外す。外すのはリンク元としてだけで、リンク先の解決に使うファイル集合には残す。除外したファイルへのリンクは今までどおり `exact` で解決し、切れにならない
- `scripts_exclude` — 一致するパスを `check --scripts` / `fix --scripts` の走査からだけ外す。ドキュメントの索引には効かない
- glob はルートからのリポジトリ相対パス全体に当てる（gitignore のような途中一致はしない）。`*`・`?`・`[abc]`・`[!abc]` は 1 セグメントの中だけ、`**` のセグメントは 0 個以上のディレクトリ、末尾の `**` は配下すべて、末尾の `/` は `/**` と同じ。先頭の `./`・`/` は無視する。どのディレクトリの `tests` でも外すなら `**/tests/**` と書く
- 未知のキー・型違い（`exclude = "a/**"` のような配列でない値、文字列でない要素、空文字）・TOML の構文エラーは、ファイルの絶対パス付きのメッセージを stderr に出して終了コード 2 で止める（`--version` 以外のすべてのコマンド）
- 設定を変えたら `sync` する。設定の変更そのものは stale 判定に入れないが、除外を増やす・減らすと索引すべきファイルの一覧が変わるので、`files`・`impact`・`check`・`fix` は stale として `sync` を案内する

[tool-conventions](../../maintenance/docs/tool-conventions.md) のレイヤー設定（環境変数 → CWD から遡るプロジェクト設定 → グローバル設定）は使わない。索引はリポジトリルート単位なので、CWD によって除外が変わると `sync` と `check` の範囲がずれる。除外はリポジトリ固有の内容で、グローバルな既定値や環境変数で切り替える意味も無い。未知のキーと型違いを止める・`tomllib` で読む・`config.example.toml` を置く点は規約に従う。

## ファイル構成

- `textgraph/cli.py` — エントリポイント
- `textgraph/extract.py` — リンク抽出
- `textgraph/resolve.py` — 解決カスケード
- `textgraph/scan.py` — git 走査と増分 sync
- `textgraph/store.py` — SQLite 索引
- `textgraph/query.py` — `files` / `impact` の読み取り
- `textgraph/check.py` — `check` / `fix` と git rename 候補
- `textgraph/config.py` — `.textgraph.toml` の読み込み・検証と glob の一致
- `tests/` — 抽出・解決・設定・init/sync/status・files/impact・check/fix・`check --baseline`
