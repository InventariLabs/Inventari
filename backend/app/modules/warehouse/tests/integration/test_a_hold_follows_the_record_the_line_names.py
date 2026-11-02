"""A confirmed document holds the stock its line names, where its line names it.

Confirmation blocks the stock a document is about to take, and completion
takes it. The two used to read the line differently: the hold went by the
document's source shelf and the line's card alone, the draw by the record the
line points at. A write-off with no source shelf held the oldest stock of the
product anywhere in the organization while the record named on the line was
the one that left; a line that named a record but no card held nothing at
all, and still took the stock at completion.

These tests pin the hold to the draw: same shelf, same card, and a refusal
that says where it looked when the shelf cannot cover the line.
"""

from __future__ import annotations

from typing import cast

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.modules.warehouse.tests.integration._records import (
    shelf_quant as _shelf_quant,
)
from app.modules.warehouse.tests.integration._records import (
    sow as _sow,
)


def _draft(client: TestClient, headers: dict[str, str], body: dict[str, object]) -> str:
    created = client.post('/api/v1/warehouse/documents', headers=headers, json=body)
    assert created.status_code == status.HTTP_201_CREATED, created.text
    return cast(str, created.json()['id'])


@pytest.mark.integration
class TestAHoldFollowsTheRecordTheLineNames:
    def test_a_write_off_holds_the_shelf_of_its_record(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_org: Organization,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        """No source shelf on the document: the record's shelf is the source.

        The older stock stands on the other shelf. Holding by the product
        alone picked it — first in, first out across the organization — while
        completion took the record the line named, so the good stock was
        blocked and the one being written off stayed free to sell.
        """
        _sow(
            db_session,
            async_engine_fixture,
            doc_org,
            doc_template,
            doc_target_location.id,
            '10',
            backdate_days=30,
        )
        record = _sow(
            db_session,
            async_engine_fixture,
            doc_org,
            doc_template,
            doc_source_location.id,
            '12',
        )

        doc_id = _draft(
            client,
            doc_auth_headers,
            {
                'type': 'SCRAP',
                'reason_code': 'DAMAGED',
                'lines': [
                    {
                        'item_id': str(record.id),
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 2,
                    }
                ],
            },
        )
        confirm = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        assert confirm.status_code == status.HTTP_200_OK, confirm.text

        db_session.expire_all()
        written_off = _shelf_quant(
            db_session, doc_org.id, doc_template.id, doc_source_location.id
        )
        spared = _shelf_quant(
            db_session, doc_org.id, doc_template.id, doc_target_location.id
        )
        assert float(written_off.reserved_quantity) == 2.0, (
            'the shelf the record stands on carries the hold'
        )
        assert float(spared.reserved_quantity) == 0.0, (
            'the older stock on the other shelf stays free'
        )

    def test_a_line_naming_only_a_record_still_holds_its_card_stock(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        doc_org: Organization,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        """The record carries the card, so a line that omits it holds all the same.

        Completion reads the card off the record when the line has none. The
        hold skipped such a line, and the document confirmed with nothing
        held while the stock could still be taken by anyone in between.
        """
        record = _sow(
            db_session,
            async_engine_fixture,
            doc_org,
            doc_template,
            doc_source_location.id,
            '10',
        )

        doc_id = _draft(
            client,
            doc_auth_headers,
            {
                'type': 'OUT',
                'partner_id': str(doc_partner.id),
                'source_location_id': str(doc_source_location.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [{'item_id': str(record.id), 'expected_quantity': 4}],
            },
        )
        confirm = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        assert confirm.status_code == status.HTTP_200_OK, confirm.text

        db_session.expire_all()
        shelf = _shelf_quant(
            db_session, doc_org.id, doc_template.id, doc_source_location.id
        )
        assert float(shelf.reserved_quantity) == 4.0
        assert float(shelf.available_quantity) == 6.0

    def test_a_short_shelf_names_where_the_record_stands(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        doc_org: Organization,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        """Both shelves named, stock only on the record's: the refusal says so.

        The document takes from its source shelf; the record the reader
        picked stands elsewhere and the source has nothing. The bare
        "could not be reserved" left them guessing which shelf had been
        searched and what to change. The document stays a draft.
        """
        record = _sow(
            db_session,
            async_engine_fixture,
            doc_org,
            doc_template,
            doc_target_location.id,
            '5',
        )

        doc_id = _draft(
            client,
            doc_auth_headers,
            {
                'type': 'OUT',
                'partner_id': str(doc_partner.id),
                'source_location_id': str(doc_source_location.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'item_id': str(record.id),
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 2,
                    }
                ],
            },
        )
        confirm = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        assert confirm.status_code == status.HTTP_400_BAD_REQUEST, confirm.text
        assert doc_source_location.name in confirm.text, 'names the shelf it searched'
        assert doc_target_location.name in confirm.text, 'names the record shelf'

        shown = client.get(
            f'/api/v1/warehouse/documents/{doc_id}', headers=doc_auth_headers
        )
        assert shown.json()['status'] == 'DRAFT'
