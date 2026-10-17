"""
Resolving a Pinterest link to the image behind it, without any cookies.

The extension reads the image out of the page the user already has open; the server has no
session, so it fetches the public pin page instead. Checked against the live site on
2026-10-17: the page answers 200 anonymously and carries `og:image` with a sized
`i.pinimg.com` URL, while the same `file_id` also appears under `/originals/` - possibly with
another extension (one pin's original had moved to `.webp`), which is why the extension is
taken from the page and never assumed.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

#: Pinterest expects a desktop browser on a pin page.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
)

PIN_URL_TEMPLATE = "https://www.pinterest.com/pin/{pin_id}/"
REQUEST_TIMEOUT_SECONDS = 15.0
#: Pause before the single retry on 429/5xx. Tests set it to zero.
RETRY_DELAY_SECONDS = 2.0

PIN_HOST_RE = re.compile(r"^(?:[a-z0-9-]+\.)*pinterest\.[a-z.]{2,}$", re.I)
SHORT_LINK_HOST_RE = re.compile(r"^(?:[a-z0-9-]+\.)*pin\.it$", re.I)
PIN_PATH_RE = re.compile(r"/pin/(\d+)")
META_TAG_RE = re.compile(r"<meta\b[^>]*>", re.I)
LINK_TAG_RE = re.compile(r"<link\b[^>]*>", re.I)
ATTRIBUTE_RE = re.compile(r'([A-Za-z:-]+)="([^"]*)"')
#: `https://i.pinimg.com/<kind-or-size>/xx/yy/zz/<32 hex>.<ext>`
IMAGE_URL_RE = re.compile(
    r"https://i\.pinimg\.com/([^/\"'\s]+/)?[0-9a-f]{2}/[0-9a-f]{2}/[0-9a-f]{2}/([0-9a-f]{32})\.(\w+)"
)
VIDEO_HINT_RE = re.compile(r'"isVideo"\s*:\s*true')


class PinLookupError(Exception):
    """
    A pin could not be resolved.

    Attributes:
        reason: stable code for the UI - `not_a_pin_link`, `pin_not_found`,
            `pinterest_unavailable` or `image_unavailable`.
        detail: human-readable cause for the log.
    """

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(detail or reason)
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class ResolvedPin:
    """
    What the pin page gave us.

    Attributes:
        pin_id: the requested pin.
        file_id: 32 hex characters naming the image on i.pinimg.com.
        extension: extension of `image_url` (not necessarily `jpg`).
        image_url: preferred download URL; `file_id` is what the fallbacks are built from.
        is_video: page-wide hint only (the recommendations may mention a video pin); it is
            logged and changes nothing.
    """

    pin_id: str
    file_id: str
    extension: str
    image_url: str
    is_video: bool


def new_client() -> httpx.Client:
    """HTTP client that follows redirects: `pin.it` links and deleted pins both need it."""
    return httpx.Client(
        headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
        follow_redirects=True,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )


def tag_attributes(tag: str) -> dict[str, str]:
    """Attributes of a single HTML tag, lower-cased names, order-independent."""
    return {name.lower(): value for name, value in ATTRIBUTE_RE.findall(tag)}


def meta_content(html: str, key: str) -> str | None:
    """
    Content of the `<meta>` whose `name` or `property` is exactly `key`.

    Exact matching matters: `og:image`, `og:image:width` and `og:image:height` all appear on
    a pin page, and Pinterest writes `content` before `property`, so a positional regex
    would miss the tag entirely.
    """
    for tag in META_TAG_RE.findall(html):
        attributes = tag_attributes(tag)
        if attributes.get("name") == key or attributes.get("property") == key:
            return attributes.get("content") or None
    return None


def link_href(html: str, link_id: str) -> str | None:
    """Href of the `<link>` with the given id (the page preloads the pin image)."""
    for tag in LINK_TAG_RE.findall(html):
        attributes = tag_attributes(tag)
        if attributes.get("id") == link_id:
            return attributes.get("href") or None
    return None


def image_parts(url: str) -> tuple[str, str] | None:
    """Split an `i.pinimg.com` URL into (file_id, extension)."""
    match = IMAGE_URL_RE.search(url or "")
    if not match:
        return None
    return match.group(2), match.group(3)


def originals_url(html: str, file_id: str, preferred_extension: str) -> str | None:
    """
    The `/originals/` URL of *this* pin, if the page offers one.

    A pin page also carries the images of the pins it recommends, so the file id has to
    match: a plain search for `/originals/` would happily return a stranger's picture.
    """
    candidates: dict[str, str] = {}
    for match in IMAGE_URL_RE.finditer(html):
        kind = (match.group(1) or "").rstrip("/")
        if kind == "originals" and match.group(2) == file_id:
            candidates.setdefault(match.group(3), match.group(0))

    if not candidates:
        return None
    if preferred_extension in candidates:
        return candidates[preferred_extension]
    return next(iter(candidates.values()))


def normalize_link(link: str) -> str:
    """Add a scheme when the user pasted `pinterest.com/pin/...` without one."""
    candidate = (link or "").strip()
    if not candidate:
        raise PinLookupError("not_a_pin_link", "empty link")
    if not candidate.startswith(("http://", "https://")):
        candidate = "https://" + candidate.lstrip("/")
    return candidate


def extract_pin_id(link: str, client: httpx.Client | None = None) -> str:
    """
    Pull the numeric pin id out of a link, following `pin.it` short links.

    Args:
        link: anything the share sheet or the user pasted.
        client: optional client (tests inject one with a mock transport).

    Returns:
        The pin id as a string.

    Raises:
        PinLookupError: reason `not_a_pin_link`, or `pinterest_unavailable` when a short
            link cannot be followed.
    """
    candidate = normalize_link(link)
    own_client = None

    try:
        parts = urlsplit(candidate)
        host = (parts.hostname or "").lower()

        if SHORT_LINK_HOST_RE.match(host):
            if client is None:
                own_client = new_client()
                client = own_client
            response = get(client, candidate)
            parts = urlsplit(str(response.url))
            host = (parts.hostname or "").lower()

        if not PIN_HOST_RE.match(host):
            raise PinLookupError("not_a_pin_link", f"not a pinterest link: {candidate}")

        match = PIN_PATH_RE.search(parts.path)
        if not match:
            raise PinLookupError("not_a_pin_link", f"no /pin/<id>/ in {candidate}")

        return match.group(1)
    finally:
        if own_client is not None:
            own_client.close()


def get(client: httpx.Client, url: str) -> httpx.Response:
    """
    GET with a single retry on 429 and 5xx.

    Raises:
        PinLookupError: reason `pinterest_unavailable` when the request keeps failing.
    """
    detail = ""
    for attempt in (1, 2):
        try:
            response = client.get(url)
        except httpx.HTTPError as error:
            detail = str(error)
        else:
            if response.status_code != 429 and response.status_code < 500:
                return response
            detail = f"HTTP {response.status_code}"
        if attempt == 1:
            time.sleep(RETRY_DELAY_SECONDS)

    raise PinLookupError("pinterest_unavailable", detail)


def fetch_pin_page(pin_id: str, client: httpx.Client | None = None) -> str:
    """
    HTML of the public pin page.

    Raises:
        PinLookupError: `pin_not_found` when Pinterest has no such pin (404, or a redirect
            that leaves the pin page), `pinterest_unavailable` when it will not answer.
    """
    own_client = None
    if client is None:
        own_client = new_client()
        client = own_client

    try:
        response = get(client, PIN_URL_TEMPLATE.format(pin_id=pin_id))
        if response.status_code == 404:
            raise PinLookupError("pin_not_found", f"HTTP 404 for pin {pin_id}")
        if response.status_code >= 400:
            raise PinLookupError("pinterest_unavailable", f"HTTP {response.status_code}")

        # Deleted pins are redirected away from the pin page (to the home page or elsewhere).
        if f"/pin/{pin_id}" not in str(response.url):
            raise PinLookupError("pin_not_found", f"redirected to {response.url}")

        return response.text
    finally:
        if own_client is not None:
            own_client.close()


def parse_pin_page(pin_id: str, html: str) -> ResolvedPin:
    """
    Pull the image out of a pin page. Pure function: no network, no database.

    Raises:
        PinLookupError: `pin_not_found` when Pinterest answered with its generic page (a pin
            id it never had gets a 200, not a 404, and no pin metadata at all), or
            `image_unavailable` when a real pin has no usable image.
    """
    sized = meta_content(html, "og:image") or link_href(html, "pin-image-preload")
    if not sized:
        if not meta_content(html, "og:url"):
            raise PinLookupError("pin_not_found", f"pin {pin_id} has no page on Pinterest")
        raise PinLookupError("image_unavailable", "no og:image on the pin page")

    parts = image_parts(sized)
    if not parts:
        raise PinLookupError("image_unavailable", f"unexpected image URL: {sized}")
    file_id, extension = parts

    originals = originals_url(html, file_id, extension)
    image_url = originals or sized
    if originals:
        extension = image_parts(originals)[1]

    return ResolvedPin(
        pin_id=pin_id,
        file_id=file_id,
        extension=extension,
        image_url=image_url,
        is_video=bool(VIDEO_HINT_RE.search(html)),
    )


def resolve_pin(pin_id: str, client: httpx.Client | None = None) -> ResolvedPin:
    """
    Fetch the public pin page and read the image out of it.

    Args:
        pin_id: numeric Pinterest pin id.
        client: optional client (tests inject one with a mock transport).

    Returns:
        The resolved pin, ready for `archive.add_pin_from_url`.

    Raises:
        PinLookupError: see `fetch_pin_page` and `parse_pin_page`.
    """
    return parse_pin_page(pin_id, fetch_pin_page(pin_id, client))


def fixture_page(html: str, pin: ResolvedPin) -> str:
    """
    Reduce a live pin page to the parts the resolver reads.

    Used by `tools/resolve_pin.py --save-fixture`: the committed test fixture stays a few
    kilobytes instead of a megabyte, while the markup the parser depends on (attribute order
    included) stays real.
    """
    kept: list[str] = []

    for tag in META_TAG_RE.findall(html):
        if tag_attributes(tag).get("property") in ("og:image", "og:image:height"):
            kept.append(tag)

    for tag in LINK_TAG_RE.findall(html):
        if tag_attributes(tag).get("id") == "pin-image-preload":
            kept.append(tag)

    decoy = ""
    for match in IMAGE_URL_RE.finditer(html):
        kind = (match.group(1) or "").rstrip("/")
        if kind == "originals" and match.group(2) != pin.file_id:
            decoy = match.group(0)
            break

    body = "\n".join(kept)
    scripts = [
        '{"images_orig":{"url":"%s"},"imageSignature":"%s","isVideo":%s}'
        % (pin.image_url, pin.file_id, "true" if pin.is_video else "false")
    ]
    if decoy:
        scripts.append('{"images_orig":{"url":"%s"}}' % decoy)

    return (
        "<!DOCTYPE html>\n"
        "<html>\n"
        "<head>\n"
        f"{body}\n"
        "</head>\n"
        "<body>\n"
        + "\n".join(f"<script>{script}</script>" for script in scripts)
        + "\n</body>\n</html>\n"
    )
