"""CLI: ``python -m links sync|check|clean|post-checkout [--root DIR] [--dry-run]``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from links.core import LinksError, check, clean, find_umbrella_root, post_checkout, sync


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="links", description=__doc__)
    parser.add_argument("command", choices=["sync", "check", "clean", "post-checkout"])
    parser.add_argument("--root", type=Path, help="umbrella root (default: nearest .umbrella-root)")
    parser.add_argument("--dry-run", action="store_true", help="sync/clean: only print")
    parser.add_argument("--quiet", action="store_true", help="print only warnings and errors")
    args = parser.parse_args(argv)
    try:
        umbrella = (args.root or find_umbrella_root(Path.cwd())).resolve()
        if args.command == "sync":
            report = sync(umbrella, dry_run=args.dry_run)
        elif args.command == "clean":
            report = clean(umbrella, dry_run=args.dry_run)
        elif args.command == "post-checkout":
            report = post_checkout(umbrella)
            report.print(quiet=True)
            return 0  # advisory only: the checkout already happened
        else:
            report = check(umbrella)
    except LinksError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    report.print(quiet=args.quiet)
    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main())
