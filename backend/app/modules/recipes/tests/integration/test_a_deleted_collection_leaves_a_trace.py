"""Deleting a recipe collection is an irreversible act the journal keeps.

A collection is a working note, so what happens inside one — renaming it,
filing a recipe under it — writes nothing. Deleting it is different: the
row goes, its sub-collections and the filing of every recipe in them go
with it, and no other table holds a copy of the name. These tests pin one
entry naming what went, the sub-collections that went with it, and silence
for everything that is not a deletion.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.contracts import AuditAction
from app.models.audit_log import AuditLog
from app.models.user import User

COLLECTIONS_URL = '/api/v1/recipes/collections'


def _journal(db_session: Session, org_id: UUID | None) -> list[AuditLog]:
    """This organization's entries about recipe collections, oldest first."""
    return list(
        db_session.scalars(
            select(AuditLog)
            .where(
                AuditLog.organization_id == org_id,
                AuditLog.target_type == 'recipe_collection',
            )
            .order_by(AuditLog.created_at)
        ).all()
    )


def _create(
    client: TestClient, headers: dict[str, str], name: str, parent_id: str | None = None
) -> str:
    body = {'name': name, 'parent_id': parent_id}
    response = client.post(COLLECTIONS_URL, json=body, headers=headers)
    assert response.status_code == 201
    collection_id: str = response.json()['id']
    return collection_id


@pytest.mark.integration
class TestADeletedCollectionLeavesATrace:
    def test_the_entry_names_the_collection_and_who_deleted_it(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
    ) -> None:
        collection_id = _create(client, auth_headers, 'Weekend Dinners')

        deleted = client.delete(
            f'{COLLECTIONS_URL}/{collection_id}', headers=auth_headers
        )
        assert deleted.status_code == 204

        db_session.expire_all()
        entries = _journal(db_session, test_user.organization_id)
        assert len(entries) == 1
        entry = entries[0]
        assert entry.target_id == UUID(collection_id)
        assert entry.action == AuditAction.HARD_DELETE
        assert entry.user_id == test_user.id
        assert entry.snapshot == {'name': 'Weekend Dinners'}
        assert not (entry.meta_data or {}).get('removed_collections')

    def test_the_entry_names_the_sub_collections_that_went_with_it(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
    ) -> None:
        parent_id = _create(client, auth_headers, 'Dinners')
        child_id = _create(client, auth_headers, 'Pasta', parent_id)
        grandchild_id = _create(client, auth_headers, 'Carbonara', child_id)
        _create(client, auth_headers, 'Soups')  # unrelated, must survive

        deleted = client.delete(f'{COLLECTIONS_URL}/{parent_id}', headers=auth_headers)
        assert deleted.status_code == 204

        db_session.expire_all()
        entries = _journal(db_session, test_user.organization_id)
        assert len(entries) == 1
        assert entries[0].target_id == UUID(parent_id)
        assert entries[0].meta_data is not None
        removed = entries[0].meta_data['removed_collections']
        assert {(c['id'], c['name']) for c in removed} == {
            (child_id, 'Pasta'),
            (grandchild_id, 'Carbonara'),
        }

    def test_a_missing_collection_writes_nothing(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
    ) -> None:
        deleted = client.delete(
            f'{COLLECTIONS_URL}/00000000-0000-0000-0000-000000000000',
            headers=auth_headers,
        )
        assert deleted.status_code == 404

        db_session.expire_all()
        assert _journal(db_session, test_user.organization_id) == []

    def test_creating_renaming_and_filing_write_nothing(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
    ) -> None:
        collection_id = _create(client, auth_headers, 'Weekend Dinners')
        renamed = client.put(
            f'{COLLECTIONS_URL}/{collection_id}',
            json={'name': 'Sunday Dinners'},
            headers=auth_headers,
        )
        assert renamed.status_code == 200

        db_session.expire_all()
        assert _journal(db_session, test_user.organization_id) == []
