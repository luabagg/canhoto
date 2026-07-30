"""Canhoto CLI adapter — thin argparse layer over ``canhoto.service``.

Package console scripts land in Phase 7. Until then, invoke via::

    python -m canhoto.cli init
    python -m canhoto.cli doctor
    python -m canhoto.cli parsers list
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Sequence

from canhoto import service
from canhoto.parsers.loader import ParserNotFoundError


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

    parsers_p = sub.add_parser("parsers", help="Manage user/plugin statement parsers")
    parsers_sub = parsers_p.add_subparsers(dest="parsers_cmd", required=True)

    sc = parsers_sub.add_parser(
        "scaffold",
        help="Write a stub parser module under data-dir/parsers and register it disabled",
    )
    sc.add_argument("--id", required=True, dest="parser_id", help="Parser id (module stem)")
    sc.add_argument(
        "--type",
        required=True,
        dest="statement_type",
        choices=("account", "card"),
        help="Statement type",
    )
    sc.add_argument(
        "--institution",
        required=True,
        help="Free-form institution label stored on the stub",
    )

    te = parsers_sub.add_parser(
        "test",
        help="Run parser against a sample file and stamp last_test_* on config",
    )
    te.add_argument("--id", required=True, dest="parser_id", help="Registered parser id")
    te.add_argument(
        "--file",
        required=True,
        dest="sample_file",
        help="Path to sample statement (.txt or .pdf)",
    )

    en = parsers_sub.add_parser(
        "enable",
        help="Enable parser only if last parser_test stamped OK",
    )
    en.add_argument("--id", required=True, dest="parser_id", help="Registered parser id")

    parsers_sub.add_parser("list", help="List registered parsers and test/enable status")

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
    if args.cmd == "parsers":
        return _run_parsers(args)

    parser.error(f"unknown command: {args.cmd}")
    return 2


def _run_parsers(args: argparse.Namespace) -> int:
    try:
        if args.parsers_cmd == "scaffold":
            _print_json(
                service.parser_scaffold(
                    args.parser_id,
                    args.statement_type,
                    args.institution,
                )
            )
            return 0
        if args.parsers_cmd == "test":
            result = service.parser_test(args.parser_id, args.sample_file)
            _print_json(result)
            return 0 if result.get("ok") else 1
        if args.parsers_cmd == "enable":
            _print_json(service.parser_enable(args.parser_id))
            return 0
        if args.parsers_cmd == "list":
            _print_json(service.parser_list())
            return 0
    except (ValueError, FileNotFoundError, PermissionError, ParserNotFoundError) as exc:
        _print_json({"ok": False, "error": str(exc)})
        return 1
    except Exception as exc:  # noqa: BLE001 — keep CLI JSON-friendly
        _print_json({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
        return 1

    _print_json({"ok": False, "error": f"unknown parsers command: {args.parsers_cmd}"})
    return 2


if __name__ == "__main__":
    sys.exit(main())
