"""A quantity on a WMS screen is worthless without the unit it counts.

The picker standing at the shelf reads one line: product, quantity, unit.
When the unit is missing the line says "3" and means nothing — three pieces,
three packs and three kilograms are three different picks.

The unit was never absent from the data: the record on the shelf carries it.
It was lost between the record and the document line, and the WMS session
copied the loss forward. These tests follow the whole way from a stored
product with a unit to the row the picker reads, because the same class was
closed once in recipes and came back here in documents.
"""

import uuid
from decimal import Decimal
from typing import cast

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.storage_location import StorageLocation
from app.models.uom import Uom
from app.modules.warehouse.models import DocumentLine


@pytest.fixture
def uncatalogued_stock(
    db_session: Session,
    doc_org: Organization,
    doc_source_location: StorageLocation,
    doc_uom_pcs: Uom,
) -> Item:
    """Stock standing on a shelf with a unit but no catalogue entry.

    The catalogue is not the only place a unit can come from — a record
    created straight on a shelf carries one too, and a document line naming
    that record has no other source for it.
    """
    item = Item(
        name='Uncatalogued widget',
        organization_id=doc_org.id,
        storage_location_id=doc_source_location.id,
        quantity=Decimal('100'),
        uom_id=doc_uom_pcs.id,
    )
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)
    return item


def _create_document(
    client: TestClient,
    auth_headers: dict[str, str],
    payload: dict[str, object],
) -> str:
    response = client.post(
        '/api/v1/warehouse/documents', headers=auth_headers, json=payload
    )
    assert response.status_code == status.HTTP_201_CREATED, response.text
    return cast(str, response.json()['id'])


def _confirm(client: TestClient, auth_headers: dict[str, str], doc_id: str) -> None:
    resp = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=auth_headers
    )
    assert resp.status_code == status.HTTP_200_OK, resp.text


@pytest.mark.integration
class TestTheLineKeepsTheUnitOfWhatItNames:
    def test_a_line_naming_stock_inherits_the_unit_of_that_stock(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_partner: Partner,
        uncatalogued_stock: Item,
    ) -> None:
        doc_id = _create_document(
            client,
            doc_auth_headers,
            {
                'type': 'OUT',
                'partner_id': str(doc_partner.id),
                'source_location_id': str(doc_source_location.id),
                'lines': [
                    {'item_id': str(uncatalogued_stock.id), 'expected_quantity': 3}
                ],
            },
        )

        detail = client.get(
            f'/api/v1/warehouse/documents/{doc_id}', headers=doc_auth_headers
        ).json()
        line = detail['lines'][0]
        assert line['uom'] is not None, 'the document detail lost the unit'
        assert line['uom']['symbol'] == 'pcs'

    def test_the_picker_reads_the_unit_on_the_session_row(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        uncatalogued_stock: Item,
    ) -> None:
        doc_id = _create_document(
            client,
            doc_auth_headers,
            {
                'type': 'OUT',
                'partner_id': str(doc_partner.id),
                'source_location_id': str(doc_source_location.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {'item_id': str(uncatalogued_stock.id), 'expected_quantity': 3}
                ],
            },
        )
        _confirm(client, doc_auth_headers, doc_id)

        resp = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/start',
            headers=doc_auth_headers,
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        assert resp.json()['lines'][0]['uom_symbol'] == 'pcs'

    def test_the_receiver_reads_the_unit_on_the_session_row(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        uncatalogued_stock: Item,
    ) -> None:
        doc_id = _create_document(
            client,
            doc_auth_headers,
            {
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {'item_id': str(uncatalogued_stock.id), 'expected_quantity': 6}
                ],
            },
        )
        _confirm(client, doc_auth_headers, doc_id)

        resp = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/start',
            headers=doc_auth_headers,
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        assert resp.json()['lines'][0]['uom_symbol'] == 'pcs'

    def test_a_line_stored_without_a_unit_still_reads_it_off_the_stock(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        uncatalogued_stock: Item,
    ) -> None:
        """Documents written before the line inherited a unit still exist.

        Their picker gets the same row as everyone else's: the record the
        line names is still on the shelf and still carries the unit.
        """
        doc_id = _create_document(
            client,
            doc_auth_headers,
            {
                'type': 'OUT',
                'partner_id': str(doc_partner.id),
                'source_location_id': str(doc_source_location.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {'item_id': str(uncatalogued_stock.id), 'expected_quantity': 3}
                ],
            },
        )
        stored = db_session.scalars(
            select(DocumentLine).where(DocumentLine.document_id == uuid.UUID(doc_id))
        ).one()
        stored.uom_id = None
        db_session.commit()

        _confirm(client, doc_auth_headers, doc_id)

        resp = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/start',
            headers=doc_auth_headers,
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        assert resp.json()['lines'][0]['uom_symbol'] == 'pcs'

    def test_a_line_naming_only_a_template_reads_the_unit_off_that_template(
        self,
        client: TestClient,
        db_session: Session,
        doc_org: Organization,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_uom_pcs: Uom,
    ) -> None:
        """A line with product_template_id and no item_id still carries the unit.

        The template is the catalogue entry; its unit is the one the
        document was written in. A line that names only the template (no
        stock record yet) must still show the unit on the session row.
        """
        from app.models.product_template import ProductTemplate

        template = ProductTemplate(
            name='Catalogue widget',
            organization_id=doc_org.id,
            uom_id=doc_uom_pcs.id,
        )
        db_session.add(template)
        db_session.commit()
        db_session.refresh(template)

        doc_id = _create_document(
            client,
            doc_auth_headers,
            {
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {'product_template_id': str(template.id), 'expected_quantity': 2}
                ],
            },
        )
        _confirm(client, doc_auth_headers, doc_id)

        resp = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/start',
            headers=doc_auth_headers,
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        assert resp.json()['lines'][0]['uom_symbol'] == 'pcs'

    def test_a_product_without_a_unit_still_reports_none(
        self,
        client: TestClient,
        db_session: Session,
        doc_org: Organization,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
    ) -> None:
        """The dash is the honest answer when nobody ever named a unit.

        Inventing one here would be worse than the missing one: the picker
        would read a unit the catalogue never agreed to.
        """
        item = Item(
            name='Unitless widget',
            organization_id=doc_org.id,
            storage_location_id=doc_source_location.id,
            quantity=Decimal('10'),
        )
        db_session.add(item)
        db_session.commit()
        db_session.refresh(item)

        doc_id = _create_document(
            client,
            doc_auth_headers,
            {
                'type': 'OUT',
                'partner_id': str(doc_partner.id),
                'source_location_id': str(doc_source_location.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [{'item_id': str(item.id), 'expected_quantity': 1}],
            },
        )
        _confirm(client, doc_auth_headers, doc_id)

        resp = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/start',
            headers=doc_auth_headers,
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        assert resp.json()['lines'][0]['uom_symbol'] is None
