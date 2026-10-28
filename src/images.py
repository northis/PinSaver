"""
Image formats: what the archive stores and what a browser can render.

Pinterest serves some pins as HEIC/HEIF (uploads from an iPhone). Chrome, Firefox and
Edge cannot decode them at all, so the gallery showed a blank card while the file itself
downloaded fine. The archive keeps what it downloaded, and anything a browser cannot
render is converted to JPEG: on the way in (`archive.py` stores the JPEG and keeps the
HEIC next to it), on the way out for files stored before 2.7.3 (`/images/{filename}`),
and in bulk for the existing archive (`convert_heic.py`).

The format is always taken from the bytes, never from the URL: Pinterest does not
guarantee that the extension of a link is the format that comes back.
"""
from __future__ import annotations

import io
import threading
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

#: Bytes read to identify a file's format: enough for the `ftyp` box of a HEIF file.
SNIFF_BYTES = 512

#: Extension of each image format the archive recognizes.
FORMAT_EXTENSIONS = {
    "jpeg": "jpg",
    "png": "png",
    "gif": "gif",
    "webp": "webp",
    "avif": "avif",
    "heic": "heic",
}

#: Formats no Chromium browser can show: the site gets a JPEG, the original is kept.
CONVERTED_FORMATS = frozenset({"heic"})

#: Extensions the archive stores under another one, whatever a link calls them.
STORED_EXTENSIONS = {"heic": "jpg", "heif": "jpg", "jpeg": "jpg"}

#: Content type per extension, for the extensions the archive can produce. Explicit
#: because `mimetypes` does not know every one of them on every platform, and a wrong
#: type (`text/plain`) makes the browser download the image instead of showing it.
MEDIA_TYPES = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "gif": "image/gif",
    "webp": "image/webp",
    "avif": "image/avif",
    "heic": "image/heic",
    "heif": "image/heif",
}

#: JPEG quality of a converted HEIC: the archive is meant to keep the original look.
JPEG_QUALITY = 95

#: `ftyp` brands of a HEIF still image, including the generic ones iPhone uploads use.
HEIC_BRANDS = frozenset({
    b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"hevm", b"hevs",
    b"mif1", b"msf1",
})
AVIF_BRANDS = frozenset({b"avif", b"avis"})

_heif_lock = threading.Lock()
_heif_registered = False


class ImageConversionError(Exception):
    """The bytes could not be turned into a format the browser shows."""


