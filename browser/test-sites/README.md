# test-sites — Playwright 実験用の自作テストサイト集

認証も外部ネットワークも要らない、ローカルだけで完結する静的サイト群。
Playwright / playwright-cli / エージェント向けスキル、`pwq`・`pwdo`（隣のディレクトリ）の挙動確認と実測に使う。
CLI ではないので `repo-tools.yaml` には登録しない。

## 起動

```bash
just test-sites                                      # アンブレラのルートで。serve.py を起動（Windows でもこれ）
uv run --no-project tools/browser/test-sites/serve.py --port 9000   # ポートを変えるとき
bash tools/browser/test-sites/serve.sh               # system nginx がある Linux 向け（NGINX_BIN で実体を差し替え）
```

`serve.py` は標準ライブラリだけで動く。`--no-project` で uv ワークスペース全体の sync を避けている。

どちらも **ポート 8080 固定・1 プロセスで全サイトを配信**する。
ディレクトリ名がそのまま URL プレフィックスになる（`test-sites/tables/` → `http://localhost:8080/tables/`）。
例外は `custom_pages` で、既存シナリオが `http://localhost:8080/<page>.html` を直接指しているため**ルート直下**に配信される。

## サイト一覧

| URL         | サイト                              | どんなサイトか                                                                                                                                                                | 主なユースケース                                                                                                |
| ----------- | ----------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| `/`         | [custom_pages](custom_pages/pages/) | 検索・フォーム・3 ステップのウィザード・意図的な失敗フィクスチャ                                                                                                              | 基本操作（`click` / `fill` / `select` / `check` / `hover` / `press`）の素振り、複数ページ遷移、失敗ケースの再現 |
| `/catalog/` | [catalog](catalog/)                 | ダミーの買い物サイト（一覧 → 詳細 → カート → 配送・支払い → 完了）。カートは localStorage                                                                                     | 実務に近い通し E2E シナリオ、ページ間の状態引き継ぎ、途中再開（resume）の検証                                   |
| `/dynamic/` | [dynamic](dynamic/)                 | 遅延表示・スピナー・自動で消えるトースト・あとから有効になるボタン・自動更新カウンター・無限スクロール                                                                        | auto-waiting の挙動、`expect` のリトライ、「消えたこと」のアサーション、スクロール駆動の読み込み                |
| `/frames/`  | [frames](frames/)                   | iframe（入れ子あり）・Shadow DOM・alert / confirm / prompt・新規タブ・ポップアップ                                                                                            | `frameLocator` の連鎖、shadow 貫通、`page.on('dialog')`、`context.waitForEvent('page')`                         |
| `/tables/`  | [tables](tables/)                   | 43 行の注文テーブル（並び替え・担当者での絞り込み・10 件ずつページ送り）＋同名リンクの重複リスト                                                                              | `filter({ hasText })` / `nth()` / 行スコープのロケータ、ページ送りをまたぐ検索、一意でないロケータの扱い        |
| `/network/` | [network](network/)                 | ページから `fetch` で静的 JSON を取得。遅い API・404 になる API・存在しない POST 先を用意                                                                                     | `page.route()` でのモック、`waitForResponse`、失敗時 UI・リトライ導線の検証、リクエストの中身の検査             |
| `/auth/`    | [auth](auth/)                       | ダミーのログイン（`demo` / `demo1234`）と、未ログインならリダイレクトする保護ページ 2 枚                                                                                      | `storageState` の保存・再利用、Cookie と localStorage の両方を使った擬似セッション、ログイン壁の再現            |
| `/inputs/`  | [inputs](inputs/)                   | ファイル添付（単一 / 複数）・ドラッグ＆ドロップ・date / time / color / range / number / datalist・contenteditable・手書きキャンバス・キーボードショートカット・クリップボード | `setInputFiles`、`dragTo`、`mouse` での描画、`keyboard.press('Control+S')`、クリップボード権限                  |
| `/visual/`  | [visual](visual/)                   | 常に同じ見た目の要素と、毎回変わる要素（時刻・乱数の色・回転アニメ）、縦に長いページ                                                                                          | `toHaveScreenshot` の `mask` / `animations: 'disabled'`、要素単位とフルページのスクショ差分                     |
| `/a11y/`    | [a11y](a11y/)                       | 名前の付き方が異なるボタン群、`hidden` / `visibility` / 画面外 / `aria-hidden` / `opacity:0`、タブ・モーダル・ライブリージョン・入力エラー                                    | `getByRole` とアクセシブルネームの理解、aria snapshot、「見えるのに取れない／取れるのに見えない」の切り分け     |
| `/slow/`    | [slow](slow/)                       | 数百〜数千セルを生成する巨大 DOM（`?rows=2000` で件数指定）、遅延読み込み要素                                                                                                 | スナップショットが膨らむ状況の再現とサイズ削減の工夫、タイムアウトや描画待ちの限界の確認                        |

## 目的から引く

| やりたいこと                                 | 行き先                               |
| -------------------------------------------- | ------------------------------------ |
| とりあえず基本操作を試す                     | `/`                                  |
| 通しの業務シナリオを書く・再開を試す         | `/catalog/`                          |
| 「待ち」が絡む不安定さを再現する             | `/dynamic/`                          |
| iframe・ダイアログ・別タブで詰まる箇所を試す | `/frames/`                           |
| 一覧から目的の 1 行を選ぶロケータを鍛える    | `/tables/`                           |
| API をモックする・失敗時の挙動を見る         | `/network/`                          |
| ログイン済み状態を使い回す                   | `/auth/`                             |
| ファイル添付や特殊 UI を操作する             | `/inputs/`                           |
| スクリーンショット比較を安定させる           | `/visual/`                           |
| ロケータが取れない原因を切り分ける           | `/a11y/`                             |
| スナップショットが大きすぎる問題に向き合う   | `/slow/`                             |
| 意図的に失敗させる                           | `/edge-cases.html`（`custom_pages`） |

## サイトを追加するときの約束

- **静的 HTML のみ**。SPA フレームワークもビルドツールも入れない。1 サイト 1 ディレクトリで、`index.html` を入口にする。
- **role ベースのロケータで一意に取れる**要素だけを置く（可視ラベルか `aria-label` を必ず付ける）。
  一意にできない要素を意図的に置くのは、負のテスト用ページ（`custom_pages/pages/edge-cases.html`、`/a11y/`、`/tables/` の重複リスト）に限り、その旨をページ本文に書く。
- 検索・一覧の結果は**固定の静的レスポンス**を基本にする（`/tables/` と `/catalog/` のクライアント側フィルタは、ロケータ練習という目的のための例外）。
- ディレクトリを追加したら **`nginx/nginx.conf` の `location` と `serve.py` の `SITES`、この README.md の表、`custom_pages/pages/index.html` のリンク**の 4 か所を更新する。
- 認証は**ダミー資格情報のみ**。実在のアカウント情報やトークンは置かない。

詳細な規約は [AGENTS.md](AGENTS.md) を参照。
