"""Service façade for CLI/MCP adapters.

Thin orchestration over core config + store + parser lifecycle. No Sheets,
no raw SQL exposure, no unbounded ledger dumps.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from canhoto.core import breakdown as core_breakdown
from canhoto.core import categorize as core_categorize
from canhoto.core import config as core_config
from canhoto.core import store as core_store
from canhoto.core.models import (
    ClassificationPatch,
    ParserEntry,
    ReportBundle,
    StatementRecord,
)
from canhoto.core.pdf_text import extract_text
from canhoto.core.policy import assert_month, clamp_batch_size
from canhoto.core.redaction import to_review_item
from canhoto.exporters.pdf_summary import PdfSummaryExporter
from canhoto.parsers import loader as parser_loader
from canhoto.parsers import scaffold as parser_scaffold_mod
from canhoto.parsers.loader import ParserLoadError, ParserNotFoundError

Source = Literal["cli", "mcp"]


def init(root: Path | None = None) -> dict[str, Any]:
    """Create data-dir layout and default config. Does not require parsers."""
    path = core_config.init_data_dir(root)
    return {
        "data_dir": str(path.resolve()),
        "config_path": str(core_config.config_path(path)),
        "db_path": str(core_config.db_path(path)),
    }


def doctor(root: Path | None = None) -> dict[str, Any]:
    """Return a JSON-serializable health report for the active data dir.

    Checks: data root writable, config present, enabled/disabled parser
    counts, database openability, pending-review total. Never returns
    ledger rows or SQL.
    """
    data_dir = (root if root is not None else core_config.get_data_dir()).expanduser()
    checks: list[str] = []
    ok = True

    writable = _is_writable(data_dir)
    if writable:
        checks.append("ok: data_dir_writable")
    else:
        ok = False
        checks.append("error: data_dir_not_writable")

    cfg_file = core_config.config_path(data_dir)
    config_present = cfg_file.is_file()
    if config_present:
        checks.append("ok: config_present")
    else:
        ok = False
        checks.append("error: config_missing")

    parsers_enabled = 0
    parsers_disabled = 0
    if config_present:
        try:
            cfg = core_config.load_config(data_dir)
            for entry in cfg.parsers:
                if entry.enabled:
                    parsers_enabled += 1
                else:
                    parsers_disabled += 1
            checks.append(
                f"ok: parsers enabled={parsers_enabled} disabled={parsers_disabled}"
            )
        except Exception as exc:  # noqa: BLE001 — report, do not raise
            ok = False
            checks.append(f"error: config_unreadable ({type(exc).__name__})")
    else:
        checks.append("skip: parsers (no config)")

    db_file = core_config.db_path(data_dir)
    db_openable = False
    pending_review = 0
    if writable:
        try:
            core_store.ensure_schema(db_file)
            # Prove a real read works after schema ensure.
            with core_store.connect(db_file) as conn:
                conn.execute("SELECT 1").fetchone()
            db_openable = True
            pending_review = core_store.count_pending_review(path=db_file)
            checks.append("ok: db_openable")
            checks.append(f"ok: pending_review={pending_review}")
        except (OSError, sqlite3.Error) as exc:
            ok = False
            checks.append(f"error: db_not_openable ({type(exc).__name__})")
    else:
        ok = False
        checks.append("skip: db (data_dir not writable)")

    return {
        "ok": ok,
        "data_dir": str(data_dir.resolve()) if data_dir.exists() else str(data_dir),
        "data_dir_writable": writable,
        "config_present": config_present,
        "config_path": str(cfg_file),
        "db_path": str(db_file),
        "parsers_enabled": parsers_enabled,
        "parsers_disabled": parsers_disabled,
        "db_openable": db_openable,
        "pending_review": pending_review,
        "checks": checks,
    }


def _is_writable(path: Path) -> bool:
    """Return True if ``path`` exists (or can be created) and is writable."""
    try:
        if path.exists():
            if not path.is_dir():
                return False
            return os.access(path, os.W_OK | os.X_OK)
        # Parent must allow creating the data dir.
        parent = path.parent
        return parent.exists() and os.access(parent, os.W_OK | os.X_OK)
    except OSError:
        return False


# --- Parser lifecycle (scaffold / write / test / enable / list) ---


def parser_scaffold(
    parser_id: str,
    statement_type: str,
    institution: str,
    *,
    root: Path | None = None,
) -> dict[str, Any]:
    """Create a stub parser module and register it disabled in config."""
    data_dir = _ensure_data_dir(root)
    cfg = core_config.load_config(data_dir)
    pid = parser_scaffold_mod.validate_parser_id(parser_id)
    if _find_parser_entry(cfg.parsers, pid) is not None:
        raise ValueError(f"parser id already registered: {pid!r}")

    parsers_root = data_dir / cfg.parsers_dir
    path = parser_scaffold_mod.write_stub_module(
        parsers_root,
        parser_id=pid,
        statement_type=statement_type,
        institution=institution,
        overwrite=False,
    )
    entry = ParserEntry(
        id=pid,
        module=path.name,
        enabled=False,
        last_test_ok=None,
        last_test_at=None,
        last_test_error=None,
    )
    parsers = list(cfg.parsers) + [entry]
    core_config.save_config(cfg.model_copy(update={"parsers": parsers}), root=data_dir)
    return {
        "id": entry.id,
        "module": entry.module,
        "path": str(path),
        "enabled": False,
        "last_test_ok": None,
        "statement_type": statement_type.strip().lower(),
        "institution": institution.strip(),
    }


def parser_write(
    parser_id: str,
    code: str,
    *,
    root: Path | None = None,
    source: Source = "cli",
) -> dict[str, Any]:
    """Overwrite a registered parser module with ``code``.

    CLI (default ``source="cli"``) always may write. MCP callers must pass
    ``source="mcp"``, which is refused unless ``agent_view.allow_parser_writes``.
    A successful write clears enable + last-test stamps so enable requires retest.
    """
    data_dir = _ensure_data_dir(root)
    cfg = core_config.load_config(data_dir)
    if source == "mcp" and not cfg.agent_view.allow_parser_writes:
        raise PermissionError(
            "parser_write refused: agent_view.allow_parser_writes is false"
        )

    entry = _require_parser_entry(cfg.parsers, parser_id)
    path = _parser_module_path(data_dir, cfg.parsers_dir, entry.module)
    if not path.parent.is_dir():
        path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(code, encoding="utf-8")

    updated = entry.model_copy(
        update={
            "enabled": False,
            "last_test_ok": None,
            "last_test_at": None,
            "last_test_error": None,
        }
    )
    core_config.save_config(
        cfg.model_copy(update={"parsers": _replace_entry(cfg.parsers, updated)}),
        root=data_dir,
    )
    return {
        "id": updated.id,
        "module": updated.module,
        "path": str(path),
        "enabled": False,
        "last_test_ok": None,
        "bytes_written": len(code.encode("utf-8")),
    }


def parser_test(
    parser_id: str,
    file: str | Path,
    *,
    root: Path | None = None,
) -> dict[str, Any]:
    """Load parser by id, run parse against sample file, stamp last_test_* on config."""
    data_dir = _ensure_data_dir(root)
    cfg = core_config.load_config(data_dir)
    entry = _require_parser_entry(cfg.parsers, parser_id)
    sample = Path(file).expanduser()
    if not sample.is_file():
        raise FileNotFoundError(f"sample file not found: {sample}")

    text = _read_sample_text(sample)
    source_file = str(sample)
    now = _utc_now_iso()
    ok = False
    error: str | None = None
    transaction_count = 0
    sniff_score: float | None = None
    statement_type: str | None = None
    institution: str | None = None

    try:
        parser = parser_loader.load_parser_by_id(cfg, entry.id, root=data_dir)
        sniff_score = float(parser.sniff(text))
        result = parser.parse(text, source_file)
        transaction_count = len(result.transactions)
        statement_type = str(result.meta.statement_type)
        institution = result.meta.institution
        ok = True
    except (ParserLoadError, ParserNotFoundError, OSError, ValueError, RuntimeError) as exc:
        error = f"{type(exc).__name__}: {exc}"
    except Exception as exc:  # noqa: BLE001 — stamp any plugin failure
        error = f"{type(exc).__name__}: {exc}"

    updated = entry.model_copy(
        update={
            "last_test_ok": ok,
            "last_test_at": now,
            "last_test_error": None if ok else (error or "parse failed"),
            # Failed or re-run tests never leave enable stuck on stale code.
            "enabled": entry.enabled if ok else False,
        }
    )
    # Keep enabled only when still OK; a failed test always disables.
    if not ok:
        updated = updated.model_copy(update={"enabled": False})

    core_config.save_config(
        cfg.model_copy(update={"parsers": _replace_entry(cfg.parsers, updated)}),
        root=data_dir,
    )
    out: dict[str, Any] = {
        "id": updated.id,
        "ok": ok,
        "last_test_ok": updated.last_test_ok,
        "last_test_at": updated.last_test_at,
        "last_test_error": updated.last_test_error,
        "enabled": updated.enabled,
        "sample": source_file,
        "transaction_count": transaction_count,
        "sniff_score": sniff_score,
    }
    if statement_type is not None:
        out["statement_type"] = statement_type
    if institution is not None:
        out["institution"] = institution
    return out


def parser_enable(
    parser_id: str,
    *,
    root: Path | None = None,
) -> dict[str, Any]:
    """Enable a parser only when the last ``parser_test`` stamped OK."""
    data_dir = _ensure_data_dir(root)
    cfg = core_config.load_config(data_dir)
    entry = _require_parser_entry(cfg.parsers, parser_id)

    if entry.last_test_ok is not True:
        detail = entry.last_test_error or "no successful test stamp"
        raise ValueError(
            f"cannot enable parser {entry.id!r}: last test not OK ({detail})"
        )

    # Prove the module still loads before flipping the enable bit.
    try:
        parser_loader.load_parser_by_id(cfg, entry.id, root=data_dir)
    except (ParserLoadError, ParserNotFoundError) as exc:
        raise ValueError(
            f"cannot enable parser {entry.id!r}: module load failed ({exc})"
        ) from exc

    updated = entry.model_copy(update={"enabled": True})
    core_config.save_config(
        cfg.model_copy(update={"parsers": _replace_entry(cfg.parsers, updated)}),
        root=data_dir,
    )
    return {
        "id": updated.id,
        "module": updated.module,
        "enabled": True,
        "last_test_ok": updated.last_test_ok,
        "last_test_at": updated.last_test_at,
    }


def parser_list(*, root: Path | None = None) -> dict[str, Any]:
    """Return registered parsers and their enable/test status."""
    data_dir = _ensure_data_dir(root)
    cfg = core_config.load_config(data_dir)
    items = [
        {
            "id": e.id,
            "module": e.module,
            "enabled": e.enabled,
            "last_test_ok": e.last_test_ok,
            "last_test_at": e.last_test_at,
            "last_test_error": e.last_test_error,
        }
        for e in cfg.parsers
    ]
    return {"count": len(items), "parsers": items, "data_dir": str(data_dir.resolve())}


# --- Ingest ---


def ingest(
    paths: Sequence[str | Path],
    *,
    root: Path | None = None,
) -> dict[str, Any]:
    """Archive, parse, and upsert statement files via enabled plugin parsers.

    For each path:
      1. Archive raw bytes under ``data_dir/raw/`` by content hash
      2. Extract text (PDF via pymupdf; plain text passthrough)
      3. Choose an enabled parser by sniff score
      4. Parse and upsert statement + transactions

    Classification columns are preserved on same-id re-ingest.

    Raises:
        FileNotFoundError: a path does not exist
        ParserNotFoundError: no enabled parser, or none claims the document
        ParserLoadError: an enabled parser module fails to load
        ValueError: empty path list or extract/parse hard failure
    """
    if not paths:
        raise ValueError("ingest requires at least one path")

    data_dir = _ensure_data_dir(root)
    cfg = core_config.load_config(data_dir)
    parsers = parser_loader.load_enabled_parsers(cfg, root=data_dir)
    if not parsers:
        raise ParserNotFoundError(
            "no enabled parser claimed this document (no enabled parsers registered)"
        )

    db_file = core_config.db_path(data_dir)
    core_store.ensure_schema(db_file)
    raw_dir = data_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    files_out: list[dict[str, Any]] = []
    total_txs = 0
    total_inserted = 0
    total_updated = 0

    for raw_path in paths:
        src = Path(raw_path).expanduser()
        if not src.is_file():
            raise FileNotFoundError(f"file not found: {src}")

        content = src.read_bytes()
        content_hash = hashlib.sha256(content).hexdigest()
        archived_path = _archive_raw(raw_dir, content_hash, src, content)

        text = extract_text(src)
        parser = parser_loader.choose_parser(text, parsers)
        source_file = str(src.resolve())
        parsed = parser.parse(text, source_file)

        # Prefer path identity for ledger source_file; keep parse meta consistent.
        meta = parsed.meta.model_copy(update={"source_file": source_file})
        txs = [
            tx.model_copy(update={"source_file": source_file})
            if tx.source_file != source_file
            else tx
            for tx in parsed.transactions
        ]

        statement = StatementRecord(
            content_hash=content_hash,
            source_file=source_file,
            statement_type=str(meta.statement_type),
            institution=meta.institution,
            meta_json=meta.model_dump(mode="json"),
        )
        upsert, stmt_result = core_store.save_statement_with_transactions(
            statement,
            txs,
            path=db_file,
            preserve_classification=True,
        )

        total_txs += len(txs)
        total_inserted += upsert.inserted
        total_updated += upsert.updated
        files_out.append(
            {
                "ok": True,
                "path": source_file,
                "archived_path": str(archived_path),
                "content_hash": content_hash,
                "parser_id": getattr(parser, "id", None),
                "statement_type": str(meta.statement_type),
                "institution": meta.institution,
                "transaction_count": len(txs),
                "inserted": upsert.inserted,
                "updated": upsert.updated,
                "statement_created": stmt_result.created,
                "linked": stmt_result.linked,
            }
        )

    return {
        "ok": True,
        "data_dir": str(data_dir.resolve()),
        "db_path": str(db_file),
        "file_count": len(files_out),
        "transaction_count": total_txs,
        "inserted": total_inserted,
        "updated": total_updated,
        "files": files_out,
    }


def parse(
    file: str | Path,
    *,
    root: Path | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Dry-run extract + choose + parse; no archive and no DB writes.

    Returns a capped JSON-serializable summary (meta + limited transaction
    rows). Row cap uses agent-view batch policy (``absolute_max_batch_size``
    hard ceiling; default ``max_batch_size``).

    Raises:
        FileNotFoundError: path does not exist
        ParserNotFoundError: no enabled parser, or none claims the document
        ParserLoadError: an enabled parser module fails to load
        ValueError: extract/parse hard failure or invalid limit
    """
    data_dir = _ensure_data_dir(root)
    cfg = core_config.load_config(data_dir)
    parsers = parser_loader.load_enabled_parsers(cfg, root=data_dir)
    if not parsers:
        raise ParserNotFoundError(
            "no enabled parser claimed this document (no enabled parsers registered)"
        )

    src = Path(file).expanduser()
    if not src.is_file():
        raise FileNotFoundError(f"file not found: {src}")

    preview_limit = clamp_batch_size(limit, cfg.agent_view)
    text = extract_text(src)
    parser = parser_loader.choose_parser(text, parsers)
    source_file = str(src.resolve())
    parsed = parser.parse(text, source_file)

    meta = parsed.meta.model_copy(update={"source_file": source_file})
    all_txs = parsed.transactions
    total = len(all_txs)
    preview_txs = all_txs[:preview_limit]
    truncated = total > preview_limit

    return {
        "ok": True,
        "dry_run": True,
        "path": source_file,
        "parser_id": getattr(parser, "id", None),
        "statement_type": str(meta.statement_type),
        "institution": meta.institution,
        "meta": meta.model_dump(mode="json"),
        "transaction_count": total,
        "preview_count": len(preview_txs),
        "preview_limit": preview_limit,
        "truncated": truncated,
        "transactions": [tx.model_dump(mode="json") for tx in preview_txs],
        "data_dir": str(data_dir.resolve()),
    }


