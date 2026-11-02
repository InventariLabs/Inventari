"""A batch on hold is on hold whichever way you reach for it.

The status filter used to live in one query — the removal-strategy pick.
Reach for the same stock by naming the batch, or let a document reserve it
at confirm, and nothing looked at the status at all. A rule enforced on one
of two paths is not a rule: a quarantined batch could be dispatched by
typing its number, and a confirmed document could hold stock that no
dispatch is ever allowed to release.

These tests come at the same lot from both directions, once per blocking
status.
"""

from __future__ import annotations

from decimal import Decimal
from typing import cast
from uuid import UUID

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import Session

from app.core.testing import ShelfRow
from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.stock_lot import LotStatus, StockLot
from app.models.storage_location import StorageLocation
from app.modules.warehouse.tests.integration._records import (
    shelf_quant,
    shelf_record,
    sow,
)

BLOCKING_STATUSES = [
    LotStatus.QUARANTINED,
    LotStatus.HELD,
    LotStatus.RECALLED,
    LotStatus.EXPIRED,
]


def _make_lot(
    db_session: Session,
    org_id: UUID,
    template_id: UUID,
    name: str,
    status_value: str = LotStatus.ACTIVE,
) -> StockLot:
    lot = StockLot(
        organization_id=org_id,
        product_template_id=template_id,
        name=name,
        status=status_value,
    )
    db_session.add(lot)
    db_session.flush()
    db_session.refresh(lot)
    return lot


def _put_batch(
    db_session: Session,
    engine: AsyncEngine,
    org_id: UUID,
    template_id: UUID,
    location_id: UUID,
    quantity: Decimal,
    lot_id: UUID | None = None,
) -> ShelfRow:
    """One record of the batch on the shelf; returns the group it makes there."""
    template = db_session.get(ProductTemplate, template_id)
    assert template is not None
    sow(
        db_session,
        engine,
        org_id,
        template,
        location_id,
        quantity,
        lot_id=lot_id,
    )
    return shelf_quant(db_session, org_id, template_id, location_id, lot_id=lot_id)


def _make_item(
    db_session: Session,
    org_id: UUID,
    template_id: UUID,
    location_id: UUID,
    quantity: Decimal,
) -> Item:
    """The record the document line names: one already standing on the shelf.

    The stock itself went in through ``sow`` (per batch); this picks up one
    of those records, so the line names a real one instead of a scalar row
    no batch on the shelf stands behind.
    """
    return shelf_record(db_session, org_id, template_id, location_id)


def _create_out(
    client: TestClient,
    headers: dict[str, str],
    *,
    partner_id: UUID,
    source_location_id: UUID,
    target_location_id: UUID,
    item_id: UUID,
    template_id: UUID,
    quantity: int,
    batch_number: str | None = None,
) -> str:
    """Create an OUT document in draft. Returns its id."""
    line: dict[str, object] = {
        'item_id': str(item_id),
        'product_template_id': str(template_id),
        'expected_quantity': quantity,
    }
    if batch_number is not None:
        line['batch_number'] = batch_number
    resp = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'OUT',
            'partner_id': str(partner_id),
            'source_location_id': str(source_location_id),
            'target_location_id': str(target_location_id),
            'lines': [line],
        },
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    return cast(str, resp.json()['id'])


@pytest.mark.integration
class TestNamingAHeldBatchDoesNotRelease:
    """Typing the batch number must not get past the status filter."""

    @pytest.mark.parametrize('lot_status', BLOCKING_STATUSES)
    def test_dispatch_naming_a_held_batch_is_refused(
        self,
        lot_status: str,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_org: Organization,
    ) -> None:
        held = _make_lot(
            db_session, doc_org.id, doc_template.id, 'LOT-HELD', lot_status
        )
        good = _make_lot(db_session, doc_org.id, doc_template.id, 'LOT-GOOD')
        _put_batch(
            db_session,
            async_engine_fixture,
            doc_org.id,
            doc_template.id,
            doc_source_location.id,
            Decimal('5'),
            lot_id=held.id,
        )
        _put_batch(
            db_session,
            async_engine_fixture,
            doc_org.id,
            doc_template.id,
            doc_source_location.id,
            Decimal('5'),
            lot_id=good.id,
        )
        item = _make_item(
            db_session,
            doc_org.id,
            doc_template.id,
            doc_source_location.id,
            Decimal('10'),
        )
        db_session.commit()

        doc_id = _create_out(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            source_location_id=doc_source_location.id,
            target_location_id=doc_target_location.id,
            item_id=item.id,
            template_id=doc_template.id,
            quantity=5,
            batch_number='LOT-HELD',
        )
        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.text
        assert lot_status in resp.text, resp.text

        db_session.expire_all()
        held_group = db_session.scalars(
            select(ShelfRow).where(ShelfRow.lot_id == held.id)
        ).one()
        assert held_group.quantity == Decimal('5')


