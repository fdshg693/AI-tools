# サンドボックス構想の検討

`README.md` に書かれたラフプランを実現可能か、どのあたりが要調査かを整理する検討メモ。
Claude Code の仕様は、`claude-plugins/meta/skills/CATALOG.md` から関連スキルを参照して根拠とした
（出典は末尾「Claude Code 仕様の参照根拠」に明記）。

## 結論サマリ

- **実現可能**。各要素（Docker・GitHub App・ポーリング・Claude Code の非対話実行・
  Bypass Permission）は確立された技術の組み合わせで、個別に成立する。
- Claude Code 公式は Bypass Permission を「**サンドボックス（インターネット非アクセス）
  専用**」と位置付けており、README の「サンドボックスだから安全」という方針と整合する。
- **ただし要注意**: Claude Code 自体が `api.anthropic.com` へ接続するため、完全な
  「no internet access」にはできない。「許可確認の省略 ≠ 安全境界」であり、真の境界は
  **Docker コンテナ + GitHub App の最小権限** にある。この位置づけを設計に反映する必要がある。
- 既存の `tools/claude-wrapper/todo_runner/todo_runner.py`（TODO 駆動・新規セッション反復ループ）の知見が
  ISSUE 駆動のステートレス実行にそのまま活きる。

## 要素別検討

### 1. Docker によるサンドボックス化

- 妥当。コンテナを境界にする方針は Bypass Permission の想定用途と合致する。
- Claude Code 組み込みの `sandbox.*` 設定（filesystem/network 隔離）は
  **macOS/Linux/WSL2 のみ**。Docker コンテナ内は Linux なので、併用して二重境界にできる
  （Claude Code 側でもネットワーク許可ドメインを絞れる）。
- **要調査**
  - コンテナのベースイメージ・Claude Code の Linux 動作要件（Node バージョン、
    ネイティブバイナリの有無）。
  - リソース制限（CPU/メモリ/ストレージ）の具体的な値。
  - **ネットワーク設計が最重要**: 完全遮断すると Claude Code が動かない。
    `api.anthropic.com`（必須）＋ `github.com`（API/git）＋ 必要なパッケージレジストリ
    だけを許可するホワイトリスト方式にする必要がある。

### 2. Claude Code のインストール・起動・認証

- コンテナ内に `claude` CLI をインストールして非対話実行する方針は妥当。
- 認証は `ANTHROPIC_API_KEY` を環境変数経由で注入（README の方針通り）。
  コンテナは非対話なので OAuth ではなく API キーが適している。
- **起動方式の選択肢**（要決定）
  - (a) `claude` CLI を `-p`/`--print` で直接起動（最も単純）。
  - (b) Claude Agent SDK（Python）でラップして起動。`tools/claude-wrapper/todo_runner/todo_runner.py`
    の新規セッション反復ループの知見を再利用できる。ポーリング〜Claude起動〜PR作成までの
    オーケストレーションを組むならこちらが自然。
- `--bare` モードを使えば keychain/OAuth を読まず `ANTHROPIC_API_KEY`（or apiKeyHelper）
  に限定でき、設定の混入も防げる。

### 3. Bypass Permission の妥当性と実現方式

- README「サンドボックスなので安全」は、公式が `--dangerously-skip-permissions` に付与した
  警告文 "Recommended only for sandboxes with no internet access." と整合し、方針として妥当。
- ただし設計上の注意点（要明文化）:
  - Bypass Permission は「**許可確認の省略**」であって「安全境界ではない」。境界は
    Docker と GitHub App の最小権限。Claude の permission は最後の防線ではない。
  - `bypassPermissions` は `ask` ルール・コネクタ ask・ユーザー対話必須ツールを除いて
    **全ツールを許可**する。`allowed_tools` を併用しても意味がない（全許可される）。
    特定ツールを拒否したい場合は `disallowed_tools` を使う。
  - `bypassPermissions` は**サブエージェントにも継承され上書き不可**。サブエージェントの
    system prompt は緩い可能性があるため、サブエージェントの暴走もコンテナ境界で防ぐ前提。
- **実現方式の選択肢**（要決定）
  - (a) CLI フラグ `--dangerously-skip-permissions`
  - (b) `--permission-mode bypassPermissions`
  - (c) settings の `defaultMode: "bypassPermissions"`（User settings のみ有効）
  - (d) SDK で `permission_mode="bypassPermissions"`
