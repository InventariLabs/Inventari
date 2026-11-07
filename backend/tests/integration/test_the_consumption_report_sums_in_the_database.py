"""The consumption report adds its quantities up where the rows live.

The report used to pull every use and every disposal in the window into
Python and read ``qty`` out of each row's JSON there — an active organization
over ninety days sent tens of thousands of rows across the wire to produce
twenty lines. The sum now happens in SQL, grouped per record, and the figures
must not move: this test pins the answer the row-by-row version gave on a
window that exercises every branch it had — two records sharing a name, both
vocabularies of each kind, a row with no quantity, a row with no changes at
all, an edit that is neither kind, a row older than the window and a stranger
organization's row.

The second test widens the query on purpose: the kind of a row is decided by
the mapping the report keeps, not by the WHERE clause, and a row the mapping
cannot name is left out with a trace in the log.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.category import Category
from app.models.item import Item
from app.models.item_history import ItemHistory
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.stock_valuation_layer import StockValuationLayer
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.services.analytics import consumption
from app.services.analytics.consumption import get_consumption_stats_async
from tests.integration._shelf import anchor_pending_records

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _organization(db: AsyncSession) -> tuple[Organization, StorageLocation]:
    from app.core.testing import ModuleTestHelper

    org = Organization(
        name=f'Consumption {uuid.uuid4().hex[:6]}',
        enabled_modules=['core', 'items', 'locations', 'stats'],
        currency='EUR',
    )
    db.add(org)
    await db.flush()
    user = await ModuleTestHelper.create_user_async(
        db, org, email=f'consumption_{uuid.uuid4().hex[:8]}@test.com', role='admin'
    )
    storage_type = StorageType(
        name='Shelf', type_code=f'SHELF_{uuid.uuid4().hex[:6]}', behavior_mode='NONE'
    )
    db.add(storage_type)
    await db.flush()
    location = StorageLocation(
        name='Pantry',
        organization_id=org.id,
        storage_type_id=storage_type.id,
        created_by=user.id,
    )
    db.add(location)
    await db.flush()
    return org, location


async def _record(
    db: AsyncSession,
    org: Organization,
    location: StorageLocation,
    name: str,
    category: Category | None = None,
    *,
    item_id: uuid.UUID | None = None,
) -> Item:
    template = ProductTemplate(name=name, organization_id=org.id)
    db.add(template)
    await db.flush()
    item = Item(
        id=item_id or uuid.uuid4(),
        organization_id=org.id,
        storage_location_id=location.id,
        template_id=template.id,
        category_id=category.id if category else None,
        name=name,
        quantity=Decimal('1'),
        currency='EUR',
    )
    db.add(item)
    await db.run_sync(anchor_pending_records)
    await db.flush()
    return item


def _row(
    item: Item, action: str, changes: dict | None, *, days_ago: int = 1
) -> ItemHistory:
    return ItemHistory(
        organization_id=item.organization_id,
        item_id=item.id,
        action=action,
        changes=changes,
        created_at=datetime.now(UTC) - timedelta(days=days_ago),
    )


def _layer(item: Item, reason: str, value: str) -> StockValuationLayer:
    return StockValuationLayer(
        organization_id=item.organization_id,
        product_template_id=item.template_id,
        item_id=item.id,
        quantity=Decimal('1'),
        remaining_qty=Decimal('0'),
        unit_cost=Decimal(value),
        total_value=Decimal(value),
        direction='OUT',
        reason=reason,
        created_at=datetime.now(UTC) - timedelta(days=1),
    )


@pytest.fixture
async def window(real_async_db_session: AsyncSession) -> Organization:
    db = real_async_db_session
    org, location = await _organization(db)
    dairy = Category(name='Dairy', code=f'dairy_{uuid.uuid4().hex[:6]}')
    db.add(dairy)
    await db.flush()

    milk_a = await _record(db, org, location, 'Milk', dairy)
    milk_b = await _record(db, org, location, 'Milk', dairy)
    bread = await _record(db, org, location, 'Bread')

    stranger, stranger_location = await _organization(db)
    foreign = await _record(db, stranger, stranger_location, 'Milk')

    db.add_all(
        [
            _row(milk_a, 'USED', {'qty': 1.5, 'old': 5.0}),
            _row(milk_a, 'USED', {'qty': 2.0, 'old': 3.5}),
            _row(milk_b, 'USED', {'qty': 0.25, 'old': 1.0}),
            _row(milk_b, 'USED', None),
            _row(bread, 'USED', {}),
            _row(bread, 'DISPOSED', {'qty': 3.0, 'reason': 'EXPIRED'}),
            _row(bread, 'DISPOSED', {'qty': 1.0}),
            # Neither kind: an edit is not an outflow.
            _row(milk_a, 'UPDATED', {'qty': 99.0}),
            # Before the window.
            _row(milk_a, 'USED', {'qty': 50.0}, days_ago=200),
            # Someone else's shelf.
            _row(foreign, 'USED', {'qty': 7.0}),
            _layer(milk_a, 'USED', '5'),
            _layer(milk_b, 'USED', '1'),
            _layer(bread, 'DISPOSED', '2.5'),
            _layer(foreign, 'USED', '9'),
        ]
    )
    await db.commit()
    return org


async def test_the_figures_are_the_ones_the_row_by_row_sum_gave(
    real_async_db_session: AsyncSession, window: Organization
) -> None:
    stats = await get_consumption_stats_async(real_async_db_session, window.id)

    consumed = [(c.name, c.category, c.quantity, c.value) for c in stats.most_consumed]
    assert consumed == [('Milk', 'Dairy', 3.75, 6.0), ('Bread', 'Other', 0.0, 0.0)]
    wasted = [(c.name, c.category, c.quantity, c.value) for c in stats.most_wasted]
    assert wasted == [('Bread', 'Other', 4.0, 2.5)]
    # Five uses and two disposals: the rate counts events, not records.
    assert stats.waste_event_rate == pytest.approx(2 / 7)
    assert stats.total_consumed_value == 6.0
    assert stats.total_wasted_value == 2.5


async def test_a_row_the_mapping_cannot_name_is_left_out_and_logged(
    real_async_db_session: AsyncSession,
    window: Organization,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(
        consumption,
        '_QUERIED_ACTIONS',
        (*consumption._QUERIED_ACTIONS, 'UPDATED'),
    )

    with caplog.at_level('WARNING'):
        stats = await get_consumption_stats_async(real_async_db_session, window.id)

    assert [c.quantity for c in stats.most_consumed] == [3.75, 0.0]
    assert stats.waste_event_rate == pytest.approx(2 / 7)
    skips = [r for r in caplog.records if 'cannot name' in r.getMessage()]
    assert len(skips) == 1
    assert "{'UPDATED': 1}" in skips[0].getMessage()


#: Twelve products, made in the reverse of their names' order and with ids
#: that sort the same way, so neither the order the rows were written in nor
#: the order of their ids is the order of their names.
_TIED = [f'Product {letter}' for letter in 'LKJIHGFEDCBA']


@pytest.fixture
async def tied_window(real_async_db_session: AsyncSession) -> Organization:
    """One clear leader and eleven products tied behind it, in both rankings."""
    db = real_async_db_session
    org, location = await _organization(db)
    leader = await _record(db, org, location, 'Leader')
    rows: list[object] = [
        _row(leader, 'USED', {'qty': 5.0}),
        _row(leader, 'DISPOSED', {'qty': 5.0}),
        _layer(leader, 'DISPOSED', '9.00'),
    ]
    first_id = uuid.uuid4().int & ~0xFF
    for position, name in enumerate(_TIED):
        item = await _record(
            db, org, location, name, item_id=uuid.UUID(int=first_id + position)
        )
        rows += [
            _row(item, 'USED', {'qty': 2.0}),
            _row(item, 'DISPOSED', {'qty': 1.0}),
            _layer(item, 'DISPOSED', '3.50'),
        ]
    db.add_all(rows)
    await db.commit()
    return org


async def test_a_tie_at_the_tenth_place_is_settled_by_the_name(
    real_async_db_session: AsyncSession, tied_window: Organization
) -> None:
    """Equal products are listed in the order of their names, both rankings.

    The rows come out of a ``GROUP BY`` in no order of their own, and both
    rankings sorted by the figure alone: which of eleven equal products made
    the top ten was settled by the order the database happened to return
    them in, and the same window could name a different tenth product on the
    next reading.
    """
    stats = await get_consumption_stats_async(real_async_db_session, tied_window.id)

    expected = ['Leader', *sorted(_TIED)[:9]]
    assert [c.name for c in stats.most_consumed] == expected
    assert [c.quantity for c in stats.most_consumed] == [5.0] + [2.0] * 9
    assert [c.name for c in stats.most_wasted] == expected
    assert [c.value for c in stats.most_wasted] == [9.0] + [3.5] * 9
