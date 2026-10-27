"""A recall asks one step back and one step forward.

EU 178/2002 Art. 18: name the immediate supplier and the immediate customer
of the batch, with quantities and dates. The ledger holds every crossing of
a batch with its date and quantity; the module that wrote it names the
partner. The trace puts the two together, per source rather than per row,
and follows a run that turned the batch into another one.

The sources here are registered by the test, the way a module registers its
own (``app.core.lot_trace``), so the Core's half is measured without any
module installed. The modules' own sources are measured in their trees.
"""

from __future__ import annotations

import io
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi import status
from httpx import AsyncClient
from openpyxl import load_workbook
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import LotTraceReferenceDTO
from app.core.lot_trace import (
    LotTraceSource,
    register_lot_trace_source,
    unregister_lot_trace_source,
)
from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.stock_lot import StockLot
from app.models.stock_move import StockMove
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.user import User
from app.services.token_service import create_access_token

_PAPER = 'trace_test_paper'
_RUN = 'trace_test_run'


def _auth(user: User) -> dict[str, str]:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


class _Paper(LotTraceSource):
    """A module's documents: a number and a partner for each."""

    reference_type = _PAPER

    def __init__(self) -> None:
        self.known: dict[UUID, LotTraceReferenceDTO] = {}

    async def describe_async(
        self, db: AsyncSession, organization_id: UUID, reference_ids: Sequence[UUID]
    ) -> dict[UUID, LotTraceReferenceDTO]:
        return {rid: self.known[rid] for rid in reference_ids if rid in self.known}


class _Run(LotTraceSource):
    """A module's production runs: they consume one batch and make another."""

    reference_type = _RUN
    transforms = True

    async def describe_async(
        self, db: AsyncSession, organization_id: UUID, reference_ids: Sequence[UUID]
    ) -> dict[UUID, LotTraceReferenceDTO]:
        return {rid: LotTraceReferenceDTO(label='RUN-1') for rid in reference_ids}


class _Recall:
    org: Organization
    user: User
    shelf: StorageLocation
    flour: StockLot
    bread: StockLot
    supplier: Partner
    shop: Partner
    receipt_id: UUID
    delivery_id: UUID
    run_id: UUID
    bread_delivery_id: UUID


