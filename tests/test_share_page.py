"""
The share outcome page, its fallback and the service worker.

The page renders from the URL alone (it must never read the database), `POST /share` is an
inert fallback for an install whose worker is not active, and the worker itself has to carry
the guard header, talk to the API and cache nothing.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

STATIC = Path(__file__).resolve().parent.parent / "src" / "static"
SERVICE_WORKER = STATIC / "sw.js"


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("status=added&pin=1234567890&size=orig", ["Saved", "Pin 1234567890 saved (orig)."]),
        ("status=added&pin=1234567890&size=local", ["Saved", "already on disk"]),
        ("status=added&pin=1234567890", ["Saved", "Pin 1234567890 saved."]),
        ("status=exists&pin=1234567890", ["Already in the archive", "Rating is now one higher."]),
        ("status=restored&pin=1234567890", ["Restored", "was deleted from Pinterest"]),
        ("error=not_a_pin_link", ["Not a pin link", "pinterest.com/pin"]),
        ("error=pin_not_found", ["Pin not found", "does not serve this pin"]),
        ("error=pinterest_unavailable", ["Pinterest is not answering", "Try again in a minute."]),
        ("error=image_unavailable", ["Image unavailable", "did not return an image"]),
        ("error=empty", ["Nothing to save", "did not contain a link"]),
        ("error=sw", ["The app has not updated", "Close and reopen"]),
        ("error=who-knows", ["Something went wrong"]),
        ("", ["PinSaver", "Share a pin from Pinterest"]),
    ],
)
def test_page_states(client: TestClient, query: str, expected: list[str]) -> None:
    response = client.get(f"/share?{query}")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    for needle in expected:
        assert needle in response.text


def test_page_does_not_touch_the_archive(client: TestClient, data_dir: Path) -> None:
    """The page is rendered from the URL: no database, no image folder, no writes."""
    before = {path.name for path in data_dir.rglob("*")}

    client.get("/share?status=added&pin=1234567890&size=orig")

    assert {path.name for path in data_dir.rglob("*")} == before


def test_parameters_are_escaped(client: TestClient) -> None:
    response = client.get("/share?status=added&pin=%3Cscript%3Ealert(1)%3C/script%3E&size=x")

    assert "<script>alert(1)</script>" not in response.text
    assert "&lt;script&gt;" in response.text


def test_forged_parameters_stay_small(client: TestClient) -> None:
    response = client.get("/share?status=added&pin=" + "9" * 5000)

    assert response.status_code == 200
    assert len(response.text) < 5000


def test_post_share_is_inert_and_not_gated(client: TestClient) -> None:
    """No service worker: the body is dropped and the browser lands on ?error=sw."""
    broken = client.post(
        "/share",
        content=b'--boundary\r\nContent-Disposition: form-data; name="url"\r\n\r\n',
        headers={"Content-Type": "multipart/form-data; boundary=boundary"},
        follow_redirects=False,
    )
    bare = client.post("/share", content=b"not multipart at all", follow_redirects=False)

    for response in (broken, bare):
        assert response.status_code == 303
        assert response.headers["location"] == "/share?error=sw"


def test_service_worker_is_served_from_the_root(client: TestClient) -> None:
    response = client.get("/sw.js")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/javascript")
    assert response.headers["cache-control"] == "no-cache"
    assert "addEventListener" in response.text


def test_service_worker_intercepts_only_the_share_post() -> None:
    source = SERVICE_WORKER.read_text(encoding="utf-8")

    assert 'event.request.method !== "POST"' in source
    assert "url.pathname !== RESULT_URL" in source


def test_service_worker_calls_the_guarded_api_and_caches_nothing() -> None:
    source = SERVICE_WORKER.read_text(encoding="utf-8")

    assert "/api/pins/resolve" in source
    assert "X-PinSaver-Request" in source
    assert "caches" not in source


def test_site_registers_the_root_worker_and_drops_the_old_one(client: TestClient) -> None:
    """The page's own JS must register /sw.js and unregister the /static/sw.js registration."""
    app_js = client.get("/static/app.js").text

    assert "register('/sw.js')" in app_js
    assert "/static/sw.js" in app_js
    assert "unregister()" in app_js
