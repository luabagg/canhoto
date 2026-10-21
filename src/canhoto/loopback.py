"""Loopback checks for the local page and the local API."""

from __future__ import annotations

from urllib.parse import urlsplit

_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def require_loopback(host: str) -> str:
    """Return ``host`` when it is a loopback name."""
    if host not in _HOSTS:
        raise ValueError(f"refused host {host!r}; bind to 127.0.0.1")
    return host


def require_loopback_origin(origin: str) -> str:
    """Return a normalized ``http://loopback:port`` origin."""
    parsed = urlsplit(origin.strip())
    if parsed.scheme != "http" or parsed.hostname not in _HOSTS or parsed.port is None:
        raise ValueError("origin must be http://127.0.0.1:<port>")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("origin must be http://127.0.0.1:<port>")
    if parsed.path not in ("", "/"):
        raise ValueError("origin must be http://127.0.0.1:<port>")
    host = parsed.hostname
    if host == "::1":
        return f"http://[::1]:{parsed.port}"
    return f"http://{host}:{parsed.port}"


def require_port(port: int) -> int:
    """Return ``port`` when it is a TCP port."""
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("port must be between 1 and 65535")
    return port
