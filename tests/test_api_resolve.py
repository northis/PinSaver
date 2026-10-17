"""
`POST /api/pins/resolve`: save a pin by its link, offline.

The two network calls the endpoint makes are both stubbed: `server.resolve_pin` (the pin page)
and `archive.new_client` (the image download). Everything else - link parsing, the guard, the
shared add path, the status codes - is the real code.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

import archive
import models
import pinterest
import server

PIN_ID = "4609715820662870592"
FILE_ID = "28a577052cef6a39e431f87d7f1d5664"
ORIGINAL_URL = f"https://i.pinimg.com/originals/28/a5/77/{FILE_ID}.jpg"
LINK = f"https://www.pinterest.com/pin/{PIN_ID}/"
HEADER = {"X-PinSaver-Request": "1"}
PAYLOAD = b"\xff\xd8\xff\xe0not-a-real-jpeg"


@pytest.fixture()
def resolved(monkeypatch: pytest.MonkeyPatch) -> None:
    """The pin page answers with our pin, the image download answers with bytes."""
    monkeypatch.setattr(
        server,
        "resolve_pin",
        lambda pin_id: pinterest.ResolvedPin(pin_id, FILE_ID, "jpg", ORIGINAL_URL, False),
    )
    monkeypatch.setattr(
        archive,
        "new_client",
        lambda: httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, content=PAYLOAD)
                if str(request.url) == ORIGINAL_URL
                else httpx.Response(404)
            ),
            follow_redirects=True,
        ),
    )


def test_pin_is_saved_by_link(client: TestClient, resolved: None, data_dir: Path) -> None:
    response = client.post("/api/pins/resolve", json={"url": LINK}, headers=HEADER)

    assert response.status_code == 200
    assert response.json() == {
        "status": "added",
        "pin_id": PIN_ID,
        "file_id": FILE_ID,
        "size": "orig",
        "message": f"Pin {PIN_ID} added to archive",
    }
    assert (data_dir / "originals" / f"{FILE_ID}.jpg").read_bytes() == PAYLOAD
    assert models.get_db_path().is_file()


def test_saving_the_same_link_twice_only_raises_the_rating(
    client: TestClient, resolved: None
) -> None:
    client.post("/api/pins/resolve", json={"url": LINK}, headers=HEADER)

    response = client.post("/api/pins/resolve", json={"url": LINK}, headers=HEADER)

    assert response.status_code == 200
    assert response.json()["status"] == "exists"

    connection = sqlite3.connect(models.get_db_path())
    try:
        rating = connection.execute("SELECT rating FROM pins").fetchone()[0]
        rows = connection.execute("SELECT COUNT(*) FROM pins").fetchone()[0]
    finally:
        connection.close()

    assert (rating, rows) == (1, 1)


def test_the_link_is_found_among_the_share_fields(client: TestClient, resolved: None) -> None:
    """Android sends the link in `text` and the pin's title in `title`: neither is a link alone."""
    response = client.post(
        "/api/pins/resolve",
        json={"url": "", "text": LINK, "title": "Cabelo bonito"},
        headers=HEADER,
    )

    assert response.status_code == 200
    assert response.json()["pin_id"] == PIN_ID


def test_the_glued_payload_of_an_older_worker_is_understood(
    client: TestClient, resolved: None
) -> None:
    """An install that has not picked up the new worker sends link and title in one `url`."""
    response = client.post(
        "/api/pins/resolve", json={"url": f"{LINK} Cabelo bonito"}, headers=HEADER
    )

    assert response.status_code == 200
    assert response.json()["pin_id"] == PIN_ID


def test_the_url_field_beats_a_link_in_the_text(client: TestClient, resolved: None) -> None:
    response = client.post(
        "/api/pins/resolve",
        json={"url": LINK, "text": "https://www.pinterest.com/pin/1234567890/", "title": ""},
        headers=HEADER,
    )

    assert response.status_code == 200
    assert response.json()["pin_id"] == PIN_ID


def test_not_a_pin_link_is_a_400(client: TestClient) -> None:
    response = client.post(
        "/api/pins/resolve", json={"url": "https://example.com/holiday-photo"}, headers=HEADER
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "not_a_pin_link"}


@pytest.mark.parametrize(
    ("reason", "status"),
    [("pin_not_found", 404), ("pinterest_unavailable", 502), ("image_unavailable", 502)],
)
def test_lookup_failures_are_mapped(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, reason: str, status: int
) -> None:
    def fail(pin_id: str) -> pinterest.ResolvedPin:
        raise pinterest.PinLookupError(reason, "stubbed")

    monkeypatch.setattr(server, "resolve_pin", fail)

    response = client.post("/api/pins/resolve", json={"url": LINK}, headers=HEADER)

    assert response.status_code == status
    assert response.json() == {"detail": reason}


def test_image_failure_is_a_502(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        server,
        "resolve_pin",
        lambda pin_id: pinterest.ResolvedPin(pin_id, FILE_ID, "jpg", ORIGINAL_URL, False),
    )
    monkeypatch.setattr(
        archive,
        "new_client",
        lambda: httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(404)),
            follow_redirects=True,
        ),
    )

    response = client.post("/api/pins/resolve", json={"url": LINK}, headers=HEADER)

    assert response.status_code == 502
    assert response.json() == {"detail": "image_unavailable"}


def test_guard_applies_to_resolve(client: TestClient) -> None:
    response = client.post("/api/pins/resolve", json={"url": LINK})

    assert response.status_code == 403
