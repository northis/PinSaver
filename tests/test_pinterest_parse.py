"""
`parse_pin_page` reads the committed fixture, so a markup change fails here first.

The fixture keeps the real attribute order (`content` before `property`), the preload link and
a decoy image from the recommendation block - the three things that made a naive regex fail
while this feature was being built.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import pinterest

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "pin_page.html"
PIN_ID = "4609715820662870592"
FILE_ID = "28a577052cef6a39e431f87d7f1d5664"
DECOY_FILE_ID = "d53b014d86a6b6761bf649a0ed813c2b"


@pytest.fixture()
def page() -> str:
    return FIXTURE.read_text(encoding="utf-8")


def test_fixture_pin_is_parsed(page: str) -> None:
    pin = pinterest.parse_pin_page(PIN_ID, page)

    assert pin.pin_id == PIN_ID
    assert pin.file_id == FILE_ID
    assert pin.extension == "webp"
    assert pin.image_url == f"https://i.pinimg.com/originals/28/a5/77/{FILE_ID}.webp"
    assert pin.is_video is False


def test_recommended_pin_image_is_not_taken(page: str) -> None:
    """The page also carries a stranger's picture: only our file id may win."""
    pin = pinterest.parse_pin_page(PIN_ID, page)

    assert DECOY_FILE_ID not in pin.image_url


def test_attribute_order_does_not_matter() -> None:
    html = (
        '<meta property="og:image" content="https://i.pinimg.com/736x/aa/bb/cc/'
        + "a" * 32
        + '.jpg"/>'
    )

    pin = pinterest.parse_pin_page(PIN_ID, html)

    assert pin.file_id == "a" * 32
    assert pin.extension == "jpg"
    assert pin.image_url == f"https://i.pinimg.com/736x/aa/bb/cc/{'a' * 32}.jpg"


def test_preload_link_is_used_when_og_image_is_missing() -> None:
    html = (
        '<link as="image" href="https://i.pinimg.com/736x/aa/bb/cc/'
        + "b" * 32
        + '.jpg" id="pin-image-preload"/>'
    )

    pin = pinterest.parse_pin_page(PIN_ID, html)

    assert pin.file_id == "b" * 32


def test_page_without_images_is_reported(page: str) -> None:
    with pytest.raises(pinterest.PinLookupError) as error:
        pinterest.parse_pin_page(PIN_ID, "<html><body>nothing here</body></html>")

    assert error.value.reason == "image_unavailable"


def test_sized_url_is_kept_when_originals_holds_a_stranger() -> None:
    html = (
        '<meta property="og:image" content="https://i.pinimg.com/736x/aa/bb/cc/'
        + "c" * 32
        + '.jpg"/>'
        '<script>{"images_orig":{"url":"https://i.pinimg.com/originals/11/22/33/'
        + "d" * 32
        + '.png"}}</script>'
    )

    pin = pinterest.parse_pin_page(PIN_ID, html)

    assert pin.file_id == "c" * 32
    assert pin.image_url == f"https://i.pinimg.com/736x/aa/bb/cc/{'c' * 32}.jpg"


def test_originals_extension_wins_over_the_sized_one() -> None:
    """One pin's original had moved to .webp while the sized copy stayed .jpg."""
    html = (
        '<meta property="og:image" content="https://i.pinimg.com/736x/aa/bb/cc/'
        + "e" * 32
        + '.jpg"/>'
        '<script>{"images_orig":{"url":"https://i.pinimg.com/originals/11/22/33/'
        + "e" * 32
        + '.webp"}}</script>'
    )

    pin = pinterest.parse_pin_page(PIN_ID, html)

    assert pin.extension == "webp"
    assert pin.image_url.endswith(".webp")


def test_video_hint_is_reported(page: str) -> None:
    pin = pinterest.parse_pin_page(PIN_ID, page.replace('"isVideo":false', '"isVideo":true'))

    assert pin.is_video is True
