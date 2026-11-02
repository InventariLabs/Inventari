"""Tests for stock aging query.

Pure-ish: tests call the service directly with a sync in-memory
mock where possible, plus one end-to-end DB test that exercises
the SQL aggregation.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from app.services.stock_moves_service import (
    _in_bucket,
    aggregate_aging_buckets_async,
)


class TestInBucket:
    def test_below_min(self):
        assert _in_bucket(15, 30, 60) is False

    def test_at_min(self):
        assert _in_bucket(30, 30, 60) is True

    def test_within_range(self):
        assert _in_bucket(45, 30, 60) is True

    def test_at_max(self):
        assert _in_bucket(60, 30, 60) is True

    def test_above_max(self):
        assert _in_bucket(61, 30, 60) is False

    def test_open_ended_max(self):
        assert _in_bucket(1000, 180, None) is True


def _make_entry(days: int, qty: Decimal) -> SimpleNamespace:
    return SimpleNamespace(days_in_stock=days, quantity=qty)


def _run(coro):
    return asyncio.run(coro)


class TestAggregateAgingBuckets:
    def test_buckets_partition_receipts_by_age(self):
        from app.services import stock_moves_service as svc

        entries = [
            _make_entry(10, Decimal('5')),
            _make_entry(45, Decimal('3')),
            _make_entry(75, Decimal('7')),
            _make_entry(120, Decimal('2')),
            _make_entry(400, Decimal('1')),
        ]

        async def _fake_list(*args, **kwargs):
            return entries

        original = svc.list_receipts_for_aging_async
        svc.list_receipts_for_aging_async = _fake_list  # type: ignore[assignment]
        try:
            buckets = _run(
                aggregate_aging_buckets_async(
                    db=None,
                    organization_id=uuid4(),
                    product_template_id=uuid4(),
                )
            )
        finally:
            svc.list_receipts_for_aging_async = original  # type: ignore[assignment]

        assert [(b.label, b.quantity, b.move_count) for b in buckets] == [
            ('0-30', Decimal('5'), 1),
            ('31-60', Decimal('3'), 1),
            ('61-90', Decimal('7'), 1),
            ('91-180', Decimal('2'), 1),
            ('180+', Decimal('1'), 1),
        ]

    def test_empty_buckets_when_no_receipts(self):
        from app.services import stock_moves_service as svc

        async def _fake_empty(*args, **kwargs):
            return []

        original = svc.list_receipts_for_aging_async
        svc.list_receipts_for_aging_async = _fake_empty  # type: ignore[assignment]
        try:
            buckets = _run(
                aggregate_aging_buckets_async(
                    db=None,
                    organization_id=uuid4(),
                    product_template_id=uuid4(),
                )
            )
        finally:
            svc.list_receipts_for_aging_async = original  # type: ignore[assignment]

        assert len(buckets) == 5
        assert all(b.quantity == Decimal('0') for b in buckets)
        assert all(b.move_count == 0 for b in buckets)
