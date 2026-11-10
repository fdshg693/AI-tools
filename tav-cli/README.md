# Tavily ラッパースクリプト群(Python 実装)

**関連スキル: `claude-plugins/my-tools/skills/tav-cli`**

このディレクトリは、Tavily SDK を **プロジェクト固有のデフォルト引数で固定した Python ラッパー** の実体です。AI や利用者には `--detail=quick|balanced|max` のような抽象化された少数引数だけ握らせ、Tavily SDK の細かいオプションはスクリプト側のプリセットでロックします。

設計意図・実装の詳細はこのファイルに、AI に読ませる判断フローや命名規約は [claude-plugins/my-tools/skills/tav-cli/SKILL.md](../../claude-plugins/my-tools/skills/tav-cli/SKILL.md) にあります。このファイルは **Python コードそのものの説明** に責務を絞っています。

## 前提条件

- Python 3.11+ / uv
- `tavily-python`(下記インストール手順で入る)
- Tavily の API キー(`TAVILY_API_KEY`)

## インストール

グローバルCLIとして使う場合は `uv tool install --editable`(`pip install -e` の代替)でエディタブルインストールする。リポジトリルートから実行可能。

```bash
uv tool install --editable tools/tav-cli
```

インストール後は `tav` コマンドが PATH 上でどこからでも使える(依存の `tavily-python` も一緒に入る。リポジトリ共通のテスト用venvに入れるだけならリポジトリルートで `uv sync` でも可)。

## セットアップ(APIキー)

Tavily API キーを **グローバル設定** `~/.config/tav/config.toml` に書くか、環境変数 `TAVILY_API_KEY` にセットします。どの CWD から `tav` を叩いても同じキーが使われます。

```bash
mkdir -p ~/.config/tav
cp tools/tav-cli/config.example.toml ~/.config/tav/config.toml
# config.toml を編集して api_key = "tvly-..." を設定
tav config   # 読み込んだファイルと各設定値の出どころを確認
```

## 設定とパス解決

設定はレイヤーで解決し、上ほど優先されます(既に値がある層より下は見ない)。正本は `tav_core/environment.py` の docstring です。

| 優先 | ソース                               | 置き場所                                                                                             |
| ---- | ------------------------------------ | ---------------------------------------------------------------------------------------------------- |
| 1    | 環境変数(空文字でも「設定済み」扱い) | `TAVILY_API_KEY` / `TAVILY_OUTPUT_DIR` / `TAVILY_WRITE_LOG` / `TAVILY_SHOW_LOG_PATH`                 |
| 2    | プロジェクト設定                     | CWD から git ルートまで遡って見つかる `.tav.toml`(近いものがキー単位で勝つ。git 管理外では CWD のみ) |
| 3    | グローバル設定                       | `$TAV_CONFIG_HOME/config.toml` → `$XDG_CONFIG_HOME/tav/config.toml` → `~/.config/tav/config.toml`    |
| 4    | 既定値                               | `output_dir = "temp/web"`、`write_log = true`、`show_log_path = true`                                |

| キー(TOML)      | 環境変数               | 型     | 備考                                                                                  |
| --------------- | ---------------------- | ------ | ------------------------------------------------------------------------------------- |
| `api_key`       | `TAVILY_API_KEY`       | 文字列 | **グローバル設定か環境変数のみ**。`.tav.toml` はコミットされうるので、書くとエラー    |
| `output_dir`    | `TAVILY_OUTPUT_DIR`    | 文字列 | `--topic` 出力のベース                                                                |
| `log_dir`       | `TAVILY_LOG_DIR`       | 文字列 | 監査ログの置き場。未設定なら `<output_dir>/.logs`。相対パスは `output_dir` と同じ規則 |
| `write_log`     | `TAVILY_WRITE_LOG`     | 真偽値 | 監査ログを書くか                                                                      |
| `show_log_path` | `TAVILY_SHOW_LOG_PATH` | 真偽値 | 監査ログのパス通知を出すか                                                            |