- サンドボックス用途なら (a)/(b)/(d) のように明示付与が事故りにくい。
  `defaultMode` を settings に書くと無意識に常時バイパス化しうるため非推奨。
- 非対話実行なら初回確認プロンプトは出ないため、`skipDangerousModePermissionPrompt` は
  気にしなくてよい（project settings からは無視される仕様でもある）。

### 4. GitHub App による最小権限付与

- Claude Code は GitHub App 認証をネイティブに持たない。git 操作は OS の git credential
  に依存する。よって GitHub App の秘密鍵から installation token を発行し、コンテナに
  `x-access-token:<token>@github.com` 形式等で注入する。
- 権限は Contents(read)・Issues(read/write)・Pull requests(write) 等を最小構成で。
- 「ブランチプロテクションで main への PUSH を防ぐ」は正しいが、これは**リポジトリ側の
  保護ルール**であって GitHub App 権限ではない。両方設定が必要。
- **要調査**
  - installation token の有効期限（1時間）と再発行タイミング・キャッシュ方法。
  - ブランチ保護ルールの具体的内容（required reviews / status checks / push 制限）。
  - fine-grained PAT 等の代替認証との比較。

### 5. ISSUE ポーリングと作業フロー

- 「ポーリング形式で外部からのアクセスを遮断」は妥当。コンテナから外へ出る方向のみで
  済み、インバウンド公開が不要になるためセキュア。
- メンション検知: Issues/コメント本文内の `@sandbox` 文字列を全文検索すればよい。
  ただし GitHub App は `@<app-name>[bot]` のボットアカウントとして振る舞うため、
  人間のメンションとは扱いが異なる点に留意（文字列ベースで拾う）。
- **要調査**
  - ポーリング間隔・レート制限（GitHub API）・処理済み ISSUE の状態管理（既読化）。
  - 1 ISSUE の作業完了をどう定義するか（PR 作成 / コメント投稿 / ステータス変更）。
  - 並列実行の要否（1 ISSUE = 1 コンテナか、1 常駐ワーカーが逐次処理か）。

### 6. セッション管理（ステートレス設計）

- README「終わったらセッション停止。次の ISSUE が来たらまた作業」は、1 ISSUE = 1 セッションの
  ステートレス設計。`tools/claude-wrapper/todo_runner/todo_runner.py` の「新規セッション反復
  （resume/continue_conversation を使わない）」と思想が一致し、知見が再利用できる。
- SDK なら `query()`（毎回新規セッション）を使い、プロンプトに ISSUE 本文・作業ディレクトリの
  絶対パス・目標を注入する。`todo_runner.py` で得た「cwd を絶対パスで明示する」知見が
  Haiku 限定でなくとも有効（パス迷走の予防）。
- **要調査**
  - 1 ISSUE ごとの作業ディレクトリ分離（`git worktree` / ブランチ切り、または
    Claude Code の `--worktree` / `--add-dir` 利用）。
  - `--no-session-persistence`（セッションをディスクに残さない）の併用可否。
  - 失敗時ロールバック（`git reset` / Claude の file checkpointing）。

### 7. クラウド移行

- 「まずは Docker、最終的にクラウド」は妥当な段階的アプローチ。コンテナ化しておけば
  ほぼそのままクラウドのジョブ基盤へ持ち運べる。
- **要調査**
  - クラウド実行基盤の選定（Cloud Run Job / ECS Fargate / Batch 等）。
  - シークレット管理（Secrets Manager / Parameter Store で API キーと GitHub App 鍵）。
  - コスト試算（Claude API 利用料 ＋ コンピュート ＋ ポーリング常駐の費用）。
  - 常駐ワーカー vs イベント駆動起動（EventBridge等）の比較。

## 主要な要調査項目（優先度順）

1. **【高】ネットワーク許可リスト設計**: `api.anthropic.com` は必須。完全遮断は不可。
   どこを開けるか（パッケージレジストリ含む）を確定する。
2. **【高】Bypass Permission の実現方式**: (a)CLIフラグ / (b)`--permission-mode` /
   (d)SDK `permission_mode` のいずれを採用するか。`disallowed_tools` で危険ツールを絞るか。
