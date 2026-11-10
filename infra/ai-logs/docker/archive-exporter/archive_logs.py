#!/usr/bin/env python3
"""Export Loki logs to Azure Blob as daily gzip JSONL, and pull them locally.

Subcommands:
  export    Loki -> gzip JSONL -> Blob for one UTC date
  serve     sleep until 01:15 UTC each day and export yesterday
  backfill  export every UTC day from the oldest log through yesterday
  pull      download one UTC date into temp/
  list      show blob dates vs _status markers

Blob keys are UTC: yyyy/mm/dd.jsonl.gz and _status/yyyy/mm/dd.ok
"""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import io
import json
import os
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

QUERY_LIMIT = 5000
INITIAL_SLICE = dt.timedelta(hours=1)
MIN_SLICE = dt.timedelta(seconds=1)
DEFAULT_QUERY = '{service_name=~".+"}'
DEFAULT_LOKI_URL = "http://loki:3100"
DEFAULT_CONTAINER = "ai-logs"
SERVE_HOUR = 1
SERVE_MINUTE = 15
QUERY_WINDOW = dt.timedelta(days=29)
LOOKBACK_MAX_DAYS = 400


class MissingCreds(Exception):
    pass


class TruncatedSlice(Exception):
    pass


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def parse_date(value: str) -> dt.date:
    text = value.strip().replace("/", "-")
    try:
        return dt.date.fromisoformat(text)
    except ValueError:
        sys.exit(f"error: date must look like YYYY-MM-DD (got {value!r})")


def day_bounds(day: dt.date) -> tuple[dt.datetime, dt.datetime]:
    start = dt.datetime(day.year, day.month, day.day, tzinfo=dt.timezone.utc)
    return start, start + dt.timedelta(days=1)


def to_ns(when: dt.datetime) -> int:
    return int(when.timestamp() * 1_000_000_000)


def blob_key(day: dt.date) -> str:
    return f"{day.year:04d}/{day.month:02d}/{day.day:02d}.jsonl.gz"


def status_key(day: dt.date) -> str:
    return f"_status/{day.year:04d}/{day.month:02d}/{day.day:02d}.ok"


def date_from_blob_key(name: str) -> dt.date | None:
    parts = name.split("/")
    if len(parts) != 3 or not parts[2].endswith(".jsonl.gz"):
        return None
    try:
        return dt.date(int(parts[0]), int(parts[1]), int(parts[2].removesuffix(".jsonl.gz")))
    except ValueError:
        return None


