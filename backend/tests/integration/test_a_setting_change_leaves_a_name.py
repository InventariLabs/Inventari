"""A module's settings leave a name in the journal when they move.

Turning the approvals module on is journaled; letting its admin approve
their own request was not — and that setting decides whether a second
person ever sees the decision at all. The entry belongs to the module the
setting belongs to, names the keys that moved with the actor beside them,
and stays silent when the write changes nothing.
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.organization import Organization
from app.models.user import User
from app.services.auth_service import get_password_hash
from app.services.token_service import create_access_token

pytestmark = pytest.mark.integration


def _auth(user: User) -> dict:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


@pytest.fixture
def admin(db_session: Session, test_household: Organization) -> User:
    user = User(
        email=f'settings_admin_{uuid.uuid4().hex[:8]}@test.com',
        hashed_password=get_password_hash('pass'),
        organization_id=test_household.id,
        role='admin',
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    return user


def _approvals_entries(db_session: Session, org_id: uuid.UUID) -> list[AuditLog]:
    rows = (
        db_session.query(AuditLog)
        .filter(
            AuditLog.organization_id == org_id,
            AuditLog.target_type == 'module',
        )
        .all()
    )
    return [row for row in rows if (row.snapshot or {}).get('name') == 'approvals']


class TestModuleSettingsLeaveAJournalEntry:
    def test_enabling_self_approval_is_journaled(
        self, db_session: Session, client: TestClient, admin: User
    ) -> None:
        resp = client.put(
            '/api/v1/modules/approvals/settings',
            json={'allow_admin_self_approve': True},
            headers=_auth(admin),
        )
        assert resp.status_code == 200, resp.text

        entries = _approvals_entries(db_session, admin.organization_id)
        assert len(entries) == 1, f'expected one entry, got {len(entries)}'
        entry = entries[0]
        assert entry.action == 'UPDATE'
        assert entry.user_id == admin.id
        assert entry.snapshot['before'] == {'allow_admin_self_approve': False}
        assert entry.snapshot['after'] == {'allow_admin_self_approve': True}

    def test_a_write_that_changes_nothing_is_not_journaled(
        self, db_session: Session, client: TestClient, admin: User
    ) -> None:
        resp = client.put(
            '/api/v1/modules/approvals/settings',
            json={'allow_admin_self_approve': False},
            headers=_auth(admin),
        )
        assert resp.status_code == 200, resp.text

        # The default is False: writing False over an unset setting changed
        # nothing, and the journal records changes, not keystrokes.
        assert _approvals_entries(db_session, admin.organization_id) == []
