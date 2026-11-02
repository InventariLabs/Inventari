"""Integration tests for GDPR erasure.

``anonymize_user_async`` must destroy personal data (email, full name,
password) while keeping the user row so audit-value rows (ItemHistory,
AuditLog) keep their FK target. These tests detect "personal-data
leakers": any table that still exposes the old email/name afterwards.

The second class is about the rows that were missing from that scan: an
invitation names the address it was issued for, and the journal writes
the address of a member and of an invitation as their name. The account
was the only thing erasure ever touched, so the procedure's inventory
described those rows as FK-only while they held the address in plain
text.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.core.public_api import core_api
from app.models.audit_log import AuditAction, AuditLog
from app.models.item_history import ItemAction, ItemHistory
from app.models.organization import OrganizationInvitation
from app.models.user import RegistrationRequest, User
from app.schemas.user import UserCreate
from app.services._org_membership import join_organization, resend_invitation
from app.services.auth_service import AuthService
from app.services.gdpr_service import anonymize_user_async

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
class TestAnonymizeUser:
    async def test_personal_data_destroyed_and_audit_rows_preserved(
        self,
        real_async_db_session,
        async_test_user,
        async_test_item,
    ):
        db = real_async_db_session
        user = async_test_user
        old_email = user.email
        old_password_hash = user.hashed_password

        # Rows with audit value referencing the user.
        history = ItemHistory(
            organization_id=user.organization_id,
            item_id=async_test_item.id,
            user_id=user.id,
            action=ItemAction.UPDATED.value,
            changes={'name': 'renamed'},
        )
        audit = AuditLog(
            organization_id=user.organization_id,
            user_id=user.id,
            action=AuditAction.UPDATE.value,
            target_type='item',
            target_id=async_test_item.id,
            snapshot={'name': 'x'},
        )
        # Pre-signup request carries raw personal data.
        request = RegistrationRequest(email=old_email, full_name=user.full_name)
        db.add_all([history, audit, request])
        await db.commit()

        anonymized = await anonymize_user_async(db, user.id)
        await db.commit()

        # Personal data gone from the user row.
        assert anonymized.email != old_email
        assert anonymized.email.endswith('@anonymized.invalid')
        assert anonymized.full_name == 'Deleted User'
        assert anonymized.hashed_password != old_password_hash
        assert anonymized.is_active is False

        # RegistrationRequest no longer leaks the old email/name.
        await db.refresh(request)
        assert request.email != old_email
        assert request.full_name is None
        assert request.token is None

        # Audit-value rows survive and still point at the (anonymized) user.
        await db.refresh(history)
        await db.refresh(audit)
        assert history.user_id == user.id
        assert audit.user_id == user.id

        # No personal data leakers anywhere in the DB for the old email.
        from sqlalchemy import select

        assert (await db.scalar(select(User).where(User.email == old_email))) is None
        assert (
            await db.scalar(
                select(RegistrationRequest).where(
                    RegistrationRequest.email == old_email
                )
            )
        ) is None

    async def test_anonymized_user_cannot_authenticate(
        self,
        real_async_client,
        real_async_db_session,
        async_test_user,
    ):
        from app.services.token_service import create_access_token

        token = create_access_token(data={'sub': str(async_test_user.id)})
        await anonymize_user_async(real_async_db_session, async_test_user.id)
        await real_async_db_session.commit()

        response = await real_async_client.get(
            '/api/v1/audit-log',
            headers={'Authorization': f'Bearer {token}'},
        )
        assert response.status_code == 401

    async def test_unknown_user_raises_value_error(self, real_async_db_session):
        import uuid

        with pytest.raises(ValueError, match='not found'):
            await anonymize_user_async(real_async_db_session, uuid.uuid4())


@pytest.mark.asyncio
class TestErasureOfTheRecordsThatKeepAnAddress:
    """The two places beside the account that carried the address.

    The inventory in ``docs/GDPR_MANUAL_PROCEDURE.md`` called invitation
    rows and journal snapshots FK-only; they are not. The handling the
    procedure now states is the one pinned here:

    - an invitation is an ordinary organization record, so erasure
      rewrites its ``invited_email`` like it rewrites the account — the
      rows below are produced by the member and invitation flows, not
      written by hand, because the old test's hand-made
      ``snapshot={'name': 'x'}`` could not see a leak it never made;
    - a journal entry is immutable in the database
      (``audit_log_immutable``; what the database refuses is pinned by
      ``test_audit_log_is_immutable.py``), so erasure leaves it exactly
      as the flow wrote it and the procedure says so instead of
      promising an anonymous history. These assertions hold whether or
      not the test database carries that trigger: they read the value,
      not the mechanism, so an erasure that started rewriting the
      entries fails here too.
    """

    async def test_invitation_row_is_scrubbed_and_journal_entries_stay_as_written(
        self,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        """Erasure rewrites the invitation row and leaves the journal alone.

        The first half fails without the rewrite — the row still holds the
        address. The second half is the documented outcome: it fails the
        day erasure starts touching journal entries, which is the thing
        the procedure must never do silently.
        """
        db = real_async_db_session
        host = async_test_household
        actor = async_test_user
        old_email = f'invitee_{uuid.uuid4().hex[:8]}@example.com'

        invitee = User(
            email=old_email,
            hashed_password='never-checked-here',
            full_name='Invitee',
            organization_id=None,
            role='user',
            is_active=True,
        )
        db.add(invitee)
        code = uuid.uuid4().hex[:8].upper()
        invitation = OrganizationInvitation(
            organization_id=host.id,
            code=code,
            created_by=actor.id,
            expires_at=datetime.now(UTC) + timedelta(days=7),
            role='user',
            invited_email=old_email,
        )
        db.add(invitation)
        await db.commit()

        # The entries the inventory is about, each written by the flow
        # that writes it in production: the invitation is re-sent, the
        # code admits the person it names, and a member's status flips.
        await resend_invitation(db, host.id, invitation.id, actor_user_id=actor.id)
        await join_organization(db, code, invitee.id)
        await core_api.users.activate_or_deactivate_async(
            db, host.id, invitee.id, actor_user_id=actor.id
        )

        anonymized = await anonymize_user_async(db, invitee.id)
        await db.commit()

        # The invitation no longer names anybody.
        await db.refresh(invitation)
        assert invitation.invited_email == anonymized.email
        assert invitation.invited_email != old_email
        assert (
            await db.scalar(
                select(OrganizationInvitation).where(
                    func.lower(OrganizationInvitation.invited_email)
                    == old_email.lower()
                )
            )
        ) is None

        # The journal keeps what the flows recorded, address and all:
        # one invitation entry, two member entries (join and status).
        entries = (
            await db.scalars(
                select(AuditLog).where(AuditLog.organization_id == host.id)
            )
        ).all()
        carried = [
            entry for entry in entries if old_email in json.dumps(entry.snapshot or {})
        ]
        invited = [e for e in carried if e.target_type == 'invitation']
        members = [e for e in carried if e.target_type == 'org_member']
        assert [e.snapshot['invited_email'] for e in invited] == [old_email]
        assert [e.snapshot['name'] for e in members] == [old_email, old_email]

    async def test_an_accepted_invitation_leaves_the_address_only_in_the_journal(
        self,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        """The path that grants access writes the address a second time.

        Registering with a code burns it and journals the acceptance
        (``invited_email`` in the snapshot) before the account behind
        that address exists — so erasure meets a row written before the
        user it is about.
        """
        db = real_async_db_session
        host = async_test_household
        old_email = f'newcomer_{uuid.uuid4().hex[:8]}@example.com'
        code = uuid.uuid4().hex[:8].upper()

        db.add(
            OrganizationInvitation(
                organization_id=host.id,
                code=code,
                created_by=async_test_user.id,
                expires_at=datetime.now(UTC) + timedelta(days=7),
                role='user',
                invited_email=old_email,
            )
        )
        await db.commit()

        newcomer = await AuthService.register_user_async(
            db,
            UserCreate(
                email=old_email,
                full_name='Newcomer',
                password='Str0ng!passphrase',
                invite_code=code,
            ),
        )
        invitation = await db.scalar(
            select(OrganizationInvitation).where(OrganizationInvitation.code == code)
        )
        assert invitation is not None and invitation.invited_email == old_email

        await anonymize_user_async(db, newcomer.id)
        await db.commit()

        await db.refresh(invitation)
        assert invitation.invited_email != old_email
        assert invitation.invited_email.endswith('@anonymized.invalid')

        accepted = (
            await db.scalars(
                select(AuditLog).where(
                    AuditLog.organization_id == host.id,
                    AuditLog.target_type == 'invitation',
                )
            )
        ).all()
        assert len(accepted) == 1
        assert accepted[0].snapshot == {
            'invited_email': old_email,
            'role': invitation.role,
        }
