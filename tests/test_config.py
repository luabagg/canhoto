"""Config + data-dir layout tests."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TextIO

import pytest
from canhoto.cli import main as cli_main
from canhoto.core import config as core_config
from canhoto.core.config import (
    config_path,
    db_path,
    get_data_dir,
    init_data_dir,
    load_config,
    save_config,
)
from canhoto.core.models import AgentViewConfig, AppConfig, ParserEntry

REQUIRED_SUBDIRS = ("parsers", "exports", "raw", "fixtures")
FORBIDDEN_CONFIG_KEYS = {
    "spreadsheet_id",
    "google_credentials",
    "google_token",
    "google_auth",
    "sheets_id",
}


@pytest.fixture
def data_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "canhoto-home"
    monkeypatch.setenv("CANHOTO_DATA_DIR", str(root))
    return root


def test_get_data_dir_uses_canhoto_data_dir_env(data_home: Path) -> None:
    assert get_data_dir() == data_home


def test_get_data_dir_defaults_to_home_dot_canhoto(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CANHOTO_DATA_DIR", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert get_data_dir() == tmp_path / ".canhoto"


def test_init_data_dir_creates_layout_and_config(data_home: Path) -> None:
    assert not data_home.exists()

    root = init_data_dir()

    assert root == data_home
    assert data_home.is_dir()
    for name in REQUIRED_SUBDIRS:
        assert (data_home / name).is_dir(), name
    assert config_path() == data_home / "config.json"
    assert config_path().is_file()
    assert db_path() == data_home / "canhoto.db"
    # DB file is a path reserved for the store layer; layout only ensures parent exists.
    assert db_path().parent == data_home
    assert not db_path().exists()


def test_init_data_dir_is_idempotent(data_home: Path) -> None:
    first = init_data_dir()
    marker = data_home / "parsers" / "keep_me.py"
    marker.write_text("# keep\n", encoding="utf-8")
    cfg = load_config()
    cfg.parsers.append(ParserEntry(id="demo", module="demo.py", enabled=True))
    save_config(cfg)

    second = init_data_dir()

    assert second == first
    assert marker.is_file()
    reloaded = load_config()
    assert len(reloaded.parsers) == 1
    assert reloaded.parsers[0].id == "demo"


def test_init_data_dir_default_config_has_no_google_fields(data_home: Path) -> None:
    init_data_dir()
    raw = json.loads(config_path().read_text(encoding="utf-8"))
    assert FORBIDDEN_CONFIG_KEYS.isdisjoint(raw.keys())
    assert "agent_view" in raw
    assert "parsers" in raw
    assert raw["data_dir"] == str(data_home.resolve())


def test_save_load_config_round_trips_agent_view_and_parsers(data_home: Path) -> None:
    init_data_dir()
    original = AppConfig(
        data_dir=str(data_home.resolve()),
        parsers_dir="parsers",
        parsers=[
            ParserEntry(id="mp-account", module="mp_account.py", enabled=False),
            ParserEntry(id="demo-card", module="demo_card.py", enabled=True),
        ],
        agent_view=AgentViewConfig(
            allow_aggregates=True,
            allow_review_items=True,
            include_amounts_in_review=False,
            include_institution=False,
            max_batch_size=10,
            absolute_max_batch_size=20,
            expense_only=False,
            allow_parser_writes=True,
            preview_max_chars=1234,
        ),
    )

    saved = save_config(original)
    loaded = load_config()

    assert saved == original
    assert loaded == original
    assert loaded.agent_view.include_amounts_in_review is False
    assert loaded.agent_view.allow_parser_writes is True
    assert loaded.agent_view.max_batch_size == 10
    assert [p.id for p in loaded.parsers] == ["mp-account", "demo-card"]
    assert loaded.parsers[1].enabled is True


def test_load_config_creates_default_when_missing_after_layout(data_home: Path) -> None:
    data_home.mkdir(parents=True)
    for name in REQUIRED_SUBDIRS:
        (data_home / name).mkdir()

    cfg = load_config()

    assert cfg.data_dir == str(data_home.resolve())
    assert cfg.parsers == []
    assert isinstance(cfg.agent_view, AgentViewConfig)
    assert config_path().is_file()


def test_currency_fallback_reads_do_not_create_config_or_ledger(data_home: Path) -> None:
    assert core_config.resolve_currency(data_home) == "BRL"
    assert core_config.get_config_value("currency", root=data_home) == "BRL"
    assert core_config.get_config_value("currency", global_scope=True) is None
    assert not data_home.exists()
    assert not core_config.global_config_path().exists()


def test_global_config_uses_xdg_config_home(tmp_path: Path) -> None:
    expected = tmp_path / "global-config" / "canhoto" / "config.json"
    assert core_config.global_config_path() == expected


@pytest.mark.parametrize("xdg", [None, "relative-directory"])
def test_global_config_falls_back_to_user_config_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, xdg: str | None
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    if xdg is None:
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    else:
        monkeypatch.setenv("XDG_CONFIG_HOME", xdg)
    assert core_config.global_config_path() == tmp_path / ".config" / "canhoto" / "config.json"


def test_global_currency_is_normalized_without_creating_local_data(data_home: Path) -> None:
    assert core_config.set_config_value("currency", " eur ", global_scope=True) == "EUR"
    assert core_config.get_config_value("currency", global_scope=True) == "EUR"
    assert core_config.resolve_currency(data_home) == "EUR"
    assert json.loads(core_config.global_config_path().read_text()) == {"currency": "EUR"}
    assert not data_home.exists()


def test_explicit_currency_and_ledger_override_take_priority(data_home: Path) -> None:
    core_config.set_config_value("currency", "EUR", global_scope=True)
    core_config.set_config_value("currency", "USD", root=data_home)

    assert core_config.resolve_currency(data_home) == "USD"
    assert core_config.resolve_currency(data_home, override="brl") == "BRL"
    assert core_config.get_config_value("currency", global_scope=True) == "EUR"
    assert not db_path(data_home).exists()


def test_config_save_does_not_freeze_inherited_currency(data_home: Path) -> None:
    init_data_dir(data_home)
    core_config.set_config_value("currency", "EUR", global_scope=True)
    cfg = load_config(data_home)
    assert cfg.currency is None
    save_config(cfg.model_copy(update={"own_name_markers": ["EXAMPLE OWNER"]}), root=data_home)
    core_config.set_config_value("currency", "USD", global_scope=True)

    assert core_config.resolve_currency(data_home) == "USD"
    assert load_config(data_home).currency is None
    assert load_config(data_home).own_name_markers == ["EXAMPLE OWNER"]


def test_unset_ledger_currency_restores_inheritance(data_home: Path) -> None:
    core_config.set_config_value("currency", "EUR", global_scope=True)
    core_config.set_config_value("currency", "USD", root=data_home)

    assert core_config.unset_config_value("currency", root=data_home) is True
    assert core_config.resolve_currency(data_home) == "EUR"
    assert core_config.unset_config_value("currency", root=data_home) is False
    assert core_config.unset_config_value("currency", global_scope=True) is True
    assert core_config.resolve_currency(data_home) == "BRL"


def test_unset_missing_currency_does_not_create_files(data_home: Path) -> None:
    assert core_config.unset_config_value("currency", root=data_home) is False
    assert core_config.unset_config_value("currency", global_scope=True) is False
    assert not data_home.exists()
    assert not core_config.global_config_path().exists()


@pytest.mark.parametrize("currency", ["", "EURO", "12A", "ßa"])
def test_invalid_currency_setting_does_not_create_files(data_home: Path, currency: str) -> None:
    with pytest.raises(ValueError, match="currency"):
        core_config.set_config_value("currency", currency, root=data_home)
    with pytest.raises(ValueError, match="currency"):
        core_config.set_config_value("currency", currency, global_scope=True)
    assert not data_home.exists()
    assert not core_config.global_config_path().exists()


def test_unknown_config_key_cannot_change_parser_policy(data_home: Path) -> None:
    init_data_dir(data_home)
    before = config_path(data_home).read_bytes()
    with pytest.raises(ValueError, match="unknown config key"):
        core_config.set_config_value("agent_view.allow_parser_writes", "true", root=data_home)
    assert config_path(data_home).read_bytes() == before
    assert not core_config.global_config_path().exists()


def test_invalid_global_config_does_not_block_explicit_or_local_currency(data_home: Path) -> None:
    global_path = core_config.global_config_path()
    global_path.parent.mkdir(parents=True)
    global_path.write_text("invalid JSON", encoding="utf-8")
    core_config.set_config_value("currency", "USD", root=data_home)

    assert core_config.resolve_currency(data_home, override="EUR") == "EUR"
    assert core_config.resolve_currency(data_home) == "USD"
    with pytest.raises(ValueError):
        core_config.get_config_value("currency", global_scope=True)


@pytest.mark.parametrize("global_scope", [False, True], ids=["ledger", "global"])
@pytest.mark.parametrize("failure", ["write", "close", "replace"])
def test_failed_config_write_preserves_old_value_and_removes_temporary_files(
    data_home: Path, monkeypatch: pytest.MonkeyPatch, global_scope: bool, failure: str
) -> None:
    core_config.set_config_value("currency", "EUR", global_scope=global_scope, root=data_home)
    path = core_config.global_config_path() if global_scope else config_path(data_home)
    before = path.read_bytes()
    fdopen = core_config.os.fdopen

    @contextmanager
    def faulty_fdopen(descriptor: int, mode: str, *, encoding: str) -> Iterator[TextIO]:
        with fdopen(descriptor, mode, encoding=encoding) as stream:
            if failure == "write":
                write = stream.write

                def partial_write(content: str) -> int:
                    write(content[:5])
                    raise OSError("config write failed")

                monkeypatch.setattr(stream, "write", partial_write)
            yield stream
            if failure == "close":
                raise OSError("config close failed")

    def fail_replace(*args: object) -> None:
        raise OSError("config installation failed")

    if failure == "replace":
        monkeypatch.setattr(core_config.os, "replace", fail_replace)
    else:
        monkeypatch.setattr(core_config.os, "fdopen", faulty_fdopen)
    with pytest.raises(OSError, match="failed"):
        core_config.set_config_value("currency", "USD", global_scope=global_scope, root=data_home)

    assert path.read_bytes() == before
    assert list(path.parent.iterdir()) == [path]


def test_cli_config_set_get_and_unset(
    data_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli_main(["config", "get", "currency"]) == 0
    assert json.loads(capsys.readouterr().out)["value"] == "BRL"
    assert not data_home.exists()

    assert cli_main(["config", "set", "--global", "currency", "eur"]) == 0
    assert json.loads(capsys.readouterr().out)["value"] == "EUR"
    assert not data_home.exists()
    assert cli_main(["config", "set", "currency", "USD"]) == 0
    assert json.loads(capsys.readouterr().out)["value"] == "USD"
    assert cli_main(["config", "get", "currency"]) == 0
    assert json.loads(capsys.readouterr().out)["value"] == "USD"
    assert cli_main(["config", "get", "--global", "currency"]) == 0
    assert json.loads(capsys.readouterr().out)["value"] == "EUR"
    assert cli_main(["config", "unset", "currency"]) == 0
    assert json.loads(capsys.readouterr().out)["removed"] is True
    assert cli_main(["config", "get", "currency"]) == 0
    assert json.loads(capsys.readouterr().out)["value"] == "EUR"
    assert cli_main(["config", "unset", "--global", "currency"]) == 0
    assert json.loads(capsys.readouterr().out)["removed"] is True
    assert cli_main(["config", "get", "--global", "currency"]) == 0
    assert json.loads(capsys.readouterr().out)["value"] is None
    assert not db_path(data_home).exists()


def test_cli_config_rejects_unknown_keys_without_writing(
    data_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli_main(["config", "set", "unknown", "EUR"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is False
    assert "unknown config key" in result["error"]
    assert not data_home.exists()


def test_save_config_never_writes_google_fields(data_home: Path) -> None:
    init_data_dir()
    cfg = load_config()
    save_config(cfg)
    raw = json.loads(config_path().read_text(encoding="utf-8"))
    assert FORBIDDEN_CONFIG_KEYS.isdisjoint(raw)
    dumped = cfg.model_dump()
    assert FORBIDDEN_CONFIG_KEYS.isdisjoint(dumped)

