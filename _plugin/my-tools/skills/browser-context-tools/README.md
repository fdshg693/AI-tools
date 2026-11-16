# browser-context-tools（メンテナ向け）

`pwq`・`pwdo`（`tools/browser/`）を使って、ブラウザ操作の出力を会話に流さずに済ませる手順のスキル。
実行時の手順は [SKILL.md](SKILL.md) と `references/`。ここは設計意図のみ。

## なぜ browser プラグインから分けたのか

microsoft/playwright のクローンでは `using-playwright-cli` の `references/` に入っていたが、
`context-saving-explore.md`・`delegating-browser-tasks.md` は全面的に `pwq`/`pwdo` のインストールを前提にしている。
「本文が `tools/` の CLI のインストールを必須にするスキルは my-tools に置く」という置き場所の基準
（`maintenance/docs/repo-layout.md`）に従い、ここへ分けた。`sharing-browser-with-user` の
`scripted-automation.md` §5（委譲が認証壁に当たったとき）も `pwdo` 前提なので `references/delegation-auth-wall.md` に移した。

browser プラグイン側（`using-playwright-cli`・`sharing-browser-with-user`）からは、スキル名で「入っていれば」と任意に参照している。

## 根拠

- CLI の表面・実測値・終了状態の定義は各ツールの README（`tools/browser/pwq/README.md`・`tools/browser/pwdo/README.md`）が正。references には転記しない
- 実測の生データ・失敗の内訳はアンブレラの `docs/topics/browser-automation/`（`delegation.md` など）
