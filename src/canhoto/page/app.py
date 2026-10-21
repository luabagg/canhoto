"""Static page server. It tells the browser where the API is. It does not call it."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from canhoto.loopback import require_loopback_origin

_STATIC = Path(__file__).resolve().parent / "static"


def create_page(*, api_origin: str) -> ASGIApp:
    """Serve the page. ``api_origin`` is published at ``/config.json``."""
    origin = require_loopback_origin(api_origin)
    app = Starlette(
        debug=False,
        routes=[
            Route("/config.json", _config(origin), methods=["GET"]),
            Mount("/", app=StaticFiles(directory=_STATIC, html=True), name="page"),
        ],
    )
    return _Headers(app, api_origin=origin)


def _config(api_origin: str) -> Callable[[Request], Awaitable[Response]]:
    async def config_json(_request: Request) -> Response:
        return JSONResponse({"api_origin": api_origin})

    return config_json


class _Headers:
    """Add a content policy that allows the page to call only its API."""

    def __init__(self, app: ASGIApp, *, api_origin: str) -> None:
        self.app = app
        self._csp = (
            "default-src 'self'; "
            f"connect-src 'self' {api_origin}; "
            "style-src 'self'; "
            "script-src 'self'; "
            "img-src 'self' blob: data:; "
            "base-uri 'none'; "
            "form-action 'self'"
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_policy(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"content-security-policy", self._csp.encode()))
                headers.append((b"x-content-type-options", b"nosniff"))
                headers.append((b"referrer-policy", b"no-referrer"))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_policy)
