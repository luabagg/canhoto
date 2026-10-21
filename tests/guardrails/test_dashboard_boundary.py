"""The page consumes HTTP. The API calls the service. They do not import each other."""

from __future__ import annotations

import ast
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_API = _ROOT / "src" / "canhoto" / "api"
_PAGE = _ROOT / "src" / "canhoto" / "page"


def test_api_does_not_import_the_page_or_the_ledger() -> None:
    imports = _imports(_API)
    assert "canhoto.page" not in imports
    assert not any(name == "canhoto.core" or name.startswith("canhoto.core.") for name in imports)
    assert "canhoto.service" in imports


def test_page_does_not_import_the_api_or_the_service() -> None:
    imports = _imports(_PAGE)
    for denied in ("canhoto.service", "canhoto.api", "canhoto.core", "canhoto.core.store"):
        assert denied not in imports
        assert not any(name.startswith(f"{denied}.") for name in imports)


def test_page_script_only_talks_http() -> None:
    script = (_PAGE / "static" / "app.js").read_text(encoding="utf-8")
    for denied in ("sqlite", "amount_minor", "canhoto.service", "innerHTML"):
        assert denied not in script


def test_api_source_has_no_html() -> None:
    for path in _API.rglob("*.py"):
        assert "<html" not in path.read_text(encoding="utf-8").lower()


def _imports(root: Path) -> set[str]:
    found: set[str] = set()
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                found.add(node.module)
                found.update(f"{node.module}.{alias.name}" for alias in node.names)
    return found
