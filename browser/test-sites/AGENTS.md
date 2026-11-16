@./README.md

## 自作テストサイトの規約

- サイト一覧と用途は [README.md](README.md) が正。ディレクトリを増やしたら README.md の表も必ず更新する。
- ページ追加時は role-based ロケータで一意に拾える要素（visible なラベル / aria-label 付き）のみを使う。SPA 化・ビルドツール導入はしない。
- 検索・一覧系のページは固定の静的レスポンスを基本とする（`tables/`・`catalog/` のクライアント側フィルタはロケータ練習という目的のための明示的な例外）。
- ローカル起動はアンブレラのルートで `just test-sites`（`serve.py` を `uv run --no-project` で起動。標準ライブラリのみ、ポート 8080、全サイトを 1 プロセスで配信）。system nginx がある Linux では `bash tools/browser/test-sites/serve.sh`（`nginx/nginx.conf`、同一 URL 構成）。どちらもフォアグラウンド起動のみで、停止は Ctrl+C。
- URL プレフィックスはディレクトリ名と一致させる。例外は `custom_pages` で、既存シナリオ（`workflow/playwright-app/scripts/stories/*.yaml`）が `http://localhost:8080/<page>.html` を直接指しているためルート直下に配信する。この配信位置は変えない。
- サイト追加時に更新する箇所は 4 つ: `nginx/nginx.conf` の location、`serve.py` の `SITES`、`README.md` の表、`custom_pages/pages/index.html` のリンク。
- 認証はダミー資格情報のみ（`auth/` は `demo` / `demo1234` をページ内 JS で判定するだけ）。実在のアカウント情報・トークンは置かない。
- 外部へのデプロイは未実装。追加する場合はこのディレクトリ直下にインフラ用ディレクトリを新設し、各サイトの HTML には手を入れない。
- `custom_pages/pages/edge-cases.html` は意図的な失敗・非対応操作の検証用フィクスチャであり、role-based ロケータの一意性規約の対象外とする（同一アクセシブルネームを持つ複数ボタンを意図的に配置している）。`index.html` からもリンクしない。
