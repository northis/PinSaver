"""
Adding pins to the archive: one code path for the API, the share page and "Save link".

The rules that decide what happens to a pin - dedupe by file id, the rating counter,
restoring a pin Pinterest dropped, and the download fallbacks - live here so the entry points
cannot drift apart.

Synchronous on purpose: the endpoints are plain `def`, so FastAPI runs them in its thread
pool and a slow image download never blocks the event loop.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass

import httpx

import images
from models import Pin, get_originals_path, insert_pin

#: `https://i.pinimg.com/<kind>/xx/yy/zz/<32 hex>.<ext>`, with or without a query string.
FILE_ID_RE = re.compile(r"/([a-f0-9]{32})\.(\w+)(?:\?|$)")
ORIGINALS_KIND = "originals"
#: Sizes Pinterest keeps serving when the original is gone.
FALLBACK_SIZES = ("736x", "564x", "474x", "236x")
#: Other formats of the same file id worth trying: one pin's original had moved to .webp
#: while its sized copies stayed .jpg. `heic` is here because Pinterest keeps iPhone
#: uploads as HEIC only; `images.py` turns those into JPEG, which is better than the
#: 736x copy that would otherwise be the best left.
FALLBACK_EXTENSIONS = ("jpg", "webp", "png", "heic")
DOWNLOAD_TIMEOUT_SECONDS = 30.0


@dataclass(frozen=True)
class DownloadedImage:
    """What actually came back from i.pinimg.com."""

    url: str
    file_id: str
    extension: str
    size: str
    content: bytes


@dataclass(frozen=True)
class AddResult:
    """
    Outcome of offering a pin to the archive.

    Attributes:
        status: `added`, `exists` (the extension shows a different message for it) or
            `restored`.
        message: human-readable summary, kept as it was before the refactor.
        size: `orig`, a Pinterest size like `736x`, or `local` when the file was already on
            disk; empty for `exists` and `restored`.
        image_url: what was actually downloaded (empty when nothing was).
    """

    status: str
    message: str
    pin_id: str
    file_id: str
    file_extension: str
    size: str = ""
    image_url: str = ""


class AddPinError(Exception):
    """
    A pin could not be added.

    Attributes:
        reason: `invalid_url` (the API answers 400) or `image_unavailable` (500/502).
        detail: human-readable cause, passed on to the caller.
    """

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(detail or reason)
        self.reason = reason
        self.detail = detail


def new_client() -> httpx.Client:
    """Client for image downloads: redirects followed, one shared timeout."""
    return httpx.Client(follow_redirects=True, timeout=DOWNLOAD_TIMEOUT_SECONDS)


def file_id_from_url(url: str) -> tuple[str, str] | None:
    """Split an `i.pinimg.com` URL into (file_id, extension)."""
    match = FILE_ID_RE.search(url or "")
    if not match:
        return None
    return match.group(1), match.group(2)


def candidates(file_id: str, extension: str, preferred_url: str = "") -> list[tuple[str, str, str]]:
    """
    Ordered download candidates as (url, extension, size).

    The URL the page gave first, then the originals of the same file id, then the sizes
    Pinterest keeps: the original is often gone (a 403) while the sized copies are fine.
    """
    prefix = f"{file_id[:2]}/{file_id[2:4]}/{file_id[4:6]}"
    ordered: list[tuple[str, str, str]] = []
    seen: set[str] = set()

    def add(url: str, item_extension: str, size: str) -> None:
        if url not in seen:
            seen.add(url)
            ordered.append((url, item_extension, size))

    if preferred_url:
        kind = preferred_url.split("i.pinimg.com/")[-1].split("/")[0]
        add(preferred_url, extension, "orig" if kind == ORIGINALS_KIND else kind)

    for item_extension in (extension, *FALLBACK_EXTENSIONS):
        add(f"https://i.pinimg.com/{ORIGINALS_KIND}/{prefix}/{file_id}.{item_extension}",
            item_extension, "orig")

    for size in FALLBACK_SIZES:
        for item_extension in (extension, "jpg"):
            add(f"https://i.pinimg.com/{size}/{prefix}/{file_id}.{item_extension}",
                item_extension, size)

    return ordered


def download_image(
    client: httpx.Client,
    file_id: str,
    extension: str,
    preferred_url: str = "",
) -> DownloadedImage:
    """
    Fetch the best available copy of an image.

    Raises:
        AddPinError: reason `image_unavailable` when every candidate failed.
    """
    failures: list[str] = []

    for url, item_extension, size in candidates(file_id, extension, preferred_url):
        try:
            response = client.get(url)
        except httpx.HTTPError as error:
            failures.append(f"{url}: {error}")
            continue

        if response.status_code == 200 and response.content:
            return DownloadedImage(
                url=url,
                file_id=file_id,
                extension=item_extension,
                size=size,
                content=response.content,
            )

        failures.append(f"{url}: HTTP {response.status_code}")

    raise AddPinError("image_unavailable", "; ".join(failures[-3:]) or "no candidates")


def add_pin_from_url(
    conn,
    pin_id: str,
    original_url: str,
    client: httpx.Client | None = None,
) -> AddResult:
    """
    Offer a pin to the archive and report what happened.

    The order of decisions is unchanged since 1.0.0 because the extension depends on it:
    a known pin id and a known image both only raise the rating, an image that was marked
    deleted is restored instead, an image already on disk skips the download, and everything
    else is downloaded and inserted.

    Args:
        conn: open SQLite connection (the caller commits nothing; this function does).
        pin_id: numeric Pinterest pin id.
        original_url: an i.pinimg.com URL of the image.
        client: optional download client (tests inject one with a mock transport).

    Returns:
        AddResult describing the outcome.

    Raises:
        AddPinError: `invalid_url` or `image_unavailable`.
    """
    cursor = conn.cursor()

    cursor.execute("SELECT id, file_id, file_extension FROM pins WHERE pin_id = ?", (pin_id,))
    existing_by_pin = cursor.fetchone()
    if existing_by_pin:
        cursor.execute("UPDATE pins SET rating = rating + 1 WHERE id = ?", (existing_by_pin["id"],))
        conn.commit()
        return AddResult(
            status="exists",
            message=f"Pin {pin_id} already exists in archive (rating +1)",
            pin_id=pin_id,
            file_id=existing_by_pin["file_id"],
            file_extension=existing_by_pin["file_extension"],
        )

    parts = file_id_from_url(original_url)
    if not parts:
        raise AddPinError("invalid_url", "Invalid original_url format")
    file_id, url_extension = parts

    cursor.execute("SELECT id, pin_id, is_deleted FROM pins WHERE file_id = ?", (file_id,))
    existing_by_file = cursor.fetchone()
    if existing_by_file:
        if existing_by_file["is_deleted"]:
            cursor.execute(
                "UPDATE pins SET pin_id = ?, pinterest_url = ?, is_deleted = 0 WHERE id = ?",
                (pin_id, f"https://pinterest.com/pin/{pin_id}/", existing_by_file["id"]),
            )
            conn.commit()
            return AddResult(
                status="restored",
                message=f"Pin restored with new ID {pin_id} (was {existing_by_file['pin_id']})",
                pin_id=pin_id,
                file_id=file_id,
                file_extension=url_extension,
            )

        cursor.execute("UPDATE pins SET rating = rating + 1 WHERE id = ?", (existing_by_file["id"],))
        conn.commit()
        return AddResult(
            status="exists",
            message=(
                f"Image already exists in archive "
                f"(pin {existing_by_file['pin_id']}, rating +1)"
            ),
            pin_id=pin_id,
            file_id=file_id,
            file_extension=url_extension,
        )

    originals_path = get_originals_path()
    originals_path.mkdir(parents=True, exist_ok=True)

    size = "local"
    image_url = original_url
    extension = images.stored_extension(url_extension)
    image_path = originals_path / f"{file_id}.{extension}"

    if not image_path.exists():
        own_client = None
        if client is None:
            own_client = new_client()
            client = own_client
        try:
            downloaded = download_image(client, file_id, url_extension, original_url)
        finally:
            if own_client is not None:
                own_client.close()

        try:
            prepared = images.prepare(downloaded.content, downloaded.extension)
        except images.ImageConversionError:
            # A pin whose HEIC cannot be decoded is still archived: the file downloads,
            # it just cannot be shown, and dropping the record would be worse.
            prepared = images.PreparedImage(downloaded.content, downloaded.extension)

        size = downloaded.size
        image_url = downloaded.url
        extension = prepared.extension
        image_path = originals_path / f"{file_id}.{extension}"
        image_path.write_bytes(prepared.content)

        if prepared.original:
            # The HEIC itself stays: the site shows the JPEG, the archive keeps the
            # original (`convert_heic.py` leaves the same pair behind).
            original_path = originals_path / f"{file_id}.{prepared.original_extension}"
            original_path.write_bytes(prepared.original)

    insert_pin(conn, Pin(
        pin_id=pin_id,
        file_id=file_id,
        file_extension=extension,
        pinterest_url=f"https://pinterest.com/pin/{pin_id}/",
        original_url=image_url,
        source_date=int(time.time()),
    ))
    conn.commit()

    return AddResult(
        status="added",
        message=f"Pin {pin_id} added to archive",
        pin_id=pin_id,
        file_id=file_id,
        file_extension=extension,
        size=size,
        image_url=image_url,
    )
