"""Smoke tests for DB models / migrations."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from verre.db import init_db, session_scope
from verre.models import ApiKey, User


@pytest.mark.asyncio
async def test_create_user_and_attach_keys(_db: None) -> None:
    async with session_scope() as session:
        user = User(telegram_id=12345, username="alice", mode="dryrun", size_percent=2.5)
        session.add(user)
        await session.flush()
        session.add(ApiKey(user_id=user.id, encrypted_key="enc-k", encrypted_secret="enc-s"))

    async with session_scope() as session:
        row = (await session.execute(select(User).where(User.telegram_id == 12345))).scalar_one()
        assert row.mode == "dryrun"
        assert row.size_percent == 2.5
        key = (await session.execute(select(ApiKey).where(ApiKey.user_id == row.id))).scalar_one()
        assert key.encrypted_key == "enc-k"


@pytest.mark.asyncio
async def test_init_db_idempotent(_db: None) -> None:
    # second call should not raise
    await init_db()
