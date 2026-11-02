"""Edits, cancels, e-mails, line imports, price lists and reorder rules are journalled.

Create and confirm always wrote an entry; every other act on an order, and
every write to the two configuration tables the module keeps, changed what a
later order says or costs and left nothing to read afterwards.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.public_api import core_api
from app.models.audit_log import AuditLog

PO_URL = '/api/v1/purchase-orders'


def _entries(
    db: Session, org: Any, target_type: str, target_id: str | None = None
) -> list[dict[str, Any]]:
    db.expire_all()
    query = select(AuditLog).where(
        AuditLog.organization_id == org.id,
        AuditLog.target_type == target_type,
        AuditLog.action == 'UPDATE',
    )
    if target_id is not None:
        query = query.where(AuditLog.target_id == UUID(target_id))
    return [
        row.snapshot or {} for row in db.scalars(query.order_by(AuditLog.created_at))
    ]


def _config(db: Session, org: Any, subject: str) -> list[dict[str, Any]]:
    return [
        entry
        for entry in _entries(db, org, 'module')
        if entry.get('subject') == subject
    ]


def _order(client: TestClient, headers: dict[str, str], partner: Any) -> dict[str, Any]:
    resp = client.post(
        PO_URL,
        headers=headers,
        json={
            'partner_id': str(partner.id),
            'notes': 'first note',
            'lines': [{'name': 'Widget', 'quantity_ordered': 2, 'unit_price': '3.50'}],
        },
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    body: dict[str, Any] = resp.json()
    return body


@pytest.mark.integration
class TestOrderActsAreJournalled:
    def test_an_edit_names_what_moved(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        po_partner: Any,
        po_org: Any,
        db_session: Session,
    ) -> None:
        po = _order(client, po_auth_headers, po_partner)
        resp = client.patch(
            f'{PO_URL}/{po["id"]}',
            headers=po_auth_headers,
            json={
                'notes': 'second note',
                'lines': [{'name': 'Widget', 'quantity_ordered': 5}],
            },
        )
        assert resp.status_code == 200, resp.text

        (entry,) = _entries(db_session, po_org, 'purchase_order', po['id'])
        snapshot = entry
        assert snapshot['number'] == po['number']
        assert snapshot['before']['notes'] == 'first note'
        assert snapshot['after']['notes'] == 'second note'
        assert snapshot['before']['lines'] == ['Widget × 2 @ 3.5']
        assert snapshot['after']['lines'] == ['Widget × 5']
        assert 'partner_id' not in snapshot['after']

    @pytest.mark.parametrize(
        ('field', 'old', 'new', 'old_text', 'new_text'),
        [
            ('tax_rate', '0.10', '0.20', ' · tax 0.1%', ' · tax 0.2%'),
            ('notes', 'line old', 'line new', ': line old', ': line new'),
        ],
    )
    def test_a_change_to_one_line_field_alone_is_journalled(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        po_partner: Any,
        po_org: Any,
        db_session: Session,
        field: str,
        old: str,
        new: str,
        old_text: str,
        new_text: str,
    ) -> None:
        line = {'name': 'Widget', 'quantity_ordered': 2, 'unit_price': '3.50'}
        created = client.post(
            PO_URL,
            headers=po_auth_headers,
            json={
                'partner_id': str(po_partner.id),
                'lines': [{**line, field: old}],
            },
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        po = created.json()
        resp = client.patch(
            f'{PO_URL}/{po["id"]}',
            headers=po_auth_headers,
            json={'lines': [{**line, field: new}]},
        )
        assert resp.status_code == 200, resp.text

        (entry,) = _entries(db_session, po_org, 'purchase_order', po['id'])
        assert entry['before']['lines'][0].endswith(old_text)
        assert entry['after']['lines'][0].endswith(new_text)

    def test_an_edit_that_changes_nothing_writes_nothing(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        po_partner: Any,
        po_org: Any,
        db_session: Session,
    ) -> None:
        po = _order(client, po_auth_headers, po_partner)
        resp = client.patch(
            f'{PO_URL}/{po["id"]}',
            headers=po_auth_headers,
            json={'notes': 'first note'},
        )
        assert resp.status_code == 200, resp.text
        assert _entries(db_session, po_org, 'purchase_order', po['id']) == []

    def test_detaching_the_supplier_names_the_old_one(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        po_partner: Any,
        po_org: Any,
        db_session: Session,
    ) -> None:
        po = _order(client, po_auth_headers, po_partner)
        resp = client.patch(
            f'{PO_URL}/{po["id"]}', headers=po_auth_headers, json={'partner_id': None}
        )
        assert resp.status_code == 200, resp.text
        (entry,) = _entries(db_session, po_org, 'purchase_order', po['id'])
        assert entry['before']['partner_name'] == po_partner.name
        assert entry['after']['partner_name'] is None

    def test_a_cancel_records_the_status_it_left(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        po_partner: Any,
        po_org: Any,
        db_session: Session,
    ) -> None:
        po = _order(client, po_auth_headers, po_partner)
        resp = client.post(f'{PO_URL}/{po["id"]}/cancel', headers=po_auth_headers)
        assert resp.status_code == 200, resp.text
        (entry,) = _entries(db_session, po_org, 'purchase_order', po['id'])
        assert entry['before'] == {'status': 'DRAFT'}
        assert entry['after'] == {'status': 'CANCELLED'}

    def test_an_e_mail_to_the_supplier_is_journalled(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        po_partner: Any,
        po_org: Any,
        db_session: Session,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        po = _order(client, po_auth_headers, po_partner)
        assert (
            client.post(
                f'{PO_URL}/{po["id"]}/confirm', headers=po_auth_headers
            ).status_code
            == 200
        )
        send = AsyncMock(return_value=True)
        monkeypatch.setattr(core_api.email, 'send_with_attachment_async', send)

        resp = client.post(f'{PO_URL}/{po["id"]}/send-email', headers=po_auth_headers)
        assert resp.status_code == 200, resp.text
        send.assert_awaited_once()
        sent = [
            e
            for e in _entries(db_session, po_org, 'purchase_order', po['id'])
            if 'emailed_to' in e
        ]
        assert len(sent) == 1
        assert sent[0]['emailed_to'] == po_partner.email
        assert sent[0]['partner_name'] == po_partner.name

    def test_a_failed_e_mail_leaves_no_entry(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        po_partner: Any,
        po_org: Any,
        db_session: Session,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        po = _order(client, po_auth_headers, po_partner)
        client.post(f'{PO_URL}/{po["id"]}/confirm', headers=po_auth_headers)
        monkeypatch.setattr(
            core_api.email,
            'send_with_attachment_async',
            AsyncMock(return_value=False),
        )
        resp = client.post(f'{PO_URL}/{po["id"]}/send-email', headers=po_auth_headers)
        assert resp.status_code == 502
        assert not [
            e
            for e in _entries(db_session, po_org, 'purchase_order', po['id'])
            if 'emailed_to' in e
        ]

    def test_a_line_import_counts_the_lines_it_added(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        po_partner: Any,
        po_org: Any,
        db_session: Session,
    ) -> None:
        po = _order(client, po_auth_headers, po_partner)
        resp = client.post(
            f'{PO_URL}/{po["id"]}/import-lines',
            headers=po_auth_headers,
            files={
                'file': (
                    'lines.csv',
                    b'name,quantity_ordered\nBolt,4\nNut,6\n',
                    'text/csv',
                )
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()['imported'] == 2
        (entry,) = _entries(db_session, po_org, 'purchase_order', po['id'])
        assert entry['before'] == {'line_count': 1}
        assert entry['after'] == {'line_count': 3}
        assert entry['imported_from'] == 'lines.csv'


@pytest.mark.integration
class TestPricelistIsJournalled:
    def test_create_edit_and_delete_each_write_an_entry(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        po_partner: Any,
        po_template: Any,
        po_org: Any,
        db_session: Session,
    ) -> None:
        created = client.post(
            f'{PO_URL}/pricelist',
            headers=po_auth_headers,
            json={
                'partner_id': str(po_partner.id),
                'product_template_id': str(po_template.id),
                'unit_price': '10.00',
                'valid_from': '2026-01-01',
            },
        )
        assert created.status_code == 201, created.text
        entry_id = created.json()['id']
        edited = client.patch(
            f'{PO_URL}/pricelist/{entry_id}',
            headers=po_auth_headers,
            json={'unit_price': '12.50'},
        )
        assert edited.status_code == 200, edited.text
        untouched = client.patch(
            f'{PO_URL}/pricelist/{entry_id}',
            headers=po_auth_headers,
            json={'unit_price': '12.50'},
        )
        assert untouched.status_code == 200, untouched.text
        deleted = client.delete(
            f'{PO_URL}/pricelist/{entry_id}', headers=po_auth_headers
        )
        assert deleted.status_code == 204, deleted.text

        created_entry, edited_entry, deleted_entry = _config(
            db_session, po_org, 'pricelist'
        )
        assert created_entry['partner_name'] == po_partner.name
        assert created_entry['product_template_name'] == po_template.name
        assert created_entry['after']['unit_price'] == '10.0000'
        assert edited_entry['before']['unit_price'] == '10.0000'
        assert edited_entry['after']['unit_price'] == '12.5000'
        assert list(edited_entry['after']) == ['unit_price']
        assert deleted_entry['before']['unit_price'] == '12.5000'
        assert not any(deleted_entry['after'].values())


@pytest.mark.integration
class TestReorderRuleIsJournalled:
    def test_create_edit_and_delete_each_write_an_entry(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        po_template: Any,
        po_location: Any,
        po_partner: Any,
        po_org: Any,
        db_session: Session,
    ) -> None:
        created = client.post(
            f'{PO_URL}/reorder-rules',
            headers=po_auth_headers,
            json={
                'product_template_id': str(po_template.id),
                'location_id': str(po_location.id),
                'min_quantity': '5',
                'max_quantity': '20',
            },
        )
        assert created.status_code == 201, created.text
        rule_id = created.json()['id']
        edited = client.patch(
            f'{PO_URL}/reorder-rules/{rule_id}',
            headers=po_auth_headers,
            json={'max_quantity': '30', 'preferred_partner_id': str(po_partner.id)},
        )
        assert edited.status_code == 200, edited.text
        deleted = client.delete(
            f'{PO_URL}/reorder-rules/{rule_id}', headers=po_auth_headers
        )
        assert deleted.status_code == 204, deleted.text

        created_entry, edited_entry, deleted_entry = _config(
            db_session, po_org, 'reorder-rule'
        )
        assert created_entry['location_name'] == po_location.name
        assert created_entry['product_template_name'] == po_template.name
        assert edited_entry['before']['max_quantity'] == '20.000'
        assert edited_entry['after']['max_quantity'] == '30.000'
        assert edited_entry['after']['preferred_partner_name'] == po_partner.name
        assert 'min_quantity' not in edited_entry['after']
        assert deleted_entry['before']['max_quantity'] == '30.000'
