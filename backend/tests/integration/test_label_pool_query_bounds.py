"""Generating a label pool costs a fixed number of queries, not one per label.

Each label used to ask the database twice whether its code was free, and once
more to reload itself after the commit: 485 statements for 120 labels, measured
in the request log. The modal offers up to 500 — the number somebody with a
sheet printer types once, and the only time they ever do it.

The bound below is deliberately loose. What it guards is the shape: a batch ten
times larger must not cost ten times more statements.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.schemas.label_pool import LabelPoolCreate
from app.services.label_service import LabelService

pytestmark = pytest.mark.integration


class _QueryCounter:
    def __init__(self) -> None:
        self.count = 0

    def reset(self) -> None:
        self.count = 0


@pytest.fixture
def query_counter() -> _QueryCounter:
    return _QueryCounter()


@pytest.fixture
def track_queries(
    real_async_db_session: AsyncSession, query_counter: _QueryCounter
) -> Iterator[None]:
    """Counts every SQL statement issued through the test's engine."""
    bind = real_async_db_session.get_bind()

    def before_cursor_execute(*_args: Any, **_kwargs: Any) -> None:
        query_counter.count += 1

    event.listen(bind, 'before_cursor_execute', before_cursor_execute)
    try:
        yield
    finally:
        event.remove(bind, 'before_cursor_execute', before_cursor_execute)


@pytest.mark.asyncio
class TestLabelPoolQueryBounds:
    async def test_five_hundred_labels_do_not_cost_five_hundred_queries(
        self,
        real_async_db_session: AsyncSession,
        async_test_user: Any,
        async_test_household: Any,
        query_counter: _QueryCounter,
        track_queries: None,
    ) -> None:
        user_ctx = UserContextDTO(
            id=async_test_user.id,
            email=async_test_user.email,
            organization_id=async_test_household.id,
            role='admin',
            full_name='Test User',
        )

        query_counter.reset()
        labels = await LabelService.generate_label_pool_async(
            real_async_db_session,
            LabelPoolCreate(count=500, prefix='QB'),
            user_ctx,
        )

        assert len(labels) == 500
        assert len({label.short_code for label in labels}) == 500
        # Read the taken codes (2), lock, insert, commit, reload the batch (1).
        # The old path issued about four per label.
        assert query_counter.count < 25, (
            f'{query_counter.count} statements for 500 labels — '
            'the batch is paying per row again'
        )

    async def test_a_batch_avoids_codes_already_taken(
        self,
        real_async_db_session: AsyncSession,
        async_test_user: Any,
        async_test_household: Any,
    ) -> None:
        """The in-memory draw still has to see what is already on the shelves."""
        user_ctx = UserContextDTO(
            id=async_test_user.id,
            email=async_test_user.email,
            organization_id=async_test_household.id,
            role='admin',
            full_name='Test User',
        )

        first = await LabelService.generate_label_pool_async(
            real_async_db_session, LabelPoolCreate(count=30, prefix='QC'), user_ctx
        )
        second = await LabelService.generate_label_pool_async(
            real_async_db_session, LabelPoolCreate(count=30, prefix='QC'), user_ctx
        )

        taken = {label.short_code for label in first}
        assert taken.isdisjoint({label.short_code for label in second})
