"""Pytest fixtures."""

from __future__ import annotations

import os
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio

from verre import config as config_module


@pytest.fixture(autouse=True)
def _env_setup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    # Stable Fernet key for tests
    monkeypatch.setenv("VERRE_ENCRYPTION_KEY", "u8WfH-pUF7c2bg0c7v_dG6XJjzgJjB7mZ-MeP0a3jJk=")
    monkeypatch.setenv("VERRE_DB_PATH", str(tmp_path / "verre.db"))
    monkeypatch.setenv("VERRE_POLL_INTERVAL_SECONDS", "1")
    monkeypatch.setenv("VERRE_BINANCE_TESTNET", "true")
    monkeypatch.setenv("VERRE_ALLOWED_TELEGRAM_IDS", "")
    config_module.reload_settings()


@pytest_asyncio.fixture
async def _db() -> AsyncIterator[None]:
    from verre.db import dispose_db, init_db

    await init_db()
    yield
    await dispose_db()


# Ensure repo root is on sys.path when run with `pytest` directly.
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
