"""The ``document.*`` events name what moved, so a subscriber need not fetch.

A module that reacts after posting — a carrier, an accounting export, a
notification — learns the product, the batch, the shelves and the quantities
from the payload itself.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Any

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import Session

from app.core.public_api import core_api
from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.stock_lot import StockLot
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.warehouse.tests.integration._records import sow

pytestmark = pytest.mark.integration

_DOCS = '/api/v1/warehouse/documents'


def _receipt(
    client: TestClient,
    headers: dict[str, str],
    *,
    partner: Partner,
    shelf: StorageLocation,
    template: ProductTemplate,
) -> str:
    created = client.post(
        _DOCS,
        headers=headers,
        json={
            'type': 'IN',
            'partner_id': str(partner.id),
            'target_location_id': str(shelf.id),
            'lines': [
                {
                    'product_template_id': str(template.id),
                    'expected_quantity': 4,
                    'batch_number': 'LOT-7',
                    'expiry_date': '2031-01-31',
                }
            ],
        },
    )
    assert created.status_code == status.HTTP_201_CREATED, created.text
    doc_id: str = created.json()['id']
    confirmed = client.patch(f'{_DOCS}/{doc_id}/confirm', headers=headers)
    assert confirmed.status_code == status.HTTP_200_OK, confirmed.text
    return doc_id


class TestDocumentEventsSayWhatMoved:
    def test_a_completed_receipt_can_be_replayed_from_its_payload_alone(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        doc_id = _receipt(
            client,
            doc_auth_headers,
            partner=doc_partner,
            shelf=doc_target_location,
            template=doc_template,
        )
        received: list[Any] = []
        core_api.events.subscribe('document.completed', received.append)

        done = client.patch(
            f'{_DOCS}/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )

        assert done.status_code == status.HTTP_200_OK, done.text
        assert len(received) == 1
        # What a subscriber can derive without fetching the document: how
        # much of which product, in which batch, arrived on which shelf.
        replayed: dict[tuple[str, str | None, str], Decimal] = defaultdict(Decimal)
        for line in received[0].lines:
            replayed[
                (line['product_id'], line['lot_number'], line['target_location_id'])
            ] += Decimal(str(line['done_quantity']))
        assert dict(replayed) == {
            (str(doc_template.id), 'LOT-7', str(doc_target_location.id)): Decimal('4')
        }

        line = received[0].lines[0]
        assert line['product_code'] == doc_template.sku
        assert line['target_location_code'] == (
            doc_target_location.short_code or doc_target_location.name
        )
        assert line['source_location_id'] is None
        assert line['lot_id'] is not None

        # The same stock really is on that shelf.
        db_session.expire_all()
        on_shelf = db_session.scalar(
            select(func.sum(Item.quantity)).where(
                Item.template_id == doc_template.id,
                Item.storage_location_id == doc_target_location.id,
            )
        )
        assert on_shelf == Decimal('4')

    def test_the_confirmed_event_names_the_product_and_shelf_before_a_lot_exists(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        received: list[Any] = []
        core_api.events.subscribe('document.confirmed', received.append)

        _receipt(
            client,
            doc_auth_headers,
            partner=doc_partner,
            shelf=doc_target_location,
            template=doc_template,
        )

        line = received[-1].lines[0]
        assert line['product_id'] == str(doc_template.id)
        assert line['lot_number'] == 'LOT-7'
        assert line['lot_id'] is None
        assert line['target_location_id'] == str(doc_target_location.id)

    def test_a_transfer_names_the_lot_its_record_carries(
        self,
        client: TestClient,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        """The line names no lot; the stock record it moves does."""
        lot = StockLot(
            organization_id=doc_org.id,
            product_template_id=doc_template.id,
            name='INHERITED-1',
        )
        db_session.add(lot)
        db_session.flush()
        record = sow(
            db_session,
            async_engine_fixture,
            doc_org,
            doc_template,
            doc_source_location.id,
            10,
            lot_id=lot.id,
        )
        created = client.post(
            _DOCS,
            headers=doc_auth_headers,
            json={
                'type': 'INT',
                'source_location_id': str(doc_source_location.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [{'item_id': str(record.id), 'expected_quantity': 3}],
            },
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        doc_id = created.json()['id']
        assert (
            client.patch(
                f'{_DOCS}/{doc_id}/confirm', headers=doc_auth_headers
            ).status_code
            == status.HTTP_200_OK
        )
        received: list[Any] = []
        core_api.events.subscribe('document.completed', received.append)

        done = client.patch(
            f'{_DOCS}/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )

        assert done.status_code == status.HTTP_200_OK, done.text
        line = received[-1].lines[0]
        assert line['lot_id'] == str(lot.id)
        assert line['lot_number'] == 'INHERITED-1'
        assert line['source_location_id'] == str(doc_source_location.id)
        assert line['target_location_id'] == str(doc_target_location.id)

    def test_a_dispatch_from_a_zone_leaves_the_shelf_and_lands_nowhere(
        self,
        client: TestClient,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_user: User,
        doc_partner: Partner,
        doc_source_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        """The executor pins the shelf it took from; that is not a target."""
        shelf = StorageLocation(
            organization_id=doc_org.id,
            name='Bin Z1',
            parent_id=doc_source_location.id,
            storage_type_id=doc_source_location.storage_type_id,
            created_by=doc_user.id,
        )
        db_session.add(shelf)
        db_session.flush()
        record = sow(
            db_session, async_engine_fixture, doc_org, doc_template, shelf.id, 10
        )
        created = client.post(
            _DOCS,
            headers=doc_auth_headers,
            json={
                'type': 'OUT',
                'partner_id': str(doc_partner.id),
                'source_location_id': str(doc_source_location.id),
                'lines': [
                    {
                        'item_id': str(record.id),
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 2,
                    }
                ],
            },
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        doc_id = created.json()['id']
        assert (
            client.patch(
                f'{_DOCS}/{doc_id}/confirm', headers=doc_auth_headers
            ).status_code
            == status.HTTP_200_OK
        )
        received: list[Any] = []
        core_api.events.subscribe('document.completed', received.append)

        done = client.patch(
            f'{_DOCS}/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )

        assert done.status_code == status.HTTP_200_OK, done.text
        line = received[-1].lines[0]
        assert line['source_location_id'] == str(shelf.id)
        assert line['target_location_id'] is None
        assert line['target_location_code'] is None

    @pytest.mark.parametrize('doc_type', ['OUT', 'SCRAP'])
    def test_an_undated_draw_names_every_batch_it_took_and_how_much(
        self,
        client: TestClient,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_partner: Partner,
        doc_source_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_type: str,
    ) -> None:
        """The item a line points at is not the whole of what an open draw takes."""
        first = StockLot(
            organization_id=doc_org.id,
            product_template_id=doc_template.id,
            name='UNDATED-A',
        )
        second = StockLot(
            organization_id=doc_org.id,
            product_template_id=doc_template.id,
            name='UNDATED-B',
        )
        db_session.add_all([first, second])
        db_session.flush()
        sow(
            db_session,
            async_engine_fixture,
            doc_org,
            doc_template,
            doc_source_location.id,
            2,
            lot_id=first.id,
        )
        named = sow(
            db_session,
            async_engine_fixture,
            doc_org,
            doc_template,
            doc_source_location.id,
            8,
            lot_id=second.id,
        )
        body: dict[str, Any] = {
            'type': doc_type,
            'source_location_id': str(doc_source_location.id),
            'lines': [
                {
                    'item_id': str(named.id),
                    'product_template_id': str(doc_template.id),
                    'expected_quantity': 4,
                }
            ],
        }
        if doc_type == 'OUT':
            body['partner_id'] = str(doc_partner.id)
        else:
            body['reason_code'] = 'DAMAGED'
        created = client.post(_DOCS, headers=doc_auth_headers, json=body)
        assert created.status_code == status.HTTP_201_CREATED, created.text
        doc_id = created.json()['id']
        assert (
            client.patch(
                f'{_DOCS}/{doc_id}/confirm', headers=doc_auth_headers
            ).status_code
            == status.HTTP_200_OK
        )
        received: list[Any] = []
        core_api.events.subscribe('document.completed', received.append)

        done = client.patch(
            f'{_DOCS}/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )

        assert done.status_code == status.HTTP_200_OK, done.text
        left: dict[str | None, Decimal] = defaultdict(Decimal)
        for line in received[-1].lines:
            left[line['lot_number']] += Decimal(str(line['done_quantity']))
        # The older batch goes first; the named record's batch only after it.
        assert dict(left) == {'UNDATED-A': Decimal('2'), 'UNDATED-B': Decimal('2')}
        asked = [Decimal(str(line['expected_quantity'])) for line in received[-1].lines]
        # An issue or a write-off stands on one line per batch it took, each
        # asking for what its batch gave: the four asked for are still four.
        assert asked == [Decimal('2'), Decimal('2')]