def sniff(data: bytes) -> str | None:
    """
    Identify an image by its first bytes.

    Args:
        data: The image bytes (a prefix is enough, see SNIFF_BYTES).

    Returns:
        `jpeg`, `png`, `gif`, `webp`, `avif` or `heic`, or None for anything else.
    """
    if data[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"

    brands = ftyp_brands(data)
    if brands & AVIF_BRANDS:
        return "avif"
    if brands & HEIC_BRANDS:
        return "heic"
    return None


def ftyp_brands(data: bytes) -> set[bytes]:
    """
    Brands of an ISO base media file, read from its `ftyp` box.

    HEIF and AVIF share the container, so the brand is the only thing that tells them
    apart (and apart from a video, which the archive never stores).
    """
    if len(data) < 12 or data[4:8] != b"ftyp":
        return set()

    limit = min(len(data), 1024)
    box_size = int.from_bytes(data[:4], "big")
    if 16 <= box_size <= limit:
        limit = box_size

    brands = {data[8:12]}
    for offset in range(16, limit - 3, 4):
        brands.add(data[offset:offset + 4])
    return brands


def stored_extension(extension: str) -> str:
    """
    Extension the archive stores a pin under, given the one its URL names.

    `heic`/`heif` are stored as `jpg` because the site shows the converted JPEG; `jpeg`
    and `jpg` are the same thing.
    """
    lowered = extension.lower()
    return STORED_EXTENSIONS.get(lowered, lowered)


def media_type(detected: str | None, filename: str) -> str | None:
    """
    Content type for a stored image.

    Args:
        detected: Format from `sniff` (wins when it is known).
        filename: The file name, for the extension fallback.

    Returns:
        The content type, or None to let the caller guess as before.
    """
    by_format = MEDIA_TYPES.get(detected or "")
    if by_format:
        return by_format
    return MEDIA_TYPES.get(Path(filename).suffix.lstrip(".").lower())


def is_image_name(filename: str) -> bool:
    """
    Whether a file name has an extension the archive serves as an image.

    `originals/` should hold nothing but pictures, but a stray copy of the database, a
    note or a backup used to be handed out by `/images` all the same: the route took any
    bare file name. An image extension is the cheapest way to keep the folder's accidents
    private; the bytes still decide the content type.
    """
    return Path(filename).suffix.lstrip(".").lower() in MEDIA_TYPES


@dataclass(frozen=True)
class PreparedImage:
    """
    What a downloaded image is written to `originals/` as.

    Attributes:
        content: The bytes the site serves.
        extension: Extension of those bytes.
        original: The bytes as they came from Pinterest, when they had to be converted.
        original_extension: Extension of `original`.
    """

    content: bytes
    extension: str
    original: bytes = b""
    original_extension: str = ""


def prepare(data: bytes, extension: str) -> PreparedImage:
    """
    Decide what to store for a downloaded image.

    HEIC/HEIF is converted to JPEG and the HEIC itself is handed back so the archive can
    keep it: the site shows the JPEG, the original stays on disk. Any other recognized
    format is stored as it is, under the extension of the format the bytes actually are.
    Bytes that are not recognized at all are returned untouched with the extension the URL
    claimed.

    Args:
        data: The downloaded bytes.
        extension: The extension of the URL they came from.

    Returns:
        A PreparedImage to write to `originals/`.

    Raises:
        ImageConversionError: the bytes are HEIC and could not be decoded.
    """
    detected = sniff(data)
    if detected is None:
        return PreparedImage(data, extension)
    if detected in CONVERTED_FORMATS:
        return PreparedImage(
            content=to_jpeg(data),
            extension="jpg",
            original=data,
            original_extension=FORMAT_EXTENSIONS[detected],
        )
    return PreparedImage(data, FORMAT_EXTENSIONS[detected])


def to_jpeg(data: bytes) -> bytes:
    """
    Decode HEIC/HEIF bytes and re-encode them as JPEG.

    Transparency is flattened onto white, EXIF is kept, and nothing is resized: the point
    is to make the original visible, not to shrink it.

    Raises:
        ImageConversionError: the bytes are not a readable HEIF image, or `pillow-heif`
            is missing from the environment.
    """
    register_heif()
    try:
        with Image.open(io.BytesIO(data)) as image:
            return _jpeg_bytes(image)
    except (OSError, ValueError, Image.DecompressionBombError) as error:
        raise ImageConversionError(f"cannot convert HEIC: {error}") from error


def _jpeg_bytes(image: Image.Image) -> bytes:
    """Encode a Pillow image as JPEG, keeping EXIF and flattening transparency."""
    exif = image.info.get("exif")
    has_alpha = image.mode in ("RGBA", "LA") or (
        image.mode == "P" and "transparency" in image.info
    )

    if has_alpha:
        rgba = image.convert("RGBA")
        frame = Image.new("RGB", rgba.size, (255, 255, 255))
        frame.paste(rgba, mask=rgba.getchannel("A"))
    else:
        frame = image.convert("RGB")

    output = io.BytesIO()
    options = {"quality": JPEG_QUALITY, "optimize": True}
    if exif:
        options["exif"] = exif
    frame.save(output, format="JPEG", **options)
    return output.getvalue()


def register_heif() -> None:
    """
    Teach Pillow to open HEIF containers.

    Idempotent and thread-safe: the endpoints are plain `def`, so FastAPI runs them in a
    thread pool and two saves can arrive at once.

    Raises:
        ImageConversionError: `pillow-heif` is not installed.
    """
    global _heif_registered
    if _heif_registered:
        return

    with _heif_lock:
        if _heif_registered:
            return
        try:
            from pillow_heif import register_heif_opener
        except ImportError as error:
            raise ImageConversionError(
                "pillow-heif is not installed: python -m pip install -r src/requirements.txt"
            ) from error
        register_heif_opener()
        _heif_registered = True
