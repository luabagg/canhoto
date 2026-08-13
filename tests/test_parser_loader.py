"""StatementParser protocol, registry, and loader tests."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from canhoto.core.config import init_data_dir, load_config, save_config
from canhoto.core.models import (
    AppConfig,
    LedgerTransaction,
    ParserEntry,
    ParseResult,
    StatementMeta,
    StatementType,
)
from canhoto.parsers.loader import (
    ParserLoadError,
    ParserNotFoundError,
    choose_parser,
    load_enabled_parsers,
    load_parser_by_id,
)
from canhoto.parsers.protocol import StatementParser


class _FakeParser:
    """In-memory fake satisfying StatementParser (not a bank parser)."""

    def __init__(
        self,
        parser_id: str,
        *,
        score: float,
        statement_type: str = "card",
        institution: str = "Fake Bank",
        version: str = "0.0.1",
        marker: str | None = None,
    ) -> None:
        self.id = parser_id
        self.statement_type = statement_type
        self.institution = institution
        self.version = version
        self._score = score
        self._marker = marker or parser_id

    def sniff(self, text: str) -> float:
        if self._marker in text:
            return self._score
        return 0.0

    def parse(self, text: str, source_file: str) -> ParseResult:
        tx = LedgerTransaction(
            id=f"{self.id}-tx-1",
            date=date(2026, 7, 1),
            amount_minor=-1000,
            source_kind=self.statement_type,
            institution=self.institution,
            source_file=source_file,
            month="2026-07",
            description=text.strip()[:40],
            merchant_raw="FAKE",
        )
        return ParseResult(
            meta=StatementMeta(
                statement_type=self.statement_type,
                source_file=source_file,
                institution=self.institution,
            ),
            transactions=[tx],
        )


def test_fake_parser_satisfies_protocol() -> None:
    parser: StatementParser = _FakeParser("demo", score=0.9)
    assert parser.id == "demo"
    assert 0.0 <= parser.sniff("demo hello") <= 1.0
    result = parser.parse("demo hello", "demo.txt")
    assert isinstance(result, ParseResult)
    assert result.meta.source_file == "demo.txt"
    assert len(result.transactions) == 1
    assert isinstance(result.transactions[0], LedgerTransaction)


def test_choose_parser_picks_highest_sniff() -> None:
    low = _FakeParser("low", score=0.4, marker="SHARED")
    high = _FakeParser("high", score=0.9, marker="SHARED")
    mid = _FakeParser("mid", score=0.6, marker="SHARED")
    chosen = choose_parser("SHARED document", [low, mid, high])
    assert chosen.id == "high"


def test_choose_parser_raises_when_empty() -> None:
    with pytest.raises(ParserNotFoundError):
        choose_parser("anything", [])


def test_choose_parser_raises_when_all_scores_non_positive() -> None:
    zero = _FakeParser("zero", score=0.0, marker="HIT")
    negative = _FakeParser("neg", score=-0.1, marker="HIT")
    with pytest.raises(ParserNotFoundError):
        choose_parser("HIT text", [zero, negative])
    with pytest.raises(ParserNotFoundError):
        choose_parser("no markers here", [zero])


def test_parse_result_shape() -> None:
    meta = StatementMeta(
        statement_type=StatementType.ACCOUNT,
        source_file="a.txt",
        institution="Example",
        period_start=date(2026, 6, 1),
        period_end=date(2026, 6, 30),
    )
    tx = LedgerTransaction(
        id="t1",
        date=date(2026, 6, 2),
        amount_minor=500,
        source_kind="account",
        month="2026-06",
    )
    result = ParseResult(meta=meta, transactions=[tx])
    assert result.meta.statement_type in ("account", StatementType.ACCOUNT)
    assert result.transactions[0].id == "t1"


def _write_parser_module(path: Path, parser_id: str, marker: str, score: float) -> None:
    """Write a data-dir plugin module using the register() convention."""
    path.write_text(
        f'''\
"""Test plugin parser (not a real bank)."""
from __future__ import annotations

from datetime import date

from canhoto.core.models import LedgerTransaction, ParseResult, StatementMeta


class _PluginParser:
    id = {parser_id!r}
    statement_type = "card"
    institution = "Plugin Bank"
    version = "1.0.0"

    def sniff(self, text: str) -> float:
        return {score!r} if {marker!r} in text else 0.0

    def parse(self, text: str, source_file: str) -> ParseResult:
        return ParseResult(
            meta=StatementMeta(
                statement_type=self.statement_type,
                source_file=source_file,
                institution=self.institution,
            ),
            transactions=[
                LedgerTransaction(
                    id=f"{{self.id}}-1",
                    date=date(2026, 7, 15),
                    amount_minor=-2500,
                    source_kind=self.statement_type,
                    institution=self.institution,
                    source_file=source_file,
                    month="2026-07",
                    merchant_raw="PLUGIN",
                )
            ],
        )


def register():
    """Required plugin entrypoint — returns a StatementParser instance."""
    return _PluginParser()
''',
        encoding="utf-8",
    )


def test_load_enabled_parsers_only(tmp_path: Path) -> None:
    root = init_data_dir(tmp_path)
    parsers_dir = root / "parsers"
    _write_parser_module(parsers_dir / "alpha.py", "alpha", "ALPHA", 0.8)
    _write_parser_module(parsers_dir / "beta.py", "beta", "BETA", 0.7)
    _write_parser_module(parsers_dir / "gamma.py", "gamma", "GAMMA", 0.9)

    cfg = load_config(root)
    cfg = cfg.model_copy(
        update={
            "parsers": [
                ParserEntry(id="alpha", module="alpha.py", enabled=True),
                ParserEntry(id="beta", module="beta.py", enabled=False),
                ParserEntry(id="gamma", module="gamma.py", enabled=True),
            ]
        }
    )
    save_config(cfg, root=root)
    cfg = load_config(root)

    loaded = load_enabled_parsers(cfg, root=root)
    ids = sorted(p.id for p in loaded)
    assert ids == ["alpha", "gamma"]

    # Disabled must not appear in ingest registry even if module exists.
    assert all(p.id != "beta" for p in loaded)

    # choose_parser works against the enabled registry
    chosen = choose_parser("ALPHA and GAMMA both present", loaded)
    assert chosen.id == "gamma"  # 0.9 > 0.8


def test_load_parser_by_id_includes_disabled(tmp_path: Path) -> None:
    root = init_data_dir(tmp_path)
    parsers_dir = root / "parsers"
    _write_parser_module(parsers_dir / "beta.py", "beta", "BETA", 0.7)

    cfg = AppConfig(
        data_dir=str(root.resolve()),
        parsers=[
            ParserEntry(id="beta", module="beta.py", enabled=False),
        ],
    )
    save_config(cfg, root=root)
    cfg = load_config(root)

    # Disabled excluded from ingest registry
    assert load_enabled_parsers(cfg, root=root) == []

    # But still loadable by id for test flows
    parser = load_parser_by_id(cfg, "beta", root=root)
    assert parser.id == "beta"
    assert parser.sniff("BETA sample") == 0.7


def test_load_parser_by_id_missing_raises(tmp_path: Path) -> None:
    root = init_data_dir(tmp_path)
    cfg = load_config(root)
    with pytest.raises(ParserNotFoundError):
        load_parser_by_id(cfg, "nope", root=root)


def test_load_enabled_missing_module_raises(tmp_path: Path) -> None:
    root = init_data_dir(tmp_path)
    cfg = AppConfig(
        data_dir=str(root.resolve()),
        parsers=[ParserEntry(id="ghost", module="ghost.py", enabled=True)],
    )
    save_config(cfg, root=root)
    cfg = load_config(root)
    with pytest.raises(ParserLoadError):
        load_enabled_parsers(cfg, root=root)
