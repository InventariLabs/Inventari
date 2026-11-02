"""A document that takes goods off a shelf has to say which goods.

The stock executors move stock by record. Dispatch and transfer said so and
refused a line naming only a catalogue entry — at the last step, after the
document had been issued, approved and reserved. Scrap did not even refuse: a
line with no record, on a document with no source location, left it nothing to
resolve, so it skipped the whole stock block and closed as COMPLETED. The
register then held a write-off of goods still on the shelf, which is the
opposite of what the module is for.

The rule now lands at confirmation, where the document commits: a draft may
still be half-written, but confirming reserves the stock and promises the
movement. The form does not produce such lines any more either — the search
behind those documents answers with the stock on hand.
"""

from __future__ import annotations

from decimal import Decimal
from typing import cast
from uuid import UUID

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.testing import ShelfRow
from app.models.item import Item
from app.models.organization import Organization
from app.models.storage_location import StorageLocation


def _create(
    client: TestClient,
    headers: dict[str, str],
    payload: dict[str, object],
) -> str:
    resp = client.post('/api/v1/warehouse/documents', headers=headers, json=payload)
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    return cast(str, resp.json()['id'])


def _shelf_at(
    db_session: Session,
    org_id: UUID,
    template_id: UUID,
    location_id: UUID,
) -> Decimal:
    """What the shelf holds of the product; 0 once its records are all gone."""
    group = db_session.scalars(
        select(ShelfRow).where(
            ShelfRow.organization_id == org_id,
            ShelfRow.product_template_id == template_id,
            ShelfRow.storage_location_id == location_id,
        )
    ).first()
    return group.quantity if group else Decimal('0')


@pytest.mark.integration
class TestLinesMustNameStock:
    def test_scrap_naming_only_a_product_is_refused_at_confirmation(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_stock_item: Item,
        db_session: Session,
    ) -> None:
        """The shape that used to close as done and move nothing."""
        template_id = doc_stock_item.template_id
        assert template_id is not None
        doc_id = _create(
            client,
            doc_auth_headers,
            {
                'type': 'SCRAP',
                'reason_code': 'DAMAGED',
                'lines': [
                    {'product_template_id': str(template_id), 'expected_quantity': 1}
                ],
            },
        )

        confirm = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        assert confirm.status_code == status.HTTP_400_BAD_REQUEST
        assert 'takes goods off a shelf' in confirm.text
        # One line is one line: the sentence said "lines 1 name only a
        # product", and a refusal a reader has to parse is a second defect.
        assert 'line 1 names only a product' in confirm.text
        assert confirm.json()['detail']['code'] == 'DOCUMENT_LINES_NEED_STOCK_ROW'

        # Nothing moved, and nothing claims otherwise: the document is still a
        # draft rather than a completed write-off of goods on the shelf.
        detail = client.get(
            f'/api/v1/warehouse/documents/{doc_id}', headers=doc_auth_headers
        )
        assert detail.json()['status'] == 'DRAFT'
        db_session.refresh(doc_stock_item)
        assert doc_stock_item.quantity == Decimal('100')

    def test_scrap_naming_a_record_takes_it_off_both_views(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_source_location: StorageLocation,
        doc_stock_item: Item,
        db_session: Session,
    ) -> None:
        """No source location needed — the record says where it stands."""
        template_id = doc_stock_item.template_id
        assert template_id is not None

        doc_id = _create(
            client,
            doc_auth_headers,
            {
                'type': 'SCRAP',
                'reason_code': 'DAMAGED',
                'lines': [{'item_id': str(doc_stock_item.id), 'expected_quantity': 4}],
            },
        )
        assert (
            client.patch(
                f'/api/v1/warehouse/documents/{doc_id}/confirm',
                headers=doc_auth_headers,
            ).status_code
            == status.HTTP_200_OK
        )
        complete = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert complete.status_code == status.HTTP_200_OK, complete.text

        db_session.expire_all()
        assert _shelf_at(
            db_session, doc_org.id, template_id, doc_source_location.id
        ) == Decimal('96')
        db_session.refresh(doc_stock_item)
        assert doc_stock_item.quantity == Decimal('96')

    def test_transfer_naming_only_a_product_is_refused_at_confirmation(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_stock_item: Item,
    ) -> None:
        """It used to be issued, confirmed, and only then found unexecutable.

        Worse than that from the floor: the scan session would start, take the
        line to picked, and leave the document unable to complete or cancel.
        """
        template_id = doc_stock_item.template_id
        assert template_id is not None
        doc_id = _create(
            client,
            doc_auth_headers,
            {
                'type': 'INT',
                'source_location_id': str(doc_source_location.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {'product_template_id': str(template_id), 'expected_quantity': 4}
                ],
            },
        )

        confirm = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        assert confirm.status_code == status.HTTP_400_BAD_REQUEST
        assert 'takes goods off a shelf' in confirm.text

    def test_a_draft_may_still_be_half_written(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_stock_item: Item,
    ) -> None:
        """The refusal is at the commitment, not at the first save."""
        template_id = doc_stock_item.template_id
        assert template_id is not None
        _create(
            client,
            doc_auth_headers,
            {
                'type': 'INTERNAL_OUT',
                'source_location_id': str(doc_source_location.id),
                'lines': [
                    {'product_template_id': str(template_id), 'expected_quantity': 1}
                ],
            },
        )

    def test_the_search_behind_such_a_document_answers_with_stock(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_stock_item: Item,
    ) -> None:
        """Without a location too — a scrap has no shelf of its own to give.

        The location used to be the only way to ask for stock, so the scrap
        form fell back to the catalogue and built the lines this test's first
        case refuses.
        """
        resp = client.get(
            '/api/v1/warehouse/product-search',
            headers=doc_auth_headers,
            params={'q': doc_stock_item.name, 'stock': 'true'},
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        results = resp.json()
        assert results, resp.text
        assert all(r['item_id'] for r in results)
        assert str(doc_stock_item.id) in {r['item_id'] for r in results}

    def test_the_catalogue_is_still_what_a_receipt_searches(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_stock_item: Item,
    ) -> None:
        """A receipt brings in goods nobody holds yet, so it names products."""
        resp = client.get(
            '/api/v1/warehouse/product-search',
            headers=doc_auth_headers,
            params={'q': doc_stock_item.name},
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        assert all(r['item_id'] is None for r in resp.json())
