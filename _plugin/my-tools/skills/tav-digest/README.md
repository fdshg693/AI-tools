# tav-digest

## このスキルの狙い

`tav extract` / `crawl` / `search-extract` / `map-extract` に `--topic` を付けて実行すると、
取得した本文は `pages/NNNN-<title>.md` に1ページ1ファイルで書き出され、ターミナルには
「Wrote N page .md file(s) to ...」という通知しか出ない(詳細は `tav-cli` スキル参照)。
`pages/index.json` を Read すればタイトルと各エントリの `char_count` は分かるが、素直に
やるとそこから先は Claude 自身が `pages/` 配下のファイルを1件ずつ順番に Read することに
なる。これは

- 件数が多くタイトルだけでは関連性を判断しづらいとき、全件を逐次 Read すると
  会話コンテキストを無関係な抜粋で消費し、時間もかかる
- タイトルから読みたいファイルは絞れていても、その中に `char_count` の大きいファイルが
  複数あると、まとめて Read した分だけコンテキストを消費する

という無駄につながる。このスキルは、この「`pages/` の結果ファイルを読む」フェーズを
`aim --parallel` の並列AI呼び出しに置き換え、**関連する内容だけ**を1コマンドでまとめて抜き出させる。
どのファイルを渡すか(全件か、`index.json` から選んだ一部か)は呼び出し側が `pages/index.json`
を見た上で決める — `char_count` の合計のような集計値は判断に使わない(`index.json` を
開かずに済ませられるわけではないため)。

discovery役割(`search/` / `map/`)は1タスク=1集約JSONファイルで元々 skim しやすく、report
役割(`research/`)は成功時のみ書かれる単一Markdownレポートなので、いずれもこのスキールの
対象外(そのまま `tav-cli` の判断フローで Read すれば足りる)。対象は本文が複数ファイルに
分割される content 役割(`pages/`)だけに絞っている。

`ms-digest`(`ms-learn` × `aim-cli` の `--parallel`)と同じ構造の薄いオーケストレーションスキルで、
`index.md` の代わりに `pages/index.json` を起点にする点、各ページ本文が `URL:` 行を
持たない(URLは `index.json` 側にしかない)ため出典URLの拾い方が異なる点が主な差分。
