"""Load and select user/plugin StatementParser implementations.

Discovery rules
---------------
- Modules are those listed in ``AppConfig.parsers`` under
  ``{data_dir}/{parsers_dir}/`` (default ``parsers/``).
- Ingest-time registry: **enabled** entries only (``load_enabled_parsers``).
- Disabled entries remain loadable by id for test flows (``load_parser_by_id``).
- Import convention: module must expose ``register() -> StatementParser``.
  See ``canhoto.parsers.protocol`` module docstring.
"""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path
from types import ModuleType

from canhoto.core.config import get_data_dir
from canhoto.core.models import AppConfig, ParserEntry
from canhoto.parsers.protocol import StatementParser


class ParserNotFoundError(LookupError):
    """No suitable parser for the document, or unknown parser id."""


class ParserLoadError(RuntimeError):
    """Parser module missing, invalid, or failed to import/register."""


def choose_parser(text: str, parsers: Sequence[StatementParser]) -> StatementParser:
    """Pick the parser with the highest positive sniff score.

    Raises ``ParserNotFoundError`` when the sequence is empty or the top score
    is ``<= 0``.
    """
    ranked = sorted(
        ((p.sniff(text), p) for p in parsers),
        key=lambda x: x[0],
        reverse=True,
    )
    if not ranked or ranked[0][0] <= 0:
        raise ParserNotFoundError(
            "no enabled parser claimed this document (best sniff score <= 0)"
        )
    return ranked[0][1]


def load_enabled_parsers(
    cfg: AppConfig,
    *,
    root: Path | None = None,
) -> list[StatementParser]:
    """Import and return parsers marked ``enabled=True`` in config order."""
    data_root = _resolve_root(cfg, root)
    parsers_root = data_root / cfg.parsers_dir
    loaded: list[StatementParser] = []
    for entry in cfg.parsers:
        if not entry.enabled:
            continue
        loaded.append(_load_entry(entry, parsers_root=parsers_root, data_root=data_root))
    return loaded


def load_parser_by_id(
    cfg: AppConfig,
    parser_id: str,
    *,
    root: Path | None = None,
) -> StatementParser:
    """Load one parser by config id, whether enabled or disabled.

    Used by test/enable flows. Raises ``ParserNotFoundError`` if id is absent
    from config; ``ParserLoadError`` if the module cannot be loaded.
    """
    entry = _find_entry(cfg.parsers, parser_id)
    if entry is None:
        raise ParserNotFoundError(f"parser id not registered in config: {parser_id!r}")
    data_root = _resolve_root(cfg, root)
    parsers_root = data_root / cfg.parsers_dir
    return _load_entry(entry, parsers_root=parsers_root, data_root=data_root)


def _find_entry(entries: Iterable[ParserEntry], parser_id: str) -> ParserEntry | None:
    for entry in entries:
        if entry.id == parser_id:
            return entry
    return None


def _resolve_root(cfg: AppConfig, root: Path | None) -> Path:
    if root is not None:
        return root.expanduser()
    if cfg.data_dir:
        return Path(cfg.data_dir).expanduser()
    return get_data_dir()


def _load_entry(
    entry: ParserEntry,
    *,
    parsers_root: Path,
    data_root: Path,
) -> StatementParser:
    module_name = entry.module
    # Normalize: allow "foo" or "foo.py"
    if module_name.endswith(".py"):
        file_name = module_name
        stem = module_name[: -len(".py")]
    else:
        file_name = f"{module_name}.py"
        stem = module_name

    module_path = (parsers_root / file_name).resolve()
    try:
        module_path.relative_to(parsers_root.resolve())
    except ValueError as exc:
        raise ParserLoadError(
            f"parser module path escapes parsers dir: {entry.module!r}"
        ) from exc

    if not module_path.is_file():
        raise ParserLoadError(
            f"parser module file not found for id={entry.id!r}: {module_path}"
        )

    # Unique, stable-ish module name so reloads in tests don't collide badly.
    import_name = f"canhoto_user_parsers.{data_root.resolve().name}.{stem}"
    module = _import_module_from_path(import_name, module_path)
    return _instantiate_parser(module, entry_id=entry.id, module_path=module_path)


def _import_module_from_path(import_name: str, module_path: Path) -> ModuleType:
    # Drop any prior import so parser_write / re-test always sees fresh source.
    sys.modules.pop(import_name, None)
    spec = importlib.util.spec_from_file_location(import_name, module_path)
    if spec is None or spec.loader is None:
        raise ParserLoadError(f"cannot create import spec for {module_path}")
    module = importlib.util.module_from_spec(spec)
    # Register before exec so dataclasses / relative patterns behave if used.
    sys.modules[import_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001 — surface plugin errors cleanly
        sys.modules.pop(import_name, None)
        raise ParserLoadError(
            f"failed importing parser module {module_path}: {exc}"
        ) from exc
    return module


def _instantiate_parser(
    module: ModuleType,
    *,
    entry_id: str,
    module_path: Path,
) -> StatementParser:
    register = getattr(module, "register", None)
    if register is None or not callable(register):
        raise ParserLoadError(
            f"parser module {module_path.name!r} must expose register() -> StatementParser"
        )
    try:
        parser = register()
    except Exception as exc:  # noqa: BLE001
        raise ParserLoadError(
            f"register() failed in {module_path.name!r}: {exc}"
        ) from exc

    if not isinstance(parser, StatementParser):
        # runtime_checkable checks methods; also require identity attrs.
        missing = [
            name
            for name in ("id", "statement_type", "institution", "version", "sniff", "parse")
            if not hasattr(parser, name)
        ]
        if missing:
            raise ParserLoadError(
                f"register() in {module_path.name!r} returned object missing: {missing}"
            )

    # Prefer config id consistency when plugin forgets to set id.
    if getattr(parser, "id", None) in (None, ""):
        try:
            parser.id = entry_id
        except Exception:  # noqa: BLE001
            pass
    return parser
