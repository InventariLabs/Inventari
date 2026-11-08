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
from unittest.mock import patch

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import func, select
from typer.testing import CliRunner

from app.core.public_api import core_api
from app.core.token_blacklist import TokenBlacklist, token_blacklist
from app.models.audit_log import AuditAction, AuditLog
from app.models.item_history import ItemAction, ItemHistory
from app.models.organization import OrganizationInvitation
from app.models.user import RegistrationRequest, User
from app.schemas.user import UserCreate
from app.services._org_membership import join_organization, resend_invitation
from app.services.auth_service import AuthService
from app.services.gdpr_service import anonymize_user_async
from manage import app as cli

pytestmark = pytest.mark.integration

cli_runner = CliRunner()


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

    async def test_a_request_typed_in_another_case_is_scrubbed_too(
        self, real_async_db_session, async_test_user
    ):
        """A request keeps the address as the person typed it.

        The request form stores the address verbatim, so the person who
        asked as ``Jan@Example.com`` and was later approved or invited as
        ``jan@example.com`` holds a request erasure must still find — the
        invitations beside it were already matched without regard to case.
        """
        db = real_async_db_session
        user = async_test_user
        typed = user.email.upper()
        request = RegistrationRequest(email=typed, full_name='Typed In Capitals')
        db.add(request)
        await db.commit()

        anonymized = await anonymize_user_async(db, user.id)
        await db.commit()

        await db.refresh(request)
        assert request.email == anonymized.email
        assert request.full_name is None

    async def test_the_reason_an_account_was_blocked_is_cleared(
        self, real_async_db_session, async_test_user
    ):
        """The reason is free text an operator wrote about the person."""
        db = real_async_db_session
        user = async_test_user
        user.is_blocked = True
        user.blocking_reason = f'Repeated misuse reported by {user.full_name}'
        await db.commit()

        anonymized = await anonymize_user_async(db, user.id)
        await db.commit()

        await db.refresh(anonymized)
        assert anonymized.blocking_reason is None


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


class _Redis:
    """Just enough Redis for the revocation, and a way to lose it."""

    def __init__(self, *, ping_error=None, write_error=None) -> None:
        self.store: dict[str, str] = {}
        self.closed = False
        self._ping_error = ping_error
        self._write_error = write_error

    async def ping(self) -> bool:
        if self._ping_error is not None:
            raise self._ping_error
        return True

    async def setex(self, key: str, ttl: int, value: str) -> None:
        if self._write_error is not None:
            raise self._write_error
        self.store[key] = value

    async def aclose(self) -> None:
        self.closed = True


class TestTheEraseCommand:
    """``manage.py user erase`` is the procedure's erasure, run as an operator runs it.

    The procedure used to paste a script that failed as written: it asked for
    a session before any async engine existed, and in production the token
    revocation refused to run with no Redis behind it. So every test here
    meets the command the way a fresh process on a deployed install does — no
    async engine, a shared blacklist with no connection, DEBUG and TESTING
    off — against the worker database, and reads the outcome back through a
    connection of its own, which only sees what was committed.
    """

    @pytest.fixture(autouse=True)
    def fresh_production_process(self, monkeypatch):
        from app import database
        from app.config import settings

        monkeypatch.setattr(settings, 'DEBUG', False)
        monkeypatch.setattr(settings, 'TESTING', False)
        monkeypatch.delenv('TESTING', raising=False)
        monkeypatch.setattr(database, 'async_engine', None)
        monkeypatch.setattr(database, 'AsyncSessionLocal', None)
        monkeypatch.setattr(token_blacklist, '_redis', None)
        # The test process loaded every module's models long ago; discovering
        # them again would register the modules a second time in the shared
        # registry.
        monkeypatch.setattr('app.cli.bootstrap_db', lambda: None)

    @pytest.fixture
    def account(self, setup_test_db):
        """An account committed where the command's own connection can see it."""
        from app.database import SessionLocal

        with SessionLocal() as db:
            user = User(
                email=f'erasable_{uuid.uuid4().hex[:8]}@example.com',
                hashed_password='never-checked-here',
                full_name='Erasable Person',
                organization_id=None,
                role='user',
                is_active=True,
            )
            db.add(user)
            db.commit()
            user_id, email = user.id, user.email
        yield user_id, email
        with SessionLocal() as db:
            db.query(User).filter(User.id == user_id).delete()
            db.commit()

    @staticmethod
    def _read_back(user_id):
        from app.database import SessionLocal

        with SessionLocal() as db:
            user = db.get(User, user_id)
            assert user is not None
            return user.email, user.full_name, user.is_active

    def test_the_account_is_erased_and_its_sessions_revoked(self, account):
        user_id, _email = account
        redis = _Redis()

        with patch('redis.asyncio.from_url', return_value=redis):
            result = cli_runner.invoke(cli, ['user', 'erase', str(user_id), '--yes'])

        assert result.exit_code == 0, result.output
        assert self._read_back(user_id) == (
            f'deleted-{user_id.hex}@anonymized.invalid',
            'Deleted User',
            False,
        )
        assert f'{TokenBlacklist.PREFIX}user:{user_id}' in redis.store
        assert redis.closed is True
        # The revocation went through a connection of the command's own: the
        # blacklist the rest of the process shares is left as it was found.
        assert token_blacklist._redis is None

    @pytest.mark.parametrize(
        'redis',
        [
            _Redis(ping_error=RedisConnectionError('connection refused')),
            _Redis(write_error=RedisConnectionError('connection lost')),
        ],
        ids=['redis-unreachable', 'revocation-lost'],
    )
    def test_a_revocation_that_cannot_be_written_erases_nothing(self, account, redis):
        """One transaction: the account is rewritten before the revocation is
        written, so a lost revocation must take the rewrite back with it."""
        user_id, email = account

        with patch('redis.asyncio.from_url', return_value=redis):
            result = cli_runner.invoke(cli, ['user', 'erase', str(user_id), '--yes'])

        assert result.exit_code == 1
        assert 'Nothing was erased' in result.output
        assert self._read_back(user_id) == (email, 'Erasable Person', True)
        assert redis.closed is True

    def test_an_unknown_id_is_reported(self, setup_test_db):
        unknown = uuid.uuid4()

        with patch('redis.asyncio.from_url', return_value=_Redis()):
            result = cli_runner.invoke(cli, ['user', 'erase', str(unknown), '--yes'])

        assert result.exit_code == 1
        assert 'Nothing was erased' in result.output
        assert str(unknown) in result.output

    def test_the_operator_sees_whose_account_it_is_and_can_decline(self, account):
        user_id, email = account
        redis = _Redis()

        with patch('redis.asyncio.from_url', return_value=redis):
            result = cli_runner.invoke(
                cli, ['user', 'erase', str(user_id)], input='n\n'
            )

        assert result.exit_code == 1
        assert email in result.output
        assert 'Erasable Person' in result.output
        assert self._read_back(user_id) == (email, 'Erasable Person', True)
        assert redis.store == {}

    def test_a_question_nobody_can_answer_names_the_way_out(self, account):
        """``exec -T`` gives the command no terminal: the question meets the end
        of its input, and the operator is told to pass ``--yes``."""
        user_id, email = account

        with patch('redis.asyncio.from_url', return_value=_Redis()):
            result = cli_runner.invoke(cli, ['user', 'erase', str(user_id)], input='')

        assert result.exit_code == 1
        assert 'Nothing was erased' in result.output
        assert '--yes' in result.output
        assert self._read_back(user_id) == (email, 'Erasable Person', True)
