# 参考資料（要件定義・設計のための調査メモ）

[README.md](README.md) の詳細設計・実装フェーズで再調査の手間を減らすための、URLと要点のまとめ。
調査日: 2026-07-08（tavily検索 `--topic ai_logs_infra` の結果より）。各ツールの仕様は変わりうるため、実装直前に一次情報URLで再確認すること。

## Claude Code の OTel テレメトリ

- <https://code.claude.com/docs/en/monitoring-usage> — 公式ドキュメント。一次情報はここ。
  - 有効化には `CLAUDE_CODE_ENABLE_TELEMETRY=1` が必須。他の `OTEL_*` は単体では無視される
  - `OTEL_LOGS_EXPORTER=otlp` / `OTEL_METRICS_EXPORTER=otlp` / `OTEL_TRACES_EXPORTER`（トレースは `CLAUDE_CODE_ENHANCED_TELEMETRY_BETA=1` も必要な beta 機能）
  - `OTEL_EXPORTER_OTLP_ENDPOINT` / `OTEL_EXPORTER_OTLP_PROTOCOL`（`grpc` / `http/json` / `http/protobuf`）、信号別に `_METRICS_ENDPOINT` / `_LOGS_ENDPOINT` / `_TRACES_ENDPOINT` で個別上書き可
  - 送信内容の詳細度は `OTEL_LOG_USER_PROMPTS` / `OTEL_LOG_ASSISTANT_RESPONSES` / `OTEL_LOG_TOOL_DETAILS` / `OTEL_LOG_TOOL_CONTENT` / `OTEL_LOG_RAW_API_BODIES` で個別制御
  - メトリクス8種（`claude_code.session.count`, `claude_code.token.usage`, `claude_code.cost.usage` 等）、イベント20種超（`claude_code.user_prompt`, `claude_code.tool_result`, `claude_code.mcp_server_connection` 等）の一覧はリポジトリ内 [`.claude/skills/investigating-claude-code-logs/otel-reference.md`](../../../.claude/skills/investigating-claude-code-logs/otel-reference.md) に整理済み
  - **注意**: `OTEL_*` 環境変数は Bash ツール・hook・MCP サーバーなどの子プロセスには伝播しない（CLI本体のイベントのみ計装される）
  - 組織全体へ強制するには managed settings の `env` キーを使う（個人利用の本基盤では未使用）

## Codex CLI の OTel テレメトリ

- <https://openai.com/index/running-codex-safely> — OpenAI公式ブログ。Codex は OTel ログ export でユーザープロンプト・ツール承認判断・ツール実行結果・MCPサーバー利用・ネットワークプロキシ許可/拒否イベント等を送信可能。SIEM集約が公式ユースケースとして明記されている
- <https://victoriametrics.com/blog/vibe-coding-observability> — Codex含む複数ツールの比較記事。`~/.codex/config.toml` の `[otel]` セクション例あり
  ```toml
  [otel]
  environment = "production" # 既定は "dev"
  log_user_prompt = false    # 既定でプロンプト本文はredact
  [otel.exporter.otlp-http]
  endpoint = "https://your-collector:4318"
  protocol = "binary"
  [otel.trace_exporter.otlp-http]
  endpoint = "https://your-collector:4318"
  protocol = "binary"
  ```
  - **Codexはログとトレースのみ対応、メトリクスは非対応**（メトリクスが要るならログから自前集計）
  - 標準属性: `service.name`（`codex_cli_rs`固定）, `conversation.id`, `app.version`, `model`, `auth_mode`, `user.email` 等
- <https://grafana.com/docs/grafana-cloud/monitor-infrastructure/integrations/integration-reference/integration-openai-codex> — Grafana Cloud公式インテグレーション。`~/.codex/config.toml` からOTLP HTTPで送信する構成（Grafana Cloud向けだが自前Collectorにも応用可）
- <https://signoz.io/docs/codex-monitoring> — SigNoz向けだが `otlp-grpc` エクスポータ設定例が具体的で参考になる
- <https://docs.oodle.ai/ai-agent-observability/codex> — イベント種別一覧（`codex.conversation_starts`, `codex.user_prompt`, `codex.tool_decision`, `codex.tool_result` 等）とメトリクス種別（トークン使用量をユーザー別/モデル別/サーフェス別に分解）

