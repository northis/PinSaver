"""
`fetch_pin_page` against Pinterest itself, with the network faked.

Two behaviours are worth pinning down: a deleted pin is not a 404 but a redirect away from
the pin page, and 429/5xx are worth exactly one retry. The retry pause is patched to zero so
the suite stays fast, and every request here goes through a mock transport - the suite never
touches the network.
"""
from __future__ import annotations

from typing import Callable

import httpx
import pytest

import pinterest

PIN_ID = "4609715820662870592"
FILE_ID = "f" * 32
PAGE = (
    '<html><head><meta content="https://i.pinimg.com/736x/aa/bb/cc/'
    + FILE_ID
    + '.jpg" property="og:image"/></head></html>'
)


@pytest.fixture(autouse=True)
def no_retry_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pinterest, "RETRY_DELAY_SECONDS", 0)


def client_with(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


def test_page_is_returned() -> None:
    client = client_with(lambda request: httpx.Response(200, text=PAGE))

    assert pinterest.fetch_pin_page(PIN_ID, client) == PAGE


def test_missing_pin_is_reported() -> None:
    client = client_with(lambda request: httpx.Response(404, text="not found"))

    with pytest.raises(pinterest.PinLookupError) as error:
        pinterest.fetch_pin_page(PIN_ID, client)

    assert error.value.reason == "pin_not_found"


def test_deleted_pin_redirected_home_is_reported() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == f"/pin/{PIN_ID}/":
            return httpx.Response(302, headers={"location": "https://www.pinterest.com/"})
        return httpx.Response(200, text="<html>home</html>")

    with pytest.raises(pinterest.PinLookupError) as error:
        pinterest.fetch_pin_page(PIN_ID, client_with(handler))

    assert error.value.reason == "pin_not_found"


def test_server_errors_are_retried_once() -> None:
    calls: list[httpx.URL] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url)
        return httpx.Response(503, text="busy")

    with pytest.raises(pinterest.PinLookupError) as error:
        pinterest.fetch_pin_page(PIN_ID, client_with(handler))

    assert error.value.reason == "pinterest_unavailable"
    assert len(calls) == 2


def test_rate_limit_is_retried_and_can_succeed() -> None:
    calls: list[httpx.URL] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url)
        if len(calls) == 1:
            return httpx.Response(429, text="slow down")
        return httpx.Response(200, text=PAGE)

    assert pinterest.fetch_pin_page(PIN_ID, client_with(handler)) == PAGE
    assert len(calls) == 2


def test_resolve_pin_reads_the_fetched_page() -> None:
    client = client_with(lambda request: httpx.Response(200, text=PAGE))

    pin = pinterest.resolve_pin(PIN_ID, client)

    assert pin.pin_id == PIN_ID
    assert pin.file_id == FILE_ID
    assert pin.image_url.endswith(f"{FILE_ID}.jpg")
