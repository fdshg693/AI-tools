# ブランチ保護ルール設定Runbook

`main`ブランチへの直接pushを防ぐための設定手順（一度きりの手動セットアップ）。
サンドボックスエージェントのGitHub Appには`Contents: Read and write`を付与しており
技術的には直接pushが可能なため、これを塞ぐのはGitHub App権限ではなく本ページの
ブランチ保護ルールの役割（[docs/github-app-setup.md](github-app-setup.md) 6節参照）。

`gh api`コマンドで適用する。個人リポジトリの一度きりの設定であり、Terraform等の
IaC化はしない（繰り返し適用が必要なインフラではないため）。

## 前提

- `gh auth login`済みで、対象リポジトリ（既定: `fdshg693/AI`）への管理者権限があること。
- 以下のコマンドはリポジトリのオーナーアカウントで実行する（GitHub Appのトークンでは
  ブランチ保護APIを呼べない。人間のアカウントで一度だけ設定する操作のため）。

## 設定内容

- `required_pull_request_reviews`を設定することで、mainへの直接push（GitHub Appの
  installation tokenを含む）が技術的に阻止され、PR経由のマージのみ可能になる。
- 個人リポジトリでレビュワーが自分しかいないため、`required_approving_review_count: 0`
  として「PR必須・承認数0」にする。
- `enforce_admins: false`にする。サンドボックスエージェント（GitHub App）のpushだけを
  止めたく、人間オーナー自身の直接pushは引き続き許可したいため。

## 適用コマンド

```bash
gh api \
  --method PUT \
  -H "Accept: application/vnd.github+json" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  /repos/fdshg693/AI/branches/main/protection \
  -f required_status_checks='null' \
  -F enforce_admins=false \
  -f 'required_pull_request_reviews[required_approving_review_count]=0' \
  -f restrictions='null'
```

- `required_status_checks`: 本リポジトリにはこのエージェント専用の必須CIチェックは
  無いため`null`（未設定）。CIを追加した場合はここに`contexts`を指定する。
- `restrictions`: push可能ユーザー/チームを絞る機能。オーナー1人での運用のため`null`
  （制限なし。ブランチ保護自体が有効なら、GitHub Appはこの設定に関わらずPR必須になる）。

## 確認

```bash
gh api /repos/fdshg693/AI/branches/main/protection
```

出力の`required_pull_request_reviews.required_approving_review_count`が`0`、
`enforce_admins.enabled`が`false`になっていれば設定完了。

続けて、GitHub Appのinstallation tokenで`main`へ直接pushを試みると
`protected branch`エラーで拒否されることを確認する（`orchestrator/run_agent.py`は
そもそも`sandbox/issue-<N>`ブランチにしかpushしない設計だが、保護ルール自体の
動作確認として一度試す価値がある）。

## 解除・変更したい場合

```bash
gh api --method DELETE /repos/fdshg693/AI/branches/main/protection
```

設定をやり直すときは、上記DELETE後に「適用コマンド」を再実行する。
