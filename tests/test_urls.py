import asyncio

from epp import urls


def call(headers: dict[str, str], path: str = "/api/letters", scheme: str = "http") -> dict:
    seen: dict = {}

    async def app(scope, receive, send):
        seen["scope"] = scope
        seen["base"] = urls.base_url()

    scope = {
        "type": "http", "scheme": scheme, "path": path, "root_path": "",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
    }
    asyncio.run(urls.ForwardedMiddleware(app)(scope, None, None))
    return seen


def test_plain_request():
    assert call({"host": "nas:3081"})["base"] == "http://nas:3081"


def test_x_forwarded_with_prefix():
    seen = call({"host": "epp:3081", "x-forwarded-proto": "https", "x-forwarded-host": "school.example.org",
                 "x-forwarded-prefix": "/epp/"})
    assert seen["base"] == "https://school.example.org/epp"
    assert seen["scope"]["scheme"] == "https"
    assert seen["scope"]["root_path"] == "/epp"


def test_x_forwarded_port_and_chain():
    seen = call({"host": "epp:3081", "x-forwarded-proto": "https, http",
                 "x-forwarded-host": "example.org", "x-forwarded-port": "8443"})
    assert seen["base"] == "https://example.org:8443"
    assert call({"host": "epp", "x-forwarded-proto": "https", "x-forwarded-host": "example.org",
                 "x-forwarded-port": "443"})["base"] == "https://example.org"


def test_rfc7239_forwarded():
    seen = call({"host": "epp:3081", "forwarded": 'for=1.2.3.4;proto=https;host="cal.example.org", for=5.6.7.8'})
    assert seen["base"] == "https://cal.example.org"


def test_configured_public_url_wins():
    urls.configure("https://fixed.example.org/x/")
    try:
        assert call({"host": "nas:3081", "x-forwarded-host": "other"})["base"] == "https://fixed.example.org/x"
    finally:
        urls.configure(None)


def test_last_seen_for_background_jobs_ignores_health():
    call({"host": "a.example:3081"})
    call({"host": "127.0.0.1:3081"}, path="/health")
    assert urls.base_url() == "http://a.example:3081"