def _archive_raw(
    raw_dir: Path,
    content_hash: str,
    src: Path,
    content: bytes,
) -> Path:
    """Write content-addressed copy under raw/. Idempotent for same hash+suffix."""
    suffix = src.suffix.lower() if src.suffix else ""
    dest = raw_dir / f"{content_hash}{suffix}"
    if dest.is_file():
        # Already archived; verify same bytes when present.
        if dest.read_bytes() == content:
            return dest.resolve()
        # Extremely unlikely hash collision with different bytes: keep first copy.
        return dest.resolve()
    dest.write_bytes(content)
    return dest.resolve()


def _ensure_data_dir(root: Path | None) -> Path:
    path = (root if root is not None else core_config.get_data_dir()).expanduser()
    return core_config.init_data_dir(path)


def _find_parser_entry(
    entries: list[ParserEntry], parser_id: str
) -> ParserEntry | None:
    for entry in entries:
        if entry.id == parser_id:
            return entry
    return None


def _require_parser_entry(
    entries: list[ParserEntry], parser_id: str
) -> ParserEntry:
    entry = _find_parser_entry(entries, parser_id)
    if entry is None:
        raise ParserNotFoundError(f"parser id not registered in config: {parser_id!r}")
    return entry


def _replace_entry(
    entries: list[ParserEntry], updated: ParserEntry
) -> list[ParserEntry]:
    out: list[ParserEntry] = []
    found = False
    for entry in entries:
        if entry.id == updated.id:
            out.append(updated)
            found = True
        else:
            out.append(entry)
    if not found:
        out.append(updated)
    return out


