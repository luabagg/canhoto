"""Parser scaffold / test / enable flow tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from canhoto import service
from canhoto.core.config import init_data_dir, load_config
from canhoto.core.models import ParserEntry


@pytest.fixture
def data_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "canhoto-home"
    monkeypatch.setenv("CANHOTO_DATA_DIR", str(root))
    init_data_dir(root)
    return root


_WORKING_PARSER = '''\
"""Working demo parser for tests (not a real bank)."""
from __future__ import annotations

from datetime import date

from canhoto.core.models import LedgerTransaction, ParseResult, StatementMeta


class _DemoParser:
    id = "demo_card"
    statement_type = "card"
    institution = "demo"
    version = "0.1.0"

    def sniff(self, text: str) -> float:
        return 0.9 if "DEMO_CARD" in text else 0.0

    def parse(self, text: str, source_file: str) -> ParseResult:
        if "DEMO_CARD" not in text:
            raise ValueError("not a demo card statement")
        return ParseResult(
            meta=StatementMeta(
                statement_type=self.statement_type,
                source_file=source_file,
                institution=self.institution,
            ),
            transactions=[
                LedgerTransaction(
                    id="demo-1",
                    date=date(2026, 7, 1),
                    amount_minor=-1500,
                    source_kind=self.statement_type,
                    institution=self.institution,
                    source_file=source_file,
                    month="2026-07",
                    merchant_raw="DEMO STORE",
                )
            ],
        )


def register():
    return _DemoParser()
'''

_BROKEN_PARSER = '''\
"""Broken parser that always fails parse."""
from __future__ import annotations

from canhoto.core.models import ParseResult, StatementMeta


class _Broken:
    id = "demo_card"
    statement_type = "card"
    institution = "demo"
    version = "0.0.0"

    def sniff(self, text: str) -> float:
        return 0.5

    def parse(self, text: str, source_file: str) -> ParseResult:
        raise RuntimeError("intentional parse failure")


def register():
    return _Broken()
'''


def test_parser_scaffold_writes_module_and_config(data_home: Path) -> None:
    result = service.parser_scaffold("demo_card", "card", "demo", root=data_home)

    assert result["id"] == "demo_card"
    assert result["module"] == "demo_card.py"
    assert result["enabled"] is False
    module_path = Path(result["path"])
    assert module_path.is_file()
    assert module_path.parent == data_home / "parsers"
    code = module_path.read_text(encoding="utf-8")
    assert "def register()" in code
    assert "PARSER" not in code or "def register()" in code

    cfg = load_config(data_home)
    assert len(cfg.parsers) == 1
    entry = cfg.parsers[0]
    assert entry.id == "demo_card"
    assert entry.module == "demo_card.py"
    assert entry.enabled is False
    assert entry.last_test_ok is None


def test_parser_scaffold_rejects_duplicate_id(data_home: Path) -> None:
    service.parser_scaffold("demo_card", "card", "demo", root=data_home)
    with pytest.raises(ValueError, match="already"):
        service.parser_scaffold("demo_card", "card", "demo", root=data_home)


def test_parser_write_overwrites_module(data_home: Path) -> None:
    service.parser_scaffold("demo_card", "card", "demo", root=data_home)
    result = service.parser_write("demo_card", _WORKING_PARSER, root=data_home)
    assert result["id"] == "demo_card"
    path = data_home / "parsers" / "demo_card.py"
    assert path.read_text(encoding="utf-8") == _WORKING_PARSER
    # Writing invalidates prior test stamp
    cfg = load_config(data_home)
    entry = next(p for p in cfg.parsers if p.id == "demo_card")
    assert entry.last_test_ok is None
    assert entry.enabled is False


def test_parser_enable_fails_without_successful_test(data_home: Path) -> None:
    service.parser_scaffold("demo_card", "card", "demo", root=data_home)
    with pytest.raises(ValueError, match="test"):
        service.parser_enable("demo_card", root=data_home)
    cfg = load_config(data_home)
    assert cfg.parsers[0].enabled is False


def test_parser_enable_fails_after_failed_test(data_home: Path) -> None:
    service.parser_scaffold("demo_card", "card", "demo", root=data_home)
    service.parser_write("demo_card", _BROKEN_PARSER, root=data_home)
    sample = data_home / "fixtures" / "sample.txt"
    sample.write_text("DEMO_CARD line\n", encoding="utf-8")

    test_result = service.parser_test("demo_card", sample, root=data_home)
    assert test_result["ok"] is False
    assert test_result["last_test_ok"] is False

    with pytest.raises(ValueError, match="test"):
        service.parser_enable("demo_card", root=data_home)
    cfg = load_config(data_home)
    assert cfg.parsers[0].enabled is False
    assert cfg.parsers[0].last_test_ok is False


def test_parser_test_fails_on_empty_transactions(data_home: Path) -> None:
    """Scaffold stubs return zero rows — must not stamp last_test_ok."""
    service.parser_scaffold("demo_card", "card", "demo", root=data_home)
    sample = data_home / "fixtures" / "sample.txt"
    sample.write_text("anything\n", encoding="utf-8")

    test_result = service.parser_test("demo_card", sample, root=data_home)
    assert test_result["ok"] is False
    assert test_result["last_test_ok"] is False
    assert test_result["transaction_count"] == 0
    assert "zero" in (test_result.get("last_test_error") or "").lower()
    with pytest.raises(ValueError, match="test"):
        service.parser_enable("demo_card", root=data_home)


def test_parser_enable_succeeds_after_ok_test(data_home: Path) -> None:
    service.parser_scaffold("demo_card", "card", "demo", root=data_home)
    service.parser_write("demo_card", _WORKING_PARSER, root=data_home)
    sample = data_home / "fixtures" / "sample.txt"
    sample.write_text("DEMO_CARD statement body\n", encoding="utf-8")

    test_result = service.parser_test("demo_card", sample, root=data_home)
    assert test_result["ok"] is True
    assert test_result["last_test_ok"] is True
    assert test_result["transaction_count"] == 1

    enable_result = service.parser_enable("demo_card", root=data_home)
    assert enable_result["id"] == "demo_card"
    assert enable_result["enabled"] is True

    cfg = load_config(data_home)
    entry = cfg.parsers[0]
    assert entry.enabled is True
    assert entry.last_test_ok is True


def test_parser_write_clears_enabled_and_requires_retest(data_home: Path) -> None:
    service.parser_scaffold("demo_card", "card", "demo", root=data_home)
    service.parser_write("demo_card", _WORKING_PARSER, root=data_home)
    sample = data_home / "fixtures" / "sample.txt"
    sample.write_text("DEMO_CARD ok\n", encoding="utf-8")
    service.parser_test("demo_card", sample, root=data_home)
    service.parser_enable("demo_card", root=data_home)

    service.parser_write("demo_card", _WORKING_PARSER, root=data_home)
    cfg = load_config(data_home)
    entry = cfg.parsers[0]
    assert entry.enabled is False
    assert entry.last_test_ok is None

    with pytest.raises(ValueError, match="test"):
        service.parser_enable("demo_card", root=data_home)


def test_parser_list_reports_status(data_home: Path) -> None:
    service.parser_scaffold("demo_card", "card", "demo", root=data_home)
    service.parser_scaffold("other", "account", "demo", root=data_home)
    listed = service.parser_list(root=data_home)
    assert listed["count"] == 2
    ids = {p["id"] for p in listed["parsers"]}
    assert ids == {"demo_card", "other"}
    demo = next(p for p in listed["parsers"] if p["id"] == "demo_card")
    assert demo["enabled"] is False
    assert demo["last_test_ok"] is None
    assert demo["module"] == "demo_card.py"


def test_cli_parsers_scaffold_test_enable_list(
    data_home: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from canhoto.cli import main

    assert (
        main(
            [
                "parsers",
                "scaffold",
                "--id",
                "demo_card",
                "--type",
                "card",
                "--institution",
                "demo",
            ]
        )
        == 0
    )
    service.parser_write("demo_card", _WORKING_PARSER, root=data_home)
    sample = tmp_path / "sample.txt"
    sample.write_text("DEMO_CARD via cli\n", encoding="utf-8")

    assert main(["parsers", "test", "--id", "demo_card", "--file", str(sample)]) == 0
    out = capsys.readouterr().out
    assert '"ok": true' in out.lower() or '"ok": true' in out

    assert main(["parsers", "enable", "--id", "demo_card"]) == 0
    assert main(["parsers", "list"]) == 0
    listed_out = capsys.readouterr().out
    assert "demo_card" in listed_out
    assert '"enabled": true' in listed_out


def test_cli_enable_without_test_exits_nonzero(
    data_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from canhoto.cli import main

    assert (
        main(
            [
                "parsers",
                "scaffold",
                "--id",
                "demo_card",
                "--type",
                "card",
                "--institution",
                "demo",
            ]
        )
        == 0
    )
    assert main(["parsers", "enable", "--id", "demo_card"]) == 1
    err = capsys.readouterr()
    combined = err.out + err.err
    assert "test" in combined.lower()


def test_parser_entry_last_test_fields_default_none() -> None:
    entry = ParserEntry(id="x", module="x.py")
    assert entry.last_test_ok is None
    assert entry.last_test_at is None
    assert entry.last_test_error is None


def _load_scaffolded(  # type: ignore[no-untyped-def]
    data_home: Path, parser_id: str = "demo_card", *, currency: str = "BRL",
):
    from canhoto.parsers.loader import load_parser_by_id

    path = data_home / "parsers" / f"{parser_id}.py"
    code = path.read_text().replace('_CURRENCY = "XXX"', f'_CURRENCY = "{currency}"')
    service.parser_write(parser_id, code, root=data_home)
    return load_parser_by_id(load_config(data_home), parser_id, root=data_home)


def test_scaffold_parse_skeleton_reads_example_rows(data_home: Path) -> None:
    service.parser_scaffold("demo_card", "card", "demo", root=data_home)
    parser = _load_scaffolded(data_home)

    text = "header\n2026-06-02  ACME STORE  -12.34\n2026-06-03  REFUND ACME  5.00\nfooter\n"
    txs = parser.parse(text, "/tmp/s.txt").transactions

    assert [(t.date.isoformat(), t.amount_minor, t.description) for t in txs] == [
        ("2026-06-02", -1234, "ACME STORE"),
        ("2026-06-03", 500, "REFUND ACME"),
    ]
    assert {t.month for t in txs} == {"2026-06"}
    assert all(t.category == "" and t.needs_review for t in txs)


@pytest.mark.parametrize(("currency", "amount", "minor", "exponent"), [
    ("JPY", "-1250", -1250, 0), ("KWD", "-12.345", -12345, 3),
])
def test_scaffold_uses_native_units(
    data_home: Path, currency: str, amount: str, minor: int, exponent: int,
) -> None:
    service.parser_scaffold("demo_card", "card", "demo", root=data_home)
    parser = _load_scaffolded(data_home, currency=currency)
    row = parser.parse(f"2026-06-02  MERCHANT  {amount}\n", "/tmp/s.txt").transactions[0]
    assert (row.currency, row.amount_minor, row.amount_exponent) == (currency, minor, exponent)
    assert str(row.amount) == amount


def test_scaffold_ids_do_not_depend_on_row_position(data_home: Path) -> None:
    service.parser_scaffold("demo_card", "card", "demo", root=data_home)
    parser = _load_scaffolded(data_home)
    row = "2026-06-02  ACME STORE  -12.34"

    alone = parser.parse(f"{row}\n", "/tmp/a.txt").transactions
    after_other = parser.parse(f"2026-06-01  OTHER  -1.00\n{row}\n", "/tmp/b.txt").transactions
    twice = parser.parse(f"{row}\n{row}\n", "/tmp/c.txt").transactions

    assert alone[0].id == after_other[1].id
    assert len({t.id for t in twice}) == 2


def test_parser_test_fails_when_sniff_does_not_claim_the_sample(data_home: Path) -> None:
    """A parser that parses rows but scores 0 would never be chosen by ingest."""
    service.parser_scaffold("demo_card", "card", "demo", root=data_home)
    _load_scaffolded(data_home)
    sample = data_home / "fixtures" / "sample.txt"
    sample.write_text("2026-06-02  ACME STORE  -12.34\n", encoding="utf-8")

    result = service.parser_test("demo_card", sample, root=data_home)

    assert result["ok"] is False
    assert result["transaction_count"] == 1
    assert "sniff" in (result.get("last_test_error") or "")


def test_cli_parsers_preview_prints_extracted_text(
    data_home: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from canhoto.cli import main

    sample = tmp_path / "statement.txt"
    sample.write_text("ACME BANK\n2026-06-02  ACME STORE  -12.34\n", encoding="utf-8")

    assert main(["parsers", "preview", "--file", str(sample)]) == 0
    assert capsys.readouterr().out == "ACME BANK\n2026-06-02  ACME STORE  -12.34\n"


def test_cli_parsers_preview_reports_truncation_on_stderr(
    data_home: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from canhoto.cli import main
    from canhoto.core.config import save_config

    cfg = load_config(data_home)
    save_config(cfg.model_copy(update={"agent_view": cfg.agent_view.model_copy(
        update={"preview_max_chars": 5})}), data_home)
    sample = tmp_path / "statement.txt"
    sample.write_text("0123456789", encoding="utf-8")

    assert main(["parsers", "preview", "--file", str(sample)]) == 0
    captured = capsys.readouterr()
    assert captured.out == "01234\n"
    assert "truncated" in captured.err
    assert "preview_max_chars" in captured.err


def test_cli_parsers_preview_missing_file_exits_nonzero(
    data_home: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from canhoto.cli import main

    assert main(["parsers", "preview", "--file", str(tmp_path / "nope.pdf")]) == 1
    assert '"ok": false' in capsys.readouterr().out
