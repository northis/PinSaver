"""
`extract_pin_id` must understand every shape a link arrives in, and refuse the rest.

The share sheet sends whatever Pinterest gives it (often a `pin.it` short link), a person
pasting a link may leave the scheme out, and a board or profile link must never be mistaken
for a pin.
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


def test_short_link_to_somewhere_else_is_refused() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "pin.it":
            return httpx.Response(302, headers={"location": "https://example.com/whatever"})
        return httpx.Response(200, text="<html>not pinterest</html>")

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)

    with pytest.raises(pinterest.PinLookupError) as error:
        pinterest.extract_pin_id("https://pin.it/AbCdEf", client=client)

    assert error.value.reason == "not_a_pin_link"
