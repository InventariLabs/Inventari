"""The start screen's feed reads the day goods were posted, and who posted them.

The list endpoint could narrow by the day a document is *for* and order by
the moment somebody typed it — neither is when the goods moved. A receipt
dated last week and completed this morning belongs to today's feed; one
typed this morning for next week does not. The feed also names the person
who posted it and, when the reader works in one warehouse, only the rows
whose shelves stand in it.
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from typing import Any, cast
from uuid import UUID

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.modules.warehouse.models import Document

from .test_the_register_reads_the_document_date import _completed_receipt


def _listed(
    client: TestClient, headers: dict[str, str], **params: Any
) -> list[dict[str, Any]]:
    resp = client.get('/api/v1/warehouse/documents', headers=headers, params=params)
    assert resp.status_code == status.HTTP_200_OK, resp.text
    return cast(list[dict[str, Any]], resp.json()['items'])


def _day_bounds(now: datetime) -> tuple[datetime, datetime]:
    start = datetime.combine(now.date(), time.min, tzinfo=UTC)
    return start, start + timedelta(days=1)


def _set_completed_at(db_session: Session, document_id: str, when: datetime) -> None:
    document = db_session.get(Document, UUID(document_id))
    assert document is not None
    document.completed_at = when
    db_session.commit()


@pytest.mark.integration
class TestTheStartScreenReadsTheDayItWasPosted:
    def test_posting_time_decides_the_day_not_the_documents_own_date(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        db_session: Session,
    ) -> None:
        """A receipt for last week, posted this morning, is in today's feed."""
        posted_today = _completed_receipt(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            location_id=doc_target_location.id,
            template_id=doc_template.id,
            scheduled_date='2026-01-05',
        )
        posted_before = _completed_receipt(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            location_id=doc_target_location.id,
            template_id=doc_template.id,
            scheduled_date=datetime.now(UTC).date().isoformat(),
        )
        _set_completed_at(
            db_session, posted_before, datetime.now(UTC) - timedelta(days=2)
        )
        start, end = _day_bounds(datetime.now(UTC))

        rows = _listed(
            client,
            doc_auth_headers,
            status='COMPLETED',
            completed_from=start.isoformat(),
            completed_to=end.isoformat(),
        )

        assert [row['id'] for row in rows] == [posted_today]

    def test_newest_posted_first(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        db_session: Session,
    ) -> None:
        earlier = _completed_receipt(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            location_id=doc_target_location.id,
            template_id=doc_template.id,
            scheduled_date='2026-01-05',
        )
        later = _completed_receipt(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            location_id=doc_target_location.id,
            template_id=doc_template.id,
            scheduled_date='2026-01-05',
        )
        _set_completed_at(db_session, earlier, datetime.now(UTC) - timedelta(hours=2))

        rows = _listed(
            client,
            doc_auth_headers,
            status='COMPLETED',
            sort_by='completed_at',
            sort_order='desc',
        )

        assert [row['id'] for row in rows][:2] == [later, earlier]

    def test_the_person_who_posted_it_is_named(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        _completed_receipt(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            location_id=doc_target_location.id,
            template_id=doc_template.id,
            scheduled_date='2026-01-05',
        )

        rows = _listed(client, doc_auth_headers, status='COMPLETED')

        assert rows[0]['completed_by_name'] == 'Documents'

    def test_one_warehouse_names_only_the_documents_on_its_shelves(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        into_target = _completed_receipt(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            location_id=doc_target_location.id,
            template_id=doc_template.id,
            scheduled_date='2026-01-05',
        )
        _completed_receipt(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            location_id=doc_source_location.id,
            template_id=doc_template.id,
            scheduled_date='2026-01-05',
        )

        rows = _listed(
            client,
            doc_auth_headers,
            status='COMPLETED',
            location_id=str(doc_target_location.id),
        )

        assert [row['id'] for row in rows] == [into_target]

    def test_a_shelf_is_named_through_the_warehouse_above_it(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        db_session: Session,
    ) -> None:
        """A document on a shelf inside the warehouse belongs to it."""
        shelf = StorageLocation(
            name='Shelf A',
            organization_id=doc_target_location.organization_id,
            parent_id=doc_target_location.id,
            usage='internal',
            created_by=doc_target_location.created_by,
        )
        db_session.add(shelf)
        db_session.commit()
        db_session.refresh(shelf)
        on_the_shelf = _completed_receipt(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            location_id=shelf.id,
            template_id=doc_template.id,
            scheduled_date='2026-01-05',
        )

        rows = _listed(
            client,
            doc_auth_headers,
            status='COMPLETED',
            location_id=str(doc_target_location.id),
        )

        assert [row['id'] for row in rows] == [on_the_shelf]
