"""the warehouse module vetoes purges of audit-relevant items.

An archived item that is linked to posted documents (CONFIRMED/COMPLETED)
or to movements inside closed inventory periods must not be permanently
deleted — the 409 carries a structured blocker list (type + count + ids).
Draft documents do not block: nothing has been posted yet.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.item import Item
from app.models.organization import Organization
from app.models.user import User
from app.modules.warehouse.models import (
    Document,
    DocumentLine,
    DocumentStatus,
    InventoryPeriod,
)

pytestmark = pytest.mark.integration


def _document_with_item_line(
    h: ModuleTestHelper,
    db_session: Session,
    doc_org: Organization,
    doc_user: User,
    doc_item: Item,
    *,
    status: str,
    doc_date: date | None = None,
) -> Document:
    doc = Document(
        organization_id=doc_org.id,
        type='IN',
        number=f'IN/PURGE/{uuid4().hex[:8]}',
        status=status,
        target_location_id=doc_item.storage_location_id,
        created_by=doc_user.id,
        scheduled_date=doc_date,
    )
    line = DocumentLine(
        item_id=doc_item.id,
        name=doc_item.name,
        quantity=Decimal('1'),
        expected_quantity=Decimal('1'),
        done_quantity=Decimal('0'),
        line_number=1,
    )
    doc.lines.append(line)
    db_session.add(doc)
    db_session.commit()
    db_session.refresh(doc)
    return doc


def _archive_item(
    client: TestClient, doc_auth_headers: dict[str, str], doc_item: Item
) -> None:
    resp = client.delete(f'/api/v1/items/{doc_item.id}', headers=doc_auth_headers)
    assert resp.status_code in (200, 204)


class TestDocumentsPurgeBlocker:
    def test_posted_document_line_blocks_purge_with_structured_blockers(
        self,
        client: TestClient,
        db_session: Session,
        h: ModuleTestHelper,
        doc_org: Organization,
        doc_user: User,
        doc_item: Item,
        doc_auth_headers: dict[str, str],
    ) -> None:
        """A CONFIRMED document referencing the item → purge 409 + blockers."""
        doc = _document_with_item_line(
            h,
            db_session,
            doc_org,
            doc_user,
            doc_item,
            status=DocumentStatus.CONFIRMED.value,
        )

        _archive_item(client, doc_auth_headers, doc_item)

        resp = client.delete(
            f'/api/v1/items/{doc_item.id}/purge', headers=doc_auth_headers
        )
        assert resp.status_code == status.HTTP_409_CONFLICT
        body = resp.json()['detail']
        blocks = body['blocks']
        posted = [b for b in blocks if b['type'] == 'posted_document_lines']
        assert posted, f'expected posted_document_lines blocker, got {blocks}'
        assert posted[0]['count'] >= 1
        assert str(doc.id) in posted[0]['ids']

    def test_closed_period_movement_blocks_purge(
        self,
        client: TestClient,
        db_session: Session,
        h: ModuleTestHelper,
        doc_org: Organization,
        doc_user: User,
        doc_item: Item,
        doc_auth_headers: dict[str, str],
    ) -> None:
        """A posted document dated inside a closed period → specific blocker."""
        doc_date = date(2026, 6, 15)
        doc = _document_with_item_line(
            h,
            db_session,
            doc_org,
            doc_user,
            doc_item,
            status=DocumentStatus.COMPLETED.value,
            doc_date=doc_date,
        )
        db_session.add(
            InventoryPeriod(
                organization_id=doc_org.id,
                year=doc_date.year,
                month=doc_date.month,
                closed_at=datetime.now(UTC),
            )
        )
        db_session.commit()

        _archive_item(client, doc_auth_headers, doc_item)

        resp = client.delete(
            f'/api/v1/items/{doc_item.id}/purge', headers=doc_auth_headers
        )
        assert resp.status_code == status.HTTP_409_CONFLICT
        blocks = resp.json()['detail']['blocks']
        closed = [b for b in blocks if b['type'] == 'closed_period_movements']
        assert closed, f'expected closed_period_movements blocker, got {blocks}'
        assert str(doc.id) in closed[0]['ids']

    def test_draft_document_line_does_not_block_purge(
        self,
        client: TestClient,
        db_session: Session,
        h: ModuleTestHelper,
        doc_org: Organization,
        doc_user: User,
        doc_item: Item,
        doc_auth_headers: dict[str, str],
    ) -> None:
        """Nothing posted yet — a DRAFT line must not veto the purge."""
        _document_with_item_line(
            h,
            db_session,
            doc_org,
            doc_user,
            doc_item,
            status=DocumentStatus.DRAFT.value,
        )

        _archive_item(client, doc_auth_headers, doc_item)

        resp = client.delete(
            f'/api/v1/items/{doc_item.id}/purge', headers=doc_auth_headers
        )
        assert resp.status_code in (200, 204)
