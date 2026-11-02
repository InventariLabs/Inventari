"""Tests for the single expiry-count entry point."""

from __future__ import annotations

import asyncio
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.storage._queries import count_expiring_soon_async


def _run(coro):
    return asyncio.run(coro)


def _db_returning(rows):
    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(all=lambda: rows))
    return db


@pytest.mark.unit
class TestCountExpiringSoon:
    """count_expiring_soon_async — one location asked of the per-location count."""

    @pytest.fixture(autouse=True)
    def _today(self):
        with patch(
            'app.services.items.expiry.expiry_today_async',
            AsyncMock(return_value=date(2026, 1, 1)),
        ):
            yield

    def test_counts_expiring_items(self):
        storage_id = uuid4()
        db = _db_returning([(storage_id, 4)])

        result = _run(count_expiring_soon_async(db, uuid4(), storage_id, days=7))
        assert result == 4

    def test_respects_custom_window(self):
        storage_id = uuid4()
        db = _db_returning([(storage_id, 2)])

        result = _run(count_expiring_soon_async(db, uuid4(), storage_id, days=14))
        assert result == 2

    def test_zero_when_none_expiring(self):
        db = _db_returning([])

        result = _run(count_expiring_soon_async(db, uuid4(), uuid4(), days=7))
        assert result == 0
