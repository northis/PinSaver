"""
The extension manifest and the hosts the extension is allowed to talk to.

The manifest is hand-written and lives in the repository, so a host committed here is a
leak: the archive address is chosen by the user at runtime, and this module pins the
declared permissions to Pinterest and localhost.
"""
from __future__ import annotations

import json
from pathlib import Path

EXTENSION = Path(__file__).resolve().parent.parent / "extension"
MANIFEST = EXTENSION / "manifest.json"
CONTENT_SCRIPT = EXTENSION / "content.js"
HOST_PERMISSIONS = {
    "https://*.pinterest.com/*",
    "http://localhost:8000/*",
    "http://127.0.0.1:8000/*",
}
OPTIONAL_HOST_PERMISSIONS = {"http://*/*", "https://*/*"}


def manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_manifest_is_mv3() -> None:
    assert manifest()["manifest_version"] == 3


def test_optional_host_permissions_cover_runtime_hosts() -> None:
    """Chrome refuses `permissions.request` for an origin that no optional permission
    covers, so both schemes have to be declared before the prompt can appear."""
    assert set(manifest()["optional_host_permissions"]) == OPTIONAL_HOST_PERMISSIONS


def test_host_permissions_are_only_pinterest_and_localhost() -> None:
    """Anything added here is committed to the repository, so the archive address is
    granted at runtime instead: any host beyond Pinterest and localhost fails this test."""
    assert set(manifest()["host_permissions"]) == HOST_PERMISSIONS


def test_content_script_does_not_mention_server_url() -> None:
    """The content script sends only a path: the background script owns the archive
    address, so a forged page cannot aim the extension at another host."""
    assert "serverUrl" not in CONTENT_SCRIPT.read_text(encoding="utf-8")
