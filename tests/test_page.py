"""The page serves files and an API address. It does not call the ledger."""

from __future__ import annotations

import pytest
from canhoto.cli import main as cli_main
from canhoto.dashboard import launch
from canhoto.page.app import create_page
from starlette.testclient import TestClient

_API = "http://127.0.0.1:8765"


def test_page_serves_itself_and_the_api_origin() -> None:
    client = TestClient(create_page(api_origin=_API))

    home = client.get("/")
    assert home.status_code == 200
    assert "Canhoto" in home.text
    assert "canhoto.service" not in home.text
    policy = home.headers["content-security-policy"]
    assert "connect-src 'self' http://127.0.0.1:8765" in policy
    assert "img-src 'self' blob: data:" in policy
    assert "frame-src" not in policy

    config = client.get("/config.json")
    assert config.json() == {"api_origin": _API}

    script = client.get("/app.js")
    assert script.status_code == 200
    assert "fetch" in script.text


def test_page_rejects_a_public_api_origin() -> None:
    with pytest.raises(ValueError, match="127.0.0.1"):
        create_page(api_origin="http://example.com:8765")


def test_dashboard_help_and_port_guard(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli_main(["dashboard", "--help"])
    assert exc.value.code == 0
    assert "8766" in capsys.readouterr().out

    with pytest.raises(ValueError, match="different ports"):
        launch(api_port=8765, page_port=8765)
