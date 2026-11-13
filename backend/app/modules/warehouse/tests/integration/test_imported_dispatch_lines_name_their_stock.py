"""An imported dispatch line names the stock it will take, so the dispatch confirms.

A dispatch, an issue, a transfer and a scrap take goods off a named shelf,
and confirmation refuses a line that names only a product. Line import found
the product and stopped there, so every one of these documents built from a
sheet was refused at confirmation — the import served receipts only, while a
small warehouse takes its orders by e-mail and spreadsheet.

The record is chosen the way the draw will take: from the document's source
shelf, in the product's removal strategy's order. A line whose product has
nothing free there is named back to the reader instead of passing in silence.

The same rows can be read before a document exists, so the create form can
take an import as it takes typed lines: nothing is written until it is saved.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, cast
from uuid import UUID

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.modules.warehouse.models import DocumentLine


def _receive(
    client: TestClient,
    headers: dict[str, str],
    *,
    partner_id: UUID,
    target_location_id: UUID,
    template_id: UUID,
    quantity: int,
    batch_number: str,
    expiry_date: str,
) -> None:
    resp = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'IN',
            'partner_id': str(partner_id),
            'target_location_id': str(target_location_id),
            'lines': [
                {
                    'product_template_id': str(template_id),
                    'expected_quantity': quantity,
                    'batch_number': batch_number,
                    'expiry_date': expiry_date,
                }
            ],
        },
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    doc_id = resp.json()['id']
    confirm = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=headers
    )
    assert confirm.status_code == status.HTTP_200_OK, confirm.text
    complete = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/complete',
        headers=headers,
        json={'complete_as_planned': True},
    )
    assert complete.status_code == status.HTTP_200_OK, complete.text


def _fefo_product_on_two_records(
    client: TestClient,
    db_session: Session,
    headers: dict[str, str],
    h: ModuleTestHelper,
    org: Organization,
    partner: Partner,
    shelf: StorageLocation,
) -> tuple[ProductTemplate, Item]:
    """A FEFO product whose earliest best-before arrived last.

    FIFO would name the first record received; FEFO names the second, so the
    record the import picks says which order it followed. FEFO reads the
    batch's date, so each delivery is a batch.
    """
    template = h.create_template(org, name='Jogurt naturalny 400 g', sku='JOG-400')
    template.removal_strategy = 'FEFO'
    db_session.commit()
    for quantity, batch, expiry in (
        (10, 'L-B', (date.today() + timedelta(days=700)).isoformat()),
        (6, 'L-A', (date.today() + timedelta(days=400)).isoformat()),
    ):
        _receive(
            client,
            headers,
            partner_id=partner.id,
            target_location_id=shelf.id,
            template_id=template.id,
            quantity=quantity,
            batch_number=batch,
            expiry_date=expiry,
        )
    db_session.expire_all()
    earliest = db_session.scalars(
        select(Item).where(
            Item.template_id == template.id,
            Item.storage_location_id == shelf.id,
            Item.quantity == 6,
        )
    ).one()
    return template, earliest


def _lines_naming(db_session: Session, item_id: UUID) -> int:
    return len(
        db_session.scalars(
            select(DocumentLine.id).where(DocumentLine.item_id == item_id)
        ).all()
    )


def _draft_dispatch(
    client: TestClient,
    headers: dict[str, str],
    *,
    partner_id: UUID,
    source_location_id: UUID,
    item_id: UUID,
) -> str:
    resp = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'OUT',
            'partner_id': str(partner_id),
            'source_location_id': str(source_location_id),
            'lines': [{'item_id': str(item_id), 'expected_quantity': 1}],
        },
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    return cast(str, resp.json()['id'])


@pytest.mark.integration
class TestImportedDispatchLinesNameTheirStock:
    def test_an_imported_dispatch_confirms(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_partner: Partner,
        doc_source_location: StorageLocation,
        h: ModuleTestHelper,
    ) -> None:
        template, earliest = _fefo_product_on_two_records(
            client,
            db_session,
            doc_auth_headers,
            h,
            doc_org,
            doc_partner,
            doc_source_location,
        )
        doc_id = _draft_dispatch(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            source_location_id=doc_source_location.id,
            item_id=earliest.id,
        )

        resp = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/import-paste',
            json={
                'text': 'kod\tilosc\nJOG-400\t8',
                'mapping_json': {
                    'name': 'kod',
                    'sku': 'kod',
                    'quantity': 'ilosc',
                },
            },
            headers=doc_auth_headers,
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        body = resp.json()
        assert body['no_stock'] == []
        assert body['lines'][0]['item_id'] == str(earliest.id)

        db_session.expire_all()
        imported = db_session.scalars(
            select(DocumentLine).where(
                DocumentLine.document_id == UUID(doc_id),
                DocumentLine.product_template_id == template.id,
                DocumentLine.line_number == 2,
            )
        ).one()
        assert imported.item_id == earliest.id

        confirm = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        assert confirm.status_code == status.HTTP_200_OK, confirm.text

    def test_a_line_with_nothing_on_the_shelf_is_named_back(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_partner: Partner,
        doc_source_location: StorageLocation,
        h: ModuleTestHelper,
    ) -> None:
        h.create_template(doc_org, name='Kefir 1 l', sku='KEF-1')
        resp = client.post(
            '/api/v1/warehouse/import/lines/paste',
            json={
                'text': 'kod\tilosc\nKEF-1\t3',
                'mapping_json': {
                    'name': 'kod',
                    'sku': 'kod',
                    'quantity': 'ilosc',
                },
                'type': 'OUT',
                'source_location_id': str(doc_source_location.id),
            },
            headers=doc_auth_headers,
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        body = resp.json()
        assert body['matched'] == 1
        assert body['lines'][0]['item_id'] is None
        assert body['no_stock'] == [{'row': 1, 'name': 'KEF-1'}]

    def test_rows_read_before_the_document_exists_build_one_that_confirms(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_partner: Partner,
        doc_source_location: StorageLocation,
        h: ModuleTestHelper,
    ) -> None:
        """The create form imports before there is a draft to import into."""
        template, earliest = _fefo_product_on_two_records(
            client,
            db_session,
            doc_auth_headers,
            h,
            doc_org,
            doc_partner,
            doc_source_location,
        )
        lines_before = _lines_naming(db_session, earliest.id)

        resp = client.post(
            '/api/v1/warehouse/import/lines/paste',
            json={
                'text': 'kod\tilosc\nJOG-400\t8',
                'mapping_json': {
                    'name': 'kod',
                    'sku': 'kod',
                    'quantity': 'ilosc',
                },
                'type': 'OUT',
                'source_location_id': str(doc_source_location.id),
            },
            headers=doc_auth_headers,
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        line: dict[str, Any] = resp.json()['lines'][0]
        assert line['item_id'] == str(earliest.id)
        assert line['product_template_id'] == str(template.id)
        db_session.expire_all()
        assert _lines_naming(db_session, earliest.id) == lines_before, (
            'reading the rows wrote a line'
        )

        created = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'OUT',
                'partner_id': str(doc_partner.id),
                'source_location_id': str(doc_source_location.id),
                'lines': [
                    {
                        'item_id': line['item_id'],
                        'product_template_id': line['product_template_id'],
                        'name': line['name'],
                        'expected_quantity': line['quantity'],
                        'uom_id': line['uom_id'],
                    }
                ],
            },
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        confirm = client.patch(
            f'/api/v1/warehouse/documents/{created.json()["id"]}/confirm',
            headers=doc_auth_headers,
        )
        assert confirm.status_code == status.HTTP_200_OK, confirm.text

    def test_a_dispatch_without_its_shelf_is_refused_before_reading(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
    ) -> None:
        """The shelf decides every record; without it there is nothing to name."""
        resp = client.post(
            '/api/v1/warehouse/import/lines/paste',
            json={
                'text': 'kod\tilosc\nJOG-400\t8',
                'mapping_json': {'name': 'kod', 'quantity': 'ilosc'},
                'type': 'OUT',
            },
            headers={**doc_auth_headers, 'Accept-Language': 'pl'},
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.text
        assert 'magazyn' in resp.text.lower() or 'miejsc' in resp.text.lower()
