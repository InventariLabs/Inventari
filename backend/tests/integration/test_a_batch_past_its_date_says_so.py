"""A batch past its date is expired, and nobody had to say so.

``LotStatus.EXPIRED`` has existed in the contract since batches did, and
nothing ever set it: no job, no query, no derivation from ``expiry_date``.
The only writers were quarantine, release and a manual PATCH, so the tab
called "Expired" answered "no batch is in this state" over a shelf of
batches a month past their date — and the picking gate, which reads the
status, let every one of them through, because the status said Active.

The date is the fact; the status column is what somebody decided. So the
date is read where the state is asked for, and a decision — quarantined,
held, recalled — still outranks it: a batch withdrawn on a supplier's
notice does not become merely "expired" when its date passes.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.stock_lot import LotStatus, StockLot
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.user import User
from app.services.token_service import create_access_token
from tests.integration._shelf import put_on_shelf

_TODAY = datetime.now(UTC).date()
_LAST_MONTH = _TODAY - timedelta(days=30)
_NEXT_MONTH = _TODAY + timedelta(days=30)


def _auth(user: User) -> dict[str, str]:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


class _Dated:
    def __init__(self) -> None:
        self.org: Organization
        self.user: User
        self.aisle: StorageLocation
        self.flour: ProductTemplate
        self.stale: StockLot
        self.fresh: StockLot
        self.recalled_and_stale: StockLot


@pytest.fixture
async def dated(real_async_db_session: AsyncSession) -> _Dated:
    db = real_async_db_session
    fixture = _Dated()

    fixture.org = Organization(
        name=f'Dated Batches {uuid4().hex[:6]}',
        enabled_modules=['core', 'items', 'locations'],
    )
    db.add(fixture.org)
    await db.commit()
    await db.refresh(fixture.org)

    fixture.user = await ModuleTestHelper.create_user_async(
        db, fixture.org, email=f'keeper_{uuid4().hex[:8]}@test.com'
    )
    await db.commit()

    storage_type = StorageType(
        name='Shelf', type_code=f'SHELF_{uuid4().hex[:6]}', behavior_mode='NONE'
    )
    db.add(storage_type)
    await db.flush()

    fixture.aisle = StorageLocation(
        name='Aisle 1',
        organization_id=fixture.org.id,
        storage_type_id=storage_type.id,
        created_by=fixture.user.id,
    )
    db.add(fixture.aisle)
    await db.flush()

    fixture.flour = ProductTemplate(name='Rye flour', organization_id=fixture.org.id)
    db.add(fixture.flour)
    await db.flush()

    fixture.stale = StockLot(
        organization_id=fixture.org.id,
        product_template_id=fixture.flour.id,
        name='L-STALE',
        expiry_date=_LAST_MONTH,
    )
    fixture.fresh = StockLot(
        organization_id=fixture.org.id,
        product_template_id=fixture.flour.id,
        name='L-FRESH',
        expiry_date=_NEXT_MONTH,
    )
    fixture.recalled_and_stale = StockLot(
        organization_id=fixture.org.id,
        product_template_id=fixture.flour.id,
        name='L-RECALLED',
        expiry_date=_LAST_MONTH,
    )
    db.add_all([fixture.stale, fixture.fresh, fixture.recalled_and_stale])
    await db.flush()

    for lot in (fixture.stale, fixture.fresh, fixture.recalled_and_stale):
        await put_on_shelf(
            db, fixture.user, fixture.flour, fixture.aisle.id, 10, lot_id=lot.id
        )
    fixture.recalled_and_stale.status = LotStatus.RECALLED
    await db.commit()
    return fixture


class TestTheDateIsRead:
    async def test_a_batch_past_its_date_is_expired_without_anyone_saying_so(
        self, real_async_client: AsyncClient, dated: _Dated
    ) -> None:
        detail = await real_async_client.get(
            f'/api/v1/stock-lots/{dated.stale.id}', headers=_auth(dated.user)
        )

        assert detail.status_code == status.HTTP_200_OK
        assert detail.json()['status'] == LotStatus.EXPIRED

    async def test_a_batch_still_in_date_is_untouched(
        self, real_async_client: AsyncClient, dated: _Dated
    ) -> None:
        detail = await real_async_client.get(
            f'/api/v1/stock-lots/{dated.fresh.id}', headers=_auth(dated.user)
        )

        assert detail.json()['status'] == LotStatus.ACTIVE

    async def test_a_decision_outranks_the_date(
        self, real_async_client: AsyncClient, dated: _Dated
    ) -> None:
        detail = await real_async_client.get(
            f'/api/v1/stock-lots/{dated.recalled_and_stale.id}',
            headers=_auth(dated.user),
        )

        # "Recalled" answers a question "expired" does not, and somebody
        # made that call. The date does not overwrite it.
        assert detail.json()['status'] == LotStatus.RECALLED

    async def test_the_tab_that_was_always_empty_has_the_batch_in_it(
        self, real_async_client: AsyncClient, dated: _Dated
    ) -> None:
        listing = await real_async_client.get(
            '/api/v1/stock-lots',
            params={'status': LotStatus.EXPIRED},
            headers=_auth(dated.user),
        )

        body = listing.json()
        assert [row['name'] for row in body['items']] == ['L-STALE']
        assert body['total'] == 1

    async def test_the_active_tab_no_longer_shows_it(
        self, real_async_client: AsyncClient, dated: _Dated
    ) -> None:
        listing = await real_async_client.get(
            '/api/v1/stock-lots',
            params={'status': LotStatus.ACTIVE},
            headers=_auth(dated.user),
        )

        assert [row['name'] for row in listing.json()['items']] == ['L-FRESH']


class TestTheShelfAgrees:
    async def test_an_expired_batch_offers_nothing_to_a_planner(
        self, real_async_client: AsyncClient, dated: _Dated
    ) -> None:
        rows = (
            await real_async_client.get(
                '/api/v1/stock-quants',
                params={'lot_id': str(dated.stale.id)},
                headers=_auth(dated.user),
            )
        ).json()['items']

        assert rows[0]['lot_status'] == LotStatus.EXPIRED
        assert Decimal(rows[0]['quantity']) == Decimal('10.000')
        assert Decimal(rows[0]['available_quantity']) == Decimal('0')

    async def test_a_batch_in_date_still_counts(
        self, real_async_client: AsyncClient, dated: _Dated
    ) -> None:
        rows = (
            await real_async_client.get(
                '/api/v1/stock-quants',
                params={'lot_id': str(dated.fresh.id)},
                headers=_auth(dated.user),
            )
        ).json()['items']

        assert Decimal(rows[0]['available_quantity']) == Decimal('10.000')


class TestThePickerIsNotHandedIt:
    async def test_the_expired_batch_is_not_chosen_before_the_fresh_one(
        self, dated: _Dated, real_async_db_session: AsyncSession
    ) -> None:
        from app.services._stock_quant_query import (
            find_best_pick_group_for_picking_async,
        )

        chosen = await find_best_pick_group_for_picking_async(
            real_async_db_session,
            dated.org.id,
            dated.flour.id,
            storage_location_id=dated.aisle.id,
        )

        # The earliest date first is exactly the wrong answer once that date
        # is in the past.
        assert chosen is not None
        assert chosen.lot_id == dated.fresh.id

    async def test_naming_the_expired_batch_is_refused_in_words(
        self, dated: _Dated, real_async_db_session: AsyncSession
    ) -> None:
        from app.services._stock_quant_query import assert_lot_consumable_async

        with pytest.raises(ValueError, match='expired'):
            await assert_lot_consumable_async(real_async_db_session, dated.stale.id)
