#!/usr/bin/env python3
"""tools/browser/test-sites/ 配下のテストサイトを標準ライブラリだけで配信する（nginx が無い環境向けの代替）。

URL 構成は nginx/nginx.conf と同じ:
  /            -> custom_pages/pages/
  /<site>/     -> <site>/        (catalog, dynamic, frames, ...)

使い方:
    just test-sites                                          # アンブレラのルートで。http://localhost:8080
    uv run --no-project tools/browser/test-sites/serve.py --port 9000
停止は Ctrl+C。
"""

from __future__ import annotations

import argparse
import functools
import http.server
import pathlib
import socketserver

ROOT = pathlib.Path(__file__).resolve().parent
DEFAULT_SITE = ROOT / "custom_pages" / "pages"
# ディレクトリ名 = URL プレフィックス。nginx.conf の location 群と揃えること。
SITES = [
    "catalog",
    "dynamic",
    "frames",
    "tables",
    "network",
    "auth",
    "inputs",
    "visual",
    "a11y",
    "slow",
]


class Handler(http.server.SimpleHTTPRequestHandler):
    def translate_path(self, path: str) -> str:
        clean = path.split("?", 1)[0].split("#", 1)[0]
        parts = [p for p in clean.split("/") if p not in ("", ".", "..")]
        if parts and parts[0] in SITES:
            base, rest = ROOT / parts[0], parts[1:]
        else:
            base, rest = DEFAULT_SITE, parts
        target = base.joinpath(*rest)
        if target.is_dir():
            target = target / "index.html"
        return str(target)

    def end_headers(self) -> None:
        # 実験の再現性のためキャッシュを無効化する
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer((args.host, args.port), Handler) as httpd:
        print(f"test-sites を http://{args.host}:{args.port} で配信中（Ctrl+C で停止）")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("停止しました")


if __name__ == "__main__":
    main()