## GitHub Copilot の OTel / 監査ログ（v1では対象外・参考）

- <https://code.visualstudio.com/docs/agents/guides/monitoring-agents> — VS Code公式ドキュメント。Copilot CLI・Chat拡張のOTel設定は `github.copilot.chat.otel.*` 系のsettingsで行う（既定エクスポータは `otlp-http`、`otlp-grpc`/`console`/`file` にも切替可）。認証ヘッダは `OTEL_EXPORTER_OTLP_HEADERS` 環境変数でのみ設定可能
- <https://github.com/github/copilot-cli/issues/2934> — Copilot CLI (`copilot monitoring`) の未解決issue。`COPILOT_OTEL_EXPORTER_TYPE` は `otlp-http`/`file` のみ対応、`OTEL_EXPORTER_OTLP_PROTOCOL` は無視されprotobuf非対応（2026年時点でJSON固定）
- <https://github.com/github/copilot-cli/issues/2471> — 「Claude Codeとの機能パリティが欲しい」というfeature request。自律的なheadless実行時の実行履歴確認ニーズが背景
- <https://docs.github.com/en/copilot/how-tos/administer-copilot/manage-for-enterprise/review-audit-logs> — 公式ドキュメント。組織のAudit Logは Enterprise/Business プラン前提、かつ**ローカルのプロンプト内容は含まれない**（別途カスタムhookでの送信が必要と明記）。保持期間180日、SIEMへのストリーミング推奨
- <https://github.com/orgs/community/discussions/190671> — Audit Log APIの実務的な使い方（`action:copilot` フィルタ、CSV export、REST API取得例）

## さくらのクラウド VM 料金

- <https://cloud.sakura.ad.jp/products/server> — 公式最新料金表（一次情報）。石狩含む全ゾーンの月額/日額/時間額を掲載。**1コア/1GB = 月額1,540円**が最安構成
- <https://media.future.ad.jp/guide-sakuracloud-pricing>（更新日2026-06-23） — 料金体系の解説。時間額・日額・月額のうち最安が自動適用される、データ転送量課金なし、**サーバー停止中は課金されないがディスクは停止中も課金される**、という運用上の注意点
- 参考（本基盤の対象外）: <https://streamrental.com/sakura-vps>, <https://www.itreview.jp/products/sakuranovps/price> — 「さくらのVPS」は512MBプラン月643円〜とさらに安いが、Terraform provider (`sacloud/sakuracloud`) の管理対象は「さくらのクラウド」であり VPS ではない点に注意

## さくらのクラウド Terraform Provider

- <https://cloud.sakura.ad.jp/news/2025/12/25/terraform-provider-sakura-v3> — 公式ニュース。2025-12-25に新メジャーバージョン `terraform-provider-sakura`（v3、Terraform Plugin Framework採用）を正式リリース。v2は当面並行提供、v3は正式リリース時点でv2の全リソースを網羅していない
- <https://github.com/sacloud/terraform-provider-sakuracloud> — v2（`sacloud/sakuracloud`）のソースリポジトリ
- <https://docs.usacloud.jp/terraform> — v2の日本語利用ドキュメント。`required_providers` ブロックの書き方、`sakuracloud_server` / `sakuracloud_disk` リソース例
- <https://qiita.com/ksawada1979/items/4ade858bfb3454cdc34c>（2025年11月時点） — v2 provider を使った実践チュートリアル。APIキー発行からserver/disk構築までの具体的なtfコード例。provider version は `2.31.2` が当時最新

## OTel Collector + Loki + Grafana の Docker Compose 構成

