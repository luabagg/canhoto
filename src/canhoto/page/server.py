"""Run the page on loopback."""

from __future__ import annotations

import argparse

import uvicorn

from canhoto.loopback import require_loopback, require_loopback_origin, require_port
from canhoto.page.app import create_page

_HOST = "127.0.0.1"


def main(argv: list[str] | None = None) -> None:
    """Start the page. The process exits when the server stops."""
    parser = argparse.ArgumentParser(prog="canhoto-page", description="Canhoto page")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--api-origin", default="http://127.0.0.1:8765")
    args = parser.parse_args(argv)
    serve(port=args.port, api_origin=args.api_origin)


def serve(*, port: int, api_origin: str) -> None:
    """Bind the page to 127.0.0.1 and block."""
    require_loopback(_HOST)
    origin = require_loopback_origin(api_origin)
    uvicorn.run(
        create_page(api_origin=origin),
        host=_HOST,
        port=require_port(port),
        log_level="info",
    )