- `output_dir` の相対パスは、**プロジェクト設定 `.tav.toml` に書いたときだけ、その `.tav.toml` のディレクトリ基準**で解決します。それ以外(グローバル `config.toml`・環境変数・既定値)は **CWD の git ルート基準**(git 管理外なら CWD 基準)です。たとえばグローバル設定の `output_dir = "temp/web"` は「各リポジトリの `temp/web`」という意味になります。つまりリポジトリのどのサブディレクトリから叩いても `<repo>/temp/web/<topic>/` に集まります。絶対パスと `~` はそのまま使います。
- 環境変数の真偽値は `false`/`0`/`no`/`off`/空(大文字小文字無視)が偽、それ以外が真です。TOML 側は `true`/`false` で書きます。
- 未知のキーや型違いの設定ファイルは、パス付きのエラーで止まります(打ち間違いを黙って無視しないため)。
- 例は [config.example.toml](config.example.toml) を参照してください。`tools/tav-cli/.env` はもう読みません。

## 実装方針

- スクリプトに渡せる引数は最小限にする
  - Tavily SDK の細かいオプションをそのまま外に出しすぎると、Python でラップする意味が薄くなる
  - AI や利用者は `--detail=max` のような抽象化された引数を使うことに集中し、Tavily のどのオプションへどう変換するかはスクリプト内のプリセットで制御する
  - デフォルト値やプリセット対応表は、各スクリプト先頭で編集しやすい形に置く
- 共通箇所は `tav_core/` パッケージへ切り出す(以前の単一巨大ファイル `tavily_common.py` を責務ごとに分割したもの)
  - `tav_core/environment.py` … レイヤー設定(環境変数 / `.tav.toml` / グローバル `config.toml`)の解決・Tavily クライアント生成・トグル
  - `tav_core/output.py` … JSON 整形・エンベロープ組み立て・唯一の出力シンク `emit()`
  - `tav_core/topic_layout.py` … 役割別の出力ライタ群(`--topic` の置き場決定。「何をどこへ」だけを担う)
  - `tav_core/run_shell.py` … 命令的シェル `finalize()`(`RunOutcome` → 副作用)とデタッチプロセス起動 `spawn_detached`
  - `tav_core/projection.py` … 結果アイテムを調査に要る列へ投影する `slim_result_item` / `project_result`
  - `tav_core/result_contract.py` … **戻り値の契約**(`ExitCode` / `ResultKind` / `ResultEnvelope` / `ResponseEnvelope` / `OutputChannel` / `RunOutcome` / `TopicArtifact` / `BackgroundTask` と役割レイアウト表)。終了コード・出力形状・出力先はここの列挙/`TypedDict`/`dataclass` が正本(詳細は後述の「実行結果の戻り値(契約)」)
  - `tav_core/tavily_types.py` … Tavily の各レスポンス要素型(実測で確定した `TypedDict`)
  - `tav_core/page_title.py` … HTML 直 Fetch のタイトル取得 / `tav_core/text_utils.py` … `slugify` / `dedupe_preserve_order`
  - 公開シンボルは `tav_core/__init__.py` が再エクスポートするので、各スクリプトは `from tav_core import ...` だけ書けば内部のファイル分割に依存しない
- 各スクリプトにはファイル冒頭コメントを書き、用途・最小引数・どこを編集すれば挙動を変えられるかを明示する
- スクリプトの詳細な引数や最新の使い方は各スクリプトの `--help` を確認する
- 複数スクリプトは薄いディスパッチャ `tav_cli.py` で 1 つのエントリポイントにまとめ、`pyproject.toml` の `[project.scripts]` 経由で `tav` という console コマンドとして公開する。`tav <サブコマンド>` は対応スクリプトの `main(argv)` に残り引数を委譲するだけで、各スクリプトの引数・プリセット・戻り値契約は不変。サブコマンド対応表は [SKILL.md](../../claude-plugins/my-tools/skills/tav-cli/SKILL.md) の「エントリポイント: `tav` コマンド」を参照

## 使い方

```bash
tav search "Microsoft Fabric overview" \
  --include-domain learn.microsoft.com \
  --topic msfabric_overview
```

