"""A receipt puts products into stock, not words.

A receipt took a line typed by hand — "Test laptop Dell" at 3000 — and posted
it: stock that no product on the list stood behind, which nobody could find
again by the product they were looking for. The form now offers to make the
typed name a product; the register refuses to commit a line that names none,
and says which line it is.

The refusal is at the commitment, like the other line rules: a draft may hold
a typed line (a pasted list, a line half-written), and a document written
before the rule still opens with the lines it has.
"""

from __future__ import annotations

from typing import Any, cast

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.modules.warehouse.models import Document

pytestmark = pytest.mark.integration


def _create(
    client: TestClient,
    headers: dict[str, str],
    payload: dict[str, Any],
) -> dict[str, Any]:
    resp = client.post('/api/v1/warehouse/documents', headers=headers, json=payload)
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    return cast(dict[str, Any], resp.json())


def _receipt(
    partner: Any, target: StorageLocation, *lines: dict[str, Any]
) -> dict[str, Any]:
    return {
        'type': 'IN',
        'partner_id': str(partner.id),
        'target_location_id': str(target.id),
        'lines': list(lines),
    }


def _records_named(db_session: Session, org: Organization, name: str) -> list[Item]:
    db_session.expire_all()
    return list(
        db_session.scalars(
            select(Item).where(Item.organization_id == org.id, Item.name == name)
        )
    )


class TestAReceiptLineNamesAProduct:
    def test_a_typed_line_is_refused_at_confirmation_naming_the_line(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Any,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        doc = _create(
            client,
            doc_auth_headers,
            _receipt(
                doc_partner,
                doc_target_location,
                {'product_template_id': str(doc_template.id), 'expected_quantity': 1},
                {
                    'name': 'Test laptop Dell',
                    'expected_quantity': 1,
                    'unit_price': '3000',
                },
            ),
        )

        confirm = client.patch(
            f'/api/v1/warehouse/documents/{doc["id"]}/confirm', headers=doc_auth_headers
        )

        assert confirm.status_code == status.HTTP_400_BAD_REQUEST
        assert 'Line 2 (Test laptop Dell) names no product' in confirm.text
        assert confirm.json()['detail']['code'] == 'DOCUMENT_RECEIPT_LINES_NEED_PRODUCT'
        detail = client.get(
            f'/api/v1/warehouse/documents/{doc["id"]}', headers=doc_auth_headers
        )
        assert detail.json()['status'] == 'DRAFT'

    def test_an_internal_receipt_asks_the_same(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
    ) -> None:
        doc = _create(
            client,
            doc_auth_headers,
            {
                'type': 'INTERNAL_IN',
                'target_location_id': str(doc_target_location.id),
                'lines': [{'name': 'Loose bolts', 'expected_quantity': 3}],
            },
        )

        confirm = client.patch(
            f'/api/v1/warehouse/documents/{doc["id"]}/confirm', headers=doc_auth_headers
        )

        assert confirm.status_code == status.HTTP_400_BAD_REQUEST
        assert 'Line 1 (Loose bolts)' in confirm.text

    def test_a_receipt_confirmed_before_the_rule_does_not_post_the_line(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_partner: Any,
        doc_target_location: StorageLocation,
        db_session: Session,
    ) -> None:
        """Confirmation was the old gate's last word; posting asks again."""
        doc = _create(
            client,
            doc_auth_headers,
            _receipt(
                doc_partner,
                doc_target_location,
                {'name': 'Test laptop Dell', 'expected_quantity': 1},
            ),
        )
        row = db_session.get(Document, doc['id'])
        assert row is not None
        row.status = 'CONFIRMED'
        db_session.commit()

        done = client.patch(
            f'/api/v1/warehouse/documents/{doc["id"]}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )

        assert done.status_code == status.HTTP_400_BAD_REQUEST
        assert 'Line 1 (Test laptop Dell)' in done.text
        assert _records_named(db_session, doc_org, 'Test laptop Dell') == []

    def test_a_code_the_list_knows_names_its_product(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Any,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        """A scanned code is a product on the list, even with no id beside it."""
        doc = _create(
            client,
            doc_auth_headers,
            _receipt(
                doc_partner,
                doc_target_location,
                {
                    'name': 'Scanned',
                    'barcode': doc_template.barcode,
                    'expected_quantity': 2,
                },
            ),
        )
        assert (
            client.patch(
                f'/api/v1/warehouse/documents/{doc["id"]}/confirm',
                headers=doc_auth_headers,
            ).status_code
            == status.HTTP_200_OK
        )
        done = client.patch(
            f'/api/v1/warehouse/documents/{doc["id"]}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )

        assert done.status_code == status.HTTP_200_OK, done.text
        assert done.json()['lines'][0]['product_template_id'] == str(doc_template.id)

    def test_a_document_holding_typed_lines_still_opens(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Any,
        doc_target_location: StorageLocation,
        db_session: Session,
    ) -> None:
        """Written and posted before the rule: it reads as it was written."""
        doc = _create(
            client,
            doc_auth_headers,
            _receipt(
                doc_partner,
                doc_target_location,
                {'name': 'Test laptop Dell', 'expected_quantity': 1},
            ),
        )
        row = db_session.get(Document, doc['id'])
        assert row is not None
        row.status = 'COMPLETED'
        db_session.commit()

        detail = client.get(
            f'/api/v1/warehouse/documents/{doc["id"]}', headers=doc_auth_headers
        )

        assert detail.status_code == status.HTTP_200_OK, detail.text
        assert detail.json()['status'] == 'COMPLETED'
        assert detail.json()['lines'][0]['name'] == 'Test laptop Dell'
        assert detail.json()['lines'][0]['product_template_id'] is None
