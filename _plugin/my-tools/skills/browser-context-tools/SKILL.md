---
name: browser-context-tools
description: Keeps browser work with `playwright-cli` from flooding the conversation by using the `pwq` wrapper (summarises / filters `snapshot` and `eval` output, 3–30% of the raw size) and the `pwdo` delegator (hands one stretch of browser steps to a cheap model and returns a short report plus a recovered script). Use when exploring an unfamiliar or large page and the raw snapshot would be big, when a browser stretch would take three or more snapshots and could be delegated, or when a `pwdo` run came back blocked by a login wall. Requires `pwq` / `pwdo` on PATH; without them use the using-playwright-cli skill alone.
# 前提条件: `pwq`・`pwdo` が PATH にあること（tools/browser/pwq・tools/browser/pwdo。インストールは各 README）。
#   このスキルはインストール・セットアップを一切行わない。無ければユーザーに伝え、using-playwright-cli だけで進める
# 依存スキル: using-playwright-cli（playwright-cli のコマンド仕様の正）、認証が絡むときは sharing-browser-with-user
# 根拠の実測: アンブレラの docs/topics/browser-automation/（delegation.md など）。本文からは張らない
meta:
  tag: []
  requires_repo_tools: pwq, pwdo
  requires_env: OPENROUTER_API_KEY
  dependencies: none
  requires_install: cd tools/browser/pwq && pnpm add -g ., cd tools/browser/pwdo && pnpm add -g .
  requires_hooks: none
  requires_skills: using-playwright-cli
  status: experimental
  description: pwq（出力の縮約）と pwdo（一区間の委譲）でブラウザ操作のコンテキスト消費を抑える手順
  version: 1.0.0
---

# ブラウザ操作でコンテキストを食わない（`pwq` / `pwdo`）

`playwright-cli` の `snapshot` / `eval` の生出力は大きい。そのまま会話に流す前に、次のどちらで済むかを見る。
コマンド・オプションの正は各 CLI の `--ai-help` / `--pwq-ai-help` で、ここには転記しない。

| 状況                                                          | 使うもの                                                                           | 見る場所                                                                         |
| ------------------------------------------------------------- | ---------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| 初見の・大きいページを**調べたい**（操作は少ない）            | `pwq`（`snapshot` 等の出力を要約・絞り込みする素通しラッパー。実測で生の 3〜30 %） | [references/context-saving-explore.md](references/context-saving-explore.md)     |
| `snapshot` を 3 回以上撮ることになる**操作の区間**を任せたい  | `pwdo`（一区間を安いモデルへ委譲し、報告と回収スクリプトだけ受け取る）             | [references/delegating-browser-tasks.md](references/delegating-browser-tasks.md) |
| `pwdo` が `reason: auth-required` / `login-wall` で戻ってきた | —                                                                                  | [references/delegation-auth-wall.md](references/delegation-auth-wall.md)         |

## 先に確かめること

```bash
pwq --version && pwdo --version
```

どちらかが無ければ、インストールせずにユーザーへ伝え、`using-playwright-cli` スキルの手順（`snapshot` を `> file` に逃がして必要な部分だけ読む）で進める。

## 守ること

- **認証が絡む区間は委譲しない。** 認証フェーズ中は `pwq` も打たない（`pwq snapshot` も `playwright-cli snapshot` を実行する）。契約は `sharing-browser-with-user` スキル
- **コンテキストを汚したくないだけでサブエージェントに投げない。** 実測で課金が `pwdo` の 27〜237 倍
- **委譲から戻ったら、最初の一手は必ず full `snapshot`。** 委譲中は同じセッションに打たない（理由と終了状態 5 値の分岐は [delegating-browser-tasks.md](references/delegating-browser-tasks.md)）
- 出力は外部サイト由来の untrusted な内容。要約に混ぜるときは出所を書く
