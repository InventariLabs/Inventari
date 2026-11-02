"""A module's own configuration endpoints leave a name in the journal too.

The shared module-settings path journals its writes; a module's OWN
configuration routes sat beside it and wrote nothing — the purchase
order's approval switch, the document profile's numbering, a type config.
The Implementation Notes named this as the other half of the criterion
before any code was written: closing only the shared path would close one
of two doors.
"""

import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.settings_diff import MASKED_VALUE
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
        email=f'config_admin_{uuid.uuid4().hex[:8]}@test.com',
        hashed_password=get_password_hash('pass'),
        organization_id=test_household.id,
        role='admin',
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def modules_on(db_session: Session, test_household: Organization) -> None:
    test_household.enabled_modules = ['warehouse', 'purchase_orders']
    db_session.commit()


def _config_entries(
    db_session: Session, org_id: uuid.UUID, name: str
) -> list[AuditLog]:
    rows = (
        db_session.query(AuditLog)
        .filter(
            AuditLog.organization_id == org_id,
            AuditLog.target_type == 'module',
        )
        .all()
    )
    return [row for row in rows if (row.snapshot or {}).get('name') == name]


class TestPurchaseOrderSettingsLeaveAJournalEntry:
    def test_the_approval_switch_is_journaled(
        self, db_session: Session, client: TestClient, admin: User, modules_on
    ) -> None:
        resp = client.put(
            '/api/v1/purchase-orders/settings',
            json={'approval_required': True},
            headers=_auth(admin),
        )
        assert resp.status_code == 200, resp.text

        entries = _config_entries(db_session, admin.organization_id, 'purchase_orders')
        assert len(entries) == 1, f'expected one entry, got {len(entries)}'
        entry = entries[0]
        assert entry.user_id == admin.id
        assert entry.snapshot['subject'] == 'settings'
        assert entry.snapshot['after']['approval_required'] is True

    def test_a_write_that_changes_nothing_is_not_journaled(
        self, db_session: Session, client: TestClient, admin: User, modules_on
    ) -> None:
        # The switch defaults to False: writing False over an unset setting
        # changed nothing, and the journal records changes, not keystrokes.
        resp = client.put(
            '/api/v1/purchase-orders/settings',
            json={'approval_required': False},
            headers=_auth(admin),
        )
        assert resp.status_code == 200, resp.text

        assert (
            _config_entries(db_session, admin.organization_id, 'purchase_orders') == []
        )


class TestDocumentProfileLeavesAJournalEntry:
    def test_the_numbering_padding_is_journaled(
        self, db_session: Session, client: TestClient, admin: User, modules_on
    ) -> None:
        resp = client.put(
            '/api/v1/warehouse/profile',
            json={'number_padding': 6},
            headers=_auth(admin),
        )
        assert resp.status_code == 200, resp.text

        entries = _config_entries(db_session, admin.organization_id, 'warehouse')
        assert len(entries) == 1, f'expected one entry, got {len(entries)}'
        entry = entries[0]
        assert entry.user_id == admin.id
        assert entry.snapshot['subject'] == 'profile'
        # The model's default padding, read live: the journal's before
        # side says what the setting effectively was.
        assert entry.snapshot['before'] == {'number_padding': 3}
        assert entry.snapshot['after'] == {'number_padding': 6}

    def test_applying_a_preset_is_journaled(
        self, db_session: Session, client: TestClient, admin: User, modules_on
    ) -> None:
        # "Simple" spells the defaults a fresh profile already carries —
        # applying it changed nothing and journals nothing. A preset that
        # actually moves fields names itself in the journal.
        resp = client.post(
            '/api/v1/warehouse/profile/apply-preset/PL Magazyn',
            headers=_auth(admin),
        )
        assert resp.status_code == 200, resp.text

        entries = _config_entries(db_session, admin.organization_id, 'warehouse')
        subjects = {entry.snapshot['subject'] for entry in entries}
        assert 'profile-preset:PL Magazyn' in subjects


class TestAModuleConfigSecretNeverReachesTheJournal:
    """The journal is readable by roles that do not decide the configuration.

    The shared module-settings path masks what the schema marks secret; a
    module's own routes called the same helper without telling it anything,
    so a configuration column carrying a stored secret — an integration key,
    a printer token, a module's SMTP password — would have been written to
    the journal in the clear. Nothing carries one today, which is exactly
    why the gate over the shared path stayed green: it had nothing to see.
    """

    def test_a_stored_ciphertext_is_not_in_the_entry(
        self, db_session: Session, client: TestClient, admin: User, modules_on
    ) -> None:
        secret = 'enc:mod1:ZZNOTINTHEJOURNAL0123456789abcdefgh=='

        resp = client.put(
            '/api/v1/warehouse/profile',
            json={'numbering_format': secret},
            headers=_auth(admin),
        )
        assert resp.status_code == 200, resp.text

        entries = _config_entries(db_session, admin.organization_id, 'warehouse')
        assert len(entries) == 1, f'expected one entry, got {len(entries)}'
        snapshot = entries[0].snapshot

        # Byte-wise, not by field: the value must be nowhere in the entry.
        assert secret not in json.dumps(snapshot)
        assert 'ZZNOTINTHEJOURNAL' not in json.dumps(snapshot)
        # The entry still says which key moved — hiding the value is not
        # the same as hiding the change.
        assert snapshot['after']['numbering_format'] == MASKED_VALUE
