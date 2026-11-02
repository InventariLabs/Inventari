"""A record bound to its card at a receipt reads in the card's unit.

A record that predates its card and names no unit of its own was bound at the
receipt, and the ledger booked its delivery in the card's unit — the card's
unit is the reference. The binding wrote the link alone, so the record kept
no unit: the location's product table said "2 —" two inches above a movement
history saying "2 g". The numbers agreed; the label did not, and between
grams and nothing the difference is worth a factor of a thousand.
"""

from __future__ import annotations

from decimal import Decimal
from typing import cast
from uuid import UUID, uuid4

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit_log import AuditAction, AuditLog
from app.models.item import Item
from app.models.item_history import ItemHistory
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.uom import Uom

pytestmark = pytest.mark.integration


def _receive(
    client: TestClient,
    headers: dict[str, str],
    *,
    partner_id: UUID,
    location_id: UUID,
    item_id: UUID,
    quantity: int,
) -> None:
    resp = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'IN',
            'partner_id': str(partner_id),
            'target_location_id': str(location_id),
            'lines': [{'item_id': str(item_id), 'expected_quantity': quantity}],
        },
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    doc_id = cast(str, resp.json()['id'])
    for step in ('confirm', 'complete'):
        done = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/{step}',
            headers=headers,
            json={'complete_as_planned': True} if step == 'complete' else None,
        )
        assert done.status_code == status.HTTP_200_OK, done.text


@pytest.fixture
def gram(db_session: Session) -> Uom:
    uom = db_session.scalars(select(Uom).where(Uom.symbol == 'g')).first()
    assert uom is not None, 'the seed has no gram'
    return uom


def test_the_record_reads_in_the_unit_its_card_booked_the_delivery_in(
    client: TestClient,
    doc_auth_headers: dict[str, str],
    doc_target_location: StorageLocation,
    doc_partner: Partner,
    db_session: Session,
    doc_org: Organization,
    gram: Uom,
) -> None:
    name = f'Weighed Spice {uuid4().hex[:6]}'
    card = ProductTemplate(
        organization_id=doc_org.id,
        name=name,
        sku=f'SKU-{uuid4().hex[:8]}',
        uom_id=gram.id,
    )
    record = Item(
        name=name,
        organization_id=doc_org.id,
        template_id=None,
        uom_id=None,
        storage_location_id=doc_target_location.id,
        quantity=Decimal('0'),
    )
    db_session.add_all([card, record])
    db_session.commit()

    _receive(
        client,
        doc_auth_headers,
        partner_id=doc_partner.id,
        location_id=doc_target_location.id,
        item_id=record.id,
        quantity=2,
    )

    db_session.expire_all()
    bound = db_session.get(Item, record.id)
    assert bound is not None and bound.template_id == card.id
    assert bound.uom_id == gram.id

    shown = client.get(f'/api/v1/items/{record.id}', headers=doc_auth_headers)
    assert shown.status_code == status.HTTP_200_OK, shown.text
    assert (shown.json().get('uom') or {}).get('symbol') == 'g'

    # The record keeps the moment its unit arrived, beside its card.
    history = db_session.scalars(
        select(ItemHistory).where(ItemHistory.item_id == record.id)
    ).all()
    assert any(
        (row.changes or {}).get('new', {}).get('uom_id') == str(gram.id)
        for row in history
    )
    # And the journal says it in the word the screens use.
    journal = db_session.scalars(
        select(AuditLog).where(
            AuditLog.target_id == record.id,
            AuditLog.action == AuditAction.UPDATE.value,
        )
    ).all()
    assert any(
        (entry.snapshot or {}).get('after', {}).get('uom_id') == 'g'
        and 'uom_id' in (entry.snapshot or {}).get('fields', [])
        for entry in journal
    )


def test_a_record_with_its_own_unit_keeps_it(
    client: TestClient,
    doc_auth_headers: dict[str, str],
    doc_target_location: StorageLocation,
    doc_partner: Partner,
    db_session: Session,
    doc_org: Organization,
    gram: Uom,
) -> None:
    name = f'Counted Spice {uuid4().hex[:6]}'
    card = ProductTemplate(
        organization_id=doc_org.id,
        name=name,
        sku=f'SKU-{uuid4().hex[:8]}',
        uom_id=gram.id,
    )
    record = Item(
        name=name,
        organization_id=doc_org.id,
        template_id=None,
        uom_id=gram.id,
        storage_location_id=doc_target_location.id,
        quantity=Decimal('0'),
    )
    db_session.add_all([card, record])
    db_session.commit()

    _receive(
        client,
        doc_auth_headers,
        partner_id=doc_partner.id,
        location_id=doc_target_location.id,
        item_id=record.id,
        quantity=2,
    )

    db_session.expire_all()
    bound = db_session.get(Item, record.id)
    assert bound is not None and bound.uom_id == gram.id
