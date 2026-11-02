"""Integration tests for POST /equipment/items/bulk-purge row-level errors.

 follow-up: a ``before_purge`` interceptor veto (posted document lines,
stock-take evidence) must be reported per row like every other bulk
rejection — the rest of the batch still purges. Regression guard: the loop
caught ``PermissionError`` and ``ValueError`` but not ``InterceptorError``,
so one blocked row failed the whole request.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.context import ModuleContext
from app.core.interceptors import (
    InterceptorError,
    ItemInterceptor,
    interceptor_pipeline,
)
from app.core.testing import ModuleTestHelper
from app.models.item import Item
from app.models.organization import Organization
from app.models.storage_location import StorageLocation


def _archived_item(
    db: Session, org: Organization, location: StorageLocation, name: str
) -> Item:
    item = Item(
        name=name,
        organization_id=org.id,
        storage_location_id=location.id,
        quantity=1,
        is_deleted=True,
        deleted_at=datetime.now(UTC),
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


class _SelectivePurgeBlocker(ItemInterceptor):
    """Test interceptor: vetoes the purge of one specific item."""

    priority = 1

    def __init__(self, blocked_id: uuid.UUID, evidence_id: uuid.UUID) -> None:
        self._blocked_id = blocked_id
        self._evidence_id = evidence_id

    async def before_create(
        self, data: dict[str, Any], context: ModuleContext
    ) -> dict[str, Any]:
        return data

    async def before_update(
        self, item_id: uuid.UUID, changes: dict[str, Any], context: ModuleContext
    ) -> dict[str, Any]:
        return changes

    async def before_purge(self, item_id: uuid.UUID, context: ModuleContext) -> None:
        if item_id == self._blocked_id:
            raise InterceptorError(
                'Item is linked to posted documents',
                error_code='PURGE_BLOCKED_DOCUMENTS',
                details={
                    'blocks': [
                        {
                            'type': 'document_lines',
                            'count': 1,
                            'ids': [str(self._evidence_id)],
                        }
                    ]
                },
            )


@pytest.mark.integration
class TestBulkPurgeRowErrors:
    def test_blocked_row_is_reported_and_rest_of_batch_purges(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        db_session: Session,
        eq_org: Organization,
        eq_storage_location: StorageLocation,
    ) -> None:
        admin = h.create_user(
            eq_org, email=f'adm_{uuid.uuid4().hex[:6]}@test.com', role='admin'
        )
        blocked = _archived_item(
            db_session, eq_org, eq_storage_location, 'Blocked asset'
        )
        purgeable = _archived_item(
            db_session, eq_org, eq_storage_location, 'Purgeable asset'
        )
        # Capture ids now — the purge below deletes rows, and accessing an
        # expired ORM attribute afterwards would trigger a refresh on a
        # row that no longer exists.
        blocked_id = blocked.id
        purgeable_id = purgeable.id

        blocker_evidence_id = str(uuid.uuid4())
        blocker = _SelectivePurgeBlocker(blocked_id, uuid.UUID(blocker_evidence_id))
        interceptor_pipeline.register_item_interceptor(blocker)
        try:
            resp = client.post(
                '/api/v1/equipment/items/bulk-purge',
                headers=h.get_auth_headers(admin),
                json=[str(blocked_id), str(purgeable_id)],
            )
        finally:
            interceptor_pipeline.unregister_item_interceptor(blocker)

        assert resp.status_code == 200
        body = resp.json()
        assert body['purged'] == 1
        assert [e['item_id'] for e in body['errors']] == [str(blocked_id)]
        # The veto's own message has to reach the caller: an empty or generic
        # string would satisfy the row count above while telling the operator
        # nothing about why that asset survived the batch.
        rejected = body['errors'][0]
        assert rejected['error'] == 'Item is linked to posted documents'
        # Same code and blocker list the single-item purge returns in its 409,
        # so a client can tell blockers apart without parsing the message.
        assert rejected['code'] == 'PURGE_BLOCKED_DOCUMENTS'
        assert rejected['blocks'] == [
            {'type': 'document_lines', 'count': 1, 'ids': [blocker_evidence_id]}
        ]

        assert db_session.scalar(select(Item.id).where(Item.id == purgeable_id)) is None
        assert (
            db_session.scalar(select(Item.id).where(Item.id == blocked_id)) is not None
        )
