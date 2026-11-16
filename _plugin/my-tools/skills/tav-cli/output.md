# tav: 出力先・出力形式・終了コード

`tav` の結果を読むとき、または `--topic` の置き場を決めるときに読む。

## 出力先と `--topic` レイアウト

出力先はフルパスではなく `--topic <name>` で指定する。実際の保存先は `<TAVILY_OUTPUT_DIR>/<topic>/`(設定の `output_dir` / `TAVILY_OUTPUT_DIR`、未設定時は git ルート基準の `temp/web`。有効値は `tav config` で確認)に解決される。`topic` は **記事やテーマ単位の「調査タスクをためる作業場」** で、短いスラッグ(英数字と `_`)に揃える。同じ `--topic` を何度叩いても**上書きせず追記**していく。

- `--topic <name>` を渡す → トピックフォルダ配下に**役割サブフォルダ**で書き出す(下記)。
- `--topic` を省く → 単一 `ResultEnvelope`(投影済み)を stdout に出す(パイプ用途)。

トピックフォルダ内は、出力の**役割**でサブフォルダを分ける(役割が違うものを同じ連番列に混ぜない)。

| 役割                        | コマンド                              | 置き場             | 形式                                                                                      | 単位                          |
| --------------------------- | ------------------------------------- | ------------------ | ----------------------------------------------------------------------------------------- | ----------------------------- |
| **discovery(候補メニュー)** | `search` → `search/` / `map` → `map/` | `NNNN-<slug>.json` | **集約 JSON リスト**(1 タスク=1 ファイル、URL 単位に分割しない)                           | 1 クエリ / 1 map = 1 ファイル |
| **content(取得本文)**       | `extract` / `crawl`                   | `pages/`           | **分割 Markdown**(`# <title>` + 本文)+ `pages/index.json`                                 | 1 ページ = 1 ファイル         |
| **report(成果物)**          | `research`                            | `research/`        | **単一 Markdown**(成功時のみ。失敗/未完は書かない=背景ポーラが後から完成 or 監査ログのみ) | 1 問い = 1 ファイル           |

`search-extract` / `map-extract` は discovery と content の両方に書く。

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

`char_count` は書き出した `.md` の文字数(`len()`)。`pages/index.json` を Read した時点で、どのページを直接 Read し、どれを `aim --parallel` にまとめて回すか([digest.md](digest.md))を、個別に開かず判断できる。

例(コマンド):

- `tav search "Microsoft Fabric overview" --include-domain learn.microsoft.com --topic msfabric_overview` → `temp/web/msfabric_overview/search/0001-microsoft-fabric-overview.json`
- `tav map-extract https://learn.microsoft.com/azure/api-management/ --topic apim_docs` → `temp/web/apim_docs/map/0001-learn-microsoft-com.json` + `pages/NNNN-<title>.md …` + `pages/index.json`

## 出力エンベロープ

各コマンドが書き出す JSON は **自己記述エンベロープ** で、トップレベルは常に同じ形。生の配列ではない。

```json
{
  "script": "...",
  "result_kind": "search_results",
  "exit_code": 0,
  "result": [/* 本体 */]
}
```

`--topic` 指定時の読み方は**役割で違う**:

- **discovery**(`search/` / `map/`): 各 `NNNN-<slug>.json` は `result` がリストの `ResultEnvelope`。ファイル名で何のタスクか分かる。
- **content**(`pages/`): **まず `pages/index.json` を読み**、各エントリの `file`(`NNNN-<title>.md`)を開く。`.md` は `# <title>` + 本文(JSON ではなくそのまま読める)。`index.json` が唯一の url↔file 対応表。件数が多い/個々の `char_count` が大きい場合は1件ずつ Read せず [digest.md](digest.md) に進む。
- **report**(`research/`): `NNNN-<question>.md` をそのまま通読。**失敗/未完ではファイルは作られない**(前景タイムアウト時は背景ポーラが完了後に同じ `.md` を書く。終端失敗や背景も尽きた場合は監査ログのみ)。

`result_kind` が `result` の読み方を示す: `search_results` / `extract_results` / `crawl_results`(`list[dict]`)、`site_pages`(`list[dict]`、タイトル記録)、`research_report`(`str` 本文 or `dict`)。

## 終了コード

`exit_code` でファイル単体でも成否が分かる(discovery の `.json`)。

| code    | 意味                                                                |
| ------- | ------------------------------------------------------------------- |
| `0`     | 成功                                                                |
| `1`     | その他失敗(research が failed/cancelled で終了した場合を含む)       |
| `2`/`3` | API キー不備                                                        |
| `4`     | 抽出対象 URL が 0 件(`search-extract` / `map-extract`)              |
| `5`     | research が前景待機内に未完了(`--topic` 指定時は背景ポーラが続行中) |

## 監査ログ

- 全実行のフル詳細(リクエスト/レスポンス、投影前の生フィールド込み)は `<log_dir>/<script>-log.json`(既定 `<output_dir>/.logs/`、つまり CWD の git ルート配下 `temp/web/.logs/`)に別途残る。設定の `write_log` / `TAVILY_WRITE_LOG`(未設定=`true`、`false`/`0`/`no`/`off`/空で抑止)でトグルできる。
- stderr の監査ログパス通知「Wrote full log to <path>」は設定の `show_log_path` / `TAVILY_SHOW_LOG_PATH`(未設定=`true`、falsey で抑止)でトグルできる。結果ファイルのパス通知(`Wrote … row(s)/report/page .md … to <path>`)は常に表示される。