3. **【高】起動方式**: `claude -p` 直叩き vs Claude Agent SDK ラップ（`todo_runner.py` 知見）。
   オーケストレーション（ISSUE 取得〜Claude 起動〜PR/コメント反映）をどこで組むか。
4. **【高】GitHub App トークン注入と更新**: installation token（1時間期限）の再発行・
   git credential への渡し方。
5. **【中】Claude Code 組み込み `sandbox.*` の併用可否**（Linux コンテナ内での動作確認）。
6. **【中】作業ディレクトリ分離**: 1 ISSUE = 1 worktree/ブランチ。
7. **【中】セッションのステートレス化**: `--no-session-persistence`、SDK で resume/continue 非使用。
8. **【中】ブランチ保護ルールの具体設定**（required reviews / status checks / push 制限）。
9. **【低】クラウド移行先**・シークレット管理・コスト試算。
10. **【低】失敗時ロールバック**（`git reset` / file checkpointing）。

## リスクと対策

- **プロンプトインジェクション**: ISSUE 本文は外部入力。Claude が本文中の悪意ある指示に
  従って変な PR/コメントを作るリスク。→ 境界はコンテナと最小権限 GitHub App で担保しつつ、
  許可ユーザのホワイトリスト・出力検証・PR 作成前フックを検討。
- **Bypass Permission の過信**: 境界は Docker と GitHub App。Claude の permission は
  安全境界ではない（本メモ・関連スキルに明記）。設計ドキュメントで明文化する。
- **API キー漏洩**: `ANTHROPIC_API_KEY` が ISSUE/PR/ログに漏れないよう、`--bare` ＋
  apiKeyHelper、ログサニタイズ、`disableBypassPermissionsMode` の誤設定防止。
- **サブエージェントの暴走**: `bypassPermissions` はサブエージェントに継承・上書き不可。
  → コンテナ境界頼み。サブエージェントの system prompt は最小限に。

## README からの補足・乖離

- README の「最小権限で GitHub アクセス」は Claude Code の機能ではなく git credential の
  設定問題。本メモで補足。
- README の「Bypass Permission（サンドボックスなので安全）」は方針として正しいが、
  「安全境界は Claude ではなく Docker＋GitHub App にある」ことを補足。
- 「no internet access」は Claude Code 公式の理想条件だが、実運用では `api.anthropic.com`
  を開ける必要があり完全遮断は不可。ネットワークは最小許可リスト方式にする点を補足。

## Claude Code 仕様の参照根拠

CATALOG.md から関連スキルを選定し、各スキルが管理する公式ドキュメント／CLI ヘルプの
スナップショットを根拠とした。

- **claude-cli-docs** — `output/help_result.yaml`（v2.1.215 スナップショット）。
  `--dangerously-skip-permissions` / `--allow-dangerously-skip-permissions` の警告文
  "Recommended only for sandboxes with no internet access."、`--permission-mode` の選択肢
  （`bypassPermissions` 含む）、`-p/--print`、`--no-session-persistence`、`--bare`、
  `--setting-sources`、`--settings`、`--worktree`、`--add-dir`、`--safe-mode` 等。
- **claude-code-docs** — `output/llms-full.txt`（公式 `code.claude.com` ミラー）。
  `permission_mode="bypassPermissions"` の挙動（`allowed_tools` 併用は無意味、
  `disallowed_tools` で拒否）、サブエージェントへの継承（上書き不可）、settings の
  `defaultMode` / `disableBypassPermissionsMode` / `skipDangerousModePermissionPrompt`、
  `sandbox.*`（macOS/Linux/WSL2）等。
- **claude-settings** — `settings.md`。permissions 評価順（deny→ask→allow）、`sandbox.*` 構造、
  `defaultMode` の User 設定制約（`auto`/プロジェクト自己付与の禁止）。
- **claude-agent-sdk** — `SKILL.md`。`query()` vs `ClaudeSDKClient`、resume/continue_conversation、
  「`bypassPermissions` のような広い自動承認を本番や未隔離ワークスペースで使わない。
  許可確認の省略は安全境界ではない」、`secure-deployment` / `hosting` の本番化要件。

> 上記スナップショットは時点凍結のため、実装段階で最新を確認する（各スキルの取得スクリプトで
> 更新可能）。
