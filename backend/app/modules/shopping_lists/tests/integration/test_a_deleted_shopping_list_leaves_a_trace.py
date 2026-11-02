"""Deleting a shopping list is the one act here the organization journal keeps.

The screen calls itself "the immutable record of this organisation's actions",
and this module wrote nothing at all — a list could be filled and thrown away
and the journal never named it. The owner's rule is deliberately narrow: edits
and additions stay out, a deleted record goes in. The deletion here is the soft
one (the row is archived, not dropped), so the entry says `SOFT_DELETE` and
carries the name beside the id.
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

LIST_URL = '/api/v1/shopping-lists'


def _journal(db_session: Session, org_id: UUID | None) -> list[AuditLog]:
    """This organization's entries about shopping lists, oldest first."""
    return list(
        db_session.scalars(
            select(AuditLog)
            .where(
                AuditLog.organization_id == org_id,
                AuditLog.target_type == 'shopping_list',
            )
            .order_by(AuditLog.created_at)
        ).all()
    )


@pytest.mark.integration
class TestADeletedShoppingListLeavesATrace:
    def test_the_entry_names_the_list_and_who_deleted_it(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
    ) -> None:
        created = client.post(
            LIST_URL, json={'name': 'Biedronka'}, headers=auth_headers
        )
        assert created.status_code == 201
        list_id = created.json()['id']

        deleted = client.delete(f'{LIST_URL}/{list_id}', headers=auth_headers)
        assert deleted.status_code == 204

        db_session.expire_all()
        entries = _journal(db_session, test_user.organization_id)
        assert len(entries) == 1
        entry = entries[0]
        assert entry.target_id == UUID(list_id)
        # The row stays behind, archived, so the act is the soft one.
        assert entry.action == AuditAction.SOFT_DELETE
        assert entry.user_id == test_user.id
        # The name is the point: the list is gone from every screen, and the
        # snapshot is where it stays readable.
        assert entry.snapshot == {'name': 'Biedronka'}

    def test_filling_the_list_writes_nothing(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
    ) -> None:
        """An item added, or a list renamed, is not a journal act."""
        list_id = client.post(
            LIST_URL, json={'name': 'Biedronka'}, headers=auth_headers
        ).json()['id']

        added = client.post(
            f'{LIST_URL}/{list_id}/items',
            json={'name': 'Mleko', 'quantity': 2},
            headers=auth_headers,
        )
        assert added.status_code == 201
        renamed = client.put(
            f'{LIST_URL}/{list_id}',
            json={'name': 'Biedronka rano'},
            headers=auth_headers,
        )
        assert renamed.status_code == 200

        db_session.expire_all()
        assert _journal(db_session, test_user.organization_id) == []

    def test_deleting_an_already_archived_list_writes_nothing(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
    ) -> None:
        """The repeat deletes nothing, so it records nothing."""
        list_id = client.post(
            LIST_URL, json={'name': 'Biedronka'}, headers=auth_headers
        ).json()['id']
        assert (
            client.delete(f'{LIST_URL}/{list_id}', headers=auth_headers).status_code
            == 204
        )

        again = client.delete(f'{LIST_URL}/{list_id}', headers=auth_headers)

        assert again.status_code == 204
        db_session.expire_all()
        assert len(_journal(db_session, test_user.organization_id)) == 1
