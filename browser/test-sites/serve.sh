#!/usr/bin/env bash
# tools/browser/test-sites/ 配下のテストサイトを system nginx でまとめてローカル配信する（ポート8080固定）。
# フォアグラウンド起動のみ（daemon off; は nginx.conf 側で指定済み）。停止は Ctrl+C。
# nginx が無い環境（Windows など）では `just test-sites`（serve.py。同じ URL 構成）を使う。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NGINX_DIR="$SCRIPT_DIR/nginx"
NGINX_BIN="${NGINX_BIN:-/usr/sbin/nginx}"

mkdir -p "$NGINX_DIR/run"

exec "$NGINX_BIN" -p "$NGINX_DIR" -c nginx.conf
