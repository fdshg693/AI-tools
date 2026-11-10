---
name: tav-cli
description: Guides multi-step Tavily research with this project's `tav` command, including web-wide search, multiple URLs, site maps/crawls, and topic-based result accumulation. Use when a task needs more than one known URL or a reusable research workspace; use `tav-lit` to extract one already-known URL.

# 前提条件: `tav`コマンドがPATH上にインストール済み
# (`uv tool install --editable tools/tav-cli`)であること。このスキルはインストール・
# セットアップは一切行わない。CLI本体は同梱せず、Pythonスクリプトを直接叩く運用は廃止した
# (実体は tools/tav-cli/ を参照)。
# 実行前に TAVILY_API_KEY を環境変数、またはグローバル設定 ~/.config/tav/config.toml の api_key に設定していること
# 出力先などはプロジェクト設定 .tav.toml(CWD〜git ルートで近いものが勝つ)・グローバル設定・環境変数で設定でき、TAVILY_OUTPUT_DIR(出力先ベース、未設定時は git ルート基準の temp/web)・TAVILY_WRITE_LOG(監査ログ出力トグル、未設定=true)・TAVILY_SHOW_LOG_PATH(監査ログ書き込み時の「Wrote full log to <path>」通知トグル、未設定=true。結果ファイルのパス通知は常に表示)も設定できる
# このスキルの設計意図・前提条件の背景は同階層のREADME.md参照(人間のメンテナ向け)

# ```!```を使った動的コンテキスト埋め込みを使い、更新漏れを防止する
# 参考: https://code.claude.com/docs/en/skills#inject-dynamic-context
meta:
  tag: []
  requires_repo_tools: tav
  requires_env: TAVILY_API_KEY, TAVILY_OUTPUT_DIR, TAVILY_LOG_DIR, TAVILY_WRITE_LOG, TAVILY_SHOW_LOG_PATH
  dependencies: tavily-python
  requires_install: uv tool install --editable tools/tav-cli
  requires_hooks: none
  requires_skills: none
  status: stable
  description: no description
  version: 1.2.5
---

## エントリポイント: `tav` コマンド

tav --help で、利用可能なコマンドと引数の概要を確認できます。

```!
tav --help
```

未インストール・エラーが出た場合はこのスキルでは対処しない。ユーザーに
`tools/tav-cli/README.md` のセットアップ手順を案内する。

## クエリ言語とドメインフィルタの実務ルール

- `query` や `input` は **日本語でも問題なく使ってよい**。特に記事調査や要件整理では、日本語の問いをそのまま渡して構わない。
- ただし、製品名、機能名、正式ドキュメント名は英語のほうが強いことがある。日本語で結果が弱い場合は、英語または日英混在クエリで再実行する。
- `--include-domain` は「その host を優先・許可するための強い絞り込み」と考え、**厳密な完全一致隔離フィルタ** だと思わないこと。
- 実際には、関連する Microsoft 系サブドメインやリダイレクト先が返ることがある。`microsoft.com` のように広い指定より、`learn.microsoft.com` や `techcommunity.microsoft.com` のような狭い host 指定を優先する。
- 返ってきた URL が想定外なら、後段で URL 一覧を見て手動またはスクリプト側で再選別する。

## 最初に見るべき判断フロー

初見で迷ったら、以下の順で選ぶ。

```text
1. すでに対象 URL が分かっているか?
   Yes -> tav extract
   No  -> 2 へ

2. すでに対象サイトのルート URL が分かっているか?
   Yes -> 3 へ
   No  -> 4 へ

3. サイトに対して何をしたいか?
   ページ一覧や構造を見たい              -> tav map
   サイト本文を一気に回収したい          -> tav crawl
   先に候補 URL を見てから本文抽出したい -> tav map-extract

4. 手元にあるのは topic / question / keyword だけか?
   Yes -> 5 へ
  No  -> 追加の入力条件を整理してから再判定

5. キーワード起点なら何がほしいか?
   まず関連 URL と要約だけ見たい        -> tav search
   まず根拠 URL を広く集めたい           -> tav search
   関連 URL の本文まで続けて取りたい     -> tav search-extract
   AI に調査と要約まで任せたい           -> tav research
```

