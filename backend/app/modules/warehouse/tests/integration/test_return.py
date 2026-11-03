"""Integration tests for return document creation."""

import uuid
from decimal import Decimal
from io import BytesIO
from typing import Any, cast

import pypdf
import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation


@pytest.fixture
def doc_item(
    db_session: Session,
    doc_org: Organization,
    doc_source_location: StorageLocation,
) -> Item:
    """A record standing on the shelf these documents draw from.

    The shared fixture lands its record on the receiving shelf, which is
    where a receipt puts goods. Every document in this file is outbound — a
    dispatch, a transfer — and an outbound door only takes stock off the
    shelf it names, so the record the tests hand them stands on the source
    shelf instead.
    """
    item = Item(
        name='Widget A',
        organization_id=doc_org.id,
        storage_location_id=doc_source_location.id,
        quantity=Decimal('10'),
    )
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)
    return item


def _pdf_text(pdf_bytes: bytes) -> str:
    reader = pypdf.PdfReader(BytesIO(pdf_bytes))
    return '\n'.join(page.extract_text() or '' for page in reader.pages)


@pytest.mark.integration
class TestReturnDocument:
    """Tests for POST /warehouse/documents/{id}/return endpoint."""

    def _create_and_complete_out(
        self,
        client: TestClient,
        headers: dict[str, str],
        source_loc_id: uuid.UUID,
        target_loc_id: uuid.UUID,
        partner_id: uuid.UUID,
        item_id: uuid.UUID,
        qty: int = 5,
        uom_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Helper: create, confirm, and complete an OUT document."""
        line: dict[str, Any] = {'item_id': str(item_id), 'expected_quantity': qty}
        # The document form copies the unit off the product card, so a line
        # the application really creates names a unit.
        if uom_id is not None:
            line['uom_id'] = str(uom_id)
        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=headers,
            json={
                'type': 'OUT',
                'partner_id': str(partner_id),
                'source_location_id': str(source_loc_id),
                'target_location_id': str(target_loc_id),
                'lines': [line],
            },
        )
        assert resp.status_code == status.HTTP_201_CREATED
        doc = resp.json()
        doc_id = doc['id']

        confirmed = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=headers
        )
        assert confirmed.status_code == status.HTTP_200_OK, confirmed.text
        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=headers,
            json={'complete_as_planned': True},
        )
        # The number is given out at confirmation: the create response was
        # the draft's identifier, and callers name the document by number.
        return cast(dict[str, Any], {**doc, 'number': confirmed.json()['number']})

    def _create_and_complete_int(
        self,
        client: TestClient,
        headers: dict[str, str],
        source_loc_id: uuid.UUID,
        target_loc_id: uuid.UUID,
        item_id: uuid.UUID,
        qty: int = 5,
    ) -> dict[str, Any]:
        """Helper: create, confirm, and complete an INT document."""
        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=headers,
            json={
                'type': 'INT',
                'source_location_id': str(source_loc_id),
                'target_location_id': str(target_loc_id),
                'lines': [{'item_id': str(item_id), 'expected_quantity': qty}],
            },
        )
        assert resp.status_code == status.HTTP_201_CREATED
        doc = resp.json()
        doc_id = doc['id']

        confirmed = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=headers
        )
        assert confirmed.status_code == status.HTTP_200_OK, confirmed.text
        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=headers,
            json={'complete_as_planned': True},
        )
        # See _create_and_complete_out: the number arrives at confirmation.
        return cast(dict[str, Any], {**doc, 'number': confirmed.json()['number']})

    def test_return_out_creates_in(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_item: Item,
    ) -> None:
        """Return of completed OUT creates an IN document."""
        doc = self._create_and_complete_out(
            client,
            doc_auth_headers,
            doc_source_location.id,
            doc_target_location.id,
            doc_partner.id,
            doc_item.id,
        )

        return_resp = client.post(
            f'/api/v1/warehouse/documents/{doc["id"]}/return',
            headers=doc_auth_headers,
            json={
                'reason_code': 'DAMAGED',
                'lines': [
                    {
                        'original_line_number': 1,
                        'return_quantity': 3,
                        'reason': 'Customer rejected 3 units',
                    }
                ],
                'notes': 'Customer return',
            },
        )
        assert return_resp.status_code == status.HTTP_201_CREATED
        ret = return_resp.json()
        assert ret['type'] == 'IN'
        assert ret['status'] == 'DRAFT'
        assert ret['partner_id'] == str(doc_partner.id)
        assert len(ret['lines']) == 1
        assert ret['lines'][0]['expected_quantity'] == '3.000'

    def test_a_delivery_return_comes_back_to_the_shelf_it_left(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_partner: Partner,
        doc_item: Item,
    ) -> None:
        """A return of a delivery is a receipt, and a receipt's place is its
        target: the shelf the delivery took the goods from. Kept as the
        delivery's source, the place sat in a field the receipt's planning
        never reads, and the screen had nowhere true to show it."""
        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'OUT',
                'partner_id': str(doc_partner.id),
                'source_location_id': str(doc_source_location.id),
                'lines': [{'item_id': str(doc_item.id), 'expected_quantity': 4}],
            },
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        doc_id = resp.json()['id']
        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        done = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert done.status_code == status.HTTP_200_OK, done.text

        return_resp = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/return',
            headers=doc_auth_headers,
            json={
                'reason_code': 'DAMAGED',
                'lines': [{'original_line_number': 1, 'return_quantity': 1}],
            },
        )
        assert return_resp.status_code == status.HTTP_201_CREATED, return_resp.text
        ret = return_resp.json()
        assert ret['type'] == 'IN'
        assert ret['target_location_id'] == str(doc_source_location.id)
        assert ret['source_location_id'] is None

    def test_return_of_a_line_that_names_a_unit_answers_201(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_item: Item,
        doc_uom_kg: Any,
    ) -> None:
        """The return endpoint answers with the document it just wrote.

        Every line the application creates names a unit, and the response
        serializes ``lines[].uom``. Lines built inside the writing session
        never fire the eager loader for it, so the serializer's reach used
        to become a lazy load on an async session — a 500 that arrived after
        the commit, reading "Failed to create return document" over a
        return that had in fact been saved.
        """
        doc = self._create_and_complete_out(
            client,
            doc_auth_headers,
            doc_source_location.id,
            doc_target_location.id,
            doc_partner.id,
            doc_item.id,
            uom_id=doc_uom_kg.id,
        )

        return_resp = client.post(
            f'/api/v1/warehouse/documents/{doc["id"]}/return',
            headers=doc_auth_headers,
            json={
                'reason_code': 'DAMAGED',
                'lines': [
                    {
                        'original_line_number': 1,
                        'return_quantity': 3,
                    }
                ],
            },
        )

        assert return_resp.status_code == status.HTTP_201_CREATED, return_resp.text
        ret = return_resp.json()
        assert ret['type'] == 'IN'
        assert ret['lines'][0]['uom']['id'] == str(doc_uom_kg.id)

    def test_return_int_creates_reverse_int(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        """Return of completed INT creates INT with swapped source/target."""
        doc = self._create_and_complete_int(
            client,
            doc_auth_headers,
            doc_source_location.id,
            doc_target_location.id,
            doc_item.id,
        )

        return_resp = client.post(
            f'/api/v1/warehouse/documents/{doc["id"]}/return',
            headers=doc_auth_headers,
            json={
                'reason_code': 'DAMAGED',
                'lines': [{'original_line_number': 1, 'return_quantity': 2}],
            },
        )
        assert return_resp.status_code == status.HTTP_201_CREATED
        ret = return_resp.json()
        assert ret['type'] == 'INT'
        # Locations should be swapped
        assert ret['source_location_id'] == str(doc_target_location.id)
        assert ret['target_location_id'] == str(doc_source_location.id)

    def test_return_links_via_document_relation(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_item: Item,
        db_session: Session,
    ) -> None:
        """Return creates DocumentRelation with type='returns'."""
        doc = self._create_and_complete_out(
            client,
            doc_auth_headers,
            doc_source_location.id,
            doc_target_location.id,
            doc_partner.id,
            doc_item.id,
        )

        return_resp = client.post(
            f'/api/v1/warehouse/documents/{doc["id"]}/return',
            headers=doc_auth_headers,
            json={
                'reason_code': 'DAMAGED',
                'lines': [{'original_line_number': 1, 'return_quantity': 2}],
            },
        )
        ret_id = return_resp.json()['id']

        from app.modules.warehouse.models import DocumentRelation

        relation = db_session.scalars(
            select(DocumentRelation).where(
                DocumentRelation.source_document_id == doc['id'],
                DocumentRelation.target_document_id == ret_id,
            )
        ).first()
        assert relation is not None
        assert relation.relation_type == 'returns'

    def test_return_created_from_an_english_session_reads_polish(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_item: Item,
    ) -> None:
        """A return stores no sentence for another language's reader to miss.

        The server used to write one into the return's notes — first English
        for every reader, then the creator's request language, so a return
        created from an English session still read "Return for IN/…" under
        Uwagi on a Polish screen and on the printout. The reference is
        structured now: the response and the printout carry the id and
        number of the document the return reverses, in every language.
        """
        doc = self._create_and_complete_out(
            client,
            doc_auth_headers,
            doc_source_location.id,
            doc_target_location.id,
            doc_partner.id,
            doc_item.id,
        )

        return_resp = client.post(
            f'/api/v1/warehouse/documents/{doc["id"]}/return',
            headers={**doc_auth_headers, 'Accept-Language': 'en'},
            json={
                'reason_code': 'DAMAGED',
                'notes': None,
                'lines': [{'original_line_number': 1, 'return_quantity': 2}],
            },
        )
        assert return_resp.status_code == status.HTTP_201_CREATED, return_resp.text
        ret = return_resp.json()
        assert ret['notes'] is None
        assert ret['return_of_id'] == doc['id']
        assert ret['return_of_number'] == doc['number']

        read = client.get(
            f'/api/v1/warehouse/documents/{ret["id"]}',
            headers={**doc_auth_headers, 'Accept-Language': 'pl'},
        )
        assert read.status_code == status.HTTP_200_OK, read.text
        body = read.json()
        assert body['notes'] is None
        assert body['return_of_id'] == doc['id']
        assert body['return_of_number'] == doc['number']

        # The printed number names the same document, so it answers the same.
        by_number = client.get(
            f'/api/v1/warehouse/documents/lookup/{ret["number"]}',
            headers=doc_auth_headers,
        )
        assert by_number.status_code == status.HTTP_200_OK, by_number.text
        assert by_number.json()['return_of_id'] == doc['id']
        assert by_number.json()['return_of_number'] == doc['number']

        pl_headers = {**doc_auth_headers, 'Accept-Language': 'pl'}
        confirmed = client.patch(
            f'/api/v1/warehouse/documents/{ret["id"]}/confirm', headers=pl_headers
        )
        assert confirmed.status_code == status.HTTP_200_OK, confirmed.text
        pdf = client.get(
            f'/api/v1/warehouse/documents/{ret["id"]}/pdf?lang=pl', headers=pl_headers
        )
        assert pdf.status_code == status.HTTP_200_OK, pdf.text
        # pypdf may split a word across lines inside the PDF — compare
        # whitespace-normalized.
        flat = ' '.join(_pdf_text(pdf.content).split())
        assert 'Zwrot do' in flat, flat
        assert doc['number'] in flat, flat
        assert 'Return for' not in flat

    def test_return_of_draft_fails(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_item: Item,
    ) -> None:
        """Cannot return a non-completed document."""
        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'OUT',
                'partner_id': str(doc_partner.id),
                'source_location_id': str(doc_target_location.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [{'item_id': str(doc_item.id), 'expected_quantity': 5}],
            },
        )
        doc_id = resp.json()['id']

        return_resp = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/return',
            headers=doc_auth_headers,
            json={
                'reason_code': 'DAMAGED',
                'lines': [{'original_line_number': 1, 'return_quantity': 1}],
            },
        )
        assert return_resp.status_code == status.HTTP_400_BAD_REQUEST
        assert 'completed document' in return_resp.json()['detail']['message']

    def test_return_quantity_exceeds_original_fails(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_item: Item,
    ) -> None:
        """Return quantity cannot exceed original done_quantity."""
        doc = self._create_and_complete_out(
            client,
            doc_auth_headers,
            doc_source_location.id,
            doc_target_location.id,
            doc_partner.id,
            doc_item.id,
            qty=5,
        )

        return_resp = client.post(
            f'/api/v1/warehouse/documents/{doc["id"]}/return',
            headers=doc_auth_headers,
            json={
                'reason_code': 'DAMAGED',
                'lines': [{'original_line_number': 1, 'return_quantity': 99}],
            },
        )
        assert return_resp.status_code == status.HTTP_400_BAD_REQUEST
        message = return_resp.json()['detail']['message']
        assert 'more than what is left' in message
        # Stated the way the screen states a quantity: no store scale.
        assert 'A return of 99' in message
        assert '.000' not in message

    def test_return_in_document_succeeds(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_item: Item,
    ) -> None:
        """IN returns now produce an OUT document (return to supplier)."""
        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [{'item_id': str(doc_item.id), 'expected_quantity': 5}],
            },
        )
        doc_id = resp.json()['id']
        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )

        return_resp = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/return',
            headers=doc_auth_headers,
            json={
                'reason_code': 'DAMAGED',
                'lines': [{'original_line_number': 1, 'return_quantity': 1}],
            },
        )
        assert return_resp.status_code == status.HTTP_201_CREATED
        assert return_resp.json()['type'] == 'OUT'

    def test_a_receipt_return_goes_back_to_the_supplier_off_the_shelf(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        db_session: Session,
    ) -> None:
        """The whole road the detail screen now offers on a receipt.

        A receipt is written from the catalogue, so its line names a product
        and the record exists only once the goods have landed. The return is
        a delivery, and a delivery refuses a line that names no record: the
        return has to be confirmable and has to take the goods off the shelf
        they were received onto.
        """
        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 5,
                    }
                ],
            },
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        doc_id = resp.json()['id']
        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        done = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert done.status_code == status.HTTP_200_OK, done.text

        returned = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/return',
            headers=doc_auth_headers,
            json={
                'reason_code': 'DAMAGED',
                'lines': [{'original_line_number': 1, 'return_quantity': 2}],
            },
        )
        assert returned.status_code == status.HTTP_201_CREATED, returned.text
        return_id = returned.json()['id']
        confirm = client.patch(
            f'/api/v1/warehouse/documents/{return_id}/confirm', headers=doc_auth_headers
        )
        assert confirm.status_code == status.HTTP_200_OK, confirm.text
        complete = client.patch(
            f'/api/v1/warehouse/documents/{return_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert complete.status_code == status.HTTP_200_OK, complete.text

        on_shelf = db_session.scalar(
            select(func.sum(Item.quantity)).where(
                Item.template_id == doc_template.id,
                Item.storage_location_id == doc_target_location.id,
            )
        )
        assert on_shelf == Decimal('3')

    def test_return_invalid_line_number_fails(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_item: Item,
    ) -> None:
        """Return with non-existent line number fails."""
        doc = self._create_and_complete_out(
            client,
            doc_auth_headers,
            doc_source_location.id,
            doc_target_location.id,
            doc_partner.id,
            doc_item.id,
        )

        return_resp = client.post(
            f'/api/v1/warehouse/documents/{doc["id"]}/return',
            headers=doc_auth_headers,
            json={
                'reason_code': 'DAMAGED',
                'lines': [{'original_line_number': 999, 'return_quantity': 1}],
            },
        )
        assert return_resp.status_code == status.HTTP_400_BAD_REQUEST
        assert 'does not exist' in return_resp.json()['detail']['message']


@pytest.mark.integration
class TestReturnReasonIsCountable:
    """A return says why, from a closed list, so returns can be counted."""

    def _completed_in(
        self,
        client: TestClient,
        headers: dict[str, str],
        target_loc_id: uuid.UUID,
        partner_id: uuid.UUID,
        item_id: uuid.UUID,
    ) -> str:
        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=headers,
            json={
                'type': 'IN',
                'partner_id': str(partner_id),
                'target_location_id': str(target_loc_id),
                'lines': [{'item_id': str(item_id), 'expected_quantity': 5}],
            },
        )
        assert resp.status_code == status.HTTP_201_CREATED
        doc_id = str(resp.json()['id'])
        client.patch(f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=headers)
        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=headers,
            json={'complete_as_planned': True},
        )
        return doc_id

    def test_return_records_its_reason_code(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_item: Item,
    ) -> None:
        doc_id = self._completed_in(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_partner.id,
            doc_item.id,
        )

        response = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/return',
            headers=doc_auth_headers,
            json={
                'reason_code': 'QUALITY',
                'lines': [{'original_line_number': 1, 'return_quantity': 1}],
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()['reason_code'] == 'QUALITY'

    def test_other_without_a_note_is_rejected(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_item: Item,
    ) -> None:
        doc_id = self._completed_in(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_partner.id,
            doc_item.id,
        )

        response = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/return',
            headers=doc_auth_headers,
            json={
                'reason_code': 'OTHER',
                'lines': [{'original_line_number': 1, 'return_quantity': 1}],
            },
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
