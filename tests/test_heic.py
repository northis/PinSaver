"""
HEIC pins must show up in the browser.

Chrome, Firefox and Edge cannot decode HEIC, so a pin saved as `.heic` showed a blank
card while the file itself downloaded fine. The archive converts it to JPEG on the way in,
serves a file stored before 2.7.3 as JPEG, and `convert_heic.py` fixes the files that are
already on disk.

Offline: the HEIC is a committed fixture, every download goes through a mock transport,
and `PINSAVER_DATA_DIR` (see conftest) points `originals/` and the database at a temporary
directory.
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
import convert_heic
import images
import models

PIN_ID = "4609715820662870592"
FILE_ID = "28a577052cef6a39e431f87d7f1d5664"
HEIC_URL = f"https://i.pinimg.com/originals/28/a5/77/{FILE_ID}.heic"
HEIC_AS_JPG_URL = f"https://i.pinimg.com/originals/28/a5/77/{FILE_ID}.jpg"
HEIC_BYTES = (Path(__file__).parent / "fixtures" / "pin_heic.heic").read_bytes()
#: A `ftyp` box that says HEIC with nothing readable after it.
BROKEN_HEIC = b"\x00\x00\x00\x1cftypheic\x00\x00\x00\x00" + b"\x00" * 32


@pytest.fixture()
def conn(data_dir: Path) -> sqlite3.Connection:
    """Connection to the temporary database (the schema is created by `data_dir`)."""
    connection = sqlite3.connect(models.get_db_path())
    connection.row_factory = sqlite3.Row
    yield connection
    connection.close()


def client_with(payload: bytes, url: str) -> httpx.Client:
    """Client that answers `url` with the payload and everything else with a 404."""

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == url:
            return httpx.Response(200, content=payload)
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


def decode(data: bytes) -> Image.Image:
    """Decode an image the way the browser would."""
    return Image.open(io.BytesIO(data))


def test_heic_is_recognized_by_its_bytes() -> None:
    assert images.sniff(HEIC_BYTES) == "heic"
    assert images.sniff(b"\xff\xd8\xff\xe0not-a-real-jpeg") == "jpeg"
    assert images.sniff(b"<html>not an image</html>") is None


def test_saved_heic_is_stored_as_jpeg(conn: sqlite3.Connection, data_dir: Path) -> None:
    result = archive.add_pin_from_url(conn, PIN_ID, HEIC_URL, client_with(HEIC_BYTES, HEIC_URL))

    assert result.status == "added"
    assert result.file_extension == "jpg"
    originals = data_dir / "originals"
    assert (originals / f"{FILE_ID}.jpg").read_bytes()[:3] == b"\xff\xd8\xff"
    # The original is not thrown away: the site shows the JPEG, the archive keeps it.
    assert (originals / f"{FILE_ID}.heic").read_bytes() == HEIC_BYTES

    row = conn.execute("SELECT file_extension, original_url FROM pins").fetchone()
    assert row["file_extension"] == "jpg"
    assert row["original_url"] == HEIC_URL

    with decode((originals / f"{FILE_ID}.jpg").read_bytes()) as converted:
        assert converted.format == "JPEG"
        assert converted.size == (60, 80)


def test_converted_file_on_disk_skips_the_download(
    conn: sqlite3.Connection, data_dir: Path
) -> None:
    """A pin whose JPEG is already on disk is not downloaded again as HEIC."""
    (data_dir / "originals" / f"{FILE_ID}.jpg").write_bytes(b"\xff\xd8\xff\xe0not-a-real-jpeg")

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("nothing should be downloaded")

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    result = archive.add_pin_from_url(conn, PIN_ID, HEIC_URL, client)

    assert result.status == "added"
    assert result.size == "local"
    assert result.file_extension == "jpg"


def test_heic_behind_a_jpg_url_is_converted_too(
    conn: sqlite3.Connection, data_dir: Path
) -> None:
    """The extension of the link is not the format of the bytes: the bytes win."""
    result = archive.add_pin_from_url(
        conn, PIN_ID, HEIC_AS_JPG_URL, client_with(HEIC_BYTES, HEIC_AS_JPG_URL)
    )

    assert result.file_extension == "jpg"
    originals = data_dir / "originals"
    assert (originals / f"{FILE_ID}.jpg").read_bytes()[:3] == b"\xff\xd8\xff"
    assert (originals / f"{FILE_ID}.heic").read_bytes() == HEIC_BYTES


def test_broken_heic_is_still_archived(conn: sqlite3.Connection, data_dir: Path) -> None:
    """A pin that cannot be converted is kept as it came: a blank card beats no pin."""
    result = archive.add_pin_from_url(
        conn, PIN_ID, HEIC_URL, client_with(BROKEN_HEIC, HEIC_URL)
    )

    assert result.status == "added"
    assert result.file_extension == "heic"
    assert (data_dir / "originals" / f"{FILE_ID}.heic").read_bytes() == BROKEN_HEIC


def test_stored_heic_is_served_as_jpeg(client: TestClient, data_dir: Path) -> None:
    (data_dir / "originals" / f"{FILE_ID}.heic").write_bytes(HEIC_BYTES)

    response = client.get(f"/images/{FILE_ID}.heic")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.content[:3] == b"\xff\xd8\xff"
    with decode(response.content) as converted:
        assert converted.format == "JPEG"
        assert converted.size == (60, 80)


def test_jpeg_is_served_untouched(client: TestClient, data_dir: Path) -> None:
    payload = b"\xff\xd8\xff\xe0not-a-real-jpeg"
    (data_dir / "originals" / f"{FILE_ID}.jpg").write_bytes(payload)

    response = client.get(f"/images/{FILE_ID}.jpg")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.content == payload


def test_script_converts_the_existing_archive(
    conn: sqlite3.Connection, data_dir: Path
) -> None:
    originals = data_dir / "originals"
    (originals / f"{FILE_ID}.heic").write_bytes(HEIC_BYTES)
    models.insert_pin(conn, models.Pin(
        pin_id=PIN_ID,
        file_id=FILE_ID,
        file_extension="heic",
        pinterest_url=f"https://pinterest.com/pin/{PIN_ID}/",
        original_url=HEIC_URL,
        source_date=1,
    ))
    conn.commit()

    stats = convert_heic.convert_archive(originals, models.get_db_path())

    assert stats == {
        "converted": 1,
        "skipped": 0,
        "failed": 0,
        "deleted": 0,
        "rows_updated": 1,
    }
    assert (originals / f"{FILE_ID}.jpg").read_bytes()[:3] == b"\xff\xd8\xff"
    # The HEIC stays by default, exactly as a pin saved after 2.7.3 leaves it.
    assert (originals / f"{FILE_ID}.heic").read_bytes() == HEIC_BYTES
    row = conn.execute("SELECT file_extension FROM pins").fetchone()
    assert row["file_extension"] == "jpg"


def test_script_dry_run_changes_nothing(conn: sqlite3.Connection, data_dir: Path) -> None:
    originals = data_dir / "originals"
    (originals / f"{FILE_ID}.heic").write_bytes(HEIC_BYTES)

    stats = convert_heic.convert_archive(originals, models.get_db_path(), dry_run=True)

    assert stats["converted"] == 1
    assert (originals / f"{FILE_ID}.heic").exists()
    assert not (originals / f"{FILE_ID}.jpg").exists()


def test_script_can_delete_the_originals(conn: sqlite3.Connection, data_dir: Path) -> None:
    originals = data_dir / "originals"
    (originals / f"{FILE_ID}.heic").write_bytes(HEIC_BYTES)

    stats = convert_heic.convert_archive(
        originals, models.get_db_path(), keep_originals=False
    )

    assert stats["deleted"] == 1
    assert not (originals / f"{FILE_ID}.heic").exists()
    assert (originals / f"{FILE_ID}.jpg").exists()


def test_script_skips_a_file_that_is_not_heic(data_dir: Path) -> None:
    originals = data_dir / "originals"
    (originals / f"{FILE_ID}.jpg").write_bytes(b"\xff\xd8\xff\xe0not-a-real-jpeg")

    stats = convert_heic.convert_archive(originals, models.get_db_path())

    assert stats["converted"] == 0
    assert (originals / f"{FILE_ID}.jpg").exists()


def test_delete_removes_the_jpeg_and_the_kept_heic(
    client: TestClient, conn: sqlite3.Connection, data_dir: Path
) -> None:
    originals = data_dir / "originals"
    (originals / f"{FILE_ID}.jpg").write_bytes(b"\xff\xd8\xff\xe0not-a-real-jpeg")
    (originals / f"{FILE_ID}.heic").write_bytes(HEIC_BYTES)
    models.insert_pin(conn, models.Pin(
        pin_id=PIN_ID,
        file_id=FILE_ID,
        file_extension="jpg",
        pinterest_url=f"https://pinterest.com/pin/{PIN_ID}/",
        original_url=HEIC_URL,
        source_date=1,
    ))
    conn.commit()

    response = client.delete(
        f"/api/pins/{PIN_ID}?delete_file=true",
        headers={"X-PinSaver-Request": "1"},
    )

    assert response.status_code == 200
    assert response.json()["file_deleted"] is True
    assert not (originals / f"{FILE_ID}.jpg").exists()
    assert not (originals / f"{FILE_ID}.heic").exists()


def test_importer_finds_a_converted_file(data_dir: Path) -> None:
    """A reimport must not skip a pin whose export says HEIC but disk holds JPEG."""
    importer = pytest.importorskip("importer", reason="needs the host tools (bs4)")
    originals = data_dir / "originals"
    (originals / f"{FILE_ID}.jpg").write_bytes(b"\xff\xd8\xff\xe0not-a-real-jpeg")

    assert importer.find_original_extension(originals, FILE_ID, "heic") == "jpg"
    assert importer.find_original_extension(originals, "0" * 32, "heic") is None