PowerShell の場合:

```powershell
tav search "Microsoft Fabric overview" `
  --include-domain learn.microsoft.com `
  --topic msfabric_overview
```

`--topic <name>` を渡すと `<output_dir>/<topic>/`(設定の `output_dir` / `TAVILY_OUTPUT_DIR`、未設定時は git ルート基準の `temp/web`)配下に書き出します。`--topic` を省くと単一 `ResultEnvelope` を stdout に出します(パイプ用途)。相対パスの解決基準は上の「設定とパス解決」を参照してください。

各サブコマンドの引数詳細は `--help` で確認できます(サブコマンド一覧は引数なしの `tav`)。

```bash
tav search --help
```

## 実行結果の戻り値(契約)

CLI の戻り値は **終了コード・出力データ・監査ログ・出力先** の 4 つの契約に分かれ、いずれも `tav_core/result_contract.py` の型/列挙で固定しています。コメントではなく実体(`IntEnum` / `Enum` / `TypedDict` / `dataclass`)が正本で、この表はその写しです。

### 内部構造 — functional core / imperative shell

各スクリプトの `main()` は **副作用を持たない計算ステップ** で、戻り値として `RunOutcome`(`dataclass`: 終了コード + `topic` + ログ + `result_kind` + `result` + `slug`〔= ファイル名の slug ヒント〕+ `discovery`〔= 合成コマンドが残す 2 つ目の役割出力 `TopicArtifact`〕+ stderr メッセージ)を返すだけ。ファイル書き込みや stdout/stderr 出力は一切しない。`finalize` が `topic` の有無で出力レイアウト(トピックフォルダの役割サブフォルダ群か stdout 単一)を決め、`result_kind` の役割で discovery/content/report のライタへ振り分ける。

I/O は唯一 `finalize(outcome) -> ExitCode` が担う。エントリポイントは常に次の 1 行:

```python
if __name__ == "__main__":
    raise SystemExit(finalize(main()))
```

これにより `main()` の本当の成果物(payload と終了コード)が **戻り値として型に現れる**。stdout やファイルを捕捉せずに `main(argv)` を呼んで結果を検証・合成できる(`finalize` を呼ばなければ何も書かれない)。エラー時(API キー不備・例外)は `RunOutcome` の `log` を `None` にして返し、`finalize` は出力エンベロープを書かず `message` だけを stderr に出す。

### 1. プロセス終了コード — `ExitCode`(`tav_core/result_contract.py`)

全スクリプトの `main()` は `ExitCode` のメンバーを返します。呼び出し側はこの整数で分岐できます。

| code | メンバー          | 意味                                                                                                                                                                     |
| ---- | ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `0`  | `SUCCESS`         | 正常完了。データは下記エンベロープにある(検索 0 件でも成功扱い)                                                                                                          |
| `1`  | `RUNTIME_ERROR`   | 想定外の失敗(ネットワーク / API エラー、research が failed・cancelled で終了)                                                                                            |
| `2`  | `MISSING_API_KEY` | `TAVILY_API_KEY` が未設定または空                                                                                                                                        |
| `3`  | `INVALID_API_KEY` | Tavily にキーを拒否された                                                                                                                                                |
| `4`  | `EMPTY_RESULT`    | 呼び出しは成功したが後段に渡せるデータが無い(抽出対象 URL が 0 件)。`search_extract` / `map_extract` のみ                                                                |
| `5`  | `INCOMPLETE`      | 長時間処理(research)が**前景**待機内に終端状態へ到達しなかった。`--topic` 指定時はデタッチした背景ポーラ(`research_background_poll.py`)が続行する。`research_topic` のみ |

`4` / `5` は以前 1 つのコードに混在していたものを分離しています(`research` の前景未完了は `4` ではなく `5`)。`research` の待機は前景 / 背景の二段構成で、終了コードはあくまで前景の結果を表します(背景ポーラの最終結果は `<log_dir>/research_background_poll-log.json` に記録)。

### 2. 出力データ — `ResultEnvelope`(トピックフォルダ配下のファイル / stdout)

