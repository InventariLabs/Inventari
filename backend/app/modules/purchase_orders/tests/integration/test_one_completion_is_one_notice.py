"""Completing an order tells each person once.

The administrators were told, and so was whoever raised the order, by two
separate paths. An administrator who raised it got "Your order is completed"
and "Order completed" side by side, about one event.
"""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.notification import Notification
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation


def _complete_an_order(
    client: TestClient,
    headers: dict[str, str],
    partner: Partner,
    template: ProductTemplate,
    shelf: StorageLocation,
) -> str:
    created = client.post(
        '/api/v1/purchase-orders',
        headers=headers,
        json={
            'partner_id': str(partner.id),
            'lines': [
                {
                    'product_template_id': str(template.id),
                    'quantity_ordered': 2,
                    'unit_price': '2.50',
                }
            ],
        },
    )
    assert created.status_code == status.HTTP_201_CREATED, created.text
    order: dict[str, Any] = created.json()
    order_id = cast(str, order['id'])
    confirmed = client.post(
        f'/api/v1/purchase-orders/{order_id}/confirm', headers=headers
    )
    assert confirmed.status_code == status.HTTP_200_OK, confirmed.text
    posted = client.post(
        '/api/v1/warehouse/documents/post',
        headers=headers,
        json={
            'type': 'IN',
            'partner_id': str(partner.id),
            'target_location_id': str(shelf.id),
            'lines': [
                {
                    'product_template_id': str(template.id),
                    'expected_quantity': 2,
                    'source_po_line_id': confirmed.json()['lines'][0]['id'],
                }
            ],
        },
    )
    assert posted.status_code == status.HTTP_201_CREATED, posted.text
    return order_id


def _told(db: Session, order_id: str) -> list[UUID]:
    db.expire_all()
    return list(
        db.scalars(
            select(Notification.user_id).where(
                Notification.link == f'/purchase-orders/{order_id}',
                Notification.type == 'success',
            )
        )
    )


@pytest.mark.integration
class TestOneCompletionIsOneNotice:
    def test_an_administrator_who_raised_the_order_is_told_once(
        self,
        client: TestClient,
        db_session: Session,
        po_user: Any,
        po_auth_headers: dict[str, str],
        po_partner: Partner,
        po_template: ProductTemplate,
        po_location: StorageLocation,
    ) -> None:
        assert po_user.role == 'admin'
        order_id = _complete_an_order(
            client, po_auth_headers, po_partner, po_template, po_location
        )
        assert _told(db_session, order_id) == [po_user.id]

    def test_a_member_who_raised_it_and_the_administrator_are_each_told_once(
        self,
        client: TestClient,
        db_session: Session,
        h: ModuleTestHelper,
        po_org: Organization,
        po_user: Any,
        po_partner: Partner,
        po_template: ProductTemplate,
        po_location: StorageLocation,
    ) -> None:
        member = h.create_user(po_org, email='buyer@example.com', role='manager')
        db_session.commit()
        order_id = _complete_an_order(
            client,
            h.get_auth_headers(member),
            po_partner,
            po_template,
            po_location,
        )
        assert sorted(_told(db_session, order_id)) == sorted([po_user.id, member.id])