迷った場合のデフォルトは以下。

- topic 起点なら、まず `tav search`
- URL 起点なら、まず `tav extract`
- サイト起点なら、まず `tav map`
- なお URL 本文の取得は `tav extract` を使い、Python などで直接 HTML を取る方法はこのスキルでは原則非推奨。

## Windows / bash の注意

- `tav` はインストール済みなら PowerShell でも bash でもそのまま `tav search "..."` で呼べる(PATH 上の console コマンドなので、シェルによるパス記法の差を受けない)。
- 出力先は `--topic <name>` で指定する(トピック名のスラッグだけ。実際の保存先は `<TAVILY_OUTPUT_DIR>/<topic>/` に解決される)。`--topic` を省くと単一 `ResultEnvelope` を stdout に出す。シェルによるパス記法の差を受けないのが利点。
- Python スクリプトを直接叩く運用(`python .../search_topic.py ...`)はこのスキルでは行わない。常にインストール済みの `tav` コマンド経由で呼ぶこと。未インストールの場合は対処せず、`tools/tav-cli/README.md` のセットアップ手順をユーザーに案内する。

## `--detail` プリセット早見表

各スクリプトの `DETAIL_PRESETS` が正本。ここではスクリプト横断で比較しやすいように主要パラメータだけ抜き出す。

| 対象                 | `quick`                                                                    | `balanced`                                                                    | `max`                                                                         |
| -------------------- | -------------------------------------------------------------------------- | ----------------------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| `tav search`         | `search_depth=fast`, `max_results=5`, `chunks=2`                           | `search_depth=advanced`, `max_results=5`, `chunks=3`                          | `search_depth=advanced`, `max_results=8`, `chunks=5`                          |
| `tav research`       | `model=mini`, 前景`<=150s`/背景`<=900s`                                    | `model=auto`, 前景`<=360s`/背景`<=1800s`                                      | `model=pro`, 前景`<=420s`/背景`<=1800s`                                       |
| `tav extract`        | `extract_depth=basic`, `query_chunks=2`                                    | `extract_depth=advanced`, `query_chunks=3`                                    | `extract_depth=advanced`, `query_chunks=5`                                    |
| `tav crawl`          | `depth=1`, `breadth=20`, `limit=10`, `extract=basic`, `query_chunks=2`     | `depth=2`, `breadth=30`, `limit=20`, `extract=advanced`, `query_chunks=3`     | `depth=3`, `breadth=40`, `limit=40`, `extract=advanced`, `query_chunks=5`     |
| `tav map`            | `map_depth=1`, `breadth=20`, `limit=20`, `title_workers=4`                 | `map_depth=2`, `breadth=30`, `limit=40`, `title_workers=6`                    | `map_depth=3`, `breadth=40`, `limit=80`, `title_workers=8`                    |
| `tav map-extract`    | `map_limit=10`, `extract=basic`, `query_chunks=2`                          | `map_limit=20`, `extract=advanced`, `query_chunks=3`                          | `map_limit=40`, `extract=advanced`, `query_chunks=5`                          |
| `tav search-extract` | `search_results=5`, `search_chunks=2`, `extract=basic`, `extract_chunks=2` | `search_results=5`, `search_chunks=3`, `extract=advanced`, `extract_chunks=3` | `search_results=8`, `search_chunks=5`, `extract=advanced`, `extract_chunks=5` |

使い分けの目安:

- まず当たりを付ける探索段階: `quick`
- 普段の標準: `balanced`
- URL 数や抽出粒度を増やしたい再実行: `max`

