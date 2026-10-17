"""
The PWA shell: the web app manifest, the installable icons and the pages that point at them.

The icons are committed PNGs (see `tools/make_pwa_icons.py`), so what is checked here is what a
browser actually fetches: the manifest's type and members, the size and the opacity of every
declared icon, and the links in each page's head. Pillow is not needed for that - the PNG
header carries the width, the height and the colour type, which is all these tests read.
"""
from __future__ import annotations

import json
import struct
from pathlib import Path

from fastapi.testclient import TestClient

STATIC = Path(__file__).resolve().parent.parent / "src" / "static"
PAGES = ("index.html", "share.html")
MANIFEST_LINK = '<link rel="manifest" href="/manifest.webmanifest">'
FAVICON_LINK = '<link rel="icon" type="image/svg+xml" href="/static/favicon.svg">'
APPLE_TOUCH_LINK = '<link rel="apple-touch-icon" href="/static/icons/apple-touch-icon-180.png">'
THEME_COLOR = '<meta name="theme-color" content="#e60023">'
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
RGBA, RGB = 6, 2  # PNG colour types: with and without an alpha channel


def manifest() -> dict:
    return json.loads((STATIC / "manifest.webmanifest").read_text(encoding="utf-8"))


def icon_path(icon: dict) -> Path:
    return STATIC / icon["src"].removeprefix("/static/")


def png_header(path: Path) -> tuple[int, int, int]:
    """(width, height, colour type) straight from IHDR - no need to decode the image."""
    data = path.read_bytes()
    assert data[:8] == PNG_MAGIC, f"{path.name} is not a PNG"
    width, height = struct.unpack(">II", data[16:24])
    return width, height, data[25]


def test_manifest_is_served_as_a_manifest(client: TestClient) -> None:
    response = client.get("/manifest.webmanifest")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/manifest+json")
    assert response.json()["name"] == "Pinterest Archive"


def test_manifest_has_what_installability_requires() -> None:
    data = manifest()
    any_purpose = {icon["sizes"] for icon in data["icons"] if icon["purpose"] == "any"}

    assert data["short_name"]
    assert data["id"] == "/"
    assert data["start_url"] == "/"
    assert data["scope"] == "/"
    assert data["display"] == "standalone"
    assert any_purpose >= {"192x192", "512x512"}


def test_manifest_declares_the_share_target() -> None:
    """The system share sheet posts the link to `action`, and the worker reads the field
    names back out of the multipart body."""
    assert manifest()["share_target"] == {
        "action": "/share",
        "method": "POST",
        "enctype": "multipart/form-data",
        "params": {"title": "title", "text": "text", "url": "url"},
    }


def test_every_declared_icon_exists_at_its_declared_size() -> None:
    for icon in manifest()["icons"]:
        width, height = (int(part) for part in icon["sizes"].split("x"))

        assert png_header(icon_path(icon))[:2] == (width, height)


def test_any_icons_are_transparent_and_maskable_is_not() -> None:
    """Android draws a transparent icon on a white circle: the maskable one must be opaque,
    while the `any` ones stay transparent like the favicon (no padding baked in)."""
    maskable = [icon for icon in manifest()["icons"] if icon["purpose"] == "maskable"]
    any_purpose = [icon for icon in manifest()["icons"] if icon["purpose"] == "any"]

    assert maskable and any_purpose
    for icon in maskable:
        assert png_header(icon_path(icon))[2] == RGB
    for icon in any_purpose:
        assert png_header(icon_path(icon))[2] == RGBA
    assert png_header(STATIC / "icons" / "apple-touch-icon-180.png") == (180, 180, RGB)


def test_declared_icons_are_served(client: TestClient) -> None:
    for icon in manifest()["icons"]:
        response = client.get(icon["src"])

        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"


def test_favicon_is_the_header_pin() -> None:
    svg = (STATIC / "favicon.svg").read_text(encoding="utf-8")

    assert "<svg" in svg and "viewBox" in svg
    assert "📌" in svg
    assert "📌" in (STATIC / "index.html").read_text(encoding="utf-8")  # the pin from <h1>


def test_favicon_ico_redirects_to_the_pin(client: TestClient) -> None:
    response = client.get("/favicon.ico")

    assert response.status_code == 200
    assert response.history[0].status_code == 307
    assert "📌" in response.text


def test_every_page_points_at_the_pwa_assets() -> None:
    for page in PAGES:
        html = (STATIC / page).read_text(encoding="utf-8")

        assert MANIFEST_LINK in html
        assert FAVICON_LINK in html
        assert APPLE_TOUCH_LINK in html
        assert THEME_COLOR in html


def test_the_manifest_moved_out_of_static(client: TestClient) -> None:
    """The manifest and the icons left /static/ in 2.2.0: the old paths must not linger as a
    second source of truth, and the public paths in sitehub and Cloudflare Access follow."""
    assert client.get("/static/manifest.json").status_code == 404
    assert client.get("/static/icon-192.png").status_code == 404
