"""Integration tests for POST /shopping-lists/{id}/convert-to-po.

Flow: un-purchased items with a ``template_id`` are grouped into a DRAFT
Purchase Order via ``purchase_orders_api``; items without a template are
skipped and reported. Converted items are marked as purchased.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.audit_log import AuditLog
from app.models.product_template import ProductTemplate
from app.models.user import User

LIST_URL = '/api/v1/shopping-lists'


@pytest.fixture
def po_template(db_session: Session, test_user: User) -> ProductTemplate:
    template = ProductTemplate(
        organization_id=test_user.organization_id, name='Milk 3.2%'
    )
    db_session.add(template)
    db_session.commit()
    db_session.refresh(template)
    return template


@pytest.fixture
def po_template_b(db_session: Session, test_user: User) -> ProductTemplate:
    template = ProductTemplate(organization_id=test_user.organization_id, name='Bread')
    db_session.add(template)
    db_session.commit()
    db_session.refresh(template)
    return template


def _create_list(client: TestClient, auth_headers: dict[str, str]) -> str:
    r = client.post(LIST_URL, json={'name': 'PO Source'}, headers=auth_headers)
    assert r.status_code == 201
    return str(r.json()['id'])


def _add_item(
    client: TestClient,
    auth_headers: dict[str, str],
    list_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    r = client.post(f'{LIST_URL}/{list_id}/items', json=payload, headers=auth_headers)
    assert r.status_code == 201, r.text
    data: dict[str, Any] = r.json()
    return data


@pytest.mark.integration
class TestConvertShoppingListToPO:
    def test_convert_groups_items_into_draft_po(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        po_template: ProductTemplate,
        po_template_b: ProductTemplate,
    ) -> None:
        """Two items of the same template merge into one PO line (summed qty)."""
        list_id = _create_list(client, auth_headers)
        tid = str(po_template.id)
        _add_item(
            client,
            auth_headers,
            list_id,
            {'name': 'Milk A', 'quantity': 2, 'template_id': tid},
        )
        _add_item(
            client,
            auth_headers,
            list_id,
            {'name': 'Milk B', 'quantity': 3, 'template_id': tid},
        )
        _add_item(
            client,
            auth_headers,
            list_id,
            {'name': 'Bread', 'quantity': 1, 'template_id': str(po_template_b.id)},
        )

        r = client.post(
            f'{LIST_URL}/{list_id}/convert-to-po', json={}, headers=auth_headers
        )

        assert r.status_code == 201, r.text
        data = r.json()
        assert data['converted_count'] == 3
        assert data['skipped_count'] == 0
        assert data['skipped_items'] == []
        assert data['po_number'].startswith('PO/')

        # PO exists as DRAFT with 2 grouped lines (2+3=5 milk, 1 bread)
        po = client.get(
            f'/api/v1/purchase-orders/{data["po_id"]}', headers=auth_headers
        )
        assert po.status_code == 200
        po_data = po.json()
        assert po_data['status'] == 'DRAFT'
        lines = {line['product_template_id']: line for line in po_data['lines']}
        assert len(lines) == 2
        assert Decimal(lines[tid]['quantity_ordered']) == 5.0
        assert Decimal(lines[str(po_template_b.id)]['quantity_ordered']) == 1

    def test_the_order_it_opens_is_journalled_by_who_converted(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        po_template: ProductTemplate,
        db_session: Session,
    ) -> None:
        """The list is a working note and journals nothing; the purchase order
        it opens is a record, and the orders module writes its entry in the
        same transaction. This pins that delegation: the conversion has no
        row of its own because the order's row is the one a reader needs."""
        list_id = _create_list(client, auth_headers)
        _add_item(
            client,
            auth_headers,
            list_id,
            {'name': 'Milk', 'quantity': 2, 'template_id': str(po_template.id)},
        )

        r = client.post(
            f'{LIST_URL}/{list_id}/convert-to-po', json={}, headers=auth_headers
        )
        assert r.status_code == 201, r.text

        db_session.expire_all()
        entries = db_session.scalars(
            select(AuditLog).where(
                AuditLog.target_type == 'purchase_order',
                AuditLog.target_id == UUID(r.json()['po_id']),
            )
        ).all()
        assert [(e.action, e.user_id) for e in entries] == [('CREATE', test_user.id)]

    def test_convert_skips_items_without_template(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        po_template: ProductTemplate,
    ) -> None:
        """Items without template_id are skipped and reported by name."""
        list_id = _create_list(client, auth_headers)
        _add_item(
            client,
            auth_headers,
            list_id,
            {'name': 'Milk', 'quantity': 1, 'template_id': str(po_template.id)},
        )
        _add_item(
            client, auth_headers, list_id, {'name': 'Fresh parsley', 'quantity': 1}
        )

        r = client.post(
            f'{LIST_URL}/{list_id}/convert-to-po', json={}, headers=auth_headers
        )

        assert r.status_code == 201, r.text
        data = r.json()
        assert data['converted_count'] == 1
        assert data['skipped_count'] == 1
        assert data['skipped_items'] == ['Fresh parsley']

    def test_convert_marks_items_purchased(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        po_template: ProductTemplate,
    ) -> None:
        """Converted items become purchased and carry the order they went to."""
        list_id = _create_list(client, auth_headers)
        item = _add_item(
            client,
            auth_headers,
            list_id,
            {'name': 'Milk', 'quantity': 1, 'template_id': str(po_template.id)},
        )

        r = client.post(
            f'{LIST_URL}/{list_id}/convert-to-po', json={}, headers=auth_headers
        )
        assert r.status_code == 201, r.text
        po_number = r.json()['po_number']

        items = client.get(
            f'{LIST_URL}/{list_id}/items',
            params={'purchased_filter': 'all'},
            headers=auth_headers,
        ).json()['items']
        by_id = {i['id']: i for i in items}
        converted = by_id[item['id']]
        assert converted['is_purchased'] is True
        assert converted['purchased_at'] is not None
        # The order's number travels as a part the list composes in the
        # reader's language; nothing is written into the item's own note.
        assert converted['note_data'] == {'converted_to_po': po_number}
        assert converted['notes'] is None

    def test_convert_keeps_the_item_note_and_its_composed_parts(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        po_template: ProductTemplate,
    ) -> None:
        """The reference joins what the item already said; it replaces none of it.

        The English line the conversion used to append to ``notes`` reached
        every language, and on an item whose note the list composes from
        ``note_data`` (a meal-plan line) it never showed at all.
        """
        list_id = _create_list(client, auth_headers)
        own = _add_item(
            client,
            auth_headers,
            list_id,
            {
                'name': 'Milk',
                'quantity': 1,
                'template_id': str(po_template.id),
                'notes': 'the blue carton',
            },
        )
        planned = _add_item(
            client,
            auth_headers,
            list_id,
            {
                'name': 'Milk for the curry',
                'quantity': 1,
                'template_id': str(po_template.id),
                'notes': 'Needed by: 2026-09-01',
                'note_data': {'needed_by': '2026-09-01'},
            },
        )

        r = client.post(
            f'{LIST_URL}/{list_id}/convert-to-po', json={}, headers=auth_headers
        )
        assert r.status_code == 201, r.text
        po_number = r.json()['po_number']

        items = client.get(
            f'{LIST_URL}/{list_id}/items',
            params={'purchased_filter': 'all'},
            headers=auth_headers,
        ).json()['items']
        by_id = {i['id']: i for i in items}
        assert by_id[own['id']]['notes'] == 'the blue carton'
        assert by_id[own['id']]['note_data'] == {'converted_to_po': po_number}
        assert by_id[planned['id']]['notes'] == 'Needed by: 2026-09-01'
        assert by_id[planned['id']]['note_data'] == {
            'needed_by': '2026-09-01',
            'converted_to_po': po_number,
        }

    def test_the_order_note_is_written_in_the_language_of_the_request(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        po_template: ProductTemplate,
    ) -> None:
        """The order's note names its list in the converting reader's language.

        It is the order's own free-text note — printed on its PDF and
        editable there — so it is written once, at conversion, rather than
        composed later; "From shopping list: …" used to reach every language.
        """
        list_id = _create_list(client, auth_headers)
        _add_item(
            client,
            auth_headers,
            list_id,
            {'name': 'Milk', 'quantity': 1, 'template_id': str(po_template.id)},
        )

        r = client.post(
            f'{LIST_URL}/{list_id}/convert-to-po',
            json={},
            headers={**auth_headers, 'Accept-Language': 'pl'},
        )
        assert r.status_code == 201, r.text
        po = client.get(
            f'/api/v1/purchase-orders/{r.json()["po_id"]}', headers=auth_headers
        ).json()
        assert po['notes'] == 'Z listy zakupów: PO Source'

    def test_convert_already_purchased_items_are_ignored(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        po_template: ProductTemplate,
    ) -> None:
        """Purchased items are not converted a second time."""
        list_id = _create_list(client, auth_headers)
        item = _add_item(
            client,
            auth_headers,
            list_id,
            {'name': 'Milk', 'quantity': 1, 'template_id': str(po_template.id)},
        )
        client.patch(
            f'{LIST_URL}/{list_id}/items/{item["id"]}/purchase',
            headers=auth_headers,
        )

        r = client.post(
            f'{LIST_URL}/{list_id}/convert-to-po', json={}, headers=auth_headers
        )
        assert r.status_code == 400

    def test_convert_nothing_to_convert_returns_400(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """A list with only template-less items yields no PO."""
        list_id = _create_list(client, auth_headers)
        _add_item(
            client, auth_headers, list_id, {'name': 'Fresh parsley', 'quantity': 1}
        )

        r = client.post(
            f'{LIST_URL}/{list_id}/convert-to-po', json={}, headers=auth_headers
        )
        assert r.status_code == 400

    def test_convert_with_supplier_sets_partner(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        po_template: ProductTemplate,
        db_session: Session,
        test_user: User,
    ) -> None:
        """supplier_id in the request body becomes the PO partner."""
        from app.models.partner import Partner

        partner = Partner(
            organization_id=test_user.organization_id,
            name='Supplier Co',
            type='SUPPLIER',
        )
        db_session.add(partner)
        db_session.commit()

        list_id = _create_list(client, auth_headers)
        _add_item(
            client,
            auth_headers,
            list_id,
            {'name': 'Milk', 'quantity': 1, 'template_id': str(po_template.id)},
        )

        r = client.post(
            f'{LIST_URL}/{list_id}/convert-to-po',
            json={'supplier_id': str(partner.id)},
            headers=auth_headers,
        )
        assert r.status_code == 201, r.text
        po = client.get(
            f'/api/v1/purchase-orders/{r.json()["po_id"]}', headers=auth_headers
        ).json()
        assert po['partner_id'] == str(partner.id)

    def test_convert_invalid_supplier_returns_400(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        po_template: ProductTemplate,
    ) -> None:
        list_id = _create_list(client, auth_headers)
        _add_item(
            client,
            auth_headers,
            list_id,
            {'name': 'Milk', 'quantity': 1, 'template_id': str(po_template.id)},
        )

        r = client.post(
            f'{LIST_URL}/{list_id}/convert-to-po',
            json={'supplier_id': str(uuid4())},
            headers=auth_headers,
        )
        assert r.status_code == 400

    def test_convert_list_not_found_returns_404(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        r = client.post(
            f'{LIST_URL}/{uuid4()}/convert-to-po', json={}, headers=auth_headers
        )
        assert r.status_code == 404