`tav research` の待機は **前景 / 背景の二段**(実測で非自明な research は ~270〜350 秒かかる)。**前景**は呼び出し側をブロックする時間で、典型完了時間より長めに取ってあるので多くは前景内に完了し、その場でレポートを受け取れる。前景内に終わらなければ `INCOMPLETE`(終了コード `5`)を即返し、`--topic` 指定時はデタッチした **背景ポーラ**(`research_background_poll.py`)を起動してそのまま調査を続行する。背景ポーラは完了すれば `research/NNNN-<question>.md` を後から書き込み、背景時間内にも終わらなければ何も書かず監査ログだけに記録する。**失敗・未完では出力ファイルを残さない**(「レポートか、無か」)。前景が長いので呼び出し側は `tav research` をバックグラウンド実行にして待つのも可。

`--query`/`query_chunks` の挙動に注意: `extract` / `crawl` / `*-extract` で `--query` を渡すと、本文全体ではなく **query に関連するチャンクだけ** を返す(`query_chunks` がその上限)。出力に現れる `[...]` はチャンク境界(=途中が省かれた非連続抽出)で、抽出失敗ではない。**本文を丸ごと取りたいときは `--query` を付けず、必要なら `--detail max` で再実行する**。

## 出力先と `--topic` レイアウト

出力先はフルパスではなく `--topic <name>` で指定する。実際の保存先は `<TAVILY_OUTPUT_DIR>/<topic>/`(設定の `output_dir` / `TAVILY_OUTPUT_DIR`、未設定時は git ルート基準の `temp/web`。有効値は `tav config` で確認)に解決される。`topic` は **記事やテーマ単位の「調査タスクをためる作業場」** で、短いスラッグ(英数字と `_`)に揃える。同じ `--topic` を何度叩いても**上書きせず追記**していく(下記)。

- `--topic <name>` を渡す → トピックフォルダ配下に**役割サブフォルダ**で書き出す(下記)。
- `--topic` を省く → 単一 `ResultEnvelope`(投影済み)を stdout に出す(パイプ用途。従来どおり)。

トピックフォルダ内は、出力の**役割**でサブフォルダを分ける(役割が違うものを同じ連番列に混ぜない)。

| 役割                        | コマンド                              | 置き場             | 形式                                                                                      | 単位                          |
| --------------------------- | ------------------------------------- | ------------------ | ----------------------------------------------------------------------------------------- | ----------------------------- |
| **discovery(候補メニュー)** | `search` → `search/` / `map` → `map/` | `NNNN-<slug>.json` | **集約 JSON リスト**(1 タスク=1 ファイル、URL 単位に分割しない)                           | 1 クエリ / 1 map = 1 ファイル |
| **content(取得本文)**       | `extract` / `crawl`                   | `pages/`           | **分割 Markdown**(`# <title>` + 本文)+ `pages/index.json`                                 | 1 ページ = 1 ファイル         |
| **report(成果物)**          | `research`                            | `research/`        | **単一 Markdown**(成功時のみ。失敗/未完は書かない=背景ポーラが後から完成 or 監査ログのみ) | 1 問い = 1 ファイル           |

レイアウト例:

```text
temp/web/                                   ← output_dir(.tav.toml / config.toml / TAVILY_OUTPUT_DIR)
└── msfabric_overview/                      ← <topic>(調査タスクの作業場)
    ├── search/                             ← discovery: 1 クエリ = 1 ファイル
    │   ├── 0001-microsoft-fabric-overview.json
    │   └── 0002-fabric-vs-synapse.json
    ├── map/                                ← discovery: 1 map = 1 ファイル
    │   └── 0001-learn-microsoft-com.json
    ├── pages/                              ← content: 1 ページ = 1 .md
    │   ├── 0001-onelake-documentation.md
    │   ├── 0002-medallion-lakehouse.md
    │   └── index.json                      ← url ↔ file ↔ title ↔ 由来コマンド の対応表
    └── research/                           ← report: 1 問い = 1 .md
        └── 0001-how-does-obo-work.md
```

`pages/index.json` の形(content 系が append。1 ページ = 1 エントリ):

