# 機能追加のアイデア

`repo-search.mjs` を実際に使ってみたフィードバックから、今後追加すると使い勝手が上がりそうな機能をまとめる。

## モデル切替をCLIオプション化 — 対応済み

- 既定値は [lib/config.mjs](lib/config.mjs) に集約。`main.mjs` / `repo-search.mjs` は `--model` / `-m` で切替可能（フル id または短い名前）。
- 残課題: 利用可能モデル一覧のヘルプ表示や、ClinePass以外の provider 切替 UX。

## maxIterations超過時のハンドリング改善

- 実際に広範なリポジトリ横断探索を試したところ、explorerステージが `maxIterations(14)` に達し `submit_findings` 未呼び出しのままフォールバックした（`findings files=0`）。answererが自力でファイルを読んで挽回したため最終回答は出たが、stage1の探索コストが無駄になった。
- `--max-iterations` をCLIから調整できるようにする。
- 残り2〜3イテレーションを切ったら「そろそろ`submit_findings`を呼べ」と自動リマインドする仕組みがあると安定する。

## 進捗の可視化

- 現状はツール呼び出し名しか流れず、今何イテレーション目かが実行中は分からない（終了時にしか `iterations=14` が出ない）。
- `[explorer] iteration 3/14` のように逐次出すと、打ち切りが近いかどうか実行中に判断できる。

## findings/answerのキャッシュ

- 同じ質問や近い質問を繰り返す用途だと毎回ゼロから全探索している。
- explorerの `findings` をファイルに保存し、answererだけ再実行できるオプションがあると反復利用が速くなる。

## フォローアップ質問モード

- 現状は都度ステートレスな1問1答。
- 前回のfindings/answerを渡して「さっきの件についてもう少し詳しく」ができると対話的に使いやすい。