全スクリプトが **同一形状の自己記述エンベロープ** を出力します。`result_kind` が判別子で、`result` の中身の読み方を示します(スクリプトのソースを読まずに形が分かる)。

```json
{
  "script": "search_topic.py",
  "result_kind": "search_results",
  "exit_code": 0,
  "result": [/* result_kind で形が決まる */]
}
```

出力先は `--topic` の有無で 2 通りです。

- **`--topic <name>` 未指定** → 単一 `ResultEnvelope`(`result` を**投影**して research に要る列だけにしたもの)を stdout に書き出す(パイプ用途。従来どおり)。
- **`--topic <name>` 指定** → `<output_dir>/<topic>/` 配下に、`result_kind` の**役割**で決まる**役割サブフォルダ**へ書き出す(役割が違うものを同じ連番列に混ぜない)。

| 役割      | 対象コマンド                                           | 置き場 / 形式                                                                                                                                                                                      |
| --------- | ------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| discovery | `search` → `search/` / `map` → `map/`                  | `NNNN-<slug>.json`(**集約 JSON リスト** 1 ファイル。URL 単位に分割しない=一覧で skim するため)。中身は投影済み `ResultEnvelope`(`result` はリスト)。                                               |
| content   | `extract` / `crawl` / `search_extract` / `map_extract` | `pages/NNNN-<slug>.md`(**1 ページ = 1 Markdown**: `# <title>` + 本文)+ `pages/index.json`。本文は読むものなので分割 + `.md`。                                                                      |
| report    | `research` → `research/`                               | `NNNN-<slug>.md`(**成功時のみ**素の Markdown を通読)。失敗/前景未完では**ファイルを書かない**(前景タイムアウトは背景ポーラが完了後に同じ `.md` を書く。終端失敗や背景も尽きた場合は監査ログのみ)。 |

`NNNN` は**サブフォルダごとに独立採番**し、既存をスキャンして `max+1` で**継続(追記)**します(上書きしない)。同じクエリ再実行は `search/` に別ファイル、同じ URL 再 extract は `pages/` に別 `.md` + index に別エントリ(**重複も保持**)。`slug` はクエリ / ドメイン / タイトル由来で、ファイル名だけで中身が分かります。

content 系の `pages/index.json` が唯一の url↔ファイル対応表で、**append 管理される共有ファイル**です。形:

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

`char_count` は書き出した `.md` ファイルの文字数(`len(markdown)`、`mslearn` の `index.md` が持つ文字数と同じ考え方)。後段はこれを見て、1件ずつ Read するか大きいものだけ `aim --parallel` にまとめて回すか判断する(`tav-digest` スキル参照)。

後段で読むときは、content 系なら **`pages/index.json` を起点に各 `NNNN-<slug>.md` を辿る**(各 `.md` は `# title` + 本文)。discovery / report はファイル名が自己説明的なので `ls` で足り、そのファイルを直接読みます(report は成功時のみファイルが存在する。前景タイムアウト直後は空でも、背景ポーラの完了後に現れる場合がある)。`title` は content 系で必ず埋まる(既存タイトル保持 = `existing`、HTML 直 Fetch で補完 = `html`、URL 由来フォールバック = `url_fallback`。Tavily はタイトル取得に使わない)。トピックファイル / stdout に書く `result` は**役割ごとに投影**され調査に無関係な列(`raw_content`==None・空 `images`・取得メタ等)を落とします(生の全フィールドは監査ログに残る)。

`result_kind`(`ResultKind`)と各スクリプトの `result` の中身:

