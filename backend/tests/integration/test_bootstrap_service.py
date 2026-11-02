"""Integration tests for app.services.bootstrap_service.

Covers the startup-time self-healing logic that every self-hosted
instance runs:

- backfill ``short_id`` on organizations missing one
- promote configured ``SUPERUSER_EMAIL`` user to superuser
- promote first system user to superuser when no email is configured
- idempotency for users already superuser
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization
from app.models.user import User
from app.services._org_reads import get_by_id_async
from app.services.bootstrap_service import run_startup_bootstrap_async


def _uniq_email(prefix: str = 'user') -> str:
    return f'{prefix}-{uuid.uuid4().hex[:8]}@bootstrap.test'


async def _make_user(
    db: AsyncSession,
    *,
    email: str | None = None,
    is_superuser: bool = False,
    organization_id: object | None = None,
) -> User:
    user = User(
        email=email or _uniq_email(),
        hashed_password='x',
        full_name='Bootstrap User',
        is_active=True,
        is_superuser=is_superuser,
        organization_id=organization_id,
    )
    db.add(user)
    await db.flush()
    return user


async def _make_org(db: AsyncSession, *, short_id: str | None = None) -> Organization:
    org = Organization(name=f'Org-{uuid.uuid4().hex[:6]}', short_id=short_id)
    db.add(org)
    await db.flush()
    return org


@pytest.fixture
async def clean_users(real_async_db_session: AsyncSession) -> AsyncSession:
    """Truncate users + organizations so first-user / org-backfill tests are deterministic.

    The shared ``real_async_db_session`` fixture does not truncate between
    async tests (xdist-friendly truncation is owned by the sync ``db_session``
    fixture). Bootstrap semantics depend on global ordering, so we wipe.
    """
    from sqlalchemy import delete

    # Organizations FK-reference users (created_by); delete in order.
    await real_async_db_session.execute(delete(User))
    await real_async_db_session.execute(delete(Organization))
    await real_async_db_session.commit()
    return real_async_db_session


@pytest.mark.integration
@pytest.mark.asyncio
class TestRunStartupBootstrapAsync:
    async def test_first_user_promoted_when_superuser_email_unset(
        self, clean_users: AsyncSession, monkeypatch
    ) -> None:
        monkeypatch.setattr(
            'app.services.bootstrap_service.settings.SUPERUSER_EMAIL', None
        )
        user = await _make_user(clean_users)

        await run_startup_bootstrap_async(db=clean_users)

        await clean_users.refresh(user)
        assert user.is_superuser is True

    async def test_configured_email_user_promoted_when_superuser_email_set(
        self, clean_users: AsyncSession, monkeypatch
    ) -> None:
        target_email = _uniq_email('admin')
        user_a = await _make_user(clean_users, email=target_email)
        user_b = await _make_user(clean_users)

        monkeypatch.setattr(
            'app.services.bootstrap_service.settings.SUPERUSER_EMAIL', target_email
        )

        await run_startup_bootstrap_async(db=clean_users)

        await clean_users.refresh(user_a)
        await clean_users.refresh(user_b)
        assert user_a.is_superuser is True
        assert user_b.is_superuser is False

    @pytest.mark.parametrize('configured_email', [False, True])
    async def test_demo_instance_promotes_nobody(
        self, clean_users: AsyncSession, monkeypatch, configured_email: bool
    ) -> None:
        email = _uniq_email('demo')
        user = await _make_user(clean_users, email=email)
        monkeypatch.setattr(
            'app.services.bootstrap_service.settings.SUPERUSER_EMAIL',
            email if configured_email else None,
        )
        monkeypatch.setattr(
            'app.services.bootstrap_service.settings.INVENTARI_DEMO', True
        )

        await run_startup_bootstrap_async(db=clean_users)

        await clean_users.refresh(user)
        assert user.is_superuser is False

    async def test_already_superuser_unchanged_idempotent(
        self, clean_users: AsyncSession, monkeypatch
    ) -> None:
        monkeypatch.setattr(
            'app.services.bootstrap_service.settings.SUPERUSER_EMAIL', None
        )
        user = await _make_user(clean_users, is_superuser=True)

        await run_startup_bootstrap_async(db=clean_users)
        await run_startup_bootstrap_async(db=clean_users)

        await clean_users.refresh(user)
        assert user.is_superuser is True

    async def test_orgs_missing_short_id_backfilled(
        self, clean_users: AsyncSession, monkeypatch
    ) -> None:
        monkeypatch.setattr(
            'app.services.bootstrap_service.settings.SUPERUSER_EMAIL', None
        )
        org_with = await _make_org(clean_users, short_id='ORG-KEEP')
        org_without = await _make_org(clean_users, short_id=None)

        await run_startup_bootstrap_async(db=clean_users)

        refreshed_without = await get_by_id_async(clean_users, org_without.id)
        refreshed_with = await get_by_id_async(clean_users, org_with.id)
        assert refreshed_without is not None and refreshed_without.short_id is not None
        assert refreshed_without.short_id.startswith('ORG-')
        assert refreshed_with is not None and refreshed_with.short_id == 'ORG-KEEP'

    async def test_no_users_no_error(
        self, clean_users: AsyncSession, monkeypatch
    ) -> None:
        # ``clean_users`` already wiped users/orgs.
        monkeypatch.setattr(
            'app.services.bootstrap_service.settings.SUPERUSER_EMAIL', None
        )
        users = (await clean_users.scalars(select(User))).all()
        assert users == []

        await run_startup_bootstrap_async(db=clean_users)
