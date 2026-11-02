"""A bearer invitation opens the door once, not once per request that arrives.

Redeeming read the invitation with a plain SELECT filtered on
``is_used == False`` and only then wrote the flag. Two requests carrying the
same code and landing together both saw the same unspent row, and both were
let in: the second one's write simply set a flag that was already set. A code
meant to admit one person admitted as many as arrived in the same instant.

The registration path had the same shape for the same reason, and is pinned
here too -- the address binding narrows who can use a code, but a bearer code
minted before that binding existed is exactly the case this race is about.

The lock is what makes the second read wait; when it unblocks, the row no
longer matches ``is_used == False`` and the refusal is the ordinary one.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.core.testing import ModuleTestHelper
from app.models.organization import Organization, OrganizationInvitation
from app.models.user import User
from app.schemas.user import UserCreate
from app.services._org_membership import join_organization
from app.services.auth_service import AuthService

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _async_test_url() -> str:
    return settings.DATABASE_URL.replace('postgresql://', 'postgresql+asyncpg://', 1)


class _Door:
    def __init__(self) -> None:
        self.host_org_id: uuid.UUID
        self.code: str
        self.arrivals: list[uuid.UUID]


async def _door(db: AsyncSession) -> _Door:
    """One host organisation, one bearer code, two people holding it."""
    fixture = _Door()

    host = Organization(name=f'Host {uuid.uuid4().hex[:6]}', enabled_modules=['core'])
    db.add(host)
    await db.flush()
    fixture.host_org_id = host.id
    owner = await ModuleTestHelper.create_user_async(
        db, host, email=f'owner_{uuid.uuid4().hex[:8]}@test.com', role='admin'
    )

    fixture.code = uuid.uuid4().hex[:8].upper()
    db.add(
        OrganizationInvitation(
            organization_id=host.id,
            code=fixture.code,
            expires_at=datetime.now(UTC) + timedelta(days=7),
            created_by=owner.id,
            role='user',
            # A bearer code: minted before invitations named an address, and
            # kept working until it expires.
            invited_email=None,
        )
    )

    fixture.arrivals = []
    for index in range(2):
        # Each in an organisation of their own, sole member, so leaving is
        # never blocked by the sole-administrator rule.
        their_org = Organization(
            name=f'Guest {index} {uuid.uuid4().hex[:6]}', enabled_modules=['core']
        )
        db.add(their_org)
        await db.flush()
        guest = await ModuleTestHelper.create_user_async(
            db, their_org, email=f'guest{index}_{uuid.uuid4().hex[:8]}@test.com'
        )
        their_org.created_by = guest.id
        fixture.arrivals.append(guest.id)

    await db.commit()
    return fixture


async def _both_knock(door: _Door) -> list[BaseException | Organization]:
    engine = create_async_engine(_async_test_url(), echo=False, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def knock(user_id: uuid.UUID):
        async with factory() as session:
            organization = await join_organization(session, door.code, user_id)
            # As the request does once the endpoint returns.
            await session.commit()
            return organization

    try:
        return await asyncio.gather(
            *(knock(user_id) for user_id in door.arrivals),
            return_exceptions=True,
        )
    finally:
        await engine.dispose()


class TestTwoPeopleWithOneCode:
    async def test_only_one_of_them_gets_in(self, real_async_db_session: AsyncSession):
        door = await _door(real_async_db_session)

        results = await _both_knock(door)

        admitted = [r for r in results if not isinstance(r, BaseException)]
        refused = [r for r in results if isinstance(r, ValueError)]
        assert len(admitted) == 1, results
        assert len(refused) == 1, results

    async def test_the_other_one_is_still_where_they_were(
        self, real_async_db_session: AsyncSession
    ):
        door = await _door(real_async_db_session)

        await _both_knock(door)

        real_async_db_session.expire_all()
        rows = await real_async_db_session.scalars(
            select(User).where(User.id.in_(door.arrivals))
        )
        joined = [u for u in rows.all() if u.organization_id == door.host_org_id]
        assert len(joined) == 1

    async def test_the_code_names_the_one_who_used_it(
        self, real_async_db_session: AsyncSession
    ):
        door = await _door(real_async_db_session)

        await _both_knock(door)

        real_async_db_session.expire_all()
        invitation = await real_async_db_session.scalar(
            select(OrganizationInvitation).where(
                OrganizationInvitation.code == door.code
            )
        )
        assert invitation is not None
        assert invitation.is_used is True
        assert invitation.used_by_user_id in door.arrivals


class TestTwoRegistrationsWithOneCode:
    """The same race one door over, where the account does not exist yet."""

    async def test_only_one_account_lands_in_the_organization(
        self, real_async_db_session: AsyncSession
    ):
        door = await _door(real_async_db_session)

        engine = create_async_engine(_async_test_url(), echo=False, poolclass=NullPool)
        factory = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )
        emails = [f'new{index}_{uuid.uuid4().hex[:8]}@test.com' for index in range(2)]

        async def sign_up(email: str):
            async with factory() as session:
                user = await AuthService.register_user_async(
                    session,
                    UserCreate(
                        email=email,
                        full_name='Newcomer',
                        password='Str0ng!passphrase',
                        invite_code=door.code,
                    ),
                )
                await session.commit()
                return user.organization_id

        try:
            landed = await asyncio.gather(
                *(sign_up(email) for email in emails), return_exceptions=True
            )
        finally:
            await engine.dispose()

        inside = [
            org_id
            for org_id in landed
            if not isinstance(org_id, BaseException) and org_id == door.host_org_id
        ]
        assert len(inside) == 1, landed
