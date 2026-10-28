"""
`/images/{filename}` must not let a request escape `originals/`.

On Windows the backslash is a path separator, and `%5c` travels through the router as
an ordinary path segment: `/images/..%5c.env` reached the repository's `.env` and
`/images/..%5cpinterest_archive.db` the whole database. The decoy files below exist on
purpose, so a 404 can only come from the guard and not from a missing file.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

TRAVERSAL_PATHS = [
    "/images/..%5c.env",
    "/images/..%5cpinterest_archive.db",
    "/images/..%5c..%5c.env",
    "/images/..%5c..%5c..%5c..%5cWindows%5cwin.ini",
    "/images/..%2f..%2f.env",
    "/images/%2e%2e%2f%2e%2e%2f.env",
    "/images/....//.env",
]


@pytest.fixture()
def decoys(data_dir: Path) -> Path:
    """Files one level above originals/: the traversal targets that must stay unreadable."""
    (data_dir / ".env").write_text("PINSAVER_SECRET=must-not-leak", encoding="utf-8")
    (data_dir / "pinterest_archive.db").write_bytes(b"SQLite format 3\x00")
    return data_dir


@pytest.mark.parametrize("path", TRAVERSAL_PATHS)
def test_traversal_is_rejected(client: TestClient, decoys: Path, path: str) -> None:
    response = client.get(path)

    assert response.status_code == 404
    assert "must-not-leak" not in response.text


def test_missing_image_is_a_404(client: TestClient) -> None:
    response = client.get("/images/does-not-exist.jpg")

    assert response.status_code == 404
    assert response.json() == {"detail": "image not found"}


def test_image_is_served_from_originals(client: TestClient, data_dir: Path) -> None:
    payload = b"\xff\xd8\xff\xe0not-a-real-jpeg"
    (data_dir / "originals" / "0123456789abcdef.jpg").write_bytes(payload)

    response = client.get("/images/0123456789abcdef.jpg")

    assert response.status_code == 200
    assert response.content == payload


#: Files that can end up in `originals/` by accident: the route used to hand them out.
NON_IMAGE_NAMES = [
    "pinterest_archive.db",
    "notes.txt",
    "backup.zip",
    "backup_state.json",
    ".env",
]


@pytest.mark.parametrize("name", NON_IMAGE_NAMES)
def test_non_image_file_is_not_served(
    client: TestClient, data_dir: Path, name: str
) -> None:
    (data_dir / "originals" / name).write_bytes(b"SQLite format 3\x00must-not-leak")

    response = client.get(f"/images/{name}")

    assert response.status_code == 404
    assert response.json() == {"detail": "image not found"}
    assert "must-not-leak" not in response.text


def test_an_image_name_with_broken_bytes_is_still_served(
    client: TestClient, data_dir: Path
) -> None:
    """The extension only gates access; a broken download still downloads."""
    payload = b"not-really-a-jpeg"
    (data_dir / "originals" / "0123456789abcdef.jpg").write_bytes(payload)

    response = client.get("/images/0123456789abcdef.jpg")

    assert response.status_code == 200
    assert response.content == payload
