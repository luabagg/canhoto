"""Canhoto CLI adapter — thin argparse layer over ``canhoto.service``.

Package console scripts land in Phase 7. Until then, invoke via::

    python -m canhoto.cli init
    python -m canhoto.cli doctor
    python -m canhoto.cli parsers list
    python -m canhoto.cli ingest path/to/statement.txt
    python -m canhoto.cli parse path/to/statement.txt
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from typing import Any, Sequence

from canhoto import service
from canhoto.parsers.loader import ParserLoadError, ParserNotFoundError


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

    ingest_p = sub.add_parser(
        "ingest",
        help="Archive, parse, and upsert one or more statement files",
    )
    ingest_p.add_argument(
        "paths",
        nargs="+",
        help="Statement file paths (.txt or .pdf)",
    )

    parse_p = sub.add_parser(
        "parse",
        help="Dry-run extract+parse; capped JSON summary, no DB write",
    )
    parse_p.add_argument("file", help="Statement file path (.txt or .pdf)")
    parse_p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max preview rows (clamped by agent-view batch caps)",
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

    cat_p = sub.add_parser("categorize", help="Classify ledger rows")
    cat_sub = cat_p.add_subparsers(dest="categorize_cmd", required=True)
    rules_p = cat_sub.add_parser(
        "rules",
        help="Run deterministic rules for a month (YYYY-MM)",
    )
    rules_p.add_argument(
        "--month",
        required=True,
        help="Target month as YYYY-MM",
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
    if args.cmd == "ingest":
        return _run_service_cmd(lambda: service.ingest(args.paths))
    if args.cmd == "parse":
        return _run_service_cmd(
            lambda: service.parse(args.file, limit=args.limit)
        )
    if args.cmd == "parsers":
        return _run_parsers(args)
    if args.cmd == "categorize":
        return _run_categorize(args)

    parser.error(f"unknown command: {args.cmd}")
    return 2


def _run_service_cmd(fn: Callable[[], dict[str, Any]]) -> int:
    """Run a service call and print JSON; map domain errors to exit 1."""
    try:
        result = fn()
        _print_json(result)
        return 0 if result.get("ok", True) else 1
    except (
        ValueError,
        FileNotFoundError,
        PermissionError,
        ParserNotFoundError,
        ParserLoadError,
    ) as exc:
        _print_json({"ok": False, "error": str(exc)})
        return 1
    except Exception as exc:  # noqa: BLE001 — keep CLI JSON-friendly
        _print_json({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
        return 1


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
    except (
        ValueError,
        FileNotFoundError,
        PermissionError,
        ParserNotFoundError,
        ParserLoadError,
    ) as exc:
        _print_json({"ok": False, "error": str(exc)})
        return 1
    except Exception as exc:  # noqa: BLE001 — keep CLI JSON-friendly
        _print_json({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
        return 1

    _print_json({"ok": False, "error": f"unknown parsers command: {args.parsers_cmd}"})
    return 2


def _run_categorize(args: argparse.Namespace) -> int:
    if args.categorize_cmd == "rules":
        return _run_service_cmd(lambda: service.run_rules(args.month))
    _print_json(
        {"ok": False, "error": f"unknown categorize command: {args.categorize_cmd}"}
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
