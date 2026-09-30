"""Tests for SSRF guards (url_guard) and the hardened JD URL fetcher."""

import pytest

from app.services.url_guard import validate_public_http_url


# ── Scheme / structure validation ─────────────────────────────────────

def test_rejects_empty_url():
    with pytest.raises(ValueError, match="No URL"):
        validate_public_http_url("")


def test_rejects_non_http_schemes():
    for url in ["ftp://example.com/x", "file:///etc/passwd", "gopher://x.com"]:
        with pytest.raises(ValueError, match="http and https"):
            validate_public_http_url(url)


def test_rejects_missing_hostname():
    with pytest.raises(ValueError, match="no hostname"):
        validate_public_http_url("http:///path")


def test_rejects_oversized_url():
    with pytest.raises(ValueError, match="too long"):
        validate_public_http_url("https://example.com/" + "a" * 3000)


# ── Literal IP hosts ──────────────────────────────────────────────────

@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/x",
        "http://10.1.2.3/x",
        "http://172.16.0.9/x",
        "http://192.168.1.10/x",
        "http://169.254.169.254/latest/meta-data",
        "http://0.0.0.0/x",
        "http://[::1]/x",
        "http://[fe80::1]/x",
        "http://[fd00::1]/x",
    ],
)
def test_rejects_private_and_metadata_ips(url):
    with pytest.raises(ValueError, match="not allowed"):
        validate_public_http_url(url)


def test_allows_public_literal_ip():
    assert validate_public_http_url("http://93.184.216.34/page") == "http://93.184.216.34/page"


# ── Hostname resolution checks ────────────────────────────────────────

def _addrinfo(ip: str):
    import socket

    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 80))]


def test_rejects_hostname_resolving_to_private_ip(monkeypatch):
    def fake_getaddrinfo(host, port):
        return _addrinfo("192.168.0.5")

    monkeypatch.setattr("app.services.url_guard.socket.getaddrinfo", fake_getaddrinfo)
    with pytest.raises(ValueError, match="not allowed"):
        validate_public_http_url("http://internal.example.com/x")


def test_rejects_hostname_resolving_to_metadata_ip(monkeypatch):
    def fake_getaddrinfo(host, port):
        return _addrinfo("169.254.169.254")

    monkeypatch.setattr("app.services.url_guard.socket.getaddrinfo", fake_getaddrinfo)
    with pytest.raises(ValueError, match="not allowed"):
        validate_public_http_url("http://evil.example.com/x")


def test_allows_hostname_resolving_to_public_ip(monkeypatch):
    def fake_getaddrinfo(host, port):
        return _addrinfo("93.184.216.34")

    monkeypatch.setattr("app.services.url_guard.socket.getaddrinfo", fake_getaddrinfo)
    assert validate_public_http_url("http://example.com/x") == "http://example.com/x"


def test_rejects_unresolvable_hostname(monkeypatch):
    import socket

    def fake_getaddrinfo(host, port):
        raise socket.gaierror("nx")

    monkeypatch.setattr("app.services.url_guard.socket.getaddrinfo", fake_getaddrinfo)
    with pytest.raises(ValueError, match="Cannot resolve"):
        validate_public_http_url("http://nope.invalid/x")


# ── fetch_jd_from_url hardening ───────────────────────────────────────

async def test_fetch_rejects_internal_url_before_any_network_call():
    from app.services.jd_service import fetch_jd_from_url

    with pytest.raises(ValueError, match="not allowed"):
        await fetch_jd_from_url("http://127.0.0.1:8000/api/v1/health")


async def test_fetch_rejects_non_http_scheme_before_any_network_call():
    from app.services.jd_service import fetch_jd_from_url

    with pytest.raises(ValueError, match="http and https"):
        await fetch_jd_from_url("file:///etc/passwd")


class _FakeResponse:
    def __init__(self, *, status=200, headers=None, text="", content=None, redirect=False):
        self.status_code = status
        self.headers = headers or {}
        self.text = text
        self.content = content if content is not None else text.encode()
        self.is_redirect = redirect
        self.has_redirect_location = redirect and bool(self.headers.get("location"))

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx

            raise httpx.HTTPStatusError("err", request=None, response=None)


class _FakeClient:
    """Minimal httpx.AsyncClient stand-in recording requested URLs."""

    responses: list = []
    requested: list = []

    def __init__(self, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, headers=None):
        _FakeClient.requested.append(url)
        return _FakeClient.responses.pop(0)


def _patch_dns_to_public(monkeypatch):
    """Avoid real DNS in fetch tests — treat *.example.com as public."""
    monkeypatch.setattr(
        "app.services.url_guard.socket.getaddrinfo",
        lambda host, port: _addrinfo("93.184.216.34"),
    )


async def test_fetch_validates_each_redirect_hop(monkeypatch):
    import app.services.jd_service as jd

    _patch_dns_to_public(monkeypatch)
    monkeypatch.setattr("httpx.AsyncClient", _FakeClient)
    _FakeClient.requested = []
    _FakeClient.responses = [
        _FakeResponse(status=302, redirect=True, headers={"location": "http://169.254.169.254/latest"}),
    ]

    with pytest.raises(ValueError, match="not allowed"):
        await jd.fetch_jd_from_url("https://jobs.example.com/123")


async def test_fetch_follows_valid_redirect_and_extracts_text(monkeypatch):
    import app.services.jd_service as jd

    _patch_dns_to_public(monkeypatch)
    monkeypatch.setattr("httpx.AsyncClient", _FakeClient)
    _FakeClient.requested = []
    _FakeClient.responses = [
        _FakeResponse(status=301, redirect=True, headers={"location": "https://boards.example.com/j/1"}),
        _FakeResponse(
            status=200,
            headers={"content-type": "text/html; charset=utf-8"},
            text="<html><body><h1>Senior Python Engineer</h1><p>We use FastAPI and react.</p></body></html>",
        ),
    ]

    text = await jd.fetch_jd_from_url("https://jobs.example.com/123")
    assert "Senior Python Engineer" in text
    assert _FakeClient.requested == [
        "https://jobs.example.com/123",
        "https://boards.example.com/j/1",
    ]


async def test_fetch_rejects_binary_content_type(monkeypatch):
    import app.services.jd_service as jd

    _patch_dns_to_public(monkeypatch)
    monkeypatch.setattr("httpx.AsyncClient", _FakeClient)
    _FakeClient.requested = []
    _FakeClient.responses = [
        _FakeResponse(status=200, headers={"content-type": "application/octet-stream"}, text="MZ..."),
    ]

    with pytest.raises(ValueError, match="text page"):
        await jd.fetch_jd_from_url("https://example.com/file")
