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
        _run_cli("init")
        assert _run_cli("rules", "list")["rules"] == []
        doctor = _run_cli("doctor")
        assert doctor["db_revision"] == migrate.HEAD_REVISION, doctor
        _run_cli(
            "manual", "add", "--date", "2026-09-05", "--amount", "-12.50",
            "--description", "Example purchase", "--category", "Food",
        )
        backup_file = root / "home.canhoto"
        _run_cli("backup", "--output", str(backup_file))
        os.environ["CANHOTO_DATA_DIR"] = str(root / "target")
        _run_cli("restore", str(backup_file))
        assert _run_cli("manual", "list")["count"] == 1
        doctor = _run_cli("doctor")
        assert doctor["db_revision"] == migrate.HEAD_REVISION, doctor
    print("smoke test passed")


if __name__ == "__main__":
    main()
