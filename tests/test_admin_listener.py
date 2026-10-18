"""
One uvicorn process on two sockets: the admin port is the only place the maintenance page exists.

The port check reads the socket that accepted the request, so it is worth testing with real
sockets: a TestClient cannot tell a spoofed `Host` from a real listener.
"""
from __future__ import annotations

import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
import uvicorn

import server


def _get(port: int, path: str, attempts: int = 6) -> tuple[int, str]:
    """GET with retries: Windows resets rapid back-to-back urllib connections."""
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as response:
                return response.status, response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8")
        except OSError as exc:
            last = exc
            time.sleep(0.1 * (attempt + 1))
    raise AssertionError(f"no response from {port}{path}: {last!r}")


def _wait_until_ready(port: int, deadline: float) -> None:
    while time.monotonic() < deadline:
        try:
            if _get(port, "/health", attempts=1)[0] == 200:
                return
        except (AssertionError, OSError):
            pass
        time.sleep(0.05)
    pytest.fail(f"server on port {port} did not start")


def test_run_servers_binds_both_ports(monkeypatch: pytest.MonkeyPatch) -> None:
    sockets = iter([server._bind("127.0.0.1", 0), server._bind("127.0.0.1", 0)])
    monkeypatch.setattr(server, "_bind", lambda host, port: next(sockets))
    monkeypatch.setattr(server, "ADMIN_PORT", 8001)
    captured: dict = {}

    def fake_run(self, sockets=None):  # noqa: ANN001 - uvicorn.Server.run replacement
        captured["sockets"] = sockets

    monkeypatch.setattr(uvicorn.Server, "run", fake_run)

    server.run_servers()

    assert len(captured["sockets"]) == 2
    assert all(sock.fileno() == -1 for sock in captured["sockets"])  # closed in the finally


def test_run_servers_without_the_admin_port(monkeypatch: pytest.MonkeyPatch) -> None:
    """PINSAVER_ADMIN_PORT=0 (or a port equal to the site's) leaves a single listener."""
    sockets = iter([server._bind("127.0.0.1", 0)])
    monkeypatch.setattr(server, "_bind", lambda host, port: next(sockets))
    monkeypatch.setattr(server, "ADMIN_PORT", 0)
    captured: dict = {}

    def fake_run(self, sockets=None):  # noqa: ANN001 - uvicorn.Server.run replacement
        captured["sockets"] = sockets

    monkeypatch.setattr(uvicorn.Server, "run", fake_run)

    server.run_servers()

    assert len(captured["sockets"]) == 1
    assert captured["sockets"][0].fileno() == -1


def test_two_sockets_split_site_and_admin(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sockets = [server._bind("127.0.0.1", 0), server._bind("127.0.0.1", 0)]
    site_port = sockets[0].getsockname()[1]
    admin_port = sockets[1].getsockname()[1]
    monkeypatch.setattr(server, "ADMIN_PORT", admin_port)

    uvicorn_server = uvicorn.Server(uvicorn.Config(server.app, log_level="warning"))
    thread = threading.Thread(target=uvicorn_server.run, kwargs={"sockets": sockets}, daemon=True)
    thread.start()
    try:
        _wait_until_ready(site_port, time.monotonic() + 10)

        assert _get(site_port, "/api/admin/state")[0] == 404
        assert _get(site_port, "/admin")[0] == 404
        assert _get(site_port, "/health")[0] == 200

        status, page = _get(admin_port, "/admin")
        assert status == 200
        assert 'id="admin"' in page
        assert _get(admin_port, "/api/admin/state")[0] == 200
    finally:
        uvicorn_server.should_exit = True
        thread.join(timeout=10)
        for sock in sockets:
            sock.close()

    assert not thread.is_alive()