```json
{
  "topic": "msfabric_overview",
  "entries": [
    {
      "file": "0001-onelake-documentation.md",
      "url": "https://…",
      "title": "…",
      "title_source": "html|existing|url_fallback",
      "script": "extract_url_content.py",
      "result_kind": "extract_results",
      "exit_code": 0,
      "char_count": 4213
    }
  ]
}
```

`char_count` は書き出した `.md` の文字数(`len()`)。`pages/index.json` を Read した時点でどの
ページを直接 Read し、どれを `aim --parallel` にまとめて回すか(`tav-digest` スキル参照)を、
個別に開かず判断できる。

例(コマンド):

- `tav search "Microsoft Fabric overview" --include-domain learn.microsoft.com --topic msfabric_overview` → `temp/web/msfabric_overview/search/0001-microsoft-fabric-overview.json`
- `tav map-extract https://learn.microsoft.com/azure/api-management/ --topic apim_docs` → `temp/web/apim_docs/map/0001-learn-microsoft-com.json` + `pages/NNNN-<title>.md …` + `pages/index.json`

## 出力エンベロープと終了コード

各コマンドが書き出す JSON は **自己記述エンベロープ** で、トップレベルは常に同じ形。生の配列ではない。

```json
{
  "script": "...",
  "result_kind": "search_results",
  "exit_code": 0,
  "result": [/* 本体 */]
}
```

- 出力先は `--topic` の有無で決まる。`--topic <name>` 指定時はトピックフォルダ配下の役割サブフォルダ(上記レイアウト)へ、未指定時は単一 `ResultEnvelope`(投影済み)を stdout へ出す。
- `--topic` 指定時の読み方は**役割で違う**:
  - **discovery**(`search/` / `map/`): 各 `NNNN-<slug>.json` は `result` がリストの `ResultEnvelope`。ファイル名で何のタスクか分かる。
  - **content**(`pages/`): **まず `pages/index.json` を読み**、各エントリの `file`(`NNNN-<title>.md`)を順に開く。`.md` は `# <title>` + 本文(JSON ではなくそのまま読める)。`index.json` が唯一の url↔file 対応表。各エントリの `char_count` を見て、件数が多い/個々の文字数が大きい場合は1件ずつ Read せず `aim --parallel` にまとめて回す(`tav-digest` スキル参照)。
  - **report**(`research/`): `NNNN-<question>.md` をそのまま通読。**失敗/未完ではファイルは作られない**(前景タイムアウト時は背景ポーラが完了後に同じ `.md` を書く。終端失敗や背景も尽きた場合は監査ログのみ)。
- `result_kind` が `result` の読み方を示す: `search_results` / `extract_results` / `crawl_results`(`list[dict]`)、`site_pages`(`list[dict]`、タイトル記録)、`research_report`(`str` 本文 or `dict`)。
- `exit_code` でファイル単体でも成否が分かる(discovery の `.json`)。`0`=成功、`2`/`3`=API キー不備、`4`=抽出対象 URL が 0 件(`search_extract`/`map_extract`)、`5`=research が前景待機内に未完了(`--topic` 指定時は背景ポーラが続行中)、`1`=その他失敗(research が failed/cancelled で終了した場合を含む)。
- 全実行のフル詳細(リクエスト/レスポンス、投影前の生フィールド込み)は `<log_dir>/<script>-log.json`(既定 `<output_dir>/.logs/`、つまり CWD の git ルート配下 `temp/web/.logs/`)に別途残る。設定の `write_log` / `TAVILY_WRITE_LOG`(未設定=`true`、`false`/`0`/`no`/`off`/空で抑止)で監査ログをトグルできる。
- stderr の監査ログパス通知「Wrote full log to <path>」は 設定の `show_log_path` / `TAVILY_SHOW_LOG_PATH`(未設定=`true`、falsey で抑止)でトグルできる(監査ログ書き込み時のみ。ファイル書き込み・stdout 契約は不変)。結果ファイルのパス通知(`Wrote … row(s)/report/page .md … to <path>`)は常に表示される。

## 並列実行・レート・コストの扱い

