"""Security helpers for untrusted URLs and sanitized provider failures."""

import ipaddress
import socket
from urllib.parse import urljoin, urlsplit


class UnsafeURLError(ValueError):
    """Raised when a URL could reach a non-public network destination."""


def validate_public_url(url: str) -> str:
    """Validate that an HTTP(S) URL resolves only to public IP addresses."""

    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"}:
        raise UnsafeURLError("only HTTP and HTTPS article URLs are allowed")
    if not parsed.hostname:
        raise UnsafeURLError("article URL has no hostname")
    if parsed.username or parsed.password:
        raise UnsafeURLError("article URLs may not contain credentials")

    try:
        addresses = {
            item[4][0]
            for item in socket.getaddrinfo(
                parsed.hostname,
                parsed.port or (443 if parsed.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            )
        }
    except socket.gaierror as error:
        raise UnsafeURLError("article hostname could not be resolved") from error

    if not addresses:
        raise UnsafeURLError("article hostname did not resolve to an address")
    for value in addresses:
        address = ipaddress.ip_address(value)
        if not address.is_global:
            raise UnsafeURLError("article URL resolves to a non-public address")
    return url


def validated_redirect(current_url: str, location: str) -> str:
    """Resolve and validate a redirect target."""

    return validate_public_url(urljoin(current_url, location))
