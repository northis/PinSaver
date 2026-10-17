"""
Shared fixtures for the offline test suite.

Tests never touch the real archive and never reach the network: `PINSAVER_DATA_DIR`
points every path at a temporary directory, so the database and `originals/` of the
working copy stay untouched.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402


@pytest.fixture()
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Temporary archive directory: the database and originals/ live here."""
    monkeypatch.setenv("PINSAVER_DATA_DIR", str(tmp_path))
    (tmp_path / "originals").mkdir()
    return tmp_path


@pytest.fixture()
def client(data_dir: Path) -> TestClient:
    """TestClient whose app reads its data from the temporary directory."""
    with TestClient(server.app) as test_client:
        yield test_client