- <https://opentelemetry.io/docs/collector/install/docker> — OTel公式。Docker/Docker Compose導入の基本
- <https://grafana.com/docs/loki/latest/send-data/otel/otel-collector-getting-started> — Grafana公式チュートリアル。CollectorからLokiの**ネイティブOTLPエンドポイント**へ直接ログを送る構成（`otlphttp/loki` exporter）
- <https://oneuptime.com/blog/post/2026-02-06-deploy-opentelemetry-collector-docker-compose/view>（2026-02-06） — Collector設定ファイルの実例が詳細。`otlphttp/loki` exporter、`file` exporter（ローテーション付き永続化）、`health_check`/`pprof` extensionの設定例あり
- <https://oneuptime.com/blog/post/2026-02-06-opentelemetry-dev-environment-docker-compose/view>（2026-02-06） — Collector→Loki/Prometheus/Jaeger→Grafana のフルスタックdocker-compose例
- <https://dev.to/tingwei628/how-to-build-a-logging-pipeline-with-opentelemetry-grafana-loki-and-grafana-in-docker-compose-4kk> — MinIO+Postgresまで含むやや重い構成例（個人利用にはオーバースペック気味、必要な部分だけ参照）

## Loki + Grafana のリソース要件（未解決・要検証）

- <https://community.grafana.com/t/hardware-requirements-for-running-grafana-loki/54790> — 公式フォーラム。明確な最小要件の回答はなく「実際に動かして確認を」という趣旨の回答のみ
- <https://community.grafana.com/t/increase-memory-and-prevent-node-crashes-in-grafana-loki-cluster/103833> — 大規模クラスタでのメモリ枯渇事例（本基盤の規模には直接当てはまらないが、Lokiがメモリ逼迫しやすい点の傍証）
- <https://blog.fixermark.com/posts/2025/monitoring-home-network-grafana-loki-prometheus-alloy> — 個人のホームラボ規模でLoki+Prometheus+Grafanaを1ノードに同居させている実例。台数構成の参考になる
- **結論（README.md記載の方針）**: 公式の最小要件が明示されていないため、まず1コア/1GBで構築して実測し、不足すれば1コア/2GBへ増強する段階的検証とする

## Loki 保持・query_range と Azure Blob アーカイブ

- <https://grafana.com/docs/loki/latest/operations/storage/retention/> — Compactor の `retention-enabled` がオフだと取り込んだログは無期限。**保持期間の変更は遡及しない**（有効化前に取り込み済みのチャンクには効かない）。本基盤はアーカイブのバックフィル完了後に `retention_period: 336h`（14日）を有効化済み
- <https://grafana.com/docs/loki/latest/operations/storage/filesystem/> — `object_store: filesystem` で retention を使うときは `compactor.delete_request_store: filesystem` が必須。`shared_store` は 3.5 系の設定に存在しない
- <https://grafana.com/docs/loki/v3.5.x/configure/> — `compactor` / `limits_config` のキーと既定値（`retention_delete_worker_count` 既定 150、`retention_delete_delay` 既定 2h、`max_query_lookback` 既定は無制限）
- <https://learn.microsoft.com/azure/storage/blobs/archive-cost-estimation> — Archive 層は再ハイドレーションに時間がかかり読み取り課金も高い。「必要になったらすぐローカルで見る」用途では Cool を選ぶ根拠
- <https://grafana.com/docs/loki/latest/reference/loki-http-api/> — `query_range` にカーソルは無い。`limit` 既定 100、サーバ天井 `max_entries_limit_per_query` 既定 5000。日次エクスポートは 1h スライスで繰り返す
- <https://learn.microsoft.com/azure/storage/blobs/access-tiers-overview> — Hot / Cool / Archive。すぐローカル確認する用途では Archive の再ハイドレーションは向かない
- <https://learn.microsoft.com/azure/storage/blobs/storage-blob-use-access-tier-python> — `upload_blob(..., standard_blob_tier=StandardBlobTier.COOL)`
- <https://learn.microsoft.com/cli/azure/storage/account#az-storage-account-create> — 既定 SKU は `Standard_RAGRS`。個人利用は `--sku Standard_LRS` を必須にする

## 次の詳細プラン作成時に見るべき順序（提案）

1. Claude Code / Codex CLI の公式OTelドキュメント（本ファイル冒頭2セクション）でクライアント側設定を確定
2. `grafana.com/docs/loki/latest/send-data/otel/otel-collector-getting-started` を土台に `otel-collector-config.yaml` を作成
3. `docs.usacloud.jp/terraform` を土台に Terraform（v2 `sacloud/sakuracloud`）でVM+ディスクを構築
4. 実データを流してから、Loki+Grafanaのリソース要件セクションの検証TODOを消化
