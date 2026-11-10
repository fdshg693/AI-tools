#!/usr/bin/env bash
# Verify Collector -> Loki -> Grafana works at all, independent of any AI CLI client.
#
# Sends one synthetic OTLP log straight to the collector's public endpoint
# (the same auth path a real client uses), then queries Loki via fetch_logs.py
# to confirm it landed. Does NOT prove a real client (claude/codex) sends
# telemetry -- see verify_client.sh for that.
#
# Usage: just verify-pipeline   (reads SERVER_IP / OTLP_AUTH_TOKEN from .env)
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
    echo "error: .env not found (cp .env.example .env, fill SERVER_IP/OTLP_AUTH_TOKEN)" >&2
    exit 1
fi
SERVER_IP=$(grep -m1 '^SERVER_IP=' .env | cut -d= -f2-)
OTLP_AUTH_TOKEN=$(grep -m1 '^OTLP_AUTH_TOKEN=' .env | cut -d= -f2-)
SSH_KEY="${SSH_KEY:-$HOME/.ssh/ai_logs_ed25519}"

MARKER="pipeline-check-$(date +%s)"
NOW_NS=$(( $(date +%s) * 1000000000 ))

echo "[1/2] sending synthetic OTLP log to http://${SERVER_IP}:4318/v1/logs (service_name=${MARKER}) ..."
HTTP_CODE=$(curl -s -o /tmp/verify_pipeline_resp.txt -w "%{http_code}" -X POST "http://${SERVER_IP}:4318/v1/logs" \
    -H 'Content-Type: application/json' \
    -H "Authorization: Bearer ${OTLP_AUTH_TOKEN}" \
    -d "{
      \"resourceLogs\": [{
        \"resource\": {\"attributes\": [{\"key\":\"service.name\",\"value\":{\"stringValue\":\"${MARKER}\"}}]},
        \"scopeLogs\": [{
          \"logRecords\": [{
            \"timeUnixNano\": \"${NOW_NS}\",
            \"severityText\": \"INFO\",
            \"body\": {\"stringValue\": \"pipeline verification log\"}
          }]
        }]
      }]
    }")
echo "  HTTP ${HTTP_CODE}: $(cat /tmp/verify_pipeline_resp.txt)"
if [ "$HTTP_CODE" != "200" ]; then
    echo "FAIL: collector did not accept the log (check OTLP_AUTH_TOKEN / SERVER_IP / firewall)" >&2
    exit 1
fi

echo "[2/2] waiting 5s, then querying Loki for service_name=${MARKER} ..."
sleep 5
python "$(dirname "$0")/fetch_logs.py" --server-ip "$SERVER_IP" --ssh-key "$SSH_KEY" logs --since 5m --service "$MARKER"

echo
echo "If a line above shows '${MARKER}', the Collector -> Loki -> Grafana pipeline is healthy."
echo "This only proves the pipeline works -- it says nothing about whether a real"
echo "claude/codex process is actually sending telemetry. Use verify_client.sh for that."
