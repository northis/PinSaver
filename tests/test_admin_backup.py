"""
The maintenance page and its API: the local-listener gate, the CSRF guard, real zips.

The page can read the database and hand out the whole archive, so it exists only on the
admin listener; every test here uses `admin_client` (which arrives on that port) except the
ones that prove the site listener cannot reach it at all.
"""
from __future__ import annotations

import json
import os
import sqlite3
import zipfile
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import models
import server

HEADER = {"X-PinSaver-Request": "1"}


def write_image(data_dir: Path, name: str, payload: bytes = b"image-bytes") -> Path:
    """Put an original image into the temporary archive."""
    path = data_dir / "originals" / name
    path.write_bytes(payload)
    return path


def add_pin(pin_id: str = "123", file_id: str = "abcdef") -> None:
    """Insert one pin into the temporary database."""
    conn = sqlite3.connect(models.get_db_path())
    try:
        models.insert_pin(conn, models.Pin(
            pin_id=pin_id,
            file_id=file_id,
            file_extension="jpg",
            pinterest_url=f"https://www.pinterest.com/pin/{pin_id}/",
            original_url="https://i.pinimg.com/originals/ab/cd/abcdef.jpg",
            source_date=1700000000,
        ))
        conn.commit()
    finally:
        conn.close()


def read_database(zip_bytes: bytes, dest: Path) -> sqlite3.Connection:
    """Open the database a backup carries, from a copy written next to the archive."""
    with zipfile.ZipFile(BytesIO(zip_bytes)) as archive:
        dest.write_bytes(archive.read("pinterest_archive.db"))

    conn = sqlite3.connect(dest)
    conn.row_factory = sqlite3.Row
    return conn


def test_site_listener_has_no_admin_at_all(client: TestClient) -> None:
    """On the site's own port the maintenance page does not exist (404, not 403)."""
    for path in ("/admin", "/api/admin/state", "/api/admin/backups", "/api/admin/backup/full"):
        assert client.get(path).status_code == 404

    assert client.post("/api/admin/backup", headers=HEADER).status_code == 404


def test_host_header_does_not_open_the_admin(client: TestClient) -> None:
    """The guard reads the port of the socket, so a claimed host changes nothing."""
    response = client.get("/api/admin/state", headers={"Host": f"127.0.0.1:{server.ADMIN_PORT}"})

    assert response.status_code == 404


def test_admin_page_renders(admin_client: TestClient) -> None:
    response = admin_client.get("/admin")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert 'id="admin"' in response.text
    assert "/static/admin.css?v=" in response.text
    assert "/static/admin.js?v=" in response.text


def test_state_reports_the_archive(admin_client: TestClient, data_dir: Path) -> None:
    write_image(data_dir, "abcdef.jpg", b"x" * 100)
    add_pin()

    state = admin_client.get("/api/admin/state").json()

    assert state["pins"] == {"total": 1, "active": 1, "deleted": 0}
    assert state["originals"]["files"] == 1
    assert state["originals"]["bytes"] == 100
    assert state["database"]["bytes"] > 0
    assert state["backups"]["count"] == 0
    assert state["backups"]["last_backup_utc"] is None
    assert state["admin_port"] == server.ADMIN_PORT
    assert state["database"]["path"] == str(models.get_db_path())
    assert state["backups"]["path"] == str(data_dir / "backups")


def test_state_counts_deleted_pins(admin_client: TestClient) -> None:
    add_pin(pin_id="123", file_id="abcdef")
    add_pin(pin_id="456", file_id="fedcba")
    conn = sqlite3.connect(models.get_db_path())
    try:
        conn.execute("UPDATE pins SET is_deleted = 1 WHERE pin_id = '456'")
        conn.commit()
    finally:
        conn.close()

    pins = admin_client.get("/api/admin/state").json()["pins"]

    assert pins == {"total": 2, "active": 1, "deleted": 1}


def test_full_backup_streams_database_and_every_image(admin_client: TestClient,
                                                      data_dir: Path) -> None:
    write_image(data_dir, "abcdef.jpg")
    write_image(data_dir, "012345.png", b"second-image")
    add_pin()

    response = admin_client.get("/api/admin/backup/full")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    disposition = response.headers["content-disposition"]
    assert disposition.startswith('attachment; filename="pinsaver_full_')
    assert disposition.endswith('.zip"')
    assert response.headers["cache-control"] == "no-store"

    with zipfile.ZipFile(BytesIO(response.content)) as archive:
        assert archive.testzip() is None
        assert sorted(archive.namelist()) == [
            "originals/012345.png", "originals/abcdef.jpg", "pinterest_archive.db"
        ]
        assert archive.read("originals/abcdef.jpg") == b"image-bytes"

    conn = read_database(response.content, data_dir / "restored.db")
    try:
        assert conn.execute("SELECT pin_id FROM pins").fetchone()["pin_id"] == "123"
    finally:
        conn.close()


