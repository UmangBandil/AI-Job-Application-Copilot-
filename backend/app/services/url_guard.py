"""URL safety checks for server-side fetching (SSRF protection).

The JD fetch endpoint retrieves arbitrary user-supplied URLs. These guards
block requests aimed at private networks, loopback, link-local, cloud
metadata endpoints, and non-HTTP schemes.

Redirects are followed manually (one validated hop at a time) so that every
destination — including redirect targets — passes the same public-host check.
"""

import ipaddress
import socket
from urllib.parse import urlparse

MAX_URL_LENGTH = 2048
ALLOWED_SCHEMES = {"http", "https"}


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
        or ip in ipaddress.ip_network("169.254.169.254/32")  # cloud metadata
    )


def validate_public_http_url(url: str) -> str:
    """Validate that a URL is a well-formed http(s) URL to a public host.

    Returns the validated URL string; raises ValueError with a clear
    message when the URL must be rejected.
    """
    if not url or not url.strip():
        raise ValueError("No URL provided")

    url = url.strip()
    if len(url) > MAX_URL_LENGTH:
        raise ValueError("URL too long")

    parsed = urlparse(url)
    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        raise ValueError("Only http and https URLs are allowed")
    if not parsed.hostname:
        raise ValueError("URL has no hostname")

    # Literal IP host (e.g. http://127.0.0.1/ or http://[::1]/)
    try:
        ip = ipaddress.ip_address(parsed.hostname)
        if _is_blocked_ip(ip):
            raise ValueError("Requests to private, loopback, or metadata addresses are not allowed")
        return url
    except ValueError as e:
        if "not allowed" in str(e):
            raise
        # Not a literal IP — resolve the hostname and check every address.
        try:
            addr_infos = socket.getaddrinfo(
                parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)
            )
        except socket.gaierror as ge:
            raise ValueError(f"Cannot resolve host: {parsed.hostname}") from ge
        for info in addr_infos:
            addr = info[4][0]
            try:
                ip = ipaddress.ip_address(addr)
            except ValueError:
                continue
            if _is_blocked_ip(ip):
                raise ValueError(
                    "Host resolves to a private, loopback, or metadata address — not allowed"
                )

    return url
