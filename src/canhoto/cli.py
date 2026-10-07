"""Canhoto CLI adapter — thin argparse layer over ``canhoto.service``.

Console entrypoint ``canhoto``. Examples::

    canhoto init
    canhoto doctor
    canhoto parsers list
    canhoto ingest path/to/statement.txt
    canhoto review --month YYYY-MM --json
    canhoto categorize apply --file patches.json
    canhoto breakdown --month YYYY-MM
    canhoto export pdf YYYY-MM
    canhoto backup --output home.canhoto
    canhoto restore home.canhoto
    canhoto manual add --date YYYY-MM-DD --amount -10.00 --description TEXT
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

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

    _add_config_commands(sub.add_parser("config", help="Get or change currency defaults"))
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
    ingest_p.add_argument(
        "--pdf-password",
        default=None,
        help="Password for encrypted PDFs (or set CANHOTO_PDF_PASSWORD)",
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
    te.add_argument(
        "--pdf-password",
        default=None,
        help="Password for encrypted PDFs (or set CANHOTO_PDF_PASSWORD)",
    )

    en = parsers_sub.add_parser(
        "enable",
        help="Enable parser only if last parser_test stamped OK",
    )
    en.add_argument("--id", required=True, dest="parser_id", help="Registered parser id")

    parsers_sub.add_parser("list", help="List registered parsers and test/enable status")

    pv = parsers_sub.add_parser(
        "preview",
        help="Print the text a parser receives for a statement file",
    )
    pv.add_argument(
        "--file",
        required=True,
        dest="sample_file",
        help="Path to a statement (.txt or .pdf)",
    )
    pv.add_argument(
        "--pdf-password",
        default=None,
        help="Password for encrypted PDFs (or set CANHOTO_PDF_PASSWORD)",
    )

    review_p = sub.add_parser(
        "review",
        help="Fetch a redacted pending-review batch for a month (YYYY-MM)",
    )
    review_p.add_argument(
        "--month",
        required=True,
        help="Target month as YYYY-MM",
    )
    review_p.add_argument(
        "--cursor",
        default=None,
        help="Pagination cursor (last item id from previous page)",
    )
    review_p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max items (clamped by agent-view batch caps)",
    )
    review_p.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON (default and currently only output mode)",
    )

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
    apply_p = cat_sub.add_parser(
        "apply",
        help="Apply classification patches from a JSON file",
    )
    apply_p.add_argument(
        "--file",
        required=True,
        dest="patches_file",
        help="Path to JSON list of classification patches",
    )
    mem_p = cat_sub.add_parser(
        "merchant",
        help="Remember merchant_key → category for later rule runs",
    )
    mem_p.add_argument(
        "--key",
        required=True,
        dest="merchant_key",
        help="Normalized merchant key to remember",
    )
    mem_p.add_argument(
        "--category",
        required=True,
        help="Category to apply on future matching rows",
    )

    rule_p = sub.add_parser("rules", help="Manage user classification rules")
    rule_sub = rule_p.add_subparsers(dest="rules_cmd", required=True)
    add_p = rule_sub.add_parser("add", help="Store a rule that run_rules applies")
    add_p.add_argument("--pattern", required=True, help="Case-insensitive regex on the description")
    add_p.add_argument("--category", required=True)
    add_p.add_argument("--kind", required=True, help="expense, income, transfer, ...")
    add_p.add_argument("--direction", choices=("in", "out", "any"), default="any")
    add_p.add_argument("--min", dest="min_amount", help="Minimum absolute amount, inclusive")
    add_p.add_argument("--max", dest="max_amount", help="Maximum absolute amount, inclusive")
    add_p.add_argument("--source-kind", help="Only rows from this source (account, card)")
    add_p.add_argument("--review", action="store_true", help="Classify, but keep for review")
    add_p.add_argument("--note", default="", help="Why this rule exists")
    add_p.add_argument("--priority", type=int, default=100, help="Lower runs first")
    rule_sub.add_parser("list", help="List rules in evaluation order")
    rm_p = rule_sub.add_parser("remove", help="Delete a rule")
    rm_p.add_argument("--id", dest="rule_id", type=int, required=True)

    breakdown_p = sub.add_parser(
        "breakdown",
        help="Aggregate month report (income/expenses/net/by_category; no tx list)",
    )
    breakdown_p.add_argument(
        "--month",
        required=True,
        help="Target month as YYYY-MM",
    )

    export_p = sub.add_parser("export", help="Export projections (summary PDF v1)")
    export_sub = export_p.add_subparsers(dest="export_cmd", required=True)
    export_pdf_p = export_sub.add_parser(
        "pdf",
        help="Write month summary PDF to data-dir/exports/YYYY-MM-summary.pdf",
    )
    export_pdf_p.add_argument(
        "month",
        help="Target month as YYYY-MM",
    )
    export_pdf_p.add_argument(
        "--output",
        "-o",
        default=None,
        help="Write PDF to this path (default: data-dir/exports/YYYY-MM-summary.pdf)",
    )
    export_pdf_p.add_argument(
        "--profile",
        choices=("canhoto", "modern", "minimal"),
        default="canhoto",
        help="Built-in visual profile (default: canhoto)",
    )

    backup_p = sub.add_parser(
        "backup",
        help="Write ledger, rules, config, and parsers to one .canhoto file (no statements)",
    )
    backup_p.add_argument(
        "--output",
        "-o",
        default=None,
        help="Backup file path (default: ./canhoto-YYYY-MM-DD.canhoto); never overwritten",
    )
    restore_p = sub.add_parser(
        "restore",
        help="Restore a trusted .canhoto file into a new or empty data dir",
    )
    restore_p.add_argument("path", help="Path to a .canhoto backup file")

    manual_p = sub.add_parser(
        "manual",
        help="Keep transactions no statement shows (e.g. a Pix sent from a reserve)",
    )
    manual_sub = manual_p.add_subparsers(dest="manual_cmd", required=True)
    madd_p = manual_sub.add_parser("add", help="Add a manual transaction")
    _add_manual_fields(madd_p, creating=True)
    madd_p.add_argument("--institution", default=None)
    mlist_p = manual_sub.add_parser("list", help="List manual transactions")
    mlist_p.add_argument("--month", default=None, help="Only this month (YYYY-MM)")
    medit_p = manual_sub.add_parser("edit", help="Change a manual transaction")
    medit_p.add_argument("--id", dest="tx_id", required=True)
    _add_manual_fields(medit_p, creating=False)
    mrm_p = manual_sub.add_parser("remove", help="Delete a manual transaction")
    mrm_p.add_argument("--id", dest="tx_id", required=True)

    return parser


def _add_config_commands(config: argparse.ArgumentParser) -> None:
    commands = config.add_subparsers(dest="config_cmd", required=True)
    for action in ("get", "set", "unset"):
        command = commands.add_parser(action, help=f"{action.capitalize()} a currency setting")
        command.add_argument("key", help="Supported key: currency")
        command.add_argument("--global", dest="global_scope", action="store_true",
                             help="Use user-wide settings instead of the active ledger")
        if action == "set":
            command.add_argument("value", help="Three-letter currency code, such as EUR")


def _add_manual_fields(p: argparse.ArgumentParser, *, creating: bool) -> None:
    p.add_argument("--date", required=creating, help="YYYY-MM-DD")
    p.add_argument("--amount", required=creating, help='Signed amount: "-3080.00" is money out')
    p.add_argument("--description", required=creating)
    p.add_argument(
        "--currency", default=None,
        help="Currency code; defaults from config on add, keeps the stored code on edit",
    )
    p.add_argument("--category", help="Set by hand; omit to let rules classify")
    p.add_argument("--kind", help="Default on add: expense for money out, income for money in")
    p.add_argument("--merchant", help="Merchant name for reports")
    p.add_argument("--account", help='Source account, e.g. "cofrinho"')
    p.add_argument(
        "--note", default="" if creating else None, help="Why this row is kept by hand"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.cmd == "config":
        return _run_service_cmd(lambda: _call_config(args))
    if args.cmd == "init":
        _print_json(service.init())
        return 0
    if args.cmd == "doctor":
        report = service.doctor()
        _print_json(report)
        return 0 if report.get("ok", False) else 1
    if args.cmd == "ingest":
        return _run_service_cmd(
            lambda: service.ingest(args.paths, pdf_password=args.pdf_password)
        )
    if args.cmd == "parsers":
        return _run_parsers(args)
    if args.cmd == "review":
        return _run_service_cmd(
            lambda: service.review_batch(
                args.month,
                cursor=args.cursor,
                limit=args.limit,
            )
        )
    if args.cmd == "categorize":
        return _run_categorize(args)
    if args.cmd == "rules":
        return _run_rules(args)
    if args.cmd == "breakdown":
        return _run_service_cmd(lambda: service.month_breakdown(args.month))
    if args.cmd == "export":
        if args.export_cmd == "pdf":
            return _run_service_cmd(
                lambda: service.export_pdf(
                    args.month, output=args.output, profile=args.profile
                )
            )
        _print_json({"ok": False, "error": f"unknown export command: {args.export_cmd}"})
        return 2
    if args.cmd == "backup":
        return _run_service_cmd(lambda: service.backup(output=args.output))
    if args.cmd == "restore":
        return _run_service_cmd(lambda: service.restore(args.path))
    if args.cmd == "manual":
        return _run_service_cmd(lambda: _call_manual(args))

    parser.error(f"unknown command: {args.cmd}")
    return 2


def _call_config(args: argparse.Namespace) -> dict[str, Any]:
    if args.config_cmd == "get":
        return service.config_get(args.key, global_scope=args.global_scope)
    if args.config_cmd == "unset":
        return service.config_unset(args.key, global_scope=args.global_scope)
    return service.config_set(args.key, args.value, global_scope=args.global_scope)


def _call_manual(args: argparse.Namespace) -> dict[str, Any]:
    if args.manual_cmd == "list":
        return service.manual_list(month=args.month)
    if args.manual_cmd == "remove":
        return service.manual_remove(args.tx_id)
    fields = {
        "date": args.date,
        "amount": args.amount,
        "currency": args.currency,
        "description": args.description,
        "category": args.category,
        "kind": args.kind,
        "merchant": args.merchant,
        "account": args.account,
        "note": args.note,
    }
    if args.manual_cmd == "add":
        return service.manual_add(institution=args.institution, **fields)
    return service.manual_edit(args.tx_id, **fields)


def _run_service_cmd(fn: Callable[[], dict[str, Any]]) -> int:
    """Run a service call and print JSON; map domain errors to exit 1."""
    try:
        result = fn()
        _print_json(result)
        return 0 if result.get("ok", True) else 1
    except (
        ValueError,
        FileNotFoundError,
        FileExistsError,
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
            result = service.parser_test(
                args.parser_id,
                args.sample_file,
                pdf_password=args.pdf_password,
            )
            _print_json(result)
            return 0 if result.get("ok") else 1
        if args.parsers_cmd == "enable":
            _print_json(service.parser_enable(args.parser_id))
            return 0
        if args.parsers_cmd == "list":
            _print_json(service.parser_list())
            return 0
        if args.parsers_cmd == "preview":
            _print_preview(
                service.statement_preview(args.sample_file, pdf_password=args.pdf_password)
            )
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


def _run_rules(args: argparse.Namespace) -> int:
    if args.rules_cmd == "add":
        return _run_service_cmd(
            lambda: service.rule_add(
                args.pattern,
                args.category,
                args.kind,
                direction=args.direction,
                min_amount=args.min_amount,
                max_amount=args.max_amount,
                source_kind=args.source_kind,
                needs_review=args.review,
                note=args.note,
                priority=args.priority,
            )
        )
    if args.rules_cmd == "list":
        return _run_service_cmd(service.rule_list)
    if args.rules_cmd == "remove":
        return _run_service_cmd(lambda: service.rule_remove(args.rule_id))
    _print_json({"ok": False, "error": f"unknown rules command: {args.rules_cmd}"})
    return 2


def _print_preview(preview: dict[str, Any]) -> None:
    """Print raw statement text; a truncation note goes to stderr."""
    text = str(preview["text"])
    print(text, end="" if text.endswith("\n") else "\n")
    if preview["truncated"]:
        print(
            f"[canhoto] preview truncated: {len(text)} of {preview['char_count']} characters."
            " Raise agent_view.preview_max_chars in config.json to see more.",
            file=sys.stderr,
        )


def _run_categorize(args: argparse.Namespace) -> int:
    if args.categorize_cmd == "rules":
        return _run_service_cmd(lambda: service.run_rules(args.month))
    if args.categorize_cmd == "apply":
        return _run_service_cmd(lambda: _load_and_set_categories(args.patches_file))
    if args.categorize_cmd == "merchant":
        return _run_service_cmd(
            lambda: service.set_merchant_category(
                args.merchant_key,
                args.category,
            )
        )
    _print_json(
        {"ok": False, "error": f"unknown categorize command: {args.categorize_cmd}"}
    )
    return 2


def _load_and_set_categories(patches_file: str) -> dict[str, Any]:
    path = Path(patches_file).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"patches file not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid patches JSON: {exc}") from exc
    if not isinstance(payload, list):
        raise ValueError("patches file must contain a JSON list")
    return service.set_categories(payload)


if __name__ == "__main__":
    sys.exit(main())
