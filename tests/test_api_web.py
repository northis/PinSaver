"""
Saving an image from any site: the extension's context menu path.

The image is downloaded straight from the link the user right-clicked, marked with the page
it came from, and kept out of the sync back to Pinterest.
"""
from __future__ import annotations

import io
import sqlite3
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

import archive
import models

HEADER = {"X-PinSaver-Request": "1"}
PIN_ID = "4609715820662870592"
PIN_FILE_ID = "28a577052cef6a39e431f87d7f1d5664"
IMAGE_URL = "https://cdn.example.com/cat.png"
PAGE_URL = "https://example.com/post/42"


def png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), "red").save(buffer, "PNG")
    return buffer.getvalue()


@pytest.fixture()
def download(monkeypatch: pytest.MonkeyPatch) -> bytes:
    """The image link answers with a real PNG; anything else is a 404."""
    payload = png_bytes()
    monkeypatch.setattr(
        archive,
        "new_client",
        lambda: httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, content=payload)
                if str(request.url) == IMAGE_URL
                else httpx.Response(404)
            ),
            follow_redirects=True,
        ),
    )
    return payload


def test_image_from_another_site_is_saved(
    client: TestClient, data_dir: Path, download: bytes
) -> None:
    response = client.post(
        "/api/pins/web",
        json={"image_url": IMAGE_URL, "page_url": PAGE_URL},
        headers=HEADER,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "added"
    assert body["pin_id"] == f"web-{body['file_id']}"
    assert body["file_extension"] == "png"
    assert (data_dir / "originals" / f"{body['file_id']}.png").read_bytes() == download

    pin = client.get("/api/pins").json()["pins"][0]
    assert pin["source_url"] == PAGE_URL
    assert pin["pinterest_url"] == ""
    assert pin["original_url"] == IMAGE_URL
    assert pin["image_url"] == f"/images/{body['file_id']}.png"


def test_the_same_image_is_saved_once(
    client: TestClient, data_dir: Path, download: bytes
) -> None:
    first = client.post(
        "/api/pins/web", json={"image_url": IMAGE_URL, "page_url": PAGE_URL}, headers=HEADER
    ).json()
    second = client.post(
        "/api/pins/web", json={"image_url": IMAGE_URL, "page_url": PAGE_URL}, headers=HEADER
    )

    assert second.status_code == 200
    assert second.json()["status"] == "exists"
    assert second.json()["pin_id"] == first["pin_id"]

    conn = sqlite3.connect(models.get_db_path())
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT rating FROM pins").fetchone()
    conn.close()
    assert row["rating"] == 1


def test_sync_leaves_pins_from_other_sites_out(client: TestClient, download: bytes) -> None:
    """The extension repins the ids from /api/pins/sync: a third-party pin has none."""
    client.post(
        "/api/pins/web", json={"image_url": IMAGE_URL, "page_url": PAGE_URL}, headers=HEADER
    )

    conn = sqlite3.connect(models.get_db_path())
    models.insert_pin(
        conn,
        models.Pin(
            pin_id=PIN_ID,
            file_id=PIN_FILE_ID,
            file_extension="jpg",
            pinterest_url=f"https://pinterest.com/pin/{PIN_ID}/",
            original_url=f"https://i.pinimg.com/originals/28/a5/77/{PIN_FILE_ID}.jpg",
            source_date=1,
        ),
    )
    conn.commit()
    conn.close()

    assert client.get("/api/pins/sync").json() == {"pin_ids": [PIN_ID], "total": 1}


def test_a_missing_page_falls_back_to_the_image_link(client: TestClient, download: bytes) -> None:
    """An empty source_url marks a Pinterest pin, so a web pin must never keep it empty."""
    client.post("/api/pins/web", json={"image_url": IMAGE_URL}, headers=HEADER)

    pin = client.get("/api/pins").json()["pins"][0]
    assert pin["source_url"] == IMAGE_URL
    assert client.get("/api/pins/sync").json() == {"pin_ids": [], "total": 0}


def test_a_link_that_is_not_an_image_is_a_400(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        archive,
        "new_client",
        lambda: httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"<html>")),
            follow_redirects=True,
        ),
    )

    response = client.post(
        "/api/pins/web", json={"image_url": IMAGE_URL}, headers=HEADER
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "not_an_image"}


def test_only_http_links_are_downloaded(client: TestClient) -> None:
    """A `file:` link would read the machine the archive runs on."""
    response = client.post(
        "/api/pins/web", json={"image_url": "file:///etc/passwd"}, headers=HEADER
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "invalid_url"}


def test_web_pin_without_the_guard_header_is_rejected(client: TestClient) -> None:
    response = client.post("/api/pins/web", json={"image_url": IMAGE_URL})

    assert response.status_code == 403
