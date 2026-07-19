import socket

import pytest

from biasradar.common.security import (
    UnsafeURLError,
    validate_public_url,
    validated_redirect,
)


def _address(ip: str):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))]


def test_public_url_is_allowed(monkeypatch) -> None:
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda *args, **kwargs: _address("8.8.8.8")
    )

    assert (
        validate_public_url("https://example.com/story") == "https://example.com/story"
    )


@pytest.mark.parametrize(
    "url,ip",
    [
        ("http://localhost/admin", "127.0.0.1"),
        ("http://metadata.internal/", "169.254.169.254"),
        ("https://private.example/", "10.0.0.4"),
    ],
)
def test_non_public_destinations_are_blocked(monkeypatch, url: str, ip: str) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: _address(ip))

    with pytest.raises(UnsafeURLError):
        validate_public_url(url)


def test_redirect_destination_is_revalidated(monkeypatch) -> None:
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda *args, **kwargs: _address("127.0.0.1")
    )

    with pytest.raises(UnsafeURLError):
        validated_redirect("https://example.com/story", "http://localhost/admin")
