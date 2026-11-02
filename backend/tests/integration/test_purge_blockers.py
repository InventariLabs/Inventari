"""Integration tests for: purge blockers and the history trail.

``purge_item`` must:

- run the ``before_purge`` interceptor hook before deleting; an interceptor
  raising ``InterceptorError(details={'blocks': [...]})`` surfaces as HTTP 409
  with the structured blocker list (type + count + ids), not a bare "no";
- capture the item's full ``ItemHistory`` into the PURGE ``audit_log`` entry
  so the FK CASCADE on ``item_history`` does not destroy the evidence.
"""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.interceptors import (
    InterceptorError,
    ItemInterceptor,
    interceptor_pipeline,
)
from app.models.audit_log import AuditLog

pytestmark = pytest.mark.integration


class _PostedDocumentsBlocker(ItemInterceptor):
    """Test interceptor: vetoes purge with a structured blocker list."""

    priority = 1

    async def before_create(self, data, context):
        return data

    async def before_update(self, item_id, changes, context):
        return changes

    async def before_purge(self, item_id, context) -> None:
        raise InterceptorError(
            'Item is linked to posted documents',
            error_code='PURGE_BLOCKED_DOCUMENTS',
            details={
                'blocks': [
                    {
                        'type': 'document_lines',
                        'count': 2,
                        'ids': [str(uuid4()), str(uuid4())],
                    }
                ]
            },
        )


class TestPurgeInterceptorBlockers:
    def test_purge_blocked_by_interceptor_returns_409_with_blockers(
        self,
        client: TestClient,
        db_session: Session,
        auth_headers,
        test_item,
    ) -> None:
        """A before_purge interceptor veto maps to 409 + structured blockers."""
        blocker = _PostedDocumentsBlocker()
        interceptor_pipeline.register_item_interceptor(blocker)
        try:
            # Archive first — the blocker must not affect the soft delete.
            resp = client.delete(f'/api/v1/items/{test_item.id}', headers=auth_headers)
            assert resp.status_code in (200, 204)

            resp = client.delete(
                f'/api/v1/items/{test_item.id}/purge', headers=auth_headers
            )
            assert resp.status_code == 409
            body = resp.json()['detail']
            assert body['code'] == 'PURGE_BLOCKED_DOCUMENTS'
            blocks = body['blocks']
            assert len(blocks) == 1
            assert blocks[0]['type'] == 'document_lines'
            assert blocks[0]['count'] == 2
            assert len(blocks[0]['ids']) == 2
        finally:
            interceptor_pipeline.unregister_item_interceptor(blocker)

    def test_purge_not_blocked_without_interceptor(
        self, client: TestClient, auth_headers, test_item
    ) -> None:
        """Sanity: with no blocker registered the purge still succeeds."""
        resp = client.delete(f'/api/v1/items/{test_item.id}', headers=auth_headers)
        assert resp.status_code in (200, 204)

        resp = client.delete(
            f'/api/v1/items/{test_item.id}/purge', headers=auth_headers
        )
        assert resp.status_code in (200, 204)


class TestPurgeHistoryTrail:
    def test_purge_captures_item_history_in_audit_entry(
        self,
        client: TestClient,
        db_session: Session,
        auth_headers,
        test_item,
    ) -> None:
        """The PURGE audit entry contains the item history that CASCADE wipes."""
        item_id = test_item.id

        # Archiving writes an ItemHistory row (action DELETED).
        resp = client.delete(f'/api/v1/items/{item_id}', headers=auth_headers)
        assert resp.status_code in (200, 204)

        resp = client.delete(f'/api/v1/items/{item_id}/purge', headers=auth_headers)
        assert resp.status_code in (200, 204)

        entry = db_session.scalars(
            select(AuditLog).where(
                AuditLog.target_type == 'item',
                AuditLog.target_id == item_id,
                AuditLog.action == 'PURGE',
            )
        ).one()
        assert entry.meta_data is not None
        history = entry.meta_data['item_history']
        assert isinstance(history, list)
        assert any(h['action'] == 'DELETED' for h in history)
