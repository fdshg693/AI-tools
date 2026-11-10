# Tavily ラッパーの型テスト

このディレクトリは、各ラッパースクリプトが返す **結果オブジェクトの型** が確かに正しいことを検証するテスト群です。型の正本は [`../tav_core/tavily_types.py`](../tav_core/tavily_types.py) の `TypedDict`(`SearchResultItem` / `ExtractResultItem` / `ExtractFailedItem` / `CrawlResultItem` / `SitePageItem` / `ResearchSource` / `CompletedResearchResponse`)で、それらが **実際の Tavily API レスポンスと一致すること** をここで担保します。

これらの型は推測やドキュメントではなく、[`../experiments/`](../experiments/README.md) の実測で確定したものです。型を再確認・更新する手順はそちらを参照してください。

## ファイル構成

```text
tests/
├── README.md              ← このファイル
├── test_result_types.py   ← 型の構造検証テスト(stdlib unittest)
└── fixtures/              ← 実 API から取得・保存した本物のレスポンス(検証の入力)
    ├── captured_at.txt    ← fixtures を取得した日時(ISO 8601・ローカルタイムゾーン)
    ├── search_response.json
    ├── extract_response.json
    ├── extract_failed_response.json
    ├── crawl_response.json
    ├── map_response.json
    ├── site_pages.json
    └── research_response.json
```

`fixtures/` がいつ取得されたものかは [`fixtures/captured_at.txt`](fixtures/captured_at.txt) を見れば分かります(`capture_fixtures.py` が再生成時に上書き)。古ければ API 形が変わっている可能性を疑う目安になります。

## テストの2層構造

| 層               | 既定           | 内容                                                                | 通信/クレジット    |
| ---------------- | -------------- | ------------------------------------------------------------------- | ------------------ |
| **オフライン**   | 常に実行       | `fixtures/` に保存した実レスポンスに対し `TypedDict` の構造を検証   | なし(高速・決定的) |
| **ライブ(任意)** | 既定でスキップ | 同じ型を **その場で API を叩いて** 取得した新鮮なレスポンスで再検証 | あり               |

- オフライン層が「確実に正しい型である」ことの主たる確認です。`fixtures/` は本物の API 応答なので、型が実体と一致していることを証明します。
- `test_result_types.py` にはバリデータ自身の自己テスト(不正データをちゃんと弾くか)も含まれます。緑=何かを確かに検証している、を保証するためです。

## 実行方法

依存は標準ライブラリのみ(`pytest` 不要)。リポジトリルートから:

```bash
# オフラインのみ(既定)
python -m unittest discover -s tools/tav-cli/tests -v
```

ライブ検証は `tests/` ディレクトリ内で環境変数を立てて実行します:

```bash
# search / extract / crawl をライブ検証(research は別フラグでスキップ)
cd tools/tav-cli/tests
TAVILY_LIVE_TESTS=1 python -m unittest test_result_types.TestLiveShapes -v

# research も含める(遅い・~1-2分・クレジット消費)
TAVILY_LIVE_TESTS=1 TAVILY_LIVE_RESEARCH=1 python -m unittest test_result_types.TestLiveShapes -v
```

PowerShell の場合は `$env:TAVILY_LIVE_TESTS = "1"` のように設定してから実行してください。

`pytest` が入っている環境なら、これらの `unittest.TestCase` はそのまま `pytest` でも検出・実行できます。

## fixtures の更新

API が安定しているため頻繁な更新は不要ですが、レスポンス形が変わった疑いがあるときは [`../experiments/capture_fixtures.py`](../experiments/capture_fixtures.py) を再実行すると `fixtures/` を本物のレスポンスで作り直せます(`raw_content` は短く切り詰めて保存)。再生成時には取得日時が [`fixtures/captured_at.txt`](fixtures/captured_at.txt) に上書きされるので、いつ時点のレスポンスかが常に追えます。

## 型を変えたくなったら

1. まず [`../experiments/`](../experiments/README.md) のプローブで実体を観測する。
2. 観測に合わせて `../tav_core/tavily_types.py` の `TypedDict` を更新する。
3. `capture_fixtures.py` で `fixtures/` を更新し、本テストで一致を確認する。