@pytest.fixture
async def recall(real_async_db_session: AsyncSession) -> AsyncIterator[_Recall]:
    db = real_async_db_session
    paper, run = _Paper(), _Run()
    register_lot_trace_source(paper)
    register_lot_trace_source(run)
    fx = _Recall()

    fx.org = Organization(name=f'Mill {uuid4().hex[:6]}', enabled_modules=['core'])
    db.add(fx.org)
    await db.commit()
    fx.user = await ModuleTestHelper.create_user_async(
        db, fx.org, email=f'miller_{uuid4().hex[:8]}@test.com'
    )
    storage_type = StorageType(
        name='Shelf', type_code=f'SHELF_{uuid4().hex[:6]}', behavior_mode='NONE'
    )
    db.add(storage_type)
    await db.flush()
    fx.shelf = StorageLocation(
        name='Aisle 1',
        organization_id=fx.org.id,
        storage_type_id=storage_type.id,
        created_by=fx.user.id,
    )
    other_shelf = StorageLocation(
        name='Aisle 2',
        organization_id=fx.org.id,
        storage_type_id=storage_type.id,
        created_by=fx.user.id,
    )
    flour = ProductTemplate(name='Rye flour', organization_id=fx.org.id)
    bread = ProductTemplate(name='Rye bread', organization_id=fx.org.id)
    db.add_all([fx.shelf, other_shelf, flour, bread])
    await db.flush()
    fx.flour = StockLot(
        organization_id=fx.org.id, product_template_id=flour.id, name='F-01'
    )
    fx.bread = StockLot(
        organization_id=fx.org.id, product_template_id=bread.id, name='B-01'
    )
    fx.supplier = Partner(
        organization_id=fx.org.id,
        name='Grain Co (record)',
        type='SUPPLIER',
        address={'street': '1 Field Rd', 'city': 'Leeds', 'country': 'GB'},
        created_by=fx.user.id,
    )
    fx.shop = Partner(
        organization_id=fx.org.id,
        name='Corner Shop',
        type='CUSTOMER',
        address={'street': '2 High St', 'city': 'York'},
        created_by=fx.user.id,
    )
    db.add_all([fx.flour, fx.bread, fx.supplier, fx.shop])
    await db.flush()

    fx.receipt_id, fx.delivery_id = uuid4(), uuid4()
    fx.run_id, fx.bread_delivery_id = uuid4(), uuid4()
    undone_run = uuid4()
    # The receipt names its supplier as it stood on the paper; the delivery
    # names only the partner, whose record says the rest.
    paper.known[fx.receipt_id] = LotTraceReferenceDTO(
        label='GR/0001',
        partner_id=fx.supplier.id,
        partner_name='Grain Co',
        partner_address={'street': '1 Field Rd', 'city': 'Leeds'},
    )
    paper.known[fx.delivery_id] = LotTraceReferenceDTO(
        label='DN/0007', partner_id=fx.shop.id
    )
    paper.known[fx.bread_delivery_id] = LotTraceReferenceDTO(
        label='DN/0008', partner_id=fx.shop.id
    )

    def _move(
        lot: StockLot,
        product: ProductTemplate,
        quantity: str,
        reference_type: str,
        reference_id: UUID,
        day: int,
        *,
        source: StorageLocation | None = None,
        target: StorageLocation | None = None,
    ) -> StockMove:
        return StockMove(
            organization_id=fx.org.id,
            product_template_id=product.id,
            lot_id=lot.id,
            quantity=Decimal(quantity),
            from_location_id=source.id if source else None,
            to_location_id=target.id if target else None,
            reference_type=reference_type,
            reference_id=reference_id,
            completed_at=datetime(2026, 9, day, 10, tzinfo=UTC),
        )

    db.add_all(
        [
            # 100 kg in on one receipt, landed on two shelves.
            _move(fx.flour, flour, '60', _PAPER, fx.receipt_id, 1, target=fx.shelf),
            _move(fx.flour, flour, '40', _PAPER, fx.receipt_id, 1, target=other_shelf),
            # Moved between shelves: the goods never left the house.
            _move(
                fx.flour,
                flour,
                '10',
                _PAPER,
                uuid4(),
                2,
                source=other_shelf,
                target=fx.shelf,
            ),
            # 30 kg out to the shop.
            _move(fx.flour, flour, '30', _PAPER, fx.delivery_id, 3, source=fx.shelf),
            # 20 kg baked into 50 loaves of B-01.
            _move(fx.flour, flour, '20', _RUN, fx.run_id, 4, source=fx.shelf),
            _move(fx.bread, bread, '50', _RUN, fx.run_id, 4, target=fx.shelf),
            # A run started and undone: nothing crossed.
            _move(fx.flour, flour, '5', _RUN, undone_run, 5, source=fx.shelf),
            _move(fx.flour, flour, '5', _RUN, undone_run, 5, target=fx.shelf),
            # 12 loaves out to the shop.
            _move(
                fx.bread, bread, '12', _PAPER, fx.bread_delivery_id, 6, source=fx.shelf
            ),
        ]
    )
    await db.commit()
    yield fx
    unregister_lot_trace_source(_PAPER)
    unregister_lot_trace_source(_RUN)


async def _trace(client: AsyncClient, fx: _Recall) -> dict:
    response = await client.get(
        f'/api/v1/stock-lots/{fx.flour.id}/trace', headers=_auth(fx.user)
    )
    assert response.status_code == status.HTTP_200_OK, response.text
    return response.json()


class TestOneStepBack:
    async def test_the_receipt_names_the_supplier_it_was_signed_by(
        self, real_async_client: AsyncClient, recall: _Recall
    ) -> None:
        flour = (await _trace(real_async_client, recall))['lots'][0]

        assert flour['lot_name'] == 'F-01'
        assert flour['product_name'] == 'Rye flour'
        # Two shelves, one receipt: one line, the whole quantity.
        [receipt] = flour['received']
        assert receipt['label'] == 'GR/0001'
        assert Decimal(receipt['quantity']) == Decimal('100')
        # The name on the paper, not the record renamed since.
        assert receipt['partner_name'] == 'Grain Co'
        assert receipt['partner_address'] == '1 Field Rd, Leeds'
        assert receipt['moved_at'].startswith('2026-09-01')


