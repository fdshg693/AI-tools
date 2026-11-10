# pyinspect — PyPI 配布物の取得と索引

PyPI 上のライブラリを **wheel として取得**し、メタデータ・ファイルツリー・先に読むパスを `index.md` に残す CLI。ドキュメント索引（`ctx7` / web-lookup）では足りない、実装・公開面・配布物の中身を一次ソースとして読む用途。

解釈・要約はしない。stdout には `index.md` のパスだけを出す（`mslearn` と同じ契約）。中身はエージェントが Read する。

フラグの正本は `--help`。

```bash
pyinspect --help
```

## 前提条件

- Python 3.11+ / uv
- `requests` / `packaging` / `python-dotenv`（下記インストールで入る）
- API キー不要（PyPI JSON と files.pythonhosted.org は公開）
- `--import` を使うときだけ、PATH 上の `uv`（隔離 venv の作成と `uv pip install`）

## インストール

リポジトリルートからエディタブルインストールする。

```bash
uv tool install --editable tools/pyinspect
```

インストール後は `pyinspect` が PATH 上で使える。共有 dev venv でテストするだけなら `uv sync` でよい。

## 使い方

```bash
# 版省略: 毎回 latest を JSON で解決し、確定版でキャッシュする
pyinspect requests

# 版ピン
pyinspect requests==2.32.3

# 隔離 venv で公開名だけ列挙（既定では走らない）
pyinspect beautifulsoup4 --import --module bs4
```

`--module` は `--import` 必須。推定（`*.dist-info/top_level.txt`）が 0 件または 2 件以上のときも `--module` が要る。

## 出力契約

- stdout: `index.md` のパス 1 行だけ（Windows でも `/` 区切り）。本文は出さない
- キャッシュ: `temp/py-inspect/<pep503-name>/<version>/`（相対パスは cwd 基準）
- 自動削除なし
- `index.md` の必須節: Metadata / Status / File tree / Recommended paths。`--import` 時だけ Import
- 推奨パスは決定的に最大 8 件: 配布物直下の `README*`、中身がある `py.typed`、トップレベルパッケージの `__init__.py`（`_` 始まりより通常名を先に、空き枠があれば複数）、`*.dist-info/METADATA`

完了の印は `index.md` と同階層の `.complete`。書き込みは `<version>.tmp-<pid>/` に行ってから置換する。印が無い／壊れているキャッシュはミスとして消して取り直す。

## 環境変数

任意。`tools/pyinspect/.env.example` をコピーして `.env` を置ける（必須キーは無い）。

| 変数                   | 既定              | 意味                                          |
| ---------------------- | ----------------- | --------------------------------------------- |
| `PYINSPECT_OUTPUT_DIR` | `temp/py-inspect` | キャッシュルート。相対パスは cwd 基準         |
| `PYINSPECT_MAX_BYTES`  | `50000000`        | ダウンロード前に `urls[].size` と比較する上限 |

## 取得の方針

1. `GET https://pypi.org/pypi/<name>/json`（版ピンなら `/<name>/<version>/json`）
2. `packagetype == bdist_wheel` の `urls[]` から選ぶ。sdist には落とさない
3. 読む用: `py3-none-any`（または `py2.py3-none-any`）の次に現行 interpreter タグに合う wheel、その次に他プラットフォーム。`--import` 用は現行 interpreter タグだけ
4. `urls[].size` が上限超なら HTTP GET しない（metadata-only）
5. 展開は zip。`setup.py` は実行しない
6. `--import` は選んだ `.whl` だけ `uv pip install --no-deps --no-index`。依存は入れない。終わったら venv を消す

版省略で latest が yanked なら実体を取らない。版ピンの yanked は取り、索引に記録する。

## 終了コード

| code | 意味                                                                      |
| ---- | ------------------------------------------------------------------------- |
| 0    | 実体取得まで成功（`--import` なし、または import も成功）                 |
| 1    | 実行時（ネットワーク・JSON 破損など）                                     |
| 2    | 使い方（`--module` のみ、範囲指定など）                                   |
| 3    | パッケージまたは版が PyPI で 404。パスは出さない                          |
| 4    | metadata-only（wheel 無し・サイズ超過・yanked-latest）。`index.md` は書く |
| 5    | 実体はあるが `--import` が失敗。パスは出す                                |

4 と 5 は非 0 でも stdout にパスを出す。呼び出し側はパスを Read してよい。

## ファイル構成

```text
tools/pyinspect/
├── README.md
├── pyproject.toml
├── pyinspect_cli.py          ← エントリ。1コマンド
├── pyinspect_core/
│   ├── config.py
│   ├── environment.py
│   ├── pypi.py               ← specifier / JSON / wheel 選択 / GET
│   ├── cache.py
│   ├── index.py
│   ├── importer.py
│   └── inspect.py
└── tests/
```
