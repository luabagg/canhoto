"""Config + data-dir layout tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
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


def test_save_config_never_writes_google_fields(data_home: Path) -> None:
    init_data_dir()
    cfg = load_config()
    save_config(cfg)
    raw = json.loads(config_path().read_text(encoding="utf-8"))
    assert FORBIDDEN_CONFIG_KEYS.isdisjoint(raw)
    dumped = cfg.model_dump()
    assert FORBIDDEN_CONFIG_KEYS.isdisjoint(dumped)

