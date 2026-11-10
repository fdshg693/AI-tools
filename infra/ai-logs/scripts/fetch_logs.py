#!/usr/bin/env python3
"""Fetch recent logs directly from Loki on the ai-logs VM, without Grafana/SSH tunnel.

Loki itself isn't exposed on the VM's host network (only reachable from other
containers on the compose network), so this SSHes in and queries it via
`docker exec ai-logs-loki wget ...` against Loki's own HTTP API, then renders
the result locally.

Invoked via `just logs` / `just log-services` (see justfile). Requires the
`ssh` client on PATH and the ai-logs VM's SSH key.
"""

import argparse
import datetime
import json
import re
import subprocess
import sys
import urllib.parse

DURATION_RE = re.compile(r"^(\d+)([smhd])$")
UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def parse_duration(value):
    m = DURATION_RE.match(value.strip())
    if not m:
        sys.exit(f"error: --since must look like '30s', '15m', '2h', '1d' (got {value!r})")
    amount, unit = m.groups()
    return int(amount) * UNIT_SECONDS[unit]


def run_on_vm(server_ip, ssh_key, url):
    cmd = [
        "ssh",
        "-i",
        ssh_key,
        f"root@{server_ip}",
        f"docker exec ai-logs-loki wget -qO- '{url}'",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(f"error: ssh/wget failed (exit {result.returncode}): {result.stderr.strip()}")
    if not result.stdout.strip():
        sys.exit("error: empty response from Loki (is the stack up? try `just stats`)")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        sys.exit(f"error: non-JSON response from Loki: {result.stdout[:300]}")


def cmd_list_services(args):
    url = "http://localhost:3100/loki/api/v1/label/service_name/values"
    data = run_on_vm(args.server_ip, args.ssh_key, url)
    values = data.get("data", [])
    if not values:
        print("(no service_name values in Loki yet -- no logs have ever been ingested)")
        return
    for v in values:
        print(v)


def cmd_logs(args):
    since_s = parse_duration(args.since)
    end_ns = int(datetime.datetime.now().timestamp() * 1_000_000_000)
    start_ns = end_ns - since_s * 1_000_000_000

    query = f'{{service_name="{args.service}"}}' if args.service else '{service_name=~".+"}'
    params = {
        "query": query,
        "start": str(start_ns),
        "end": str(end_ns),
        "limit": str(args.limit),
        "direction": "backward",
    }
    url = "http://localhost:3100/loki/api/v1/query_range?" + urllib.parse.urlencode(params)

    data = run_on_vm(args.server_ip, args.ssh_key, url)
    streams = data.get("data", {}).get("result", [])
    if not streams:
        print(
            f"(no log entries in the last {args.since}"
            + (f" for service_name={args.service!r}" if args.service else "")
            + ")"
        )
        return

    entries = []
    for stream in streams:
        labels = stream.get("stream", {})
        for ts_ns, line in stream.get("values", []):
            entries.append((int(ts_ns), labels, line))
    entries.sort(key=lambda e: e[0])

    for ts_ns, labels, line in entries:
        ts = datetime.datetime.fromtimestamp(ts_ns / 1_000_000_000)
        svc = labels.get("service_name", "?")
        level = labels.get("detected_level") or labels.get("severity_text") or "-"
        print(f"{ts:%Y-%m-%d %H:%M:%S} [{svc}] [{level}] {line}")

    print(f"\n({len(entries)} entries, last {args.since})", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server-ip", required=True)
    parser.add_argument("--ssh-key", required=True)
    sub = parser.add_subparsers(dest="action", required=True)

    p_logs = sub.add_parser("logs")
    p_logs.add_argument("--since", default="1h")
    p_logs.add_argument("--limit", type=int, default=200)
    p_logs.add_argument("--service", default="")
    p_logs.set_defaults(func=cmd_logs)

    p_services = sub.add_parser("list-services")
    p_services.set_defaults(func=cmd_list_services)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
