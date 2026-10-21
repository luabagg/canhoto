"""Owner JSON API. It calls the service and stays off ledger-dump routes."""

from __future__ import annotations

import base64
import shutil
from pathlib import Path

import pytest
from canhoto.api.app import create_api
from canhoto.core.config import init_data_dir
from canhoto.loopback import require_loopback, require_loopback_origin
from starlette.routing import Route
from starlette.testclient import TestClient

_REPO = Path(__file__).resolve().parents[1]
_DEMO = _REPO / "examples" / "parsers" / "demo_line_parser.py"
_FIXTURE = _REPO / "examples" / "parsers" / "fixtures" / "demo_statement.txt"
_ORIGIN = "http://127.0.0.1:8766"


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    root = tmp_path / "home"
    monkeypatch.setenv("CANHOTO_DATA_DIR", str(root))
    init_data_dir(root)
    return TestClient(create_api(page_origin=_ORIGIN), base_url="http://127.0.0.1:8765")


def test_refuses_a_public_bind_and_origin() -> None:
    with pytest.raises(ValueError, match="127.0.0.1"):
        require_loopback("0.0.0.0")
    with pytest.raises(ValueError, match="127.0.0.1"):
        require_loopback_origin("https://example.com")
    with pytest.raises(ValueError, match="127.0.0.1"):
        create_api(page_origin="http://example.com:8766")


def test_routes_cover_owner_work_and_skip_dumps() -> None:
    paths = {
        route.path
        for route in create_api(page_origin=_ORIGIN).routes
        if isinstance(route, Route)
    }
    assert {
        "/doctor",
        "/ingest",
        "/months",
        "/breakdown",
        "/export/pdf",
        "/review",
        "/categories",
        "/rules",
        "/rules/run",
        "/manual",
    } <= paths
    assert "/backup" not in paths
    assert "/restore" not in paths
    assert "/sql" not in paths


def test_cors_allows_only_the_page_origin(client: TestClient) -> None:
    ok = client.get("/doctor", headers={"Origin": _ORIGIN})
    assert ok.headers["access-control-allow-origin"] == _ORIGIN
    blocked = client.get("/doctor", headers={"Origin": "http://example.com"})
    assert blocked.headers.get("access-control-allow-origin") != "http://example.com"


def test_refuses_writes_from_another_site(client: TestClient) -> None:
    # A text/plain POST skips the CORS preflight, so CORS alone does not stop it.
    sneaky = client.post(
        "/rules",
        content='{"pattern": "x", "category": "Taken", "kind": "expense"}',
        headers={"Origin": "https://evil.example", "Content-Type": "text/plain"},
    )
    assert sneaky.status_code == 403
    assert client.get("/rules").json()["rules"] == []

    from_page = client.post(
        "/rules",
        json={"pattern": "x", "category": "Kept", "kind": "expense"},
        headers={"Origin": _ORIGIN},
    )
    assert from_page.status_code == 200


def test_refuses_a_rebound_host_name(client: TestClient) -> None:
    rebound = client.get("/rules", headers={"Host": "evil.example:8765"})
    assert rebound.status_code == 400


def test_ingest_breakdown_and_pdf(client: TestClient, tmp_path: Path) -> None:
    _enable_demo(Path(client.get("/doctor").json()["data_dir"]))
    statement = _FIXTURE.read_bytes()
    secret = "pdf-secret-not-for-logs"

    uploaded = client.post(
        "/ingest",
        files={"file": ("../../demo_statement.txt", statement, "text/plain")},
        data={"pdf_password": secret},
    )

    assert uploaded.status_code == 200
    body = uploaded.json()
    assert secret not in uploaded.text
    assert body["transaction_count"] == 3
    assert body["original_names"] == ["demo_statement.txt"]
    inbox = Path(body["files"][0]["path"])
    assert inbox.parent.name == "inbox"

    months = client.get("/months")
    assert months.json()["months"][0]["month"] == "2026-07"

    report = client.get("/breakdown", params={"month": "2026-07"})
    assert report.status_code == 200
    currencies = report.json()["breakdown"]["by_currency"]
    assert "BRL" in currencies
    assert "transactions" not in report.json()

    exports = Path(body["data_dir"]) / "exports"
    preview = client.get("/export/pdf/preview", params={"month": "2026-07", "profile": "modern"})
    assert preview.status_code == 200
    pages = preview.json()["pages"]
    assert preview.json()["page_count"] == len(pages) >= 1
    assert base64.b64decode(pages[0]).startswith(b"\x89PNG\r\n\x1a\n")
    assert list(exports.iterdir()) == []

    pdf = client.post("/export/pdf", json={"month": "2026-07", "profile": "minimal"})
    assert pdf.status_code == 200
    assert pdf.headers["content-type"].startswith("application/pdf")
    assert pdf.content.startswith(b"%PDF")
    assert "attachment" in pdf.headers["content-disposition"]
    assert (exports / "2026-07-summary.pdf").is_file()


def test_manual_and_rules(client: TestClient) -> None:
    added = client.post(
        "/manual",
        json={
            "date": "2026-08-02",
            "amount": "-10.00",
            "description": "Market",
            "category": "Groceries",
        },
    )
    assert added.status_code == 200
    tx_id = added.json()["transaction"]["id"]

    listed = client.get("/manual", params={"month": "2026-08"})
    assert listed.json()["count"] == 1

    edited = client.patch(f"/manual/{tx_id}", json={"amount": "-12.50", "category": "Food"})
    assert edited.status_code == 200
    assert edited.json()["transaction"]["amount"] == "-12.50"

    removed = client.delete(f"/manual/{tx_id}")
    assert removed.status_code == 200

    rule = client.post(
        "/rules",
        json={"pattern": "MARKET", "category": "Groceries", "kind": "expense"},
    )
    assert rule.status_code == 200
    rule_id = rule.json()["rule"]["id"]
    assert client.delete(f"/rules/{rule_id}").json()["removed"] is True


def test_pdf_layouts_and_bad_input(client: TestClient) -> None:
    profiles = client.get("/export/profiles").json()
    assert profiles["default"] == "canhoto"
    assert {p["id"] for p in profiles["profiles"]} == {"canhoto", "modern", "minimal"}

    bad_profile = client.get("/export/pdf/preview", params={"month": "2026-07", "profile": "x"})
    assert bad_profile.status_code == 400
    assert bad_profile.json()["ok"] is False

    bad_edit = client.patch("/manual/manual-x", json={})
    assert bad_edit.status_code == 400


def test_currency_round_trip(client: TestClient) -> None:
    saved = client.put("/config/currency", json={"value": "EUR"})
    assert saved.status_code == 200
    assert client.get("/config/currency").json()["value"] == "EUR"


def _enable_demo(data_home: Path) -> None:
    from canhoto.core.config import load_config, save_config
    from canhoto.core.models import ParserEntry

    shutil.copy2(_DEMO, data_home / "parsers" / "demo_line_parser.py")
    cfg = load_config(data_home)
    entry = ParserEntry(
        id="demo_line",
        module="demo_line_parser.py",
        enabled=True,
        last_test_ok=True,
        last_test_at="2026-07-29T00:00:00Z",
    )
    save_config(cfg.model_copy(update={"parsers": [entry]}), root=data_home)
