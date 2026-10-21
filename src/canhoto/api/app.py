"""JSON routes for owner operations. Each route calls ``canhoto.service``."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import Headers, UploadFile
from starlette.exceptions import HTTPException
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

from canhoto import service
from canhoto.loopback import require_loopback_origin
from canhoto.parsers.loader import ParserLoadError, ParserNotFoundError

_MAX_UPLOAD_PART_BYTES = 32 * 1024 * 1024
# Host names a browser may use to reach the API. Any other Host is DNS rebinding.
_LOOPBACK_HOSTS = ["127.0.0.1", "localhost"]
_MANUAL_EDIT_FIELDS = (
    "date",
    "amount",
    "description",
    "currency",
    "category",
    "kind",
    "merchant",
    "account",
    "note",
)


def create_api(*, page_origin: str) -> Starlette:
    """Build the JSON API. ``page_origin`` is the only allowed browser origin."""
    origin = require_loopback_origin(page_origin)
    return Starlette(
        debug=False,
        routes=_routes(),
        middleware=[
            Middleware(TrustedHostMiddleware, allowed_hosts=_LOOPBACK_HOSTS),
            Middleware(_RefuseForeignOrigin, page_origin=origin),
            Middleware(
                CORSMiddleware,
                allow_origins=[origin],
                allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
                allow_headers=["content-type"],
            )
        ],
        exception_handlers={
            HTTPException: _http_error,
            ValueError: _error_handler(400),
            PermissionError: _error_handler(403),
            FileNotFoundError: _error_handler(404),
            ParserNotFoundError: _error_handler(422),
            ParserLoadError: _error_handler(422),
            Exception: _unhandled,
        },
    )


def _routes() -> list[Route]:
    return [
        Route("/doctor", _doctor, methods=["GET"]),
        Route("/init", _init, methods=["POST"]),
        Route("/config/currency", _currency_get, methods=["GET"]),
        Route("/config/currency", _currency_set, methods=["PUT"]),
        Route("/config/currency", _currency_unset, methods=["DELETE"]),
        Route("/parsers", _parsers, methods=["GET"]),
        Route("/months", _months, methods=["GET"]),
        Route("/breakdown", _breakdown, methods=["GET"]),
        Route("/export/profiles", _pdf_profiles, methods=["GET"]),
        Route("/export/pdf/preview", _preview_pdf, methods=["GET"]),
        Route("/export/pdf", _export_pdf, methods=["POST"]),
        Route("/ingest", _ingest, methods=["POST"]),
        Route("/review", _review, methods=["GET"]),
        Route("/categories", _categories, methods=["POST"]),
        Route("/merchants", _merchants, methods=["POST"]),
        Route("/rules", _rule_list, methods=["GET"]),
        Route("/rules", _rule_add, methods=["POST"]),
        Route("/rules/run", _rules_run, methods=["POST"]),
        Route("/rules/{rule_id:int}", _rule_remove, methods=["DELETE"]),
        Route("/manual", _manual_list, methods=["GET"]),
        Route("/manual", _manual_add, methods=["POST"]),
        Route("/manual/{tx_id}", _manual_edit, methods=["PATCH"]),
        Route("/manual/{tx_id}", _manual_remove, methods=["DELETE"]),
    ]


async def _doctor(_request: Request) -> Response:
    return await _call(service.doctor)


async def _init(_request: Request) -> Response:
    return await _call(service.init)


async def _currency_get(request: Request) -> Response:
    scope = _global_flag(request.query_params.get("global"))
    return await _call(lambda: service.config_get("currency", global_scope=scope))


async def _currency_set(request: Request) -> Response:
    body = await _body(request)
    value = body.get("value")
    if not isinstance(value, str) or not value.strip():
        raise HTTPException(status_code=400, detail="value must be a currency code")
    scope = _global_flag(_as_flag(body.get("global")))
    return await _call(lambda: service.config_set("currency", value, global_scope=scope))


async def _currency_unset(request: Request) -> Response:
    scope = _global_flag(request.query_params.get("global"))
    return await _call(lambda: service.config_unset("currency", global_scope=scope))


async def _parsers(_request: Request) -> Response:
    return await _call(service.parser_list)


async def _months(_request: Request) -> Response:
    return await _call(service.list_months)


async def _breakdown(request: Request) -> Response:
    month = _month(request)
    return await _call(lambda: service.month_breakdown(month))


async def _pdf_profiles(_request: Request) -> Response:
    return await _call(service.pdf_profiles)


async def _preview_pdf(request: Request) -> Response:
    month = _month(request)
    profile = request.query_params.get("profile") or "canhoto"
    return await _call(lambda: service.preview_pdf(month, profile=profile))


async def _export_pdf(request: Request) -> Response:
    body = await _body(request)
    month = _text(body, "month", required=True) or ""
    profile = _text(body, "profile") or "canhoto"
    payload = await run_in_threadpool(lambda: service.export_pdf(month, profile=profile))
    path = _export_file(payload)
    return FileResponse(path, media_type="application/pdf", filename=path.name)


async def _ingest(request: Request) -> Response:
    form = await request.form(max_files=8, max_fields=8, max_part_size=_MAX_UPLOAD_PART_BYTES)
    uploads = [item for item in form.getlist("file") if isinstance(item, UploadFile)]
    if not uploads:
        raise HTTPException(status_code=400, detail="choose a .pdf or .txt statement")
    password = form.get("pdf_password")
    if isinstance(password, UploadFile):
        raise HTTPException(status_code=400, detail="pdf_password must be text")
    secret = password.strip() if isinstance(password, str) and password.strip() else None
    files: list[tuple[str, bytes]] = []
    for upload in uploads:
        content = await upload.read()
        files.append((upload.filename or "statement", content))
    return await _call(
        lambda: service.receive_statements(files, pdf_password=secret)
    )


async def _review(request: Request) -> Response:
    month = _month(request)
    cursor = request.query_params.get("cursor") or None
    limit = _limit(request.query_params.get("limit"))
    return await _call(lambda: service.review_batch(month, cursor=cursor, limit=limit))


async def _categories(request: Request) -> Response:
    body = await _body(request)
    patches = body.get("patches")
    if not isinstance(patches, list):
        raise HTTPException(status_code=400, detail="patches must be a list")
    return await _call(lambda: service.set_categories(patches))


async def _merchants(request: Request) -> Response:
    body = await _body(request)
    key = body.get("merchant_key")
    category = body.get("category")
    if not isinstance(key, str) or not isinstance(category, str):
        raise HTTPException(status_code=400, detail="merchant_key and category are required")
    return await _call(lambda: service.set_merchant_category(key, category))


async def _rule_list(_request: Request) -> Response:
    return await _call(service.rule_list)


async def _rule_add(request: Request) -> Response:
    body = await _body(request)
    return await _call(lambda: service.rule_add(**_rule_kwargs(body)))


async def _rules_run(request: Request) -> Response:
    body = await _body(request)
    month = body.get("month")
    if not isinstance(month, str):
        raise HTTPException(status_code=400, detail="month is required")
    return await _call(lambda: service.run_rules(month))


async def _rule_remove(request: Request) -> Response:
    rule_id: int = request.path_params["rule_id"]
    return await _call(lambda: service.rule_remove(rule_id))


async def _manual_list(request: Request) -> Response:
    month = request.query_params.get("month") or None
    return await _call(lambda: service.manual_list(month=month))


async def _manual_add(request: Request) -> Response:
    body = await _body(request)
    return await _call(lambda: service.manual_add(**_manual_add_kwargs(body)))


async def _manual_edit(request: Request) -> Response:
    body = await _body(request)
    tx_id = request.path_params["tx_id"]
    if not isinstance(tx_id, str) or not tx_id:
        raise HTTPException(status_code=400, detail="transaction id is required")
    fields = _manual_edit_fields(body)
    return await _call(lambda: service.manual_edit(tx_id, **fields))


async def _manual_remove(request: Request) -> Response:
    tx_id = request.path_params["tx_id"]
    if not isinstance(tx_id, str) or not tx_id:
        raise HTTPException(status_code=400, detail="transaction id is required")
    return await _call(lambda: service.manual_remove(tx_id))


def _export_file(payload: dict[str, Any]) -> Path:
    data_dir = Path(str(payload.get("data_dir", ""))).resolve()
    path = Path(str(payload.get("path", ""))).resolve()
    exports = (data_dir / "exports").resolve()
    if path.parent != exports or not path.is_file():
        raise PermissionError("export file is outside the exports directory")
    return path


def _limit(raw: str | None) -> int | None:
    if raw is None or raw == "":
        return None
    try:
        value = int(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="limit must be an integer") from exc
    if value <= 0:
        raise HTTPException(status_code=400, detail="limit must be a positive integer")
    return value


def _month(request: Request) -> str:
    month = request.query_params.get("month")
    if not month:
        raise HTTPException(status_code=400, detail="month is required")
    return month


def _global_flag(value: str | None) -> bool:
    if value is None or value in {"", "false", "0"}:
        return False
    if value in {"true", "1"}:
        return True
    raise HTTPException(status_code=400, detail="global must be true or false")


def _as_flag(value: object) -> str | None:
    if value is True:
        return "true"
    if value is False or value is None:
        return "false"
    if isinstance(value, str):
        return value
    raise HTTPException(status_code=400, detail="global must be true or false")


async def _body(request: Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="request body must be JSON") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="request body must be a JSON object")
    return payload


def _rule_kwargs(body: dict[str, Any]) -> dict[str, Any]:
    pattern = _text(body, "pattern", required=True)
    category = _text(body, "category", required=True)
    kind = _text(body, "kind", required=True)
    return {
        "pattern": pattern,
        "category": category,
        "kind": kind,
        "direction": _text(body, "direction") or "any",
        "min_amount": _text(body, "min_amount"),
        "max_amount": _text(body, "max_amount"),
        "currency": _text(body, "currency"),
        "source_kind": _text(body, "source_kind"),
        "needs_review": _bool(body.get("needs_review", False), "needs_review"),
        "note": _text(body, "note") or "",
        "priority": _priority(body.get("priority", 100)),
    }


def _manual_add_kwargs(body: dict[str, Any]) -> dict[str, Any]:
    return {
        "date": _text(body, "date", required=True),
        "amount": _text(body, "amount", required=True),
        "description": _text(body, "description", required=True),
        "currency": _text(body, "currency"),
        "category": _text(body, "category"),
        "kind": _text(body, "kind"),
        "merchant": _text(body, "merchant"),
        "account": _text(body, "account"),
        "note": _text(body, "note") or "",
    }


def _manual_edit_fields(body: dict[str, Any]) -> dict[str, Any]:
    fields = {key: _text(body, key) for key in _MANUAL_EDIT_FIELDS if key in body}
    if not fields:
        raise ValueError("nothing to change: pass at least one field")
    return fields


def _text(body: dict[str, Any], key: str, *, required: bool = False) -> str | None:
    if key not in body or body[key] is None:
        if required:
            raise ValueError(f"{key} is required")
        return None
    value = body[key]
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    if required and not value.strip():
        raise ValueError(f"{key} is required")
    return value


def _bool(value: object, key: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be true or false")
    return value


def _priority(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("priority must be an integer")
    return value


async def _call(fn: Callable[[], dict[str, Any]]) -> JSONResponse:
    return JSONResponse(await run_in_threadpool(fn))


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse({"ok": False, "error": message}, status_code=status)


def _error_handler(code: int) -> Callable[[Request, Exception], Awaitable[JSONResponse]]:
    async def handler(_request: Request, exc: Exception) -> JSONResponse:
        return _error(code, str(exc))

    return handler


async def _http_error(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, HTTPException)
    detail = exc.detail if isinstance(exc.detail, str) else "request failed"
    return _error(exc.status_code, detail)


async def _unhandled(_request: Request, exc: Exception) -> JSONResponse:
    return _error(500, f"{type(exc).__name__}: {exc}")


class _RefuseForeignOrigin:
    """Refuse a browser request sent from any page but the Canhoto page.

    CORS only hides the response. Without this check, another site could still
    send a form or ``text/plain`` POST that changes the ledger. Requests with no
    ``Origin`` header, such as curl, pass.
    """

    def __init__(self, app: ASGIApp, *, page_origin: str) -> None:
        self.app = app
        self.page_origin = page_origin

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            origin = Headers(scope=scope).get("origin")
            if origin is not None and origin != self.page_origin:
                refusal = _error(403, "request origin is not the Canhoto page")
                await refusal(scope, receive, send)
                return
        await self.app(scope, receive, send)