def _parser_module_path(data_dir: Path, parsers_dir: str, module: str) -> Path:
    name = module if module.endswith(".py") else f"{module}.py"
    parsers_root = (data_dir / parsers_dir).resolve()
    path = (parsers_root / name).resolve()
    try:
        path.relative_to(parsers_root)
    except ValueError as exc:
        raise ValueError(f"parser module path escapes parsers dir: {module!r}") from exc
    return path


def _read_sample_text(sample: Path) -> str:
    """Read sample file as text via shared extract helper."""
    return extract_text(sample)


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


# --- Categorization (deterministic rules) ---


def run_rules(
    month: str,
    *,
    root: Path | None = None,
    own_name_markers: list[str] | None = None,
) -> dict[str, Any]:
    """Apply deterministic rules, then merchant memory, for ``month`` (YYYY-MM).

    Order: rule pack → self-transfer markers → merchant_category_map recall
    for rows still uncategorized / needs_review.

    Uses ``AppConfig.own_name_markers`` when ``own_name_markers`` is omitted.
    Never returns full ledger rows — only counts and pending-review total.
    """
    data_dir = _ensure_data_dir(root)
    cfg = core_config.load_config(data_dir)
    db_file = core_config.db_path(data_dir)
    core_store.ensure_schema(db_file)

    markers = (
        list(own_name_markers)
        if own_name_markers is not None
        else list(cfg.own_name_markers)
    )
    result = core_categorize.run_rules_for_month(
        month,
        path=db_file,
        own_name_markers=markers,
    )
    pending = core_store.count_pending_review(month=month, path=db_file)
    return {
        "ok": True,
        "month": month,
        "applied": result.applied,
        "missing": list(result.missing),
        "merchant_memory_applied": result.merchant_memory_applied,
        "pending_review": pending,
        "own_name_markers_count": len(markers),
        "data_dir": str(data_dir.resolve()),
        "db_path": str(db_file),
    }