def parse_status_date(name: str) -> dt.date | None:
    # _status/yyyy/mm/dd.ok
    if not name.startswith("_status/") or not name.endswith(".ok"):
        return None
    rest = name[len("_status/") : -len(".ok")]
    parts = rest.split("/")
    if len(parts) != 3:
        return None
    try:
        return dt.date(int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError:
        return None


def load_env_files() -> None:
    """Fill missing os.environ keys from local/VM .env files. Existing env wins."""
    candidates = [
        Path("/opt/ai-logs/.env"),
        Path.cwd() / ".env",
    ]
    try:
        candidates.insert(1, Path(__file__).resolve().parents[2] / ".env")
    except IndexError:
        pass
    seen: set[Path] = set()
    for path in candidates:
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if resolved in seen or not path.is_file():
            continue
        seen.add(resolved)
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            if not key or key in os.environ:
                continue
            os.environ[key] = value.strip().strip("'").strip('"')


def loki_url() -> str:
    return os.environ.get("LOKI_URL", DEFAULT_LOKI_URL).rstrip("/")


def export_query() -> str:
    return os.environ.get("EXPORT_QUERY", DEFAULT_QUERY)


def sleep_seconds() -> float:
    raw = os.environ.get("EXPORT_SLEEP_SECONDS", "0.5")
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 0.5


def require_azure_sdk():
    try:
        from azure.storage.blob import BlobServiceClient, StandardBlobTier
    except ImportError:
        sys.exit(
            "error: azure-storage-blob is not installed. "
            "Install with: pip install -r docker/archive-exporter/requirements.txt"
        )
    return BlobServiceClient, StandardBlobTier


def connection_string() -> str:
    value = os.environ.get("AZURE_STORAGE_CONNECTION_STRING", "").strip()
    if not value:
        raise MissingCreds("AZURE_STORAGE_CONNECTION_STRING is not set")
    return value


def container_name() -> str:
    return os.environ.get("AZURE_STORAGE_CONTAINER", DEFAULT_CONTAINER).strip() or DEFAULT_CONTAINER


def blob_clients():
    BlobServiceClient, StandardBlobTier = require_azure_sdk()
    client = BlobServiceClient.from_connection_string(connection_string())
    container = client.get_container_client(container_name())
    return container, StandardBlobTier


def loki_query_range(
    url_base: str,
    query: str,
    start: dt.datetime,
    end: dt.datetime,
    limit: int,
    direction: str = "forward",
) -> list[tuple[int, dict, str]]:
    params = {
        "query": query,
        "start": str(to_ns(start)),
        "end": str(to_ns(end)),
        "limit": str(limit),
        "direction": direction,
    }
    url = url_base + "/loki/api/v1/query_range?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, method="GET")
    last_err: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            if exc.code >= 500 and attempt < 2:
                last_err = RuntimeError(f"Loki HTTP {exc.code}: {body[:300]}")
                time.sleep(2**attempt)
                continue
            raise RuntimeError(f"Loki HTTP {exc.code}: {body[:500]}") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_err = exc
            if attempt < 2:
                time.sleep(2**attempt)
                continue
            raise RuntimeError(f"Loki request failed: {exc}") from exc
    else:
        raise RuntimeError(f"Loki request failed: {last_err}")

    status = payload.get("status")
    if status not in (None, "success"):
        raise RuntimeError(f"Loki status={status!r}: {payload!r}"[:500])

    entries: list[tuple[int, dict, str]] = []
    for stream in payload.get("data", {}).get("result", []):
        labels = stream.get("stream") or {}
        for ts_ns, line in stream.get("values") or []:
            entries.append((int(ts_ns), labels, line))
    return entries


def collect_window(
    url_base: str,
    query: str,
    start: dt.datetime,
    end: dt.datetime,
) -> list[tuple[int, dict, str]]:
    if end <= start:
        return []
    pause = sleep_seconds()
    entries = loki_query_range(url_base, query, start, end, QUERY_LIMIT, "forward")
    if pause:
        time.sleep(pause)
    if len(entries) < QUERY_LIMIT:
        return entries
    if end - start <= MIN_SLICE:
        raise TruncatedSlice(
            f"slice {start.isoformat()}..{end.isoformat()} returned {len(entries)} "
            f"entries (limit {QUERY_LIMIT}); narrower window is not possible"
        )
    mid = start + (end - start) / 2
    log(f"  slice {start:%H:%M:%S}-{end:%H:%M:%S} hit limit {QUERY_LIMIT}; splitting")
    return collect_window(url_base, query, start, mid) + collect_window(url_base, query, mid, end)


def collect_day(
    url_base: str,
    query: str,
    day: dt.date,
) -> list[tuple[int, dict, str]]:
    start, end = day_bounds(day)
    collected: list[tuple[int, dict, str]] = []
    cursor = start
    while cursor < end:
        slice_end = min(cursor + INITIAL_SLICE, end)
        log(f"  querying {cursor:%Y-%m-%d %H:%M}Z-{slice_end:%H:%M}Z")
        collected.extend(collect_window(url_base, query, cursor, slice_end))
        cursor = slice_end
    collected.sort(key=lambda item: (item[0], item[2]))
    deduped: list[tuple[int, dict, str]] = []
    seen: set[tuple[int, str]] = set()
    for ts_ns, labels, line in collected:
        key = (ts_ns, line)
        if key in seen:
            continue
        seen.add(key)
        deduped.append((ts_ns, labels, line))
    return deduped


def entries_to_gzip(entries: list[tuple[int, dict, str]]) -> bytes:
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as gz:
        for ts_ns, labels, line in entries:
            ts = dt.datetime.fromtimestamp(ts_ns / 1_000_000_000, tz=dt.timezone.utc)
            row = {
                "ts_ns": str(ts_ns),
                "ts": ts.isoformat().replace("+00:00", "Z"),
                "labels": labels,
                "line": line,
            }
            gz.write(
                (json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
            )
    return buf.getvalue()


def blob_exists(container, key: str) -> bool:
    blob = container.get_blob_client(key)
    try:
        blob.get_blob_properties()
        return True
    except Exception as exc:  # ResourceNotFoundError without importing Azure at module load
        if type(exc).__name__ == "ResourceNotFoundError":
            return False
        raise


def upload_bytes(container, key: str, data: bytes, tier) -> None:
    blob = container.get_blob_client(key)
    blob.upload_blob(data, overwrite=True, standard_blob_tier=tier)


def export_day(day: dt.date, *, force: bool) -> int:
    container, StandardBlobTier = blob_clients()
    if not force and blob_exists(container, status_key(day)):
        log(f"skip {day.isoformat()} (status marker already present; pass --force to overwrite)")
        return 0
    url_base = loki_url()
    query = export_query()
    log(f"export {day.isoformat()} UTC  query={query}  loki={url_base}")
    entries = collect_day(url_base, query, day)
    payload = entries_to_gzip(entries)
    upload_bytes(container, blob_key(day), payload, StandardBlobTier.COOL)
    marker = {
        "date": day.isoformat(),
        "entries": len(entries),
        "bytes": len(payload),
        "exported_at": utcnow().isoformat().replace("+00:00", "Z"),
    }
    upload_bytes(
        container,
        status_key(day),
        (json.dumps(marker, separators=(",", ":")) + "\n").encode("utf-8"),
        StandardBlobTier.COOL,
    )
    log(f"uploaded {blob_key(day)} ({len(entries)} entries, {len(payload)} bytes)")
    return len(entries)


def find_oldest_day(url_base: str, query: str) -> dt.date | None:
    end = utcnow()
    horizon = end - dt.timedelta(days=LOOKBACK_MAX_DAYS)
    oldest: dt.date | None = None
    cursor_end = end
    while cursor_end > horizon:
        cursor_start = max(cursor_end - QUERY_WINDOW, horizon)
        log(
            f"looking for oldest log {cursor_start.date().isoformat()} .. {cursor_end.date().isoformat()} UTC"
        )
        entries = loki_query_range(url_base, query, cursor_start, cursor_end, 1, "forward")
        time.sleep(sleep_seconds())
        if entries:
            ts = dt.datetime.fromtimestamp(entries[0][0] / 1_000_000_000, tz=dt.timezone.utc)
            oldest = ts.date()
        cursor_end = cursor_start
    return oldest


def daterange(first: dt.date, last: dt.date):
    day = first
    while day <= last:
        yield day
        day += dt.timedelta(days=1)


def next_serve_at(now: dt.datetime) -> dt.datetime:
    target = now.replace(hour=SERVE_HOUR, minute=SERVE_MINUTE, second=0, microsecond=0)
    if now >= target:
        target += dt.timedelta(days=1)
    return target


def sleep_until(target: dt.datetime) -> None:
    while True:
        remaining = (target - utcnow()).total_seconds()
        if remaining <= 0:
            return
        time.sleep(min(remaining, 60.0))


def cmd_export(args: argparse.Namespace) -> None:
    load_env_files()
    day = parse_date(args.date)
    try:
        export_day(day, force=args.force)
    except MissingCreds as exc:
        sys.exit(f"error: {exc}")


def cmd_backfill(args: argparse.Namespace) -> None:
    load_env_files()
    try:
        connection_string()
    except MissingCreds as exc:
        sys.exit(f"error: {exc}")
    url_base = loki_url()
    query = export_query()
    yesterday = utcnow().date() - dt.timedelta(days=1)
    last = parse_date(args.to) if args.to else yesterday
    if args.from_date:
        first = parse_date(args.from_date)
    else:
        first = find_oldest_day(url_base, query)
        if first is None:
            log("no logs found in Loki; nothing to backfill")
            return
    if last < first:
        sys.exit(f"error: --to {last.isoformat()} is before --from {first.isoformat()}")
    log(f"backfill {first.isoformat()} .. {last.isoformat()} UTC")
    failures: list[str] = []
    for day in daterange(first, last):
        try:
            export_day(day, force=args.force)
        except (MissingCreds, TruncatedSlice, RuntimeError) as exc:
            log(f"error: {day.isoformat()} failed: {exc}")
            failures.append(day.isoformat())
            if isinstance(exc, MissingCreds):
                break
        except Exception as exc:
            log(f"error: {day.isoformat()} failed: {exc}")
            traceback.print_exc()
            failures.append(day.isoformat())
        time.sleep(max(sleep_seconds(), 1.0))
    if failures:
        sys.exit("error: backfill incomplete for " + ", ".join(failures))
    log("backfill complete")


def cmd_serve(_args: argparse.Namespace) -> None:
    load_env_files()
    log(f"archive-exporter serve started; daily run at {SERVE_HOUR:02d}:{SERVE_MINUTE:02d} UTC")
    while True:
        yesterday = utcnow().date() - dt.timedelta(days=1)
        try:
            export_day(yesterday, force=False)
        except MissingCreds as exc:
            log(
                f"error: {exc}; not exiting (would restart-loop). sleeping until next {SERVE_HOUR:02d}:{SERVE_MINUTE:02d} UTC"
            )
        except Exception as exc:
            log(f"error: export {yesterday.isoformat()} failed: {exc}")
            traceback.print_exc()
        target = next_serve_at(utcnow())
        log(f"sleeping until {target.isoformat()}")
        sleep_until(target)


def cmd_list(_args: argparse.Namespace) -> None:
    load_env_files()
    try:
        container, _tier = blob_clients()
    except MissingCreds as exc:
        sys.exit(f"error: {exc}")
    blob_days: set[dt.date] = set()
    ok_days: set[dt.date] = set()
    for blob in container.list_blobs():
        name = blob.name
        day = date_from_blob_key(name)
        if day is not None:
            blob_days.add(day)
            continue
        day = parse_status_date(name)
        if day is not None:
            ok_days.add(day)
    all_days = sorted(blob_days | ok_days)
    if not all_days:
        print("(no archive blobs yet)")
        return
    print(f"{'date':<12} {'jsonl':<6} {'status'}")
    missing = 0
    for day in all_days:
        has_blob = "yes" if day in blob_days else "NO"
        has_ok = "ok" if day in ok_days else "MISSING"
        if has_blob != "yes" or has_ok != "ok":
            missing += 1
        print(f"{day.isoformat():<12} {has_blob:<6} {has_ok}")
    print(f"\n({len(all_days)} dates, {missing} with jsonl/status mismatch)", file=sys.stderr)


def default_pull_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "temp" / "ai-logs-archive"


def cmd_pull(args: argparse.Namespace) -> None:
    load_env_files()
    day = parse_date(args.date)
    try:
        container, _tier = blob_clients()
    except MissingCreds as exc:
        sys.exit(f"error: {exc}")
    dest_dir = Path(args.dest) if args.dest else default_pull_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)
    key = blob_key(day)
    blob = container.get_blob_client(key)
    try:
        data = blob.download_blob().readall()
    except Exception as exc:
        if type(exc).__name__ == "ResourceNotFoundError":
            sys.exit(f"error: blob {key} not found")
        raise
    gz_path = dest_dir / f"{day.isoformat()}.jsonl.gz"
    jsonl_path = dest_dir / f"{day.isoformat()}.jsonl"
    gz_path.write_bytes(data)
    jsonl_path.write_bytes(gzip.decompress(data))
    print(jsonl_path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)

    p_export = sub.add_parser("export", help="export one UTC date from Loki to Blob")
    p_export.add_argument("--date", required=True, help="UTC date YYYY-MM-DD")
    p_export.add_argument(
        "--force", action="store_true", help="overwrite even if status marker exists"
    )
    p_export.set_defaults(func=cmd_export)

    p_serve = sub.add_parser("serve", help="loop: export yesterday after 01:15 UTC")
    p_serve.set_defaults(func=cmd_serve)

    p_backfill = sub.add_parser(
        "backfill", help="export every UTC day from oldest (or --from) through yesterday"
    )
    p_backfill.add_argument(
        "--from", dest="from_date", default="", help="first UTC date YYYY-MM-DD"
    )
    p_backfill.add_argument(
        "--to", dest="to", default="", help="last UTC date YYYY-MM-DD (default: yesterday)"
    )
    p_backfill.add_argument(
        "--force", action="store_true", help="overwrite days that already have a status marker"
    )
    p_backfill.set_defaults(func=cmd_backfill)

    p_list = sub.add_parser("list", help="list Blob dates and status markers")
    p_list.set_defaults(func=cmd_list)

    p_pull = sub.add_parser("pull", help="download one UTC date into temp/")
    p_pull.add_argument("--date", required=True, help="UTC date YYYY-MM-DD")
    p_pull.add_argument(
        "--dest", default="", help="directory (default: tools/infra/ai-logs/temp/ai-logs-archive)"
    )
    p_pull.set_defaults(func=cmd_pull)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