class TestOneStepForward:
    async def test_the_delivery_names_the_customer_from_the_record(
        self, real_async_client: AsyncClient, recall: _Recall
    ) -> None:
        flour = (await _trace(real_async_client, recall))['lots'][0]

        delivery = next(e for e in flour['sent'] if e['label'] == 'DN/0007')
        assert Decimal(delivery['quantity']) == Decimal('30')
        assert delivery['partner_name'] == 'Corner Shop'
        assert delivery['partner_address'] == '2 High St, York'

    async def test_shelf_to_shelf_and_undone_runs_are_not_crossings(
        self, real_async_client: AsyncClient, recall: _Recall
    ) -> None:
        flour = (await _trace(real_async_client, recall))['lots'][0]

        # The delivery and the run that baked — not the move between aisles,
        # not the run that was taken back.
        assert [e['reference_id'] for e in flour['sent']] == [
            str(recall.delivery_id),
            str(recall.run_id),
        ]
        assert len(flour['received']) == 1


class TestThroughProduction:
    async def test_the_run_leads_to_the_batch_it_made_and_its_customers(
        self, real_async_client: AsyncClient, recall: _Recall
    ) -> None:
        trace = await _trace(real_async_client, recall)

        run = next(e for e in trace['lots'][0]['sent'] if e['label'] == 'RUN-1')
        assert Decimal(run['quantity']) == Decimal('20')
        [made] = run['produced']
        assert made['lot_name'] == 'B-01'
        assert made['product_name'] == 'Rye bread'
        assert Decimal(made['quantity']) == Decimal('50')

        # The bread's own step forward follows the flour's.
        bread = trace['lots'][1]
        assert bread['lot_id'] == str(recall.bread.id)
        assert bread['made_from_lot_id'] == str(recall.flour.id)
        [delivery] = bread['sent']
        assert delivery['label'] == 'DN/0008'
        assert delivery['partner_name'] == 'Corner Shop'
        assert Decimal(delivery['quantity']) == Decimal('12')
        assert trace['truncated'] is False


class TestTheTraceIsTheOrganizations:
    async def test_another_organization_gets_a_404(
        self,
        real_async_client: AsyncClient,
        recall: _Recall,
        real_async_db_session: AsyncSession,
    ) -> None:
        db = real_async_db_session
        stranger_org = Organization(
            name=f'Stranger {uuid4().hex[:6]}', enabled_modules=['core']
        )
        db.add(stranger_org)
        await db.commit()
        stranger = await ModuleTestHelper.create_user_async(
            db, stranger_org, email=f'stranger_{uuid4().hex[:8]}@test.com'
        )
        await db.commit()

        for path in ('trace', 'trace/export/xlsx'):
            response = await real_async_client.get(
                f'/api/v1/stock-lots/{recall.flour.id}/{path}', headers=_auth(stranger)
            )
            assert response.status_code == status.HTTP_404_NOT_FOUND


class TestTheTraceExports:
    async def test_the_sheet_carries_every_crossing_with_its_partner(
        self, real_async_client: AsyncClient, recall: _Recall
    ) -> None:
        response = await real_async_client.get(
            f'/api/v1/stock-lots/{recall.flour.id}/trace/export/xlsx',
            params={'tz': 'UTC'},
            headers=_auth(recall.user),
        )

        assert response.status_code == status.HTTP_200_OK
        book = load_workbook(io.BytesIO(response.content))
        rows = list(book['Trace'].iter_rows(values_only=True))
        header, body = rows[0], rows[1:]
        assert 'Partner address' in header
        records = [dict(zip(header, row, strict=True)) for row in body]
        # Receipt, delivery and run of the flour; the run and delivery of
        # the bread.
        assert [(r['Batch'], r['Direction'], r['Document']) for r in records] == [
            ('F-01', 'In', 'GR/0001'),
            ('F-01', 'Out', 'DN/0007'),
            ('F-01', 'Out', 'RUN-1'),
            ('B-01', 'In', 'RUN-1'),
            ('B-01', 'Out', 'DN/0008'),
        ]
        assert records[0]['Partner'] == 'Grain Co'
        assert records[0]['Quantity'] == 100
        assert records[2]['Made into'] == 'B-01 (Rye bread)'
        assert records[4]['Made from batch'] == 'F-01'
        about = dict(book['Batch'].iter_rows(min_row=2, values_only=True))
        assert about['Batch'] == 'F-01'
        assert about['Batches made from it'] == '1'