def set_merchant_category(
    merchant_key: str,
    category: str,
    *,
    root: Path | None = None,
) -> dict[str, Any]:
    """Remember ``merchant_key → category`` for later rule runs.

    Skips person-id-like keys (empty, CPF-shaped, digit-heavy). Does not
    rewrite existing ledger rows — call ``run_rules`` to apply memory.
    """
    key = (merchant_key or "").strip()
    cat = (category or "").strip()
    if not cat:
        raise ValueError("category must be a non-empty string")

    data_dir = _ensure_data_dir(root)
    db_file = core_config.db_path(data_dir)
    core_store.ensure_schema(db_file)

    if not core_categorize.is_learnable_merchant_key(key):
        return {
            "ok": True,
            "learned": False,
            "skipped_reason": "unlearnable_merchant_key",
            "merchant_key": key,
            "category": cat,
            "data_dir": str(data_dir.resolve()),
            "db_path": str(db_file),
        }

    core_store.set_merchant_category(key, cat, path=db_file)
    return {
        "ok": True,
        "learned": True,
        "merchant_key": key,
        "category": cat,
        "data_dir": str(data_dir.resolve()),
        "db_path": str(db_file),
    }

# --- Review batches + category patches ---


def review_batch(
    month: str,
    cursor: str | None = None,
    limit: int | None = None,
    *,
    root: Path | None = None,
) -> dict[str, Any]:
    """Return a capped, redacted pending-review batch for ``month`` (YYYY-MM).

    Uses Phase 0 policy (``assert_month``, ``clamp_batch_size``) and redaction
    (``to_review_item`` only). Default queue is pending review; when
    ``agent_view.expense_only`` is true (default), only expense rows are included.

    ``cursor`` is the last item id from a previous page (keyset pagination).
    Never returns raw ledger fields.
    """
    month_value = assert_month(month)
    data_dir = _ensure_data_dir(root)
    cfg = core_config.load_config(data_dir)
    if not cfg.agent_view.allow_review_items:
        raise PermissionError("review_batch refused: agent_view.allow_review_items is false")

    batch_limit = clamp_batch_size(limit, cfg.agent_view)
    db_file = core_config.db_path(data_dir)
    core_store.ensure_schema(db_file)

    # Fetch one extra row to detect a following page without exposing total dumps.
    fetch_limit = batch_limit + 1
    txs = core_store.list_transactions(
        month=month_value,
        needs_review=True,
        is_expense=True if cfg.agent_view.expense_only else None,
        after_id=cursor,
        limit=fetch_limit,
        path=db_file,
    )
    page = txs[:batch_limit]
    has_more = len(txs) > batch_limit
    items = [to_review_item(tx, cfg.agent_view).model_dump(mode="json") for tx in page]
    next_cursor = page[-1].id if has_more and page else None

    out: dict[str, Any] = {
        "ok": True,
        "month": month_value,
        "items": items,
        "count": len(items),
        "limit": batch_limit,
        "expense_only": cfg.agent_view.expense_only,
        "data_dir": str(data_dir.resolve()),
        "db_path": str(db_file),
    }
    if next_cursor is not None:
        out["next_cursor"] = next_cursor
    elif cursor is not None:
        # Explicit null when a page was requested and there is no successor.
        out["next_cursor"] = None
    return out


