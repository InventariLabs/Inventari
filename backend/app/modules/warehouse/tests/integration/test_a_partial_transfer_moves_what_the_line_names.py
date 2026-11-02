"""A partial transfer moves what the line names, and the rest stays put.

The transfer executor used to do two independent writes: the record moved
to the target shelf whole, while the stock moved only the line's quantity.
A line smaller than its record left the two books disagreeing — the drift
the reconciliation read. These tests hold the executor to the line: the
quantity the line names changes shelves, the remainder stays where it stood,
and the records and the movement ledger agree on both shelves.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.item import Item
from app.models.product_template import ProductTemplate
from app.models.stock_move import StockMove
from app.modules.warehouse.tests.integration._records import (
    sow as _sow,
)
from app.schemas.item import ItemCreate
from app.services.items import create_item
from tests.integration._shelf import run_in_async_session, shelf_keeper

pytestmark = pytest.mark.integration


def _records_total(
    db: Session, org_id: UUID, template_id: UUID | None, location_id: UUID
) -> Decimal:
    stmt = select(Item).where(
        Item.organization_id == org_id,
        Item.template_id == template_id,
        Item.storage_location_id == location_id,
        Item.is_deleted.is_(False),
    )
    return sum((row.quantity or Decimal('0') for row in db.scalars(stmt)), Decimal('0'))


def _moved_total(
    db: Session, org_id: UUID, template_id: UUID | None, location_id: UUID
) -> Decimal:
    """What the done movements of the card net to on *location_id*."""
    total = Decimal('0')
    for move in db.scalars(
        select(StockMove).where(
            StockMove.organization_id == org_id,
            StockMove.product_template_id == template_id,
            StockMove.state == 'done',
        )
    ):
        if move.to_location_id == location_id:
            total += move.quantity
        if move.from_location_id == location_id:
            total -= move.quantity
    return total


def _records_at(
    db: Session, org_id: UUID, template_id: UUID | None, location_id: UUID
) -> list[Item]:
    stmt = select(Item).where(
        Item.organization_id == org_id,
        Item.template_id == template_id,
        Item.storage_location_id == location_id,
        Item.is_deleted.is_(False),
    )
    return list(db.scalars(stmt))


def _run_doc(
    client: Any, headers: dict[str, str], payload: dict[str, object]
) -> dict[str, Any]:
    resp = client.post('/api/v1/warehouse/documents', headers=headers, json=payload)
    assert resp.status_code == 201, resp.text
    doc_id = resp.json()['id']
    confirm = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=headers
    )
    assert confirm.status_code == 200, confirm.text
    complete = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/complete',
        headers=headers,
        json={'complete_as_planned': True},
    )
    assert complete.status_code == 200, complete.text
    created: dict[str, Any] = resp.json()
    return created


def _carded_item(
    h: ModuleTestHelper,
    db: Session,
    engine: AsyncEngine,
    org: Any,
    location_id: UUID,
    quantity: Decimal,
) -> Item:
    """A carded record standing on a shelf, put there through the items
    service — the record, its movement and its cost layer, the shelf the
    confirm gate consults."""
    template = h.create_template(org, name=f'partial-int-{uuid4().hex[:6]}')
    return _sow(db, engine, org, template, location_id, quantity)


class TestPartialTransfer:
    def test_partial_int_moves_the_lines_quantity_and_leaves_the_rest(
        self,
        client: Any,
        doc_auth_headers: dict[str, str],
        doc_source_location: Any,
        doc_target_location: Any,
        doc_org: Any,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        """Record 10, line 3: three units change shelves, seven stay; both books agree."""
        h = ModuleTestHelper(db_session)
        item = _carded_item(
            h,
            db_session,
            async_engine_fixture,
            doc_org,
            doc_source_location.id,
            Decimal('10'),
        )
        template_id = item.template_id
        assert template_id is not None

        doc = _run_doc(
            client,
            doc_auth_headers,
            {
                'type': 'INT',
                'source_location_id': str(doc_source_location.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [{'item_id': str(item.id), 'expected_quantity': 3}],
            },
        )

        db_session.refresh(item)
        assert item.storage_location_id == doc_target_location.id
        assert item.quantity == Decimal('3')
        remainders = [
            row
            for row in _records_at(
                db_session, doc_org.id, template_id, doc_source_location.id
            )
            if row.id != item.id
        ]
        assert len(remainders) == 1
        assert remainders[0].quantity == Decimal('7')
        assert _records_total(
            db_session, doc_org.id, template_id, doc_target_location.id
        ) == Decimal('3')
        assert _records_total(
            db_session, doc_org.id, template_id, doc_source_location.id
        ) == Decimal('7')
        assert _moved_total(
            db_session, doc_org.id, template_id, doc_target_location.id
        ) == Decimal('3')
        assert _moved_total(
            db_session, doc_org.id, template_id, doc_source_location.id
        ) == Decimal('7')
        assert doc['type'] == 'INT'

    def test_partial_transfer_of_a_cardless_record_splits_after_adoption(
        self,
        client: Any,
        doc_auth_headers: dict[str, str],
        doc_source_location: Any,
        doc_target_location: Any,
        doc_org: Any,
        db_session: Session,
    ) -> None:
        """A record without a card adopts one first, then splits the same way."""
        item = Item(
            name=f'cardless-partial-{uuid4().hex[:6]}',
            organization_id=doc_org.id,
            storage_location_id=doc_source_location.id,
            quantity=Decimal('10'),
        )
        db_session.add(item)
        db_session.commit()
        db_session.refresh(item)

        _run_doc(
            client,
            doc_auth_headers,
            {
                'type': 'INT',
                'source_location_id': str(doc_source_location.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [{'item_id': str(item.id), 'expected_quantity': 3}],
            },
        )

        db_session.refresh(item)
        assert item.storage_location_id == doc_target_location.id
        assert item.quantity == Decimal('3')
        template_id = item.template_id
        assert template_id is not None, 'the adoption binds the card to the record'
        assert _records_total(
            db_session, doc_org.id, template_id, doc_target_location.id
        ) == Decimal('3')
        assert _records_total(
            db_session, doc_org.id, template_id, doc_source_location.id
        ) == Decimal('7')
        assert _moved_total(
            db_session, doc_org.id, template_id, doc_target_location.id
        ) == Decimal('3')
        assert _moved_total(
            db_session, doc_org.id, template_id, doc_source_location.id
        ) == Decimal('7')

    def test_partial_return_int_brings_back_only_the_lines_quantity(
        self,
        client: Any,
        doc_auth_headers: dict[str, str],
        doc_source_location: Any,
        doc_target_location: Any,
        doc_org: Any,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        """A partial return of a completed INT brings back what the line names."""
        h = ModuleTestHelper(db_session)
        item = _carded_item(
            h,
            db_session,
            async_engine_fixture,
            doc_org,
            doc_source_location.id,
            Decimal('10'),
        )
        template_id = item.template_id
        assert template_id is not None

        doc = _run_doc(
            client,
            doc_auth_headers,
            {
                'type': 'INT',
                'source_location_id': str(doc_source_location.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [{'item_id': str(item.id), 'expected_quantity': 10}],
            },
        )
        db_session.refresh(item)
        assert item.quantity == Decimal('10'), (
            'the full transfer keeps the record whole'
        )

        resp = client.post(
            f'/api/v1/warehouse/documents/{doc["id"]}/return',
            headers=doc_auth_headers,
            json={
                'reason_code': 'DAMAGED',
                'lines': [{'original_line_number': 1, 'return_quantity': 3}],
            },
        )
        assert resp.status_code == 201, resp.text
        ret_id = resp.json()['id']
        confirm = client.patch(
            f'/api/v1/warehouse/documents/{ret_id}/confirm', headers=doc_auth_headers
        )
        assert confirm.status_code == 200, confirm.text
        complete = client.patch(
            f'/api/v1/warehouse/documents/{ret_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert complete.status_code == 200, complete.text

        db_session.refresh(item)
        assert item.storage_location_id == doc_source_location.id
        assert item.quantity == Decimal('3')
        remainders = [
            row
            for row in _records_at(
                db_session, doc_org.id, template_id, doc_target_location.id
            )
            if row.id != item.id
        ]
        assert len(remainders) == 1
        assert remainders[0].quantity == Decimal('7')
        assert _moved_total(
            db_session, doc_org.id, template_id, doc_source_location.id
        ) == Decimal('3')
        assert _moved_total(
            db_session, doc_org.id, template_id, doc_target_location.id
        ) == Decimal('7')

    def test_a_full_quantity_transfer_moves_the_record_whole(
        self,
        client: Any,
        doc_auth_headers: dict[str, str],
        doc_source_location: Any,
        doc_target_location: Any,
        doc_org: Any,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        """A line naming the whole record moves it as before: no split, no remainder."""
        h = ModuleTestHelper(db_session)
        item = _carded_item(
            h,
            db_session,
            async_engine_fixture,
            doc_org,
            doc_source_location.id,
            Decimal('10'),
        )
        template_id = item.template_id
        assert template_id is not None

        _run_doc(
            client,
            doc_auth_headers,
            {
                'type': 'INT',
                'source_location_id': str(doc_source_location.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [{'item_id': str(item.id), 'expected_quantity': 10}],
            },
        )

        db_session.refresh(item)
        assert item.storage_location_id == doc_target_location.id
        assert item.quantity == Decimal('10')
        assert _records_total(
            db_session, doc_org.id, template_id, doc_target_location.id
        ) == Decimal('10')
        assert _records_total(
            db_session, doc_org.id, template_id, doc_source_location.id
        ) == Decimal('0')
        assert _moved_total(
            db_session, doc_org.id, template_id, doc_target_location.id
        ) == Decimal('10')
        assert _moved_total(
            db_session, doc_org.id, template_id, doc_source_location.id
        ) == Decimal('0')

    def test_split_remainder_carries_the_goods_fields(
        self,
        client: Any,
        doc_auth_headers: dict[str, str],
        doc_source_location: Any,
        doc_target_location: Any,
        doc_org: Any,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        """What describes the goods rides with the remainder: the image, the
        freeze date (which lives inside meta_data) and the receipt date the
        rotation analytics read. Weight and volume belong to the card, not
        the record — the remainder under the same card reads the same ones.
        Barcode and serial stay with the record on purpose: they name it."""
        h = ModuleTestHelper(db_session)
        template = h.create_template(doc_org, name=f'goods-fields-{uuid4().hex[:6]}')
        template.weight_value = Decimal('0.500')
        template.volume_value = Decimal('0.250')
        db_session.commit()
        item = _sow(
            db_session,
            async_engine_fixture,
            doc_org,
            template,
            doc_source_location.id,
            Decimal('10'),
        )
        item.image_url = 'https://example.test/goods.jpg'
        item.meta_data = {'food': {'freeze_date': '2026-09-01'}}
        item.added_date = date(2026, 8, 15)
        db_session.commit()
        template_id = item.template_id
        assert template_id is not None

        _run_doc(
            client,
            doc_auth_headers,
            {
                'type': 'INT',
                'source_location_id': str(doc_source_location.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [{'item_id': str(item.id), 'expected_quantity': 3}],
            },
        )

        db_session.refresh(item)
        remainders = [
            row
            for row in _records_at(
                db_session, doc_org.id, template_id, doc_source_location.id
            )
            if row.id != item.id
        ]
        assert len(remainders) == 1
        rest = remainders[0]
        assert rest.image_url == 'https://example.test/goods.jpg'
        assert (rest.meta_data or {}).get('food', {}).get('freeze_date') == (
            '2026-09-01'
        )
        assert rest.added_date == date(2026, 8, 15)
        assert rest.template_id == template_id
        # Weight and volume are the card's (ADR-015): the remainder under the
        # same card reads the same ones, so the source's values carry without
        # a record column to copy them into.
        assert rest.template is not None
        assert rest.template.weight_value == Decimal('0.500')
        assert rest.template.volume_value == Decimal('0.250')

    def test_split_remainder_returns_to_the_records_own_card(
        self,
        client: Any,
        doc_auth_headers: dict[str, str],
        doc_source_location: Any,
        doc_target_location: Any,
        doc_org: Any,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        """Two cards of one name: the remainder must land under the record's
        own card, not answer to the name and land on its twin — and no third
        card may appear. The record is named unlike its card on purpose: the
        name is not what binds it."""
        twin_name = f'twin-card-{uuid4().hex[:6]}'
        first = ProductTemplate(name=twin_name, organization_id=doc_org.id)
        second = ProductTemplate(name=twin_name, organization_id=doc_org.id)
        db_session.add_all([first, second])
        db_session.commit()
        db_session.refresh(first)
        db_session.refresh(second)
        organization_id = doc_org.id

        async def _put(session: AsyncSession) -> UUID:
            keeper = await shelf_keeper(session, organization_id)
            record = await create_item(
                session,
                ItemCreate(
                    name=f'odd-named-record-{uuid4().hex[:6]}',
                    template_id=second.id,
                    location_id=doc_source_location.id,
                    quantity=Decimal('10'),
                ),
                keeper,
            )
            return record.id

        record_id = run_in_async_session(async_engine_fixture, _put)
        db_session.expire_all()
        item = db_session.get(Item, record_id)
        assert item is not None

        _run_doc(
            client,
            doc_auth_headers,
            {
                'type': 'INT',
                'source_location_id': str(doc_source_location.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [{'item_id': str(item.id), 'expected_quantity': 3}],
            },
        )

        db_session.refresh(item)
        remainders = [
            row
            for row in _records_at(
                db_session, doc_org.id, second.id, doc_source_location.id
            )
            if row.id != item.id
        ]
        assert len(remainders) == 1, 'the remainder belongs under the record own card'
        cards = list(
            db_session.scalars(
                select(ProductTemplate).where(ProductTemplate.name == twin_name)
            )
        )
        assert len(cards) == 2, 'no third card may appear'

    def test_split_remainder_of_an_adopted_record_binds_the_adopted_card(
        self,
        client: Any,
        doc_auth_headers: dict[str, str],
        doc_source_location: Any,
        doc_target_location: Any,
        doc_org: Any,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        """A record that predates its card adopts the card its barcode names —
        a card standing under a different name — and the remainder must land
        under that adopted card, not answer to the record's own name and mint
        a second one. The executor reads the record through a snapshot taken
        before the adoption, so what it says about the card must be the card
        the adoption resolved."""
        barcode = f'BCPT{uuid4().hex[:10]}'
        card = ProductTemplate(
            name=f'adopted-card-{uuid4().hex[:6]}',
            barcode=barcode,
            organization_id=doc_org.id,
        )
        db_session.add(card)
        db_session.commit()
        db_session.refresh(card)
        item = Item(
            name=f'odd-named-record-{uuid4().hex[:6]}',
            organization_id=doc_org.id,
            storage_location_id=doc_source_location.id,
            quantity=Decimal('10'),
            barcode=barcode,
        )
        db_session.add(item)
        db_session.commit()
        db_session.refresh(item)
        assert item.template_id is None, 'the record stands before its card'

        _run_doc(
            client,
            doc_auth_headers,
            {
                'type': 'INT',
                'source_location_id': str(doc_source_location.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [{'item_id': str(item.id), 'expected_quantity': 3}],
            },
        )

        db_session.refresh(item)
        assert item.template_id == card.id, (
            'the adoption binds the card the barcode names'
        )
        remainders = [
            row
            for row in _records_at(
                db_session, doc_org.id, card.id, doc_source_location.id
            )
            if row.id != item.id
        ]
        assert len(remainders) == 1, 'the remainder belongs under the adopted card'
        assert remainders[0].quantity == Decimal('7')
        cards = list(
            db_session.scalars(
                select(ProductTemplate).where(ProductTemplate.barcode == barcode)
            )
        )
        assert len(cards) == 1, 'no second card may appear'
