"""A batch is the one question you ask once a year and cannot afford to fail.

When a supplier recalls a lot, the warehouse has hours to answer three
things: what came in under that number, where it is now, and where the rest
of it went. Every fact was already recorded — the receipt, the transfers,
the dispatches, the quantity left on each shelf — and no screen and no
endpoint put them together, so answering meant a database session.

So the core answers for one lot: what it is, what state it is in, how much
of it is still on hand and where. The movements themselves come from the
ledger, which already narrows by batch.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.public_api import core_api
from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.stock_lot import LotStatus, StockLot
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.uom import Uom, UomCategory
from app.models.user import User
from app.services.token_service import create_access_token
from tests.integration._shelf import put_on_shelf

# Best-before ahead of the clock, so the batch stays active whenever the suite runs.
_EXPIRY = date.today() + timedelta(days=400)


def _auth(user: User) -> dict[str, str]:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


class _Batch:
    """One recalled batch, and the paper trail behind it."""

    def __init__(self) -> None:
        self.org: Organization
        self.user: User
        self.aisle_one: StorageLocation
        self.aisle_two: StorageLocation
        self.flour: ProductTemplate
        self.lot: StockLot
        self.other_lot: StockLot


@pytest.fixture
async def batch(real_async_db_session: AsyncSession) -> _Batch:
    db = real_async_db_session
    fixture = _Batch()

    fixture.org = Organization(
        name=f'Batch Trace {uuid4().hex[:6]}',
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

    def _location(name: str) -> StorageLocation:
        location = StorageLocation(
            name=name,
            organization_id=fixture.org.id,
            storage_type_id=storage_type.id,
            created_by=fixture.user.id,
        )
        db.add(location)
        return location

    fixture.aisle_one = _location('Aisle 1')
    fixture.aisle_two = _location('Aisle 2')
    await db.flush()

    category = UomCategory(
        name=f'Weight {uuid4().hex[:6]}', organization_id=fixture.org.id
    )
    db.add(category)
    await db.flush()
    kilo = Uom(
        organization_id=fixture.org.id,
        name='Kilogram',
        symbol='kg',
        category_id=category.id,
        factor=1.0,
        is_reference=True,
    )
    db.add(kilo)
    await db.flush()

    fixture.flour = ProductTemplate(
        name='Rye flour', organization_id=fixture.org.id, uom_id=kilo.id
    )
    db.add(fixture.flour)
    await db.flush()

    fixture.lot = StockLot(
        organization_id=fixture.org.id,
        product_template_id=fixture.flour.id,
        name='L-2026-04',
        expiry_date=_EXPIRY,
        production_date=date(2026, 4, 2),
    )
    fixture.other_lot = StockLot(
        organization_id=fixture.org.id,
        product_template_id=fixture.flour.id,
        name='L-2026-05',
    )
    db.add_all([fixture.lot, fixture.other_lot])
    await db.flush()

    # Twenty kilos of the batch arrive, sixteen in aisle one and four in
    # aisle two; then ten single-kilo issues go out of aisle one.
    user = fixture.user
    aisle_one_stock = await put_on_shelf(
        db, user, fixture.flour, fixture.aisle_one.id, 16, lot_id=fixture.lot.id
    )
    await put_on_shelf(
        db, user, fixture.flour, fixture.aisle_two.id, 4, lot_id=fixture.lot.id
    )
    for left in range(15, 5, -1):
        await core_api.items.update_quantity_async(
            db, fixture.org.id, aisle_one_stock.id, Decimal(left), user_id=user.id
        )
    # The neighbouring batch, on the same shelf, which must never be counted in.
    await put_on_shelf(
        db, user, fixture.flour, fixture.aisle_one.id, 5, lot_id=fixture.other_lot.id
    )
    await db.commit()
    return fixture


class TestTheBatchNamesItself:
    async def test_the_batch_says_what_it_is(
        self, real_async_client: AsyncClient, batch: _Batch
    ) -> None:
        response = await real_async_client.get(
            f'/api/v1/stock-lots/{batch.lot.id}', headers=_auth(batch.user)
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body['name'] == 'L-2026-04'
        assert body['expiry_date'] == _EXPIRY.isoformat()
        assert body['production_date'] == '2026-04-02'
        assert body['status'] == LotStatus.ACTIVE

    async def test_the_batch_names_its_product_not_its_key(
        self, real_async_client: AsyncClient, batch: _Batch
    ) -> None:
        response = await real_async_client.get(
            f'/api/v1/stock-lots/{batch.lot.id}', headers=_auth(batch.user)
        )

        body = response.json()
        # A recall notice quotes a product, not a UUID.
        assert body['product_name'] == 'Rye flour'
        assert body['uom_symbol'] == 'kg'

    async def test_a_quarantined_batch_says_so(
        self,
        real_async_client: AsyncClient,
        batch: _Batch,
        real_async_db_session: AsyncSession,
    ) -> None:
        batch.lot.status = LotStatus.RECALLED
        real_async_db_session.add(batch.lot)
        await real_async_db_session.commit()

        response = await real_async_client.get(
            f'/api/v1/stock-lots/{batch.lot.id}', headers=_auth(batch.user)
        )

        assert response.json()['status'] == LotStatus.RECALLED


class TestTheBatchSaysWhereItIs:
    async def test_it_reports_what_is_left_and_where(
        self, real_async_client: AsyncClient, batch: _Batch
    ) -> None:
        response = await real_async_client.get(
            f'/api/v1/stock-lots/{batch.lot.id}', headers=_auth(batch.user)
        )

        body = response.json()
        assert Decimal(body['on_hand']) == Decimal('10.000')
        places = {
            row['location_name']: Decimal(row['quantity']) for row in body['locations']
        }
        assert places == {'Aisle 1': Decimal('6.000'), 'Aisle 2': Decimal('4.000')}

    async def test_it_does_not_count_the_batch_next_to_it(
        self, real_async_client: AsyncClient, batch: _Batch
    ) -> None:
        response = await real_async_client.get(
            f'/api/v1/stock-lots/{batch.other_lot.id}', headers=_auth(batch.user)
        )

        # Same product, same shelf, different batch — the whole point.
        assert Decimal(response.json()['on_hand']) == Decimal('5.000')

    async def test_a_batch_with_nothing_left_still_answers(
        self,
        real_async_client: AsyncClient,
        batch: _Batch,
        real_async_db_session: AsyncSession,
    ) -> None:
        empty = StockLot(
            organization_id=batch.org.id,
            product_template_id=batch.flour.id,
            name='L-GONE',
        )
        real_async_db_session.add(empty)
        await real_async_db_session.commit()

        response = await real_async_client.get(
            f'/api/v1/stock-lots/{empty.id}', headers=_auth(batch.user)
        )

        # A recall asks about batches that are gone more often than about
        # batches still on the shelf.
        assert response.status_code == status.HTTP_200_OK
        assert Decimal(response.json()['on_hand']) == Decimal('0')
        assert response.json()['locations'] == []

    async def test_a_drained_shelf_stops_answering_where_it_is(
        self,
        real_async_client: AsyncClient,
        batch: _Batch,
        real_async_db_session: AsyncSession,
    ) -> None:
        """A shelf the batch fully left stops naming itself as where it is.

        A quant drained to zero stays in the table forever, and the one place
        the batch used to sit kept the answer to "where is it" pointed at a
        shelf holding none of it — while the page's own nothingLeft message,
        written for exactly this end of a batch's life, stayed unreachable.
        """
        emptied_shelf = StorageLocation(
            organization_id=batch.org.id,
            storage_type_id=batch.aisle_one.storage_type_id,
            created_by=batch.user.id,
            name='Aisle 3',
        )
        real_async_db_session.add(emptied_shelf)
        await real_async_db_session.flush()
        # The batch used to sit here too; the shelf drained to zero and the
        # quant row stayed, as drained quants do.
        drained = await put_on_shelf(
            real_async_db_session,
            batch.user,
            batch.flour,
            emptied_shelf.id,
            2,
            lot_id=batch.lot.id,
        )
        await core_api.items.update_quantity_async(
            real_async_db_session,
            batch.org.id,
            drained.id,
            Decimal('0'),
            user_id=batch.user.id,
        )
        await real_async_db_session.commit()

        response = await real_async_client.get(
            f'/api/v1/stock-lots/{batch.lot.id}', headers=_auth(batch.user)
        )

        assert response.status_code == status.HTTP_200_OK
        # On hand is unchanged, and the emptied shelf stops answering for
        # the batch — only the shelves holding some of it remain.
        assert Decimal(response.json()['on_hand']) == Decimal('10.000')
        places = {
            row['location_name']: Decimal(row['quantity'])
            for row in response.json()['locations']
        }
        assert places == {'Aisle 1': Decimal('6.000'), 'Aisle 2': Decimal('4.000')}


class TestTheTrailAddsUp:
    async def test_ten_issues_are_ten_rows_and_they_match_the_stock(
        self, real_async_client: AsyncClient, batch: _Batch
    ) -> None:
        detail = await real_async_client.get(
            f'/api/v1/stock-lots/{batch.lot.id}', headers=_auth(batch.user)
        )
        ledger = await real_async_client.get(
            '/api/v1/stock-moves',
            params={'lot_id': str(batch.lot.id), 'limit': 100},
            headers=_auth(batch.user),
        )

        rows = ledger.json()['items']
        issues = [row for row in rows if row['to_location_id'] is None]
        assert len(issues) == 10
        # The ledger and the shelf are two independent records of the same
        # goods. If they disagree, one of them is lying and the batch cannot
        # be traced at all.
        received = sum(
            Decimal(row['quantity']) for row in rows if row['from_location_id'] is None
        )
        issued = sum(Decimal(row['quantity']) for row in issues)
        assert received - issued == Decimal(detail.json()['on_hand'])

    async def test_the_trail_leaves_the_neighbouring_batch_out(
        self, real_async_client: AsyncClient, batch: _Batch
    ) -> None:
        ledger = await real_async_client.get(
            '/api/v1/stock-moves',
            params={'lot_id': str(batch.lot.id), 'limit': 100},
            headers=_auth(batch.user),
        )

        # Its own two arrivals, one per shelf, and its ten issues.
        assert ledger.json()['total'] == 12


class TestTheBatchBelongsToOneOrganization:
    async def test_another_organization_cannot_read_the_batch(
        self,
        real_async_client: AsyncClient,
        batch: _Batch,
        real_async_db_session: AsyncSession,
    ) -> None:
        db = real_async_db_session
        stranger_org = Organization(
            name=f'Stranger {uuid4().hex[:6]}', enabled_modules=['core', 'items']
        )
        db.add(stranger_org)
        await db.commit()
        stranger = await ModuleTestHelper.create_user_async(
            db, stranger_org, email=f'stranger_{uuid4().hex[:8]}@test.com'
        )
        await db.commit()

        response = await real_async_client.get(
            f'/api/v1/stock-lots/{batch.lot.id}', headers=_auth(stranger)
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_a_batch_that_does_not_exist_is_a_404(
        self, real_async_client: AsyncClient, batch: _Batch
    ) -> None:
        response = await real_async_client.get(
            f'/api/v1/stock-lots/{uuid4()}', headers=_auth(batch.user)
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestTheBatchTellsItsDecisions:
    """The history section promises everything that happened to the batch.

    A quarantine is a decision somebody made for a reason on a day — the
    entry was already in ``meta_data['status_history']`` — and a trail that
    skips it answers the recall question halfway.
    """

    async def test_the_history_names_who_decided_and_why(
        self,
        real_async_client: AsyncClient,
        batch: _Batch,
        real_async_db_session: AsyncSession,
    ) -> None:
        batch.lot.meta_data = {
            'status_history': [
                {
                    'status': 'quarantined',
                    'reason': 'supplier notice 41/26',
                    'at': '2026-09-01T08:00:00+00:00',
                    'by': str(batch.user.id),
                },
                {
                    'status': 'active',
                    'reason': 'released after the check',
                    'at': '2026-09-03T10:00:00+00:00',
                    'by': str(batch.user.id),
                },
            ]
        }
        real_async_db_session.add(batch.lot)
        await real_async_db_session.commit()

        response = await real_async_client.get(
            f'/api/v1/stock-lots/{batch.lot.id}', headers=_auth(batch.user)
        )

        assert response.status_code == status.HTTP_200_OK
        history = response.json()['status_history']
        # The reader came for the latest decision; it speaks first.
        assert [entry['status'] for entry in history] == ['active', 'quarantined']
        assert history[0]['reason'] == 'released after the check'
        # A name, not the UUID the entry stores.
        assert history[0]['by_name'] == batch.user.full_name
        assert history[1]['at'].startswith('2026-09-01')

    async def test_a_batch_nobody_ever_decided_about_has_no_history(
        self, real_async_client: AsyncClient, batch: _Batch
    ) -> None:
        response = await real_async_client.get(
            f'/api/v1/stock-lots/{batch.lot.id}', headers=_auth(batch.user)
        )

        assert response.json()['status_history'] == []
