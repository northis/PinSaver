"""
Adding pins to the archive: dedupe, restore, and the download fallbacks.

No network and no real archive: every download goes through a mock transport, and
`PINSAVER_DATA_DIR` (see conftest) points `originals/` and the database at a temporary
directory.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Callable

import httpx
import pytest

import archive
import models

PIN_ID = "4609715820662870592"
OTHER_PIN_ID = "1146236542703035354"
FILE_ID = "28a577052cef6a39e431f87d7f1d5664"
ORIGINAL_URL = f"https://i.pinimg.com/originals/28/a5/77/{FILE_ID}.jpg"
SIZED_URL = f"https://i.pinimg.com/736x/28/a5/77/{FILE_ID}.jpg"
PAYLOAD = b"\xff\xd8\xff\xe0not-a-real-jpeg"


@pytest.fixture()
def conn(data_dir: Path) -> sqlite3.Connection:
    """Connection to the temporary database, schema created."""
    models.init_db()
    connection = sqlite3.connect(models.get_db_path())
    connection.row_factory = sqlite3.Row
    yield connection
    connection.close()


def client_with(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


def only_original(request: httpx.Request) -> httpx.Response:
    """Everything but the original is missing."""
    if str(request.url) == ORIGINAL_URL:
        return httpx.Response(200, content=PAYLOAD)
    return httpx.Response(404)


def test_pin_is_added(conn: sqlite3.Connection, data_dir: Path) -> None:
    result = archive.add_pin_from_url(conn, PIN_ID, ORIGINAL_URL, client_with(only_original))

    assert result.status == "added"
    assert result.file_id == FILE_ID
    assert result.file_extension == "jpg"
    assert result.size == "orig"
    assert (data_dir / "originals" / f"{FILE_ID}.jpg").read_bytes() == PAYLOAD
    row = conn.execute("SELECT pin_id, original_url, rating FROM pins").fetchone()
    assert row["pin_id"] == PIN_ID
    assert row["original_url"] == ORIGINAL_URL
    assert row["rating"] == 0


def test_second_save_raises_the_rating(conn: sqlite3.Connection) -> None:
    client = client_with(only_original)
    archive.add_pin_from_url(conn, PIN_ID, ORIGINAL_URL, client)

    result = archive.add_pin_from_url(conn, PIN_ID, ORIGINAL_URL, client)

    assert result.status == "exists"
    assert result.message == f"Pin {PIN_ID} already exists in archive (rating +1)"
    assert conn.execute("SELECT rating FROM pins").fetchone()["rating"] == 1
    assert conn.execute("SELECT COUNT(*) AS n FROM pins").fetchone()["n"] == 1


def test_same_image_under_another_pin_raises_the_rating(conn: sqlite3.Connection) -> None:
    client = client_with(only_original)
    archive.add_pin_from_url(conn, PIN_ID, ORIGINAL_URL, client)

    result = archive.add_pin_from_url(conn, OTHER_PIN_ID, ORIGINAL_URL, client)

    assert result.status == "exists"
    assert f"pin {PIN_ID}" in result.message
    assert conn.execute("SELECT rating FROM pins").fetchone()["rating"] == 1
    assert conn.execute("SELECT COUNT(*) AS n FROM pins").fetchone()["n"] == 1


def test_deleted_pin_is_restored_without_rating_bump(conn: sqlite3.Connection) -> None:
    client = client_with(only_original)
    archive.add_pin_from_url(conn, PIN_ID, ORIGINAL_URL, client)
    conn.execute("UPDATE pins SET is_deleted = 1, rating = 3")
    conn.commit()

    result = archive.add_pin_from_url(conn, OTHER_PIN_ID, ORIGINAL_URL, client)

    assert result.status == "restored"
    assert result.message == f"Pin restored with new ID {OTHER_PIN_ID} (was {PIN_ID})"
    row = conn.execute("SELECT pin_id, is_deleted, rating FROM pins").fetchone()
    assert row["pin_id"] == OTHER_PIN_ID
    assert row["is_deleted"] == 0
    assert row["rating"] == 3


def test_missing_original_falls_back_to_a_size(conn: sqlite3.Connection, data_dir: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == SIZED_URL:
            return httpx.Response(200, content=PAYLOAD)
        return httpx.Response(403)

    result = archive.add_pin_from_url(conn, PIN_ID, ORIGINAL_URL, client_with(handler))

    assert result.status == "added"
    assert result.size == "736x"
    assert result.image_url == SIZED_URL
    assert (data_dir / "originals" / f"{FILE_ID}.jpg").read_bytes() == PAYLOAD
    assert conn.execute("SELECT original_url FROM pins").fetchone()["original_url"] == SIZED_URL


def test_file_already_on_disk_skips_the_download(conn: sqlite3.Connection, data_dir: Path) -> None:
    (data_dir / "originals" / f"{FILE_ID}.jpg").write_bytes(PAYLOAD)

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("nothing should be downloaded")

    result = archive.add_pin_from_url(conn, PIN_ID, ORIGINAL_URL, client_with(handler))

    assert result.status == "added"
    assert result.size == "local"
    assert conn.execute("SELECT COUNT(*) AS n FROM pins").fetchone()["n"] == 1


def test_url_without_a_file_id_is_rejected(conn: sqlite3.Connection) -> None:
    with pytest.raises(archive.AddPinError) as error:
        archive.add_pin_from_url(conn, PIN_ID, "https://example.com/nope.jpg")

    assert error.value.reason == "invalid_url"


def test_all_candidates_failing_is_reported(conn: sqlite3.Connection) -> None:
    client = client_with(lambda request: httpx.Response(404, text="gone"))

    with pytest.raises(archive.AddPinError) as error:
        archive.add_pin_from_url(conn, PIN_ID, ORIGINAL_URL, client)

    assert error.value.reason == "image_unavailable"
    assert conn.execute("SELECT COUNT(*) AS n FROM pins").fetchone()["n"] == 0


def test_candidate_order_starts_with_the_page_url() -> None:
    urls = [url for url, _, _ in archive.candidates(FILE_ID, "webp", ORIGINAL_URL)]

    assert urls[0] == ORIGINAL_URL
    assert f"https://i.pinimg.com/originals/28/a5/77/{FILE_ID}.webp" in urls
    assert f"https://i.pinimg.com/236x/28/a5/77/{FILE_ID}.jpg" in urls
    assert len(urls) == len(set(urls))
