from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from finance_ingest import service


def _print(obj) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False, default=str))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="finance", description="Personal finance ingest CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_cfg = sub.add_parser("configure", help="Set spreadsheet id / Google token paths")
    p_cfg.add_argument("--spreadsheet-id")
    p_cfg.add_argument("--google-token")
    p_cfg.add_argument("--google-client-secret")

    sub.add_parser("config", help="Show config")

    p_parse = sub.add_parser("parse", help="Parse a statement without storing")
    p_parse.add_argument("path")

    p_ingest = sub.add_parser("ingest", help="Ingest statement file(s)")
    p_ingest.add_argument("paths", nargs="+")
    p_ingest.add_argument("--no-categorize", action="store_true")

    p_list = sub.add_parser("list", help="List transactions")
    p_list.add_argument("--month")
    p_list.add_argument("--needs-review", action="store_true")
    p_list.add_argument("--source-kind", choices=["account", "card"])
    p_list.add_argument("--limit", type=int, default=200)

    p_cat = sub.add_parser("categorize", help="Re-run rule categorization")
    p_cat.add_argument("--month")

    p_sum = sub.add_parser("summary", help="Monthly summary")
    p_sum.add_argument("month")

    p_rec = sub.add_parser("reconcile", help="Reconcile month")
    p_rec.add_argument("month")

    p_setup = sub.add_parser("sheets-setup", help="Create sheet tabs/headers")
    p_setup.add_argument("--spreadsheet-id")

    p_push = sub.add_parser("sheets-push", help="Push month to Google Sheets")
    p_push.add_argument("month")

    p_exp = sub.add_parser("export", help="Export month JSON")
    p_exp.add_argument("month")

    sub.add_parser("mcp", help="Run MCP server (stdio)")

    args = parser.parse_args(argv)

    if args.cmd == "configure":
        _print(
            service.configure(
                spreadsheet_id=args.spreadsheet_id,
                google_token_path=args.google_token,
                google_client_secret_path=args.google_client_secret,
            )
        )
    elif args.cmd == "config":
        _print(service.get_config())
    elif args.cmd == "parse":
        _print(service.parse_statement(args.path))
    elif args.cmd == "ingest":
        _print(service.ingest_paths(args.paths, auto_categorize=not args.no_categorize))
    elif args.cmd == "list":
        _print(
            service.list_transactions(
                month=args.month,
                needs_review=True if args.needs_review else None,
                source_kind=args.source_kind,
                limit=args.limit,
            )
        )
    elif args.cmd == "categorize":
        _print(service.auto_categorize(month=args.month))
    elif args.cmd == "summary":
        _print(service.get_monthly_summary(args.month))
    elif args.cmd == "reconcile":
        _print(service.reconcile(args.month))
    elif args.cmd == "sheets-setup":
        _print(service.sheets_setup(spreadsheet_id=args.spreadsheet_id))
    elif args.cmd == "sheets-push":
        _print(service.sheets_push(args.month))
    elif args.cmd == "export":
        _print(service.export_json(args.month))
    elif args.cmd == "mcp":
        from finance_ingest.mcp_server import main as mcp_main

        mcp_main()
    else:
        parser.error(f"unknown command {args.cmd}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