def test_full_backup_needs_no_previous_backup_and_writes_nothing(admin_client: TestClient,
                                                                 data_dir: Path) -> None:
    """The streamed archive is built on the fly: backups/ stays empty and no temp files stay."""
    write_image(data_dir, "abcdef.jpg")

    assert admin_client.get("/api/admin/backup/full").status_code == 200

    assert not (data_dir / "backups").exists()


def test_incremental_backup_creates_and_serves_a_zip(admin_client: TestClient,
                                                     data_dir: Path) -> None:
    write_image(data_dir, "abcdef.jpg")
    add_pin()

    created = admin_client.post("/api/admin/backup", headers=HEADER)

    assert created.status_code == 200
    assert created.json()["status"] == "created"
    result = created.json()["backup"]
    assert result["name"].startswith("backup_") and result["name"].endswith(".zip")
    assert result["originals"] == 1
    assert result["database"] is True
    assert result["previous_backup_utc"] is None

    zip_path = data_dir / "backups" / result["name"]
    assert zip_path.is_file()
    assert result["bytes"] == zip_path.stat().st_size

    with zipfile.ZipFile(zip_path) as archive:
        assert sorted(archive.namelist()) == ["originals/abcdef.jpg", "pinterest_archive.db"]

    state = admin_client.get("/api/admin/state").json()
    assert state["backups"]["count"] == 1
    assert state["backups"]["last_backup_utc"] == result["created_utc"]
    assert state["backups"]["bytes"] == result["bytes"]

    state_file = json.loads((data_dir / "backups" / "backup_state.json").read_text(encoding="utf-8"))
    assert state_file["last_backup_zip"] == result["name"]

    listing = admin_client.get("/api/admin/backups").json()["backups"]
    assert [item["name"] for item in listing] == [result["name"]]

    download = admin_client.get(f"/api/admin/backups/{result['name']}")
    assert download.status_code == 200
    assert download.headers["content-type"] == "application/zip"
    assert download.headers["content-disposition"] == f'attachment; filename="{result["name"]}"'
    assert download.content == zip_path.read_bytes()


def test_incremental_backup_takes_only_images_changed_since_the_last_one(
        admin_client: TestClient, data_dir: Path) -> None:
    old_image = write_image(data_dir, "abcdef.jpg", b"old")
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).timestamp()
    os.utime(old_image, (yesterday, yesterday))

    first = admin_client.post("/api/admin/backup", headers=HEADER).json()["backup"]
    write_image(data_dir, "012345.png", b"fresh")
    second = admin_client.post("/api/admin/backup", headers=HEADER).json()["backup"]

    assert first["originals"] == 1
    assert second["originals"] == 1
    assert second["previous_backup_utc"] == first["created_utc"]
    assert second["name"] != first["name"]

    with zipfile.ZipFile(data_dir / "backups" / second["name"]) as archive:
        assert sorted(archive.namelist()) == ["originals/012345.png", "pinterest_archive.db"]


def test_backup_list_is_newest_first(admin_client: TestClient, data_dir: Path) -> None:
    backups_dir = data_dir / "backups"
    backups_dir.mkdir()
    for index, name in enumerate(("backup_20260101_010101.zip", "backup_20260202_020202.zip")):
        path = backups_dir / name
        path.write_bytes(b"zip")
        os.utime(path, (1700000000 + index * 60, 1700000000 + index * 60))

    listing = admin_client.get("/api/admin/backups").json()["backups"]

    assert [item["name"] for item in listing] == [
        "backup_20260202_020202.zip", "backup_20260101_010101.zip"
    ]
    assert listing[0]["bytes"] == 3
    assert listing[0]["created_utc"].startswith("2023-11-14T")


def test_backup_run_needs_the_csrf_header(admin_client: TestClient) -> None:
    assert admin_client.post("/api/admin/backup").status_code == 403


def test_only_one_backup_runs_at_a_time(admin_client: TestClient) -> None:
    assert server.BACKUP_LOCK.acquire(blocking=False)
    try:
        response = admin_client.post("/api/admin/backup", headers=HEADER)
    finally:
        server.BACKUP_LOCK.release()

    assert response.status_code == 409
    assert "already running" in response.json()["detail"]


@pytest.mark.parametrize("name", [
    "backup_state.json",
    "nothing.zip",
    "..%5c..%5c.env",
    "..%2f..%2f.env",
    "%2e%2e%5c%2e%2e%5c.env",
    "backup_20260101_010101.zip.exe",
])
def test_backup_download_serves_only_backup_zips(admin_client: TestClient, data_dir: Path,
                                                 name: str) -> None:
    """A decoy next to the backups must stay unreadable, and only zips are served."""
    (data_dir / ".env").write_text("PINSAVER_SECRET=must-not-leak", encoding="utf-8")
    backups_dir = data_dir / "backups"
    backups_dir.mkdir()
    (backups_dir / "backup_state.json").write_text("{}", encoding="utf-8")

    response = admin_client.get(f"/api/admin/backups/{name}")

    assert response.status_code == 404
    assert "must-not-leak" not in response.text