def set_categories(
    patches: list[dict[str, Any]],
    *,
    root: Path | None = None,
) -> dict[str, Any]:
    """Apply classification patches via ``store.apply_classifications``.

    Each patch is a dict accepted by ``ClassificationPatch``. Missing ids are
    reported; never returns ledger rows.
    """
    if not isinstance(patches, list):
        raise ValueError("patches must be a list of objects")

    data_dir = _ensure_data_dir(root)
    db_file = core_config.db_path(data_dir)
    core_store.ensure_schema(db_file)

    parsed: list[ClassificationPatch] = []
    for i, raw in enumerate(patches):
        if not isinstance(raw, dict):
            raise ValueError(f"patches[{i}] must be an object")
        parsed.append(ClassificationPatch.model_validate(raw))

    result = core_store.apply_classifications(parsed, path=db_file)
    return {
        "ok": True,
        "applied": result.applied,
        "missing": list(result.missing),
        "count": len(parsed),
        "data_dir": str(data_dir.resolve()),
        "db_path": str(db_file),
    }


def month_breakdown(
    month: str,
    *,
    root: Path | None = None,
) -> dict[str, Any]:
    """Return aggregate month report (no transaction list).

    Uses portable accounting rules: expenses include ``is_expense`` / expense
    kinds (card spend counts); ``card_payment`` / ``self_transfer`` /
    ``internal_transfer`` are excluded from spend; income is income-kind or
    positive non-expense inflows. Amounts are decimal strings.

    Honors ``agent_view.allow_aggregates``. Never returns ledger rows.
    """
    month_value = assert_month(month)
    data_dir = _ensure_data_dir(root)
    cfg = core_config.load_config(data_dir)
    if not cfg.agent_view.allow_aggregates:
        raise PermissionError(
            "month_breakdown refused: agent_view.allow_aggregates is false"
        )

    db_file = core_config.db_path(data_dir)
    core_store.ensure_schema(db_file)
    txs = core_store.list_transactions(
        month=month_value,
        limit=core_breakdown.DEFAULT_MONTH_LIMIT,
        path=db_file,
    )
    breakdown = core_breakdown.compute_month_breakdown(month_value, txs)
    return {
        "ok": True,
        "month": month_value,
        "breakdown": breakdown.model_dump(mode="json"),
        "data_dir": str(data_dir.resolve()),
        "db_path": str(db_file),
    }


