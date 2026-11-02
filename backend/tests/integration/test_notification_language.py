"""A notification is stored in the language its recipient reads.

A notification row is text, written once and read months later, so the language
it is written in is the language it keeps. The tray held "Nowy wniosek
o akceptację" next to "Receipt IN/2026/001 created" because some senders
localized against the recipient and others wrote English literals.

These tests cover the mechanism the senders now share: a language table handed
to ``core_api.notifications``, resolved against ``preferred_language``.
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.public_api import core_api
from app.models.notification import Notification
from app.models.organization import Organization
from app.models.user import User

TITLE = {
    'en': 'Purchase order {po} completed',
    'pl': 'Zamówienie {po} zrealizowane',
    'de': 'Bestellung {po} abgeschlossen',
    'fr': 'Commande {po} terminée',
    'es': 'Pedido {po} completado',
}


async def _make_user(
    db: AsyncSession,
    organization_id,
    *,
    role: str,
    language: str | None,
) -> User:
    from app.services.token_service import get_password_hash

    user = User(
        email=f'lang-{uuid.uuid4().hex[:8]}@test.com',
        hashed_password=get_password_hash('pass'),
        full_name='Language Test User',
        role=role,
        is_active=True,
        organization_id=organization_id,
        preferred_language=language,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


@pytest.fixture
async def org(real_async_db_session: AsyncSession) -> Organization:
    organization = Organization(name=f'Lang Org {uuid.uuid4().hex[:6]}')
    real_async_db_session.add(organization)
    await real_async_db_session.flush()
    await real_async_db_session.refresh(organization)
    return organization


@pytest.mark.integration
@pytest.mark.asyncio
class TestNotificationLanguage:
    async def test_single_recipient_gets_their_own_language(
        self, real_async_db_session: AsyncSession, org: Organization
    ) -> None:
        user = await _make_user(
            real_async_db_session, org.id, role='member', language='pl'
        )

        dto = await core_api.notifications.create_async(
            real_async_db_session,
            user_id=user.id,
            title=core_api.notifications.localize(TITLE, po='PO/2026/001'),
            content='—',
        )

        assert dto is not None
        assert dto.title == 'Zamówienie PO/2026/001 zrealizowane'

    async def test_falls_back_to_english_when_no_preference(
        self, real_async_db_session: AsyncSession, org: Organization
    ) -> None:
        user = await _make_user(
            real_async_db_session, org.id, role='member', language=None
        )

        dto = await core_api.notifications.create_async(
            real_async_db_session,
            user_id=user.id,
            title=core_api.notifications.localize(TITLE, po='PO/2026/002'),
            content='—',
        )

        assert dto is not None
        assert dto.title == 'Purchase order PO/2026/002 completed'

    async def test_a_plain_string_is_stored_as_written(
        self, real_async_db_session: AsyncSession, org: Organization
    ) -> None:
        # Every existing caller passes a str; that must keep working.
        user = await _make_user(
            real_async_db_session, org.id, role='member', language='pl'
        )

        dto = await core_api.notifications.create_async(
            real_async_db_session,
            user_id=user.id,
            title='Written once',
            content='—',
        )

        assert dto is not None
        assert dto.title == 'Written once'

    async def test_admins_are_grouped_by_the_language_they_read(
        self, real_async_db_session: AsyncSession, org: Organization
    ) -> None:
        polish = await _make_user(
            real_async_db_session, org.id, role='admin', language='pl'
        )
        german = await _make_user(
            real_async_db_session, org.id, role='admin', language='de'
        )

        await core_api.notifications.notify_org_admins_async(
            real_async_db_session,
            org.id,
            title=core_api.notifications.localize(TITLE, po='PO/2026/003'),
            content='—',
        )
        await real_async_db_session.flush()

        rows = (
            await real_async_db_session.scalars(
                select(Notification).where(
                    Notification.user_id.in_([polish.id, german.id])
                )
            )
        ).all()
        by_user = {row.user_id: row.title for row in rows}

        assert by_user[polish.id] == 'Zamówienie PO/2026/003 zrealizowane'
        assert by_user[german.id] == 'Bestellung PO/2026/003 abgeschlossen'