| スクリプト                    | `result_kind`     | `result` の中身                                                                                                                             |
| ----------------------------- | ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| `search_topic.py`             | `search_results`  | `list[SearchResultItem]`: Tavily search の結果オブジェクト                                                                                  |
| `extract_url_content.py`      | `extract_results` | `list[ExtractResultItem]`: Tavily extract の結果オブジェクト                                                                                |
| `crawl_site_content.py`       | `crawl_results`   | `list[CrawlResultItem]`: Tavily crawl の結果オブジェクト                                                                                    |
| `map_site_titles.py`          | `site_pages`      | `list[SitePageItem]`: ページタイトル記録(`PageTitleResult`)                                                                                 |
| `map_extract_site_content.py` | `extract_results` | `list[ExtractResultItem]`: extract 結果(URL 0 件なら空配列)                                                                                 |
| `search_extract_topic.py`     | `extract_results` | `list[ExtractResultItem]`: extract 結果(URL 0 件なら空配列)                                                                                 |
| `research_topic.py`           | `research_report` | `str`: レポート本文(markdown)。非成功時は最終レスポンス dict(ファイルには書かれず stdout / 監査ログにのみ現れる)                            |
| `research_background_poll.py` | `research_report` | `research_topic` の前景未完了を引き継ぐデタッチ poller。完了すれば同じ `research/NNNN-<slug>.md` を書く(内部用・`tav` サブコマンドではない) |

> 後段で結果を読むときは、トップレベルの `result` を取り出してから中身を処理する。`exit_code` を見れば、ファイル単体でも成功/空/未完了が判別できる。
>
> 合成コマンド(`search_extract` / `map_extract`)は **discovery 半分も残す**。primary の `result`(= extract 本文)は `pages/` に書きつつ、検索 / map のメニューを `search/` / `map/` にも書く。`RunOutcome.discovery`(`TopicArtifact`)がこの 2 つ目の役割出力を担い、stdout 経路では無視される(パイプ契約は 1 エンベロープのまま)。

各 `*Item` は `tav_core/tavily_types.py` の `TypedDict` で **実際の API レスポンスから実測して確定** させた型です(ドキュメントではなく実体が正本)。スクリプトの固定フラグ(`include_raw_content` / `include_images` / `include_favicon` はすべて False)前提なので、例えば search は `raw_content` キーを常に持つが値は `None`、extract は未ドキュメントの `title` を必ず持つ、といった実測事実を反映しています。

- 型を **どう実測して確定したか**(プローブ各種・fixtures 再生成)→ [experiments/README.md](experiments/README.md)
- 型が **実 API と一致することの検証**(オフライン構造検証 + `TAVILY_LIVE_TESTS=1` のライブ再検証)→ [tests/README.md](tests/README.md)

### 3. 監査ログ — `ResponseEnvelope`(`TAVILY_WRITE_LOG` で制御)

`--topic` の有無にかかわらず、毎回 `<log_dir>/<script>-log.json`(既定 `<output_dir>/.logs/`)にリクエスト/レスポンス全体を `{script, request, environment, response}` の形で残します。再現・原因追跡用の詳細ビューで、出力エンベロープよりも冗長です。設定の `write_log` / `TAVILY_WRITE_LOG`(未設定=`true`、`false`/`0`/`no`/`off`/空で抑止)でこの監査ログ出力をトグルできます。

### 4. 出力先 — `OutputChannel`(どのストリーム/ファイルに何が出るか)

上の 1〜3 が **何を** 返すかなら、これは **どこへ** 出すかの契約です。全出力は唯一のシンク `emit(channel, ...)` を通り、`OutputChannel` で行先が決まります。これにより「どこからどこまでが結果で、どこからが通知か」が一意になります。

| メンバー        | 中身                                                                                          | 行先                                                                                                | 構造化                          |
| --------------- | --------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- | ------------------------------- |
| `RESULT_STDOUT` | `ResultEnvelope` JSON(投影済み)                                                               | stdout(`--topic` 未指定時のみ)                                                                      | あり                            |
| `RESULT_FILE`   | discovery `.json`(リスト)/ `pages/index.json` / report の `.md`(成功時のみ)/ content の `.md` | トピックフォルダの役割サブフォルダ配下(`search/` `map/` `pages/` `research/`)。`--topic` 指定時のみ | `.json` は構造化 / `.md` は本文 |
| `AUDIT_LOG`     | `ResponseEnvelope` JSON(投影前の生フィールド込み)                                             | `<log_dir>/<script>-log.json`(`write_log` が有効なときのみ)                                         | あり                            |
| `DIAGNOSTIC`    | 「Wrote ...」「Research finished ...」等の 1 行                                               | stderr                                                                                              | なし                            |

