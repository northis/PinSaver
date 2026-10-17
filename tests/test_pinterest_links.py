"""
`extract_pin_id` must understand every shape a link arrives in, and refuse the rest.

The share sheet sends whatever Pinterest gives it (often a `pin.it` short link) with the pin's
title next to it, a person pasting a link may leave the scheme out, and a board or profile link
must never be mistaken for a pin.
"""
from __future__ import annotations

import httpx
import pytest

import pinterest

PIN_ID = "4609715820662870592"

PIN_LINKS = [
    f"https://www.pinterest.com/pin/{PIN_ID}/",
    f"https://pinterest.com/pin/{PIN_ID}/",
    f"https://id.pinterest.com/pin/{PIN_ID}/",
    f"https://www.pinterest.de/pin/{PIN_ID}/",
    f"https://www.pinterest.co.uk/pin/{PIN_ID}/sent/?nic=1",
    f"http://www.pinterest.com/pin/{PIN_ID}/#fragment",
    f"www.pinterest.com/pin/{PIN_ID}/",
    f"pinterest.com/pin/{PIN_ID}/",
    f"  https://www.pinterest.com/pin/{PIN_ID}/  ",
    # What the share sheet really produces: the pin's title, glued to the link.
    f"https://www.pinterest.com/pin/{PIN_ID}/ Cabelo bonito",
    f"Cabelo bonito https://www.pinterest.com/pin/{PIN_ID}/",
    f"Cabelo bonito\nhttps://www.pinterest.com/pin/{PIN_ID}/\n",
    f"<https://www.pinterest.com/pin/{PIN_ID}/>",
    f"https://www.pinterest.com/pin/{PIN_ID}/.",
    f"Look at https://example.com/cat and https://www.pinterest.com/pin/{PIN_ID}/",
]

NOT_PIN_LINKS = [
    "",
    "   ",
    "https://www.pinterest.com/",
    "https://www.pinterest.com/user/boards/",
    "https://www.pinterest.com/board/12345/some-board/",
    "https://www.pinterest.com/search/pins/?q=cats",
    "https://example.com/pin/1234567890/",
    "https://www.pinterest.com/pin/not-a-number/",
    "just some text from a description",
    "see https://example.com/pin/1234567890/ for the original",
    "https://www.pinterest.com/ and https://example.com/pin/1234567890/",
]


@pytest.mark.parametrize("link", PIN_LINKS)
def test_pin_links_are_understood(link: str) -> None:
    assert pinterest.extract_pin_id(link) == PIN_ID


@pytest.mark.parametrize("link", NOT_PIN_LINKS)
def test_other_links_are_refused(link: str) -> None:
    with pytest.raises(pinterest.PinLookupError) as error:
        pinterest.extract_pin_id(link)

    assert error.value.reason == "not_a_pin_link"


def test_short_link_is_followed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "pin.it":
            return httpx.Response(
                302, headers={"location": f"https://www.pinterest.com/pin/{PIN_ID}/"}
            )
        assert request.url.host == "www.pinterest.com"
        return httpx.Response(200, text="<html></html>")

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)

    assert pinterest.extract_pin_id("https://pin.it/AbCdEf", client=client) == PIN_ID


def test_short_link_with_the_pin_title_glued_to_it_is_followed() -> None:
    """The title must never reach the shortener: only the link is requested."""
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        if request.url.host == "pin.it":
            return httpx.Response(
                302, headers={"location": f"https://www.pinterest.com/pin/{PIN_ID}/"}
            )
        return httpx.Response(200, text="<html></html>")

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)

    assert pinterest.extract_pin_id("https://pin.it/AbCdEf Cabelo bonito", client=client) == PIN_ID
    assert pinterest.extract_pin_id("Cabelo bonito https://pin.it/AbCdEf", client=client) == PIN_ID
    # Two lookups, each of them a short link and its redirect - never a title in the path.
    assert requested == [
        "https://pin.it/AbCdEf",
        f"https://www.pinterest.com/pin/{PIN_ID}/",
        "https://pin.it/AbCdEf",
        f"https://www.pinterest.com/pin/{PIN_ID}/",
    ]


def test_first_link_reads_the_link_out_of_the_text() -> None:
    link = f"https://www.pinterest.com/pin/{PIN_ID}/"

    assert pinterest.first_link(f"Cabelo bonito {link}") == link
    assert pinterest.first_link(f"{link} Cabelo bonito") == link
    assert pinterest.first_link(f"(https://example.com/cat) {link}") == link
    assert pinterest.first_link("just some text from a description") is None
    assert pinterest.first_link("") is None


def test_a_link_with_a_control_character_is_refused() -> None:
    """`httpx.InvalidURL` is not an `HTTPError`: it has to come back as a bad link, not a 500."""
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200)))

    with pytest.raises(pinterest.PinLookupError) as error:
        pinterest.extract_pin_id("https://pin.it/Ab\x00CdEf", client=client)

    assert error.value.reason == "not_a_pin_link"


def test_short_link_to_somewhere_else_is_refused() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "pin.it":
            return httpx.Response(302, headers={"location": "https://example.com/whatever"})
        return httpx.Response(200, text="<html>not pinterest</html>")

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)

    with pytest.raises(pinterest.PinLookupError) as error:
        pinterest.extract_pin_id("https://pin.it/AbCdEf", client=client)

    assert error.value.reason == "not_a_pin_link"
