"""
Restoring image files that are missing from `originals/`.

No network and no real archive: the download goes through a mock transport and
`PINSAVER_DATA_DIR` (see conftest) points `originals/` and the database at a temporary
directory.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Callable

import httpx

import models
import repair_images

FILE_ID = "28a577052cef6a39e431f87d7f1d5664"
ORIGINAL_URL = f"https://i.pinimg.com/originals/28/a5/77/{FILE_ID}.jpg"
PAYLOAD = b"\xff\xd8\xff\xe0not-a-real-jpeg"


def add_row(data_dir: Path, extension: str = "jpg", original_url: str = ORIGINAL_URL) -> None:
    conn = sqlite3.connect(models.get_db_path())
    conn.execute(
        "INSERT INTO pins (pin_id, file_id, file_extension, pinterest_url, original_url,"
        " source_date) VALUES (?, ?, ?, '', ?, 0)",
        (f"pin-{extension}", FILE_ID, extension, original_url),
    )
    conn.commit()
    conn.close()


def client_with(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


def respond_with_payload(request: httpx.Request) -> httpx.Response:
    assert str(request.url) == ORIGINAL_URL
    return httpx.Response(200, content=PAYLOAD)


def repair(data_dir: Path, client: httpx.Client, dry_run: bool = False) -> dict:
    return repair_images.repair_archive(
        data_dir / "originals", models.get_db_path(), dry_run=dry_run, client=client
    )


def test_missing_file_is_downloaded(data_dir: Path) -> None:
    add_row(data_dir)

    stats = repair(data_dir, client_with(respond_with_payload))

    assert stats["missing"] == 1
    assert stats["repaired"] == 1
    assert stats["failed"] == 0
    assert (data_dir / "originals" / f"{FILE_ID}.jpg").read_bytes() == PAYLOAD


def test_file_on_disk_is_not_downloaded(data_dir: Path) -> None:
    add_row(data_dir)
    (data_dir / "originals" / f"{FILE_ID}.jpg").write_bytes(PAYLOAD)

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("nothing should be downloaded")

    stats = repair(data_dir, client_with(handler))

    assert stats["pins"] == 1
    assert stats["missing"] == 0


def test_dry_run_writes_nothing(data_dir: Path) -> None:
    add_row(data_dir)

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("nothing should be downloaded")

    stats = repair(data_dir, client_with(handler), dry_run=True)

    assert stats["missing"] == 1
    assert not (data_dir / "originals" / f"{FILE_ID}.jpg").exists()


def test_format_of_the_bytes_wins_over_the_row(data_dir: Path) -> None:
    add_row(data_dir, extension="png")

    stats = repair(data_dir, client_with(respond_with_payload))

    assert stats["rows_updated"] == 1
    assert (data_dir / "originals" / f"{FILE_ID}.jpg").read_bytes() == PAYLOAD
    conn = sqlite3.connect(models.get_db_path())
    try:
        row = conn.execute("SELECT file_extension FROM pins").fetchone()
    finally:
        conn.close()
    assert row[0] == "jpg"


def test_unreachable_image_is_counted_as_failed(data_dir: Path) -> None:
    add_row(data_dir)

    stats = repair(data_dir, client_with(lambda request: httpx.Response(404)))

    assert stats["missing"] == 1
    assert stats["failed"] == 1
    assert stats["repaired"] == 0
    assert not (data_dir / "originals" / f"{FILE_ID}.jpg").exists()
