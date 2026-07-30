"""Canhoto CLI adapter — thin argparse layer over ``canhoto.service``.

Package console scripts land in Phase 7. Until then, invoke via::

    python -m canhoto.cli init
    python -m canhoto.cli doctor
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Sequence

from canhoto import service


def _print_json(obj: Any) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False, default=str))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="canhoto",
        description="Canhoto — local personal finance engine",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="Create data-dir layout and default config.json")
    sub.add_parser(
        "doctor",
        help="Report data-dir health as JSON (writable, config, parsers, db, pending)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.cmd == "init":
        _print_json(service.init())
        return 0
    if args.cmd == "doctor":
        report = service.doctor()
        _print_json(report)
        return 0 if report.get("ok", False) else 1

    parser.error(f"unknown command: {args.cmd}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
