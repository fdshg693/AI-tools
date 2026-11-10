# ona-run 動作検証メモ（2026-08-12）

対象リポジトリ: `https://github.com/fdshg693/AI.git`（このリポジトリ自身）。`tools/aim`（OpenRouter専用実装をOpenAI互換エンドポイント全般に対応させる）のプラン作成をONAへ委譲するテストとして`ona-run`を実行し、複数の実バグ・環境整備不足を発見・対処した。次回以降の再検証のためのチェックリストとして残す。

## 見つかった問題と対応

### 1. このリポジトリの`.devcontainer`がツールチェーン未導入のスタブだった

- 症状: Onaが自動生成する既定の`.devcontainer`はNode.js/Python/uv等が一切入っていない素の`mcr.microsoft.com/devcontainers/base:2.0.4-noble`イメージだった（当時リポジトリに`.devcontainer`自体が存在しなかった）
- 対応: `.devcontainer/devcontainer.json` + `Dockerfile`を追加し、Node.js/pnpm/uv/Claude Code CLI/Codex CLIを導入（mainへpush済み: `55be498`）
- 導入したツールのバージョンは`mise.toml`のピン留めに合わせている（Node.jsのみnodesourceのメジャーバージョン指定、pnpmはバージョン固定）

### 2. 追加したDockerfileが`corepack`未同梱で失敗

- 症状: Node.js 26系では`corepack`がデフォルトバンドルから外れており、`corepack enable`が`corepack: not found`（exit 127）でビルド失敗
- 対応: `corepack`経由をやめ`npm install -g pnpm@<version>`に変更（mainへpush済み: `5f39642`）
- 教訓: Node.jsのメジャーバージョンが上がるとバンドルツールの前提が変わりうる。`corepack`に依存するDockerfile/CIは要注意

### 3. `tools/ona-run/ona_run_cli.py`の起動待ち判定バグ（本命）

- 症状: `wait_until_running()`が`envs[0].get("phase")`（トップレベル）を見ていたが、`ona environment get -o json`の実際のレスポンス形は`envs[0]["status"]["phase"]`にネストされている。そのため実際の起動状況に関わらず常に`phase=None`扱いになり、`--start-timeout`到達まで待った末に必ず`infra_error`で失敗していた
  - 環境自体は正常に起動していた（`ona environment get`のtable出力や直接JSON確認では正しく`phase`が取れる）。つまり**軽量なタスクであっても`ona-run`は今日までほぼ確実に失敗していた**
- 対応: `phase = envs[0].get("status", {}).get("phase")`に修正（`features/saas-connect`ブランチにコミット済み: `fbf59b3`。**`tools/ona-run`自体がまだ`origin/main`に存在しないためmainへは未push**。`tools/ona-run`がmainに乗るタイミングでこの修正も一緒に反映される）
- 再発防止のヒント: `tools/ona-run/tests/test_command_building.py`にはargv組み立てのユニットテストはあるが、`wait_until_running`のphase判定ロジックに対するテスト（`ona environment get -o json`のレスポンス形をモックした単体テスト）が無い。追加を検討する価値がある

### 4. Windows(Git Bash/MSYS) + `ona`公式CLI(ネイティブWindowsバイナリ)特有の落とし穴

`ona-run`経由ではなく`ona`公式CLIを直接叩いて調査した際に踏んだ問題。`ona-run`内部（Python `subprocess.run`にargvリストを渡す形）では発生しないが、人手で`ona environment exec`等を直接叩いて調査する際は注意。

- **パス自動変換**: Git BashのMSYSは`/tmp/foo`のような絶対パス風の引数を自動でWindowsパスに変換してから渡す。`ona.exe`はネイティブWindowsバイナリなのでこの変換が素通りし、リモートコンテナ内のパス（`/workspaces/AI/...`等）を渡したつもりが存在しないWindowsパスに化ける。**回避策: `export MSYS_NO_PATHCONV=1`を先に設定してから`ona`コマンドを叩く**
- **`ona environment exec`はローカルstdinをリモートへ転送しない**: `ona environment exec <id> -- bash -c "cat > /tmp/x" < local_file`のような形でファイルを転送しようとしても、リモート側のstdinは空。ファイル転送が必要な場合はDockerfile/devcontainer機能側で完結させるか、コマンド引数に埋め込む
- **長いタスク文字列を`--agent claude`で渡すと、タスク文中の半角括弧`(`でリモート側シェルが構文エラーになるケースを観測**（`sh: 1: Syntax error: "(" unexpected`）。`ona environment exec`のRPCがリモート側で最終的に`sh -c`相当を経由している可能性がある。**未確定・未再現テスト**（この问题を踏んだ実行では後述の認証エラーで先に失敗しており、括弧を含まない短いタスクでの再現確認はできていない）。長いタスク文字列を渡す場合は半角括弧・バッククォート・二重引用符等のシェルメタ文字を避けるか、`--command`でシェル外の実行形にするのが安全

## 未解決: Ona環境内のClaude Code CLIが未認証

- `--agent claude`で実際に`claude -p "..." --dangerously-skip-permissions`を実行すると`Not logged in · Please run /login`で失敗する
- Ona環境（コンテナ）にはAnthropic APIキー等の認証情報が渡っていない。`ona environment create`に環境変数/組織シークレットとして`ANTHROPIC_API_KEY`等を渡す仕組みが必要と思われるが、具体的な設定方法・secrets機構の詳細は未調査
- 認証情報を含む具体的な設定手順・値は、秘密情報のためこのファイル（Git管理下）には書かない。もし調査した設定方法を残したい場合は、同じ`check/`配下に`*.local.md`ファイルを作ること（`.gitignore`済み。中身は空でも作成済み — [local-secrets-template.local.md](local-secrets-template.local.md)参照）

## 次回再検証時のチェックリスト

- [ ] Claude Code CLIの認証方法を解決する（`ANTHROPIC_API_KEY`をOna環境変数/シークレットとして渡す方法を確認）
- [ ] `tools/ona-run`が`origin/main`にマージされたら、[上記3番目の修正](#3-toolsona-runona_run_clipyの起動待ち判定バグ本命)がちゃんと乗っているか確認する（乗っていなければ再度パッチが必要）
- [ ] `ona-run`実行時は`--class-id`を明示指定する（未指定だと自動解決で`GPU Large`が選ばれることがあり、無駄にコストが高い・遅いクラスになりうる。軽量タスクなら`Small`で十分）
  - このリポジトリでの参考クラスID: Small=`019c5c59-55db-796b-aa0b-989b87907b1c`, Regular=`019c5c59-55db-7978-9828-6ff7f0ff9e7c`（`ona environment list-classes`で最新を確認すること。IDは変わりうる）
- [ ] `--start-timeout`は既定の300秒では不足しがち。このリポジトリはdevcontainerビルドを含めて起動に5〜8分程度かかるため、`600`〜`900`秒程度を指定する
- [ ] 長いタスク文字列を`--agent`テンプレートで渡す場合、半角括弧等のシェルメタ文字を含めないか、含む場合は`--command`での代替を検討し、実際に動くか確認する（上記4番目の未確定事項の再現確認を兼ねる）