`--topic` 指定時の content 系では、`RESULT_FILE` が per-page の `NNNN-<slug>.md` と `pages/index.json` の両方に使われます(チャンネルは増やさず `emit` の呼び出し回数を増やすだけ。`write_output` が `str` を Markdown、それ以外を JSON として書き分ける)。監査ログのパス通知「Wrote full log to `<path>`」は `TAVILY_SHOW_LOG_PATH`(未設定=`true`、`false`/`0`/`no`/`off`/空で抑止)でトグルできます(監査ログ書き込み時のみ)。結果ファイルのパス通知は常に表示されます。

規律: **stdout には機械可読な `ResultEnvelope` だけ(または何も出さない)。「Wrote ...」等の通知・エラー・進捗はすべて stderr の `DIAGNOSTIC`。** 後段で結果をパースするときは stdout をそのまま読めばよく、stderr は純粋な診断として扱える。`emit()` 以外の場所で `print` しない(出力点を一箇所に集約する)ことがこの契約を成立させています。

## どのスクリプトを使うか

迷ったら以下を出発点にしてください。詳細な判断フローは [SKILL.md](../../claude-plugins/my-tools/skills/tav-cli/SKILL.md) の「最初に見るべき判断フロー」を参照。

| 状況                                       | 使うスクリプト                |
| ------------------------------------------ | ----------------------------- |
| キーワードから関連 URL を集めたい          | `search_topic.py`             |
| キーワード → 候補 URL → 本文抽出まで一気に | `search_extract_topic.py`     |
| 問いに対して AI 調査と要約まで任せたい     | `research_topic.py`           |
| 取得したい URL がもう手元にある            | `extract_url_content.py`      |
| サイト内のページ一覧と構造を見たい         | `map_site_titles.py`          |
| サイトをマップしてから関連ページを抽出     | `map_extract_site_content.py` |
| サイト全体から関連本文をまとめて回収       | `crawl_site_content.py`       |

## ファイル構成

```text
tools/tav-cli/
├── README.md                    ← このファイル(Python コードの説明)
├── AGENTS.md / CLAUDE.md        ← リポジトリ規約に合わせたエージェント向け入口(実体はこのREADME)
├── pyproject.toml                ← `tav` コンソールコマンドのパッケージング
├── config.example.toml           ← グローバル config.toml / プロジェクト .tav.toml の記入例
├── tav_core/                    ← 共通実装パッケージ(旧 tavily_common.py を責務分割)
│   ├── __init__.py              ← 公開シンボルの再エクスポート(`from tav_core import ...` の窓口)
│   ├── result_contract.py       ← 戻り値契約: ExitCode / ResultKind / 各 Envelope / OutputChannel / RunOutcome / TopicArtifact / BackgroundTask / 役割レイアウト表
│   ├── tavily_types.py          ← Tavily の各レスポンス要素型(実測で確定した TypedDict)
│   ├── environment.py           ← レイヤー設定の解決・Tavily クライアント生成・トグル(WRITE_LOG / OUTPUT_DIR ほか)
│   ├── output.py                ← JSON 整形・エンベロープ組み立て・唯一の出力シンク emit()
│   ├── topic_layout.py          ← 役割別出力ライタ(discovery/content/report)・slug/連番採番・.md レンダラ・title 補完(「何をどこへ」だけ)
│   ├── run_shell.py             ← 命令的シェル finalize()(RunOutcome→副作用)+ デタッチプロセス起動 spawn_detached
│   ├── projection.py            ← 結果アイテムを調査に要る列へ投影(slim_result_item / project_result)
│   ├── page_title.py            ← HTML 直 Fetch でタイトル取得(map_site_titles と topic_layout の title 補完が共有)
│   └── text_utils.py            ← slugify / dedupe_preserve_order(汎用テキスト/列ヘルパ)
├── search_topic.py              ← キーワード検索の最小ラッパー
├── search_extract_topic.py      ← search → extract の合成
├── research_topic.py            ← Research API ラッパー(前景待機 + 前景未完了時に背景 poller を起動)
├── research_background_poll.py  ← 前景未完了の research を引き継ぐデタッチ poller(完了後に research/ へ書く。内部用)
├── extract_url_content.py       ← URL 群から本文抽出
├── map_site_titles.py           ← サイトの URL 一覧 + タイトル
├── map_extract_site_content.py  ← map → extract の合成
├── crawl_site_content.py        ← サイトクロール + 本文回収
├── tav_cli.py                   ← サブコマンドを各ラッパーへ振り分ける薄いディスパッチャ(`tav` の実体)
├── tests/                       ← オフライン構造検証 + ライブ再検証テスト
├── experiments/                 ← 型を実測で確定するためのプローブスクリプト群
```