- 軽い処理の初期探索では `search_topic.py` や `map_site_titles.py` を優先し、重い `extract` / `crawl` / `research` は候補を絞ってから打つ
- `quick` または `balanced` の `search` / `map` / 単発 `extract` は、まず 3 並列を基準にする
- 問題がなければ 5 並列程度までは試してよいが、`crawl` と `research` は 1 から 2 並列を基本にする(`research` が前景未完了になると 1 本あたり背景ポーラが 1 つ残り、裏でポーリングを続けることも頭に置く)
- `map_extract` や `search_extract` は内部で 2 段階 API を呼ぶため、外側の並列度は低めに保つ
- `429`、タイムアウト増加、応答遅延が見えたら並列数を半分に落とす
- 大量実行時は、まず `quick` で候補選定し、必要な対象だけ `balanced` または `max` で再実行する

## スクリプト一覧

各スクリプトの詳細な引数や最新の使い方は、対象スクリプトの `--help` を利用して確認する。

### 1. キーワード起点で調べる

ここが最も呼び出し頻度が高い起点。特に迷ったら、まず `tav search` を使う。

| 区分 | コマンド             | 概要                                                                                                                                                                                                                                                                 | 使う場面                                                                                                                                                                         |
| ---- | -------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1.a  | `tav search`         | `search` 単体を実行する最小ラッパー。詳細度プリセットと必要最小限のドメインフィルタだけ公開する。                                                                                                                                                                    | 関連 URL とスニペットをまず確認したい場合。初手として最も無難。                                                                                                                  |
| 1.b  | `tav search-extract` | `search` で候補 URL を集め、返ってきた URL をそのまま `extract` に渡して本文を取得する。`tav search` と `tav extract` の再利用で構成する。                                                                                                                           | まず関連ページを把握し、その後に根拠ページ本文まで明示的に確認したい場合。                                                                                                       |
| 1.c  | `tav research`       | `research` に調査タスクを投げ、前景待機内に完了すればレポートを返す最小ラッパー。前景内に終わらなければ `INCOMPLETE` を即返し、`--topic` 指定時はデタッチした背景ポーラが続行して完了後に `research/` へ書き込む。モデル選択と二段待機は詳細度プリセットで管理する。 | キーワードや問いに対して、単発検索ではなく AI に調査と要約までまとめて任せたい場合。`--topic` を付けて結果の置き場を確保しておくと、前景で間に合わなくても後からレポートが揃う。 |

### 2. URL 起点で調べる

| 区分 | コマンド      | 概要                                                                                                      | 使う場面                                                                            |
| ---- | ------------- | --------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------- |
| 2.a  | `tav extract` | 1つ以上の URL を対象に `extract` を実行する最小ラッパー。詳細度プリセットで Tavily の抽出設定を内包する。 | 対象 URL がすでに決まっており、全文または特定話題に絞った内容をすぐ取得したい場合。 |

### 3. サイト起点で網羅的に調べる

| 区分 | コマンド          | 概要                                                                                                                                                                                                             | 使う場面                                                                         |
| ---- | ----------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| 3.a  | `tav map`         | `map` で URL 一覧を取得し、各ページの HTML からタイトルを自動取得して一覧化する。失敗時は URL 由来のフォールバック名を返す。                                                                                     | サイト内ページの一覧や構造を確認しつつ、後段の処理を自分で細かく制御したい場合。 |
| 3.b  | `tav crawl`       | `crawl` を 1 ステップで実行する最小ラッパー。詳細度プリセットでクロール深さ・抽出品質を内包し、`--query` は内部で `instructions` に変換して関連内容を優先取得する。                                              | サイト全体から関連ページ本文をまとめて収集したい場合。                           |
| 3.c  | `tav map-extract` | `map` で候補 URL を取得し、その URL 群に対して `extract` を実行する合成ラッパー。`tav map` と同じフィルタ引数を維持しつつ、抽出対象を `--detail` の `map_limit`(`quick`=10 / `balanced`=20 / `max`=40)件に絞る。 | 取得対象 URL をいったん見極めてから、必要なページだけ抽出したい場合。            |
