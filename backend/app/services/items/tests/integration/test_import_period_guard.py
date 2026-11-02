"""Integration tests: failed import rows must not be persisted.

When a row of a bulk CSV/XLSX import fails *after* the item was flushed —
e.g. the current inventory period is closed and ``check_not_closed_async``
raises — the per-row ``except`` swallowed the error, but the item stayed in
the session and the final ``db.commit()`` persisted it anyway. The user was
told the row failed while a phantom item silently appeared, and because
``apply_quantity_change_async`` was skipped, no movement stood behind it
(a record the ledger could not explain).

This test pins the fixed contract: a row that fails on a closed period
is reported as failed AND is absent from the DB AND leaves the movement
ledger untouched.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.models.item import Item
from app.models.stock_move import StockMove
from app.models.storage_location import StorageLocation
from app.modules.warehouse.inventory_period_service import close_period
from app.services.items import import_items
from app.services.items._stock_quant import apply_quantity_change_async


def _make_user_ctx(user) -> UserContextDTO:
    """Minimal user context matching what ``import_items`` reads."""
    return UserContextDTO(
        organization_id=user.organization_id,
        id=user.id,
        role='admin',
    )


def _make_csv_bytes(rows: list[dict]) -> bytes:
    """Encode rows as CSV bytes, matching the import endpoint's input."""
    return pd.DataFrame(rows).to_csv(index=False).encode()


async def _close_current_period(db: AsyncSession, org_id, user_id) -> None:
    """Close the period containing ``date.today()`` for the given org."""
    today = date.today()
    await close_period(db, org_id, today.year, today.month, user_id)


@pytest.mark.integration
class TestImportFailedRowNotPersisted:
    """Rows that fail during import must not leak into the DB."""

    async def test_import_row_failed_on_closed_period_is_not_persisted(
        self,
        real_async_db_session: AsyncSession,
        async_test_user,
        async_test_storage_location,
    ) -> None:
        """A row rejected on a closed period must not end up in the DB.

        Red today: the item is flushed, the period check raises, the per-row
        ``except`` swallows it, and the final commit persists the item while
        ``apply_quantity_change_async`` never ran — phantom item + missing
        movement.
        """
        await _close_current_period(
            real_async_db_session,
            async_test_user.organization_id,
            async_test_user.id,
        )

        moves_before = await real_async_db_session.scalar(
            select(func.count())
            .select_from(StockMove)
            .where(
                StockMove.organization_id == async_test_user.organization_id,
                StockMove.to_location_id == async_test_storage_location.id,
            )
        )

        result = await import_items(
            real_async_db_session,
            _make_csv_bytes([{'Name': 'Closed Period Row', 'Qty': 3}]),
            'test.csv',
            {'name': 'Name', 'quantity': 'Qty'},
            _make_user_ctx(async_test_user),
            create_missing_locations=False,
            create_missing_categories=False,
        )

        assert result['total'] == 1
        assert result['imported'] == 0
        assert result['failed'] == 1
        assert 'closed' in result['errors'][0]['error'].lower()

        # The failed row must not be persisted.
        item = (
            await real_async_db_session.scalars(
                select(Item).where(
                    Item.organization_id == async_test_user.organization_id,
                    Item.name == 'Closed Period Row',
                )
            )
        ).first()
        assert item is None

        # And it must not have leaked a movement onto the shelf either.
        moves_after = await real_async_db_session.scalar(
            select(func.count())
            .select_from(StockMove)
            .where(
                StockMove.organization_id == async_test_user.organization_id,
                StockMove.to_location_id == async_test_storage_location.id,
            )
        )
        assert moves_after == moves_before


@pytest.mark.integration
class TestImportFailedRowCacheRollback:
    """A failed row must not poison the shared storage/category caches.

    Storage/category created by a row are flushed inside the row savepoint
    AND recorded in the in-memory caches shared across rows.
    When the row fails later, the savepoint rolls back the INSERT — but the
    cache entry survives, pointing at an id that no longer exists. The next
    row reusing the same name then fails with an FK violation instead of
    importing cleanly.
    """

    async def test_failed_row_does_not_poison_storage_cache(
        self,
        real_async_db_session: AsyncSession,
        async_test_user,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Row 1 creates storage 'NewWH' then fails; row 2 reuses 'NewWH'.

        Red today: row 2 hits the poisoned cache and dies on an FK violation.
        Fixed: the failed row drops the cache entries it added, so row 2
        re-creates the storage and imports successfully.
        """
        calls = 0

        # **kwargs so the double follows the real signature rather than a
        # snapshot of it: the import path also passes who is importing.
        # ValueError on purpose: a refusal sentence is expected to name the
        # cause, and ``explain`` passes a ValueError through verbatim — so
        # the assertion below pins the actual reason this row failed, not
        # just its position.
        async def fail_first_call(db, item, new_quantity, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise ValueError('boom on first row')
            return await apply_quantity_change_async(db, item, new_quantity, **kwargs)

        # Import rows stopped calling this from _import itself: the row goes
        # through create_item_async, which applies the quantity in _create —
        # the patch follows the caller, not the old home of the name.
        monkeypatch.setattr(
            'app.services.items._create.apply_quantity_change_async',
            fail_first_call,
        )

        result = await import_items(
            real_async_db_session,
            _make_csv_bytes(
                [
                    {'Name': 'Row A', 'Qty': 1, 'Storage': 'NewWH'},
                    {'Name': 'Row B', 'Qty': 2, 'Storage': 'NewWH'},
                ]
            ),
            'test.csv',
            {'name': 'Name', 'quantity': 'Qty', 'location': 'Storage'},
            _make_user_ctx(async_test_user),
            create_missing_locations=True,
            create_missing_categories=False,
        )

        assert result['total'] == 2
        assert result['failed'] == 1
        # The cause travels with the row: the injected ValueError names it,
        # and the failure being THIS row's quantity write (not some other
        # refusal) is what makes the cache-rollback scenario real.
        assert 'boom on first row' in result['errors'][0]['error']
        # Row B must import cleanly — the poisoned cache must not FK-fail it.
        assert result['imported'] == 1

        item_b = (
            await real_async_db_session.scalars(
                select(Item).where(
                    Item.organization_id == async_test_user.organization_id,
                    Item.name == 'Row B',
                )
            )
        ).first()
        assert item_b is not None
        storage = await real_async_db_session.get(
            StorageLocation, item_b.storage_location_id
        )
        assert storage is not None
        assert storage.name == 'NewWH'