# --- Agent preview + PDF export (PDF body lands in Phase 6) ---


def statement_preview(
    path: str | Path,
    *,
    root: Path | None = None,
) -> dict[str, Any]:
    """Extract statement text and return a truncated agent-safe preview.

    Resolves the user path, extracts text via the shared PDF/text helper, and
    truncates to ``agent_view.preview_max_chars``. Returns basename only — never
    directory listings or unrelated filesystem dumps.
    """
    data_dir = _ensure_data_dir(root)
    cfg = core_config.load_config(data_dir)
    max_chars = int(cfg.agent_view.preview_max_chars)
    if max_chars <= 0:
        raise ValueError("agent_view.preview_max_chars must be positive")

    src = Path(path).expanduser()
    if not src.is_file():
        raise FileNotFoundError(f"file not found: {src}")

    text = extract_text(src)
    char_count = len(text)
    truncated = char_count > max_chars
    preview = text[:max_chars] if truncated else text
    return {
        "path_basename": src.name,
        "char_count": char_count,
        "truncated": truncated,
        "text": preview,
    }


def export_pdf(
    month: str,
    *,
    root: Path | None = None,
) -> dict[str, Any]:
    """Build month aggregates and write a summary PDF under ``exports/``.

    Path is always ``{data_dir}/exports/{month}-summary.pdf``. Never includes
    a full transaction listing — metrics + category totals only.
    """
    month_value = assert_month(month)
    data_dir = _ensure_data_dir(root)
    cfg = core_config.load_config(data_dir)
    if not cfg.agent_view.allow_aggregates:
        raise PermissionError(
            "export_pdf refused: agent_view.allow_aggregates is false"
        )

    db_file = core_config.db_path(data_dir)
    core_store.ensure_schema(db_file)
    txs = core_store.list_transactions(
        month=month_value,
        limit=core_breakdown.DEFAULT_MONTH_LIMIT,
        path=db_file,
    )
    breakdown = core_breakdown.compute_month_breakdown(month_value, txs)
    generated_at = _utc_now_iso()
    bundle = ReportBundle(
        breakdown=breakdown,
        generated_at=generated_at,
        title=f"Canhoto summary — {month_value}",
    )

    exports_dir = (data_dir / "exports").resolve()
    exports_dir.mkdir(parents=True, exist_ok=True)
    dest = (exports_dir / f"{month_value}-summary.pdf").resolve()
    if exports_dir not in dest.parents and dest.parent != exports_dir:
        raise RuntimeError("export path escaped exports directory")

    written = PdfSummaryExporter().export(bundle, dest)
    size = written.stat().st_size
    if size <= 0:
        raise RuntimeError("export produced empty PDF")

    return {
        "ok": True,
        "month": month_value,
        "path": str(written),
        "size": size,
        "data_dir": str(data_dir.resolve()),
    }
