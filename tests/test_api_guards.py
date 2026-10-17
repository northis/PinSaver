"""
Mutating endpoints need the custom header, and a foreign page must not get through.

A foreign page cannot set `X-PinSaver-Request` (its preflight is rejected by CORS), and a
cross-site browser request always carries an http(s) `Origin` that does not match our host.
The extension and the service worker send `chrome-extension://` or no `Origin` at all, so
they pass. `/api/pins/check` with an empty list is used as the cheapest guarded endpoint:
it touches neither the network nor the database.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

HEADER = {"X-PinSaver-Request": "1"}
BODY = {"pins": []}


def test_missing_header_is_rejected(client: TestClient) -> None:
    response = client.post("/api/pins/check", json=BODY)

    assert response.status_code == 403
    assert "reload the extension" in response.json()["detail"]


def test_cross_site_origin_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/pins/check", json=BODY, headers={**HEADER, "Origin": "https://evil.example"}
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "cross-site request rejected"


def test_same_origin_is_accepted(client: TestClient) -> None:
    response = client.post(
        "/api/pins/check", json=BODY, headers={**HEADER, "Origin": "http://testserver"}
    )

    assert response.status_code == 200
    assert response.json() == {"existing": []}


def test_extension_origin_is_accepted(client: TestClient) -> None:
    response = client.post(
        "/api/pins/check",
        json=BODY,
        headers={
            **HEADER,
            "Origin": "chrome-extension://abcdefghijklmnopabcdefghijklmnop",
            "Sec-Fetch-Site": "cross-site",
        },
    )

    assert response.status_code == 200


def test_forwarded_host_is_used_for_the_origin_check(client: TestClient) -> None:
    """Behind Traefik the public host arrives in X-Forwarded-Host, not in Host."""
    response = client.post(
        "/api/pins/check",
        json=BODY,
        headers={
            **HEADER,
            "Origin": "https://pinsaver.example",
            "X-Forwarded-Host": "pinsaver.example",
        },
    )

    assert response.status_code == 200


def test_origin_host_with_default_port_matches(client: TestClient) -> None:
    """`https://host:443` and `host` must compare equal."""
    response = client.post(
        "/api/pins/check",
        json=BODY,
        headers={
            **HEADER,
            "Origin": "https://pinsaver.example:443",
            "X-Forwarded-Host": "pinsaver.example",
        },
    )

    assert response.status_code == 200


def test_delete_without_header_is_rejected(client: TestClient) -> None:
    response = client.delete("/api/pins/1234567890")

    assert response.status_code == 403