監査ログはツール配下ではなく `<log_dir>`(既定 `<output_dir>/.logs/`)に書かれます。

コマンドラッパー(`search_topic.py` 等)と `tav_cli.py` は **トップレベルのまま** にしてある。`python tools/tav-cli/<script>.py` の直接実行と、`tav_cli` の `importlib` ディスパッチをそのまま動かすため。共通実装だけを `tav_core/` パッケージにまとめている。

`claude-plugins/my-tools/skills/tav-cli/` 側には `SKILL.md`(AI が実行時に読む判断フロー・使い方)と `README.md`(スキルの設計意図)だけが残る。CLI 本体はこの `tools/tav-cli/` に切り出してあり、スキル側から Python スクリプトを直接叩くことはしない(インストール済みの `tav` コマンド経由が前提)。

## カスタマイズ箇所

| 変えたいこと                                                                                                                                   | 編集場所                                                                                                        |
| ---------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| `--detail` プリセット(検索深さ / 結果数 / チャンク数)                                                                                          | 各スクリプト冒頭の `DETAIL_PRESETS` 辞書                                                                        |
| デフォルトの詳細度                                                                                                                             | 各スクリプトの `DEFAULT_DETAIL` 定数                                                                            |
| `include_answer` / `include_raw_content` などの固定フラグ                                                                                      | 各スクリプト冒頭の定数(`INCLUDE_ANSWER` 等)                                                                     |
| タイムアウト                                                                                                                                   | 各スクリプトの `REQUEST_TIMEOUT_SECONDS`                                                                        |
| `research` の前景 / 背景待機(`foreground_wait_seconds` / `background_wait_seconds` とポーリング間隔)                                           | `research_topic.py` の `DETAIL_PRESETS`(実測の根拠は `experiments/measure_research_timing.py`)                  |
| 設定のレイヤー解決                                                                                                                             | `tav_core/environment.py`                                                                                       |
| JSON 出力フォーマット・出力シンク `emit()`                                                                                                     | `tav_core/output.py`                                                                                            |
| 出力先ベースディレクトリ(`--topic` の解決先、未設定時 `temp/web`)                                                                              | 設定の `output_dir`                                                                                             |
| 監査ログ `<log_dir>/<script>-log.json` を書くか(未設定=`true`、`false`/`0`/`no`/`off`/空で抑止)                                                | 設定の `write_log`                                                                                              |
| 監査ログのパス通知「Wrote full log to `<path>`」を出すか(未設定=`true`、falsey で抑止。監査ログ書き込み時のみ。結果ファイルのパス通知は常に表示) | 設定の `show_log_path`                                                                                          |
| 出力先と `--topic` レイアウト                                                                                                                  | [SKILL.md](../../claude-plugins/my-tools/skills/tav-cli/SKILL.md) の「出力先と `--topic` レイアウト」セクション |
| AI に提示する判断フロー / 引数例                                                                                                               | [SKILL.md](../../claude-plugins/my-tools/skills/tav-cli/SKILL.md) 本体                                          |

新しい使い方を追加したい場合は、`tools/tav-cli/` 配下に同じスタイルで新スクリプトを作り、`SKILL.md` に判断フローと引数例を追記してください。`--detail` プリセットやデフォルト値は新スクリプト冒頭にも同じ形で置きます。
