"""
Tests for HTTP security headers, documentation disabling, and reverse proxy IP resolution.
"""

import pytest
from gateway.src.main import app
from httpx import ASGITransport, AsyncClient
from tollgate_core.security import resolve_client_ip


@pytest.mark.asyncio
async def test_http_security_headers_present():
    """Verify essential security headers are attached to API responses."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/healthz")
        assert resp.status_code == 200

        # Validate security headers
        assert resp.headers.get("x-content-type-options") == "nosniff"
        assert resp.headers.get("x-frame-options") == "DENY"
        assert resp.headers.get("referrer-policy") == "strict-origin-when-cross-origin"
        assert "default-src 'self'" in resp.headers.get("content-security-policy", "")
        assert "frame-ancestors 'none'" in resp.headers.get("content-security-policy", "")


@pytest.mark.asyncio
async def test_hsts_header_on_https_forwarded():
    """Verify Strict-Transport-Security is emitted only when HTTPS is signaled."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Standard HTTP - HSTS should NOT be sent
        resp_http = await client.get("/healthz")
        assert "strict-transport-security" not in resp_http.headers

        # Forwarded HTTPS - HSTS should be present
        resp_https = await client.get("/healthz", headers={"X-Forwarded-Proto": "https"})
        assert "strict-transport-security" in resp_https.headers
        assert "max-age=31536000" in resp_https.headers["strict-transport-security"]


def test_resolve_client_ip_anti_spoofing():
    """Verify that client IP resolution resists header spoofing from untrusted callers."""
    trusted = ["127.0.0.1", "10.0.0.1"]

    # 1. Untrusted direct client sends spoofed X-Forwarded-For
    untrusted_peer = "198.51.100.5"
    spoofed_xff = "203.0.113.195, 10.0.0.1"
    resolved = resolve_client_ip(
        untrusted_peer, x_forwarded_for=spoofed_xff, trusted_proxies=trusted
    )
    # Since peer is untrusted, XFF MUST be ignored
    assert resolved == untrusted_peer

    # 2. Trusted proxy forwards single client hop
    proxy_peer = "10.0.0.1"
    legit_xff = "203.0.113.195"
    resolved = resolve_client_ip(proxy_peer, x_forwarded_for=legit_xff, trusted_proxies=trusted)
    assert resolved == "203.0.113.195"

    # 3. Chained proxies: client -> untrusted spoofed hop -> edge proxy -> Tollgate
    # Header: "spoofed_ip, 203.0.113.50, 10.0.0.1"
    chain_xff = "1.2.3.4, 203.0.113.50, 10.0.0.1"
    resolved = resolve_client_ip(proxy_peer, x_forwarded_for=chain_xff, trusted_proxies=trusted)
    # The rightmost non-trusted IP should be 203.0.113.50
    assert resolved == "203.0.113.50"
