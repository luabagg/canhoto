"""Smoke test for a built Canhoto distribution.

Run against an installed wheel or sdist, outside the project:

    uv run --isolated --no-project --with dist/*.whl scripts/smoke_test.py

Checks that the package imports, that the migration scripts ship with it,
and that the CLI can create and migrate a fresh data directory.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
from pathlib import Path


def _run_cli(*args: str) -> dict[str, object]:
    from canhoto.cli import main

    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = main(list(args))
    assert code == 0, f"canhoto {' '.join(args)} exited {code}: {out.getvalue()}"
    return json.loads(out.getvalue())


def main() -> None:
    import canhoto.mcp.server as mcp_server
    from canhoto.core import migrate

    assert callable(mcp_server.main)
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        os.environ["CANHOTO_DATA_DIR"] = str(root / "source")
        os.environ["XDG_CONFIG_HOME"] = str(root / "global-config")
        _run_cli("config", "set", "--global", "currency", "EUR")
        assert _run_cli("config", "get", "currency")["value"] == "EUR"
        _run_cli("config", "set", "currency", "USD")
        _run_cli("init")
        assert _run_cli("rules", "list")["rules"] == []
        doctor = _run_cli("doctor")
        assert doctor["db_revision"] == migrate.HEAD_REVISION, doctor
        _run_cli(
            "manual", "add", "--date", "2026-09-05", "--amount", "-12.50",
            "--description", "Example purchase", "--category", "Food",
        )
        for currency, amount in [("KWD", "-12.345"), ("JPY", "-1250")]:
            _run_cli(
                "manual", "add", "--date", "2026-09-05", "--amount", amount,
                "--currency", currency, "--description", "Example foreign purchase",
                "--category", "Food",
            )
        backup_file = root / "home.canhoto"
        _run_cli("backup", "--output", str(backup_file))
        os.environ["CANHOTO_DATA_DIR"] = str(root / "target")
        _run_cli("restore", str(backup_file))
        rows = _run_cli("manual", "list")
        assert rows["count"] == 3
        transactions = rows["transactions"]
        assert isinstance(transactions, list)
        assert {row["currency"]: row["amount"] for row in transactions} == {
            "USD": "-12.50", "KWD": "-12.345", "JPY": "-1250",
        }
        report = _run_cli("breakdown", "--month", "2026-09")["breakdown"]
        assert isinstance(report, dict)
        groups = report["by_currency"]
        assert groups["KWD"]["expenses"] == "12.345"
        assert groups["JPY"]["expenses"] == "1250"
        pdf = _run_cli("export", "pdf", "2026-09")
        assert Path(str(pdf["path"])).is_file()
        assert _run_cli("config", "get", "currency")["value"] == "USD"
        doctor = _run_cli("doctor")
        assert doctor["db_revision"] == migrate.HEAD_REVISION, doctor
    print("smoke test passed")


if __name__ == "__main__":
    main()