@pytest.mark.integration
class TestAHeldBatchIsNotReservable:
    """Confirm must not hold stock that dispatch is forbidden to release."""

    @pytest.mark.parametrize('lot_status', BLOCKING_STATUSES)
    def test_confirm_does_not_reserve_a_held_batch(
        self,
        lot_status: str,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_org: Organization,
    ) -> None:
        held = _make_lot(
            db_session, doc_org.id, doc_template.id, 'LOT-HELD', lot_status
        )
        _put_batch(
            db_session,
            async_engine_fixture,
            doc_org.id,
            doc_template.id,
            doc_source_location.id,
            Decimal('8'),
            lot_id=held.id,
        )
        item = _make_item(
            db_session,
            doc_org.id,
            doc_template.id,
            doc_source_location.id,
            Decimal('8'),
        )
        db_session.commit()

        doc_id = _create_out(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            source_location_id=doc_source_location.id,
            target_location_id=doc_target_location.id,
            item_id=item.id,
            template_id=doc_template.id,
            quantity=8,
        )
        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )

        db_session.expire_all()
        held_group = shelf_quant(
            db_session,
            doc_org.id,
            doc_template.id,
            doc_source_location.id,
            lot_id=held.id,
        )
        assert held_group.reserved_quantity == Decimal('0')


def _create_release(
    client: TestClient,
    headers: dict[str, str],
    *,
    doc_type: str,
    source_location_id: UUID,
    target_location_id: UUID | None,
    item_id: UUID,
    template_id: UUID,
    quantity: int,
    batch_number: str | None,
) -> str:
    """Create a scrap or a transfer in draft. Returns its id."""
    line: dict[str, object] = {
        'item_id': str(item_id),
        'product_template_id': str(template_id),
        'expected_quantity': quantity,
    }
    if batch_number is not None:
        line['batch_number'] = batch_number
    body: dict[str, object] = {
        'type': doc_type,
        'source_location_id': str(source_location_id),
        'lines': [line],
    }
    if target_location_id is not None:
        body['target_location_id'] = str(target_location_id)
    if doc_type == 'SCRAP':
        body['reason_code'] = 'DAMAGED'
    resp = client.post('/api/v1/warehouse/documents', headers=headers, json=body)
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    return cast(str, resp.json()['id'])


@pytest.mark.integration
class TestADeliberateDoorTakesAHeldBatchByName:
    """A write-off or a move of a held batch is confirmed, not refused.

    Confirmation reserves, and the reservation used to plan over dispatchable
    stock only, so a scrap naming a quarantined batch was refused as
    "insufficient stock" while the whole batch stood on the shelf. The one
    way to write it off was to release the batch for picking first. The
    batch the door names is what it reserves, held or not, and it stays
    held for that document until it leaves. A transfer carries its record
    as itself, so the record's own batch is the one it names when the line
    names none.
    """

    @pytest.mark.parametrize(
        ('doc_type', 'batch_number'),
        [('SCRAP', 'LOT-HELD'), ('INT', 'LOT-HELD'), ('INT', None)],
    )
    @pytest.mark.parametrize('lot_status', BLOCKING_STATUSES)
    def test_a_named_held_batch_is_reserved_and_taken(
        self,
        doc_type: str,
        batch_number: str | None,
        lot_status: str,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_org: Organization,
    ) -> None:
        held = _make_lot(
            db_session, doc_org.id, doc_template.id, 'LOT-HELD', lot_status
        )
        _put_batch(
            db_session,
            async_engine_fixture,
            doc_org.id,
            doc_template.id,
            doc_source_location.id,
            Decimal('10'),
            lot_id=held.id,
        )
        item = _make_item(
            db_session,
            doc_org.id,
            doc_template.id,
            doc_source_location.id,
            Decimal('10'),
        )
        db_session.commit()

        doc_id = _create_release(
            client,
            doc_auth_headers,
            doc_type=doc_type,
            source_location_id=doc_source_location.id,
            target_location_id=doc_target_location.id if doc_type == 'INT' else None,
            item_id=item.id,
            template_id=doc_template.id,
            quantity=10,
            batch_number=batch_number,
        )
        confirm = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        assert confirm.status_code == status.HTTP_200_OK, confirm.text

        db_session.expire_all()
        assert shelf_quant(
            db_session,
            doc_org.id,
            doc_template.id,
            doc_source_location.id,
            lot_id=held.id,
        ).reserved_quantity == Decimal('10')

        done = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert done.status_code == status.HTTP_200_OK, done.text

        db_session.expire_all()
        left = db_session.scalars(
            select(ShelfRow).where(
                ShelfRow.lot_id == held.id,
                ShelfRow.storage_location_id == doc_source_location.id,
            )
        ).first()
        assert (left.quantity if left is not None else Decimal('0')) == Decimal('0')
        # The batch kept its status: nobody had to release it for picking.
        lot = db_session.get(StockLot, held.id)
        assert lot is not None
        assert lot.status == lot_status
