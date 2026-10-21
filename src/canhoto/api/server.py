"""Run the JSON API on loopback."""

from __future__ import annotations

import argparse

import uvicorn

from canhoto.api.app import create_api
from canhoto.loopback import require_loopback, require_loopback_origin, require_port

_HOST = "127.0.0.1"


def main(argv: list[str] | None = None) -> None:
    """Start the API. The process exits when the server stops."""
    parser = argparse.ArgumentParser(prog="canhoto-api", description="Canhoto JSON API")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--page-origin", default="http://127.0.0.1:8766")
    args = parser.parse_args(argv)
    serve(port=args.port, page_origin=args.page_origin)


def serve(*, port: int, page_origin: str) -> None:
    """Bind the API to 127.0.0.1 and block."""
    require_loopback(_HOST)
    origin = require_loopback_origin(page_origin)
    app = create_api(page_origin=origin)
    uvicorn.run(app, host=_HOST, port=require_port(port), log_level="info")
