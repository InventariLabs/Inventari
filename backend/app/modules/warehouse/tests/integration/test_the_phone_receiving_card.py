"""The phone's receiving card: a scan that names the item, and a shelf to offer.

The phone receives one item at a time. Scanning the product only says which
line is in hand — the count is the worker's, confirmed on the card — so the
scan must not count anything: a one-unit line scanned once used to be
received, the session closed and the document posted before the worker had
looked at the number.

When no rule names a shelf, the plan is the document's own target, which on
a delivery is usually the whole warehouse and tells the person holding the
box nothing. The card then offers the shelf the product already lies on,
else the shelf last received onto in that warehouse.
"""

import uuid
from typing import Any, cast

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.user import User
from app.modules.warehouse.tests.integration._records import sow


def _delivery(
    client: TestClient,
    headers: dict[str, str],
    target_id: uuid.UUID,
    partner_id: uuid.UUID,
    template_id: uuid.UUID,
    quantity: int,
) -> str:
    """A confirmed delivery of one line."""
    created = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'IN',
            'partner_id': str(partner_id),
            'target_location_id': str(target_id),
            'lines': [
                {'product_template_id': str(template_id), 'expected_quantity': quantity}
            ],
        },
    )
    assert created.status_code == status.HTTP_201_CREATED, created.text
    doc_id = cast(str, created.json()['id'])
    confirmed = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=headers
    )
    assert confirmed.status_code == status.HTTP_200_OK, confirmed.text
    return doc_id


def _receive(
    client: TestClient,
    headers: dict[str, str],
    target_id: uuid.UUID,
    partner_id: uuid.UUID,
    template_id: uuid.UUID,
    quantity: int,
) -> tuple[str, dict[str, Any]]:
    """A confirmed delivery with its receiving session started."""
    doc_id = _delivery(client, headers, target_id, partner_id, template_id, quantity)
    started = client.post(
        f'/api/v1/warehouse/documents/{doc_id}/receiving/start', headers=headers
    )
    assert started.status_code == status.HTTP_201_CREATED, started.text
    return doc_id, started.json()


def _shelf(
    db: Session,
    org: Organization,
    storage_type: StorageType,
    user: User,
    parent: StorageLocation,
    name: str,
) -> StorageLocation:
    shelf = StorageLocation(
        name=name,
        organization_id=org.id,
        storage_type_id=storage_type.id,
        created_by=user.id,
        parent_id=parent.id,
    )
    db.add(shelf)
    db.commit()
    db.refresh(shelf)
    return shelf


@pytest.mark.integration
class TestTheIdentifyingScan:
    def test_names_the_line_and_counts_nothing(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        doc_id, session = _receive(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_partner.id,
            doc_template.id,
            quantity=1,
        )
        line_id = session['lines'][0]['id']

        resp = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/{session["id"]}/scan',
            headers=doc_auth_headers,
            json={'barcode': doc_template.barcode, 'identify': True},
        )

        assert resp.status_code == status.HTTP_200_OK, resp.text
        data = resp.json()
        assert data['status'] == 'identified'
        assert data['line_id'] == line_id
        assert data['received_quantity'] == 0
        assert data['session_complete'] is False
        stored = client.get(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/{session["id"]}',
            headers=doc_auth_headers,
        ).json()
        assert stored['status'] == 'active'
        assert stored['lines'][0]['status'] == 'pending'
        assert stored['lines'][0]['received_quantity'] == 0


@pytest.mark.integration
class TestTheShelfTheCardOffers:
    def test_a_warehouse_target_offers_the_shelf_the_product_lies_on(
        self,
        client: TestClient,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        h: ModuleTestHelper,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_storage_type: StorageType,
        doc_user: User,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        _shelf(
            db_session, doc_org, doc_storage_type, doc_user, doc_target_location, 'A-01'
        )
        holding = _shelf(
            db_session, doc_org, doc_storage_type, doc_user, doc_target_location, 'A-02'
        )
        sow(db_session, async_engine_fixture, doc_org, doc_template, holding.id, '4')

        _doc_id, session = _receive(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_partner.id,
            doc_template.id,
            quantity=3,
        )

        line = session['lines'][0]
        assert line['planned_source'] == 'document'
        assert line['suggested_location_id'] == str(holding.id)
        assert line['suggested_location_name'] == 'A-02'
        assert line['suggested_source'] == 'stock'

    def test_without_stock_it_offers_the_shelf_last_received_onto(
        self,
        client: TestClient,
        db_session: Session,
        h: ModuleTestHelper,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_storage_type: StorageType,
        doc_user: User,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        used = _shelf(
            db_session, doc_org, doc_storage_type, doc_user, doc_target_location, 'B-01'
        )
        earlier = _delivery(
            client, doc_auth_headers, used.id, doc_partner.id, doc_template.id, 2
        )
        completed = client.patch(
            f'/api/v1/warehouse/documents/{earlier}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert completed.status_code == status.HTTP_200_OK, completed.text
        newcomer = h.create_template(doc_org, name='Newcomer', barcode='5900000000017')

        _doc_id, session = _receive(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_partner.id,
            newcomer.id,
            quantity=1,
        )

        line = session['lines'][0]
        assert line['suggested_location_id'] == str(used.id)
        assert line['suggested_source'] == 'zone'

    def test_a_shelf_named_by_the_document_needs_no_offer(
        self,
        client: TestClient,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_target_location: StorageLocation,
        doc_source_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        # The product lies elsewhere, but the document names a shelf with
        # nothing below it: that shelf is the answer, not a fallback.
        sow(
            db_session,
            async_engine_fixture,
            doc_org,
            doc_template,
            doc_source_location.id,
            '4',
        )

        _doc_id, session = _receive(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_partner.id,
            doc_template.id,
            quantity=1,
        )

        line = session['lines'][0]
        assert line['planned_location_id'] == str(doc_target_location.id)
        assert line['suggested_location_id'] is None
        assert line['suggested_source'] is None
