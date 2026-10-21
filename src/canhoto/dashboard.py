"""Start the page and the API as two servers in one command."""

from __future__ import annotations

import asyncio
import threading

import uvicorn

from canhoto.api.app import create_api
from canhoto.loopback import require_loopback_origin, require_port
from canhoto.page.app import create_page

_HOST = "127.0.0.1"


def launch(*, api_port: int = 8765, page_port: int = 8766) -> None:
    """Bind both servers to 127.0.0.1 and block until the API stops."""
    api_port = require_port(api_port)
    page_port = require_port(page_port)
    if api_port == page_port:
        raise ValueError("the page and the API need different ports")
    api_origin = require_loopback_origin(f"http://{_HOST}:{api_port}")
    page_origin = require_loopback_origin(f"http://{_HOST}:{page_port}")
    page_server = uvicorn.Server(
        uvicorn.Config(
            create_page(api_origin=api_origin),
            host=_HOST,
            port=page_port,
            log_level="info",
        )
    )
    api_server = uvicorn.Server(
        uvicorn.Config(
            create_api(page_origin=page_origin),
            host=_HOST,
            port=api_port,
            log_level="info",
        )
    )

    def run_page() -> None:
        asyncio.run(page_server.serve())

    thread = threading.Thread(target=run_page, name="canhoto-page", daemon=True)
    thread.start()
    print(f"Page  {page_origin}", flush=True)
    print(f"API   {api_origin}", flush=True)
    api_server.run()
    page_server.should_exit = True
    thread.join(timeout=5)
