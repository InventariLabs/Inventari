"""The cut-off notice tells the admin where the cause lives, not what to fix.

The endpoint card stopped guessing first — its banner already names the
delivery log — so the notification an administrator reads BEFORE opening the
card was the last surface left claiming the target address is the problem.
That claim is wrong on a real path (an unreadable signing secret cuts a
channel off too), which makes the first thing the administrator reads a lie.
The notice now tells the card's story, word for word: the cause of the last
attempt is named in the delivery log.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.notification import Notification
from app.models.organization import Organization
from app.models.user import User
from app.modules.webhooks.models import WebhookEndpoint

pytestmark = pytest.mark.integration

_REFUSED_URL = 'http://127.0.0.1:9/hook'  # closed port: the probe fails fast

#: The instruction the old copy gave in every language — the guess this
#: behaviour retires. Asserted per language so a revival in any one of them
#: turns red with the language named.
_THE_ADDRESS_INSTRUCTION: dict[str, str] = {
    'en': 'Fix the target address',
    'pl': 'Popraw adres docelowy',
    'de': 'Korrigieren Sie die Zieladresse',
    'fr': "Corrigez l'adresse cible",
    'es': 'Corrija la dirección de destino',
}

#: Where the card says the cause lives — the notification must name the same
#: place with the same words, so the two channels cannot drift apart again.
_THE_JOURNAL_NAMED: dict[str, str] = {
    'en': 'delivery log',
    'pl': 'logach dostarczeń',
    'de': 'Zustellprotokoll',
    'fr': 'journaux de livraison',
    'es': 'registros de entrega',
}


async def _seed_cutoff(
    session: AsyncSession, *, admin_language: str
) -> tuple[Organization, User, WebhookEndpoint]:
    from app.core.public_api import core_api
    from app.services.token_service import get_password_hash

    org = Organization(name='Notice Org', enabled_modules=['webhooks'])
    session.add(org)
    await session.flush()
    await core_api.settings.set_bulk_async(
        session, org.id, 'webhooks', {'circuit_breaker_threshold': 3}
    )
    admin = User(
        email='notice-admin@example.com',
        hashed_password=get_password_hash('noticepass'),
        full_name='Notice Admin',
        organization_id=org.id,
        role='admin',
        is_active=True,
        preferred_language=admin_language,
    )
    session.add(admin)
    endpoint = WebhookEndpoint(
        organization_id=org.id,
        name='Notice receiver',
        url=_REFUSED_URL,
        http_method='POST',
        event_types=['item.created'],
        max_retries=3,
        retry_backoff_seconds=1,
        timeout_seconds=2,
        is_active=True,
        consecutive_failures=2,
    )
    session.add(endpoint)
    await session.commit()
    return org, admin, endpoint


class TestTheCutOffNoticeTellsWhereTheCauseLives:
    async def test_the_notice_an_administrator_reads_points_at_the_delivery_log(
        self,
        async_engine_fixture: Any,
        setup_test_db: Any,
    ) -> None:
        from app.modules.webhooks.webhook_service import deliver_test_ping

        factory = async_sessionmaker(
            async_engine_fixture, class_=AsyncSession, expire_on_commit=False
        )
        async with factory() as session:
            org, admin, endpoint = await _seed_cutoff(session, admin_language='en')

            await deliver_test_ping(session, endpoint, str(org.id))
            await session.commit()

            rows = (
                (
                    await session.execute(
                        select(Notification).where(Notification.user_id == admin.id)
                    )
                )
                .scalars()
                .all()
            )
            assert len(rows) == 1
            content = rows[0].content
            assert _THE_ADDRESS_INSTRUCTION['en'] not in content, (
                'the card stopped claiming the target address is the problem — '
                'the notice an administrator reads first must not claim it either'
            )
            assert _THE_JOURNAL_NAMED['en'] in content, (
                'the notice must tell the card story: the cause of the last '
                'attempt is named in the delivery log'
            )
            assert rows[0].link == '/settings/webhooks', (
                'the notice sends the administrator to the log, so it must '
                'carry the way there'
            )

    async def test_no_language_tells_the_administrator_to_fix_the_address(
        self,
        async_engine_fixture: Any,
        setup_test_db: Any,
    ) -> None:
        from app.modules.webhooks import _notification_labels as labels

        assert set(labels.AUTO_DISABLED_CONTENT) == set(_THE_JOURNAL_NAMED)
        for language, text in labels.AUTO_DISABLED_CONTENT.items():
            assert _THE_ADDRESS_INSTRUCTION[language].lower() not in text.lower(), (
                language
            )
            assert _THE_JOURNAL_NAMED[language] in text, language
