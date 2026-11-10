#!/usr/bin/env bash
# Verify that the REAL `claude` CLI actually emits OTLP telemetry that reaches Loki.
#
# Unlike verify_pipeline.sh (which fakes a log via curl), this runs a real
# one-shot `claude -p` invocation with the OTEL_* env vars passed explicitly
# on the command line -- so the result doesn't depend on whether the calling
# shell/terminal/VSCode window happens to have picked up the Windows User env
# vars set by `just env-install` (a separate, easy-to-get-wrong concern).
#
# Uses `claude --debug-file` to capture Claude Code's OWN internal telemetry
# log (the "[3P telemetry]" lines), because Loki showing zero data is
# ambiguous by itself -- it doesn't tell you whether the client never tried,
# tried and got rejected (auth), or crashed during init (e.g. a malformed
# OTEL_EXPORTER_OTLP_HEADERS token breaks URI parsing before any network call
# happens at all -- this bit us once: an OTLP_AUTH_TOKEN containing `%` caused
# "Telemetry init failed: URI error" and silently no-op'd the whole logger).
#
# Usage: just verify-client   (reads SERVER_IP / OTLP_AUTH_TOKEN from .env)
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
    echo "error: .env not found (cp .env.example .env, fill SERVER_IP/OTLP_AUTH_TOKEN)" >&2
    exit 1
fi
SERVER_IP=$(grep -m1 '^SERVER_IP=' .env | cut -d= -f2-)
OTLP_AUTH_TOKEN=$(grep -m1 '^OTLP_AUTH_TOKEN=' .env | cut -d= -f2-)
SSH_KEY="${SSH_KEY:-$HOME/.ssh/ai_logs_ed25519}"
DEBUG_LOG=$(mktemp)
trap 'rm -f "$DEBUG_LOG"' EXIT

if ! command -v claude >/dev/null 2>&1; then
    echo "error: 'claude' CLI not found on PATH" >&2
    exit 1
fi

echo "[1/4] snapshotting known service_name values in Loki (before) ..."
BEFORE=$(python "$(dirname "$0")/fetch_logs.py" --server-ip "$SERVER_IP" --ssh-key "$SSH_KEY" list-services)
echo "$BEFORE"

echo
echo "[2/4] running a real 'claude -p' with OTEL_* passed explicitly (not relying on ambient shell env) ..."
echo "      (CLAUDE_CODE_CHILD_SESSION is unset so this looks like a top-level invocation even if"
echo "       you're running this from inside another Claude Code session)"
env -u CLAUDE_CODE_CHILD_SESSION \
  CLAUDE_CODE_ENABLE_TELEMETRY=1 \
  OTEL_LOGS_EXPORTER=otlp \
  OTEL_EXPORTER_OTLP_PROTOCOL=grpc \
  OTEL_EXPORTER_OTLP_ENDPOINT="http://${SERVER_IP}:4317" \
  OTEL_EXPORTER_OTLP_HEADERS="Authorization=Bearer ${OTLP_AUTH_TOKEN}" \
  OTEL_LOGS_EXPORT_INTERVAL=1000 \
  claude --debug-file "$DEBUG_LOG" -p --model haiku "reply with exactly the word: pong"

echo
echo "[3/4] Claude Code's own internal telemetry log ([3P telemetry] lines from --debug-file):"
grep -i "3P telemetry\|OTEL diag" "$DEBUG_LOG" | sed 's/^/  /' || echo "  (no [3P telemetry] lines found at all -- telemetry code path may not have run)"

echo
echo "[4/4] waiting 15s for the batch exporter to flush, then diffing service_name values (after) ..."
sleep 15
AFTER=$(python "$(dirname "$0")/fetch_logs.py" --server-ip "$SERVER_IP" --ssh-key "$SSH_KEY" list-services)
echo "$AFTER"

NEW=$(comm -13 <(echo "$BEFORE" | sort) <(echo "$AFTER" | sort) || true)
echo
if [ -n "$NEW" ]; then
    echo "SUCCESS: NEW service_name(s) seen after this run: $NEW"
    echo "--- recent entries ---"
    for svc in $NEW; do
        python "$(dirname "$0")/fetch_logs.py" --server-ip "$SERVER_IP" --ssh-key "$SSH_KEY" logs --since 5m --service "$svc"
    done
elif grep -qi "URI error\|Telemetry init failed" "$DEBUG_LOG"; then
    echo "FAIL: telemetry init crashed before any network call was made -- see [3P telemetry] lines above."
    echo "Likely cause: OTEL_EXPORTER_OTLP_HEADERS contains a character (e.g. a literal '%') that breaks"
    echo "the SDK's header/URI parsing. Regenerate OTLP_AUTH_TOKEN as pure alphanumeric/hex"
    echo "(e.g. \`openssl rand -hex 32\`, which is what \`just vm-env\` generates by default) and redeploy."
elif grep -qi "UNAUTHENTICATED\|401" "$DEBUG_LOG"; then
    echo "FAIL: telemetry initialized and tried to send, but the collector rejected the token (auth mismatch)."
    echo "Check that .env's OTLP_AUTH_TOKEN here matches /opt/ai-logs/.env on the VM (\`just show-secrets\`)."
else
    echo "FAIL: no new service_name appeared and no obvious error in the debug log -- inspect it directly:"
    echo "  $DEBUG_LOG (deleted on exit; rerun without 'set -e' cleanup / trap to keep it, or add '2>&1 | tee')"
fi
