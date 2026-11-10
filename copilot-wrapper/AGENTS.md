# Copilot SDK BYOK ラッパー

`@github/copilot-sdk`（Node.js/TypeScript版 GitHub Copilot SDK）を使い、BYOK（Bring Your Own Key）でOpenAI互換APIのモデルを1ターンだけ呼び出すCLIです。接続先（ベースURL・APIキー・モデル）、有効化するカスタムツール、reasoning effort等の実行オプションをすべてコマンドライン引数（または`.env`）で指定して実行できます。

- `main.mjs` — CLI本体。
- `lib/config.mjs` — CLI引数と`.env`をマージしてBYOKの`ProviderConfig`等を組み立てる。
- `lib/tools.mjs` — `--tool`で有効化できるデモ用カスタムツール定義（`defineTool` + zod）。
- `lib/cliPath.mjs` — 下記「既知の問題」の回避策。
- `lib/dotenv.mjs` — 外部依存なしの最小`.env`ローダー（cline-wrapperと同じ実装）。

## セットアップ

```powershell
pnpm install --filter copilot-wrapper-byok
Copy-Item tools\copilot-wrapper\.env.example tools\copilot-wrapper\.env
# .env を編集して COPILOT_BYOK_BASE_URL / COPILOT_BYOK_API_KEY / COPILOT_BYOK_MODEL を設定
```

`.env`の値はCLI引数で個別に上書きできる（例: `--model`は`COPILOT_BYOK_MODEL`を上書き）。実際の環境変数が`.env`より優先される（`lib/dotenv.mjs`は未設定のキーのみ埋める）。

## 実行

リポジトリルートから、またはこのディレクトリ内から実行する。

```powershell
node tools\copilot-wrapper\main.mjs --model gpt-4 --base-url https://my-api.example.com/v1 --api-key $env:MY_API_KEY -p "1+1="

# Ollama等ローカルプロバイダー（APIキー不要）
node tools\copilot-wrapper\main.mjs --model deepseek-coder-v2:16b --base-url http://localhost:11434/v1 -p "Hello!"

# .env の値をそのまま使う場合
node tools\copilot-wrapper\main.mjs -p "自己紹介して"

# カスタムツールを有効化 + ストリーミング + JSON出力
node tools\copilot-wrapper\main.mjs --tool get_time --tool http_get --stream --json -p "現在時刻を教えて"
```

`node main.mjs --help`で全オプション一覧、`node main.mjs --list-tools`で登録済みツール名一覧を表示する。

### 主なオプション

| オプション            | 説明                                                                                       |
| --------------------- | ------------------------------------------------------------------------------------------ |
| `--model` / `-m`      | モデルID（BYOK使用時は必須）                                                               |
| `--base-url`          | OpenAI互換APIのベースURL（必須）                                                           |
| `--api-key`           | APIキー（Ollama等ローカルプロバイダーでは省略可）                                          |
| `--provider-type`     | `openai` \| `azure` \| `anthropic`（既定 `openai`。Azure OpenAIホストは`azure`必須）       |
| `--wire-api`          | `completions` \| `responses`（openai/azureのみ、既定 `completions`）                       |
| `--azure-api-version` | `provider-type=azure`のAPIバージョン                                                       |
| `--tool <name>`       | 有効化するカスタムツール名（複数指定可）。`lib/tools.mjs`参照                              |
| `--approve-all`       | shell/write等すべてのツール実行を自動承認（危険）。既定は`read`/カスタムツールのみ自動承認 |
| `--stream`            | ストリーミング出力（差分を標準エラー出力に書き出す）                                       |
| `--reasoning-effort`  | `low` \| `medium` \| `high` \| `xhigh` \| `max`                                            |
| `--system`            | システムメッセージに追記する内容                                                           |
| `--json`              | 最終応答をテキストではなくJSONで出力                                                       |

`provider`（BYOK設定）の各フィールドの意味は`@github/copilot-sdk`パッケージ本体の`README.md`（`Custom Providers`節）が一次情報。詳しい機能やイベントの仕様は[github-copilot-sdk-docs](../../copilot-plugins/meta/github-copilot-sdk-docs/SKILL.md)スキル経由で公式ドキュメントを参照する。

## 権限ポリシー（既定）

非対話実行のため、`onPermissionRequest`に既定のポリシーを設定している（`main.mjs`の`makePermissionHandler`）。

- `read` / `custom-tool`（`--tool`で有効化したツール自身の呼び出し） → 自動承認
- それ以外（`shell` / `write` / `mcp` / `url` 等、Copilot CLIの組み込みツール）→ 既定は拒否（モデルへフィードバックを返す）
- `--approve-all`を付けると`approveAll`（SDK組み込み）を使い、全リクエストを自動承認する。ファイル書き込みやshell実行までモデルに許可することになるため、信頼できるBYOKモデル・用途でのみ使用する。

## 既知の問題: pnpm環境での`@github/copilot`プラットフォームパッケージ解決

`@github/copilot-sdk`はランタイム本体（`@github/copilot-win32-x64`等、OS/アーキ別パッケージ）を自分自身のファイル位置から`import.meta.resolve`で探すため、pnpmの隔離されたnode_modules構成では見つからず`Could not resolve a @github/copilot platform package`で失敗する（npmのフラットインストール前提の実装で、pnpmのstrict node_modulesと相性が悪い）。

このリポジトリでは以下で回避している。

1. `package.json`で`@github/copilot`をこのパッケージの直接の依存関係として明記する（`@github/copilot-sdk`の推移的依存だけでは不可視）。
2. `lib/cliPath.mjs`の`resolveBundledCliPath()`が、直接依存として解決できる`@github/copilot`のインストール位置から、同じnode_modules内の兄弟パッケージとしてプラットフォーム別バイナリのパスを自前で組み立てる。
3. `main.mjs`が起動時に`COPILOT_CLI_PATH`未設定なら上記で解決したパスをセットする（`COPILOT_CLI_PATH`はSDKが最優先で使う）。

`pnpm install --filter copilot-wrapper-byok`実行時に`koffi`（`@github/copilot-sdk`のFFI依存）のビルドスクリプト承認を求められた場合は、リポジトリルートの`pnpm-workspace.yaml`の`allowBuilds.koffi: true`で許可済み。
