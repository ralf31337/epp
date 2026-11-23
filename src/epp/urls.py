"""Public base URL detection, so generated links work behind reverse proxies and sub-paths.

Precedence: EPP_PUBLIC_URL, then the proxy headers of the current request (RFC 7239 Forwarded,
X-Forwarded-Proto/-Host/-Port/-Prefix), then the plain request. Background jobs (webhooks) use
EPP_PUBLIC_URL or the base URL of the most recent browser/API request.
"""

from contextvars import ContextVar

_current: ContextVar[str | None] = ContextVar("epp_public_base", default=None)
_last_seen: str | None = None
_configured: str | None = None

DEFAULT_PORTS = {"http": "80", "https": "443"}


def configure(public_url: str | None) -> None:
    global _configured
    _configured = public_url.rstrip("/") if public_url else None


def base_url() -> str | None:
    """Public base URL without trailing slash, e.g. "https://example.org/epp"."""
    return _configured or _current.get() or _last_seen


def _first(value: str | None) -> str | None:
    return value.split(",")[0].strip() if value else None


def _parse_forwarded(value: str | None) -> dict[str, str]:
    """First element of an RFC 7239 Forwarded header, e.g. 'for=1.2.3.4;proto=https;host=x'."""
    out: dict[str, str] = {}
    for pair in (_first(value) or "").split(";"):
        key, _, val = pair.partition("=")
        if val:
            out[key.strip().lower()] = val.strip().strip('"')
    return out


def _headers(scope) -> dict[str, str]:
    return {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}


class ForwardedMiddleware:
    """Applies proxy headers to the ASGI scope (scheme, host, root_path) and records the public base URL."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        global _last_seen
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)

        headers = _headers(scope)
        fwd = _parse_forwarded(headers.get("forwarded"))
        scheme = (fwd.get("proto") or _first(headers.get("x-forwarded-proto")) or scope.get("scheme", "http")).lower()
        host = fwd.get("host") or _first(headers.get("x-forwarded-host")) or headers.get("host")
        port = _first(headers.get("x-forwarded-port"))
        if host and port and ":" not in host.rsplit("]", 1)[-1] and DEFAULT_PORTS.get(scheme) != port:
            host = f"{host}:{port}"
        prefix = (_first(headers.get("x-forwarded-prefix")) or "").rstrip("/")
        if prefix and not prefix.startswith("/"):
            prefix = "/" + prefix

        scope = dict(scope)
        if scope["type"] == "http":
            scope["scheme"] = scheme
        elif scheme in ("http", "https"):
            scope["scheme"] = "wss" if scheme == "https" else "ws"
        scope["root_path"] = prefix + scope.get("root_path", "")
        if host:
            scope["headers"] = [(k, v) for k, v in scope.get("headers", []) if k.lower() != b"host"] + [
                (b"host", host.encode("latin-1"))
            ]

        base = f"{scheme}://{host}{scope['root_path']}".rstrip("/") if host else None
        token = _current.set(base)
        if base and scope.get("path") != "/health":
            _last_seen = base
        try:
            await self.app(scope, receive, send)
        finally:
            _current.reset(token)
