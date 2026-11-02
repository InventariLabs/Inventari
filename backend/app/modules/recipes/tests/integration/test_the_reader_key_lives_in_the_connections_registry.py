"""The reader key lives in the connections registry, not module settings.

A credential for an external provider
belongs on /settings/ai with every other credential — visible, rotatable
and testable where the administrator looks — and the recipes settings
screen stops asking a cook to know what a reader or a rate limit is.

``resolve_jina_api_key_async`` therefore answers from the connection bound
to ``recipes.url_fetch``: the row's encrypted key when a binding serves,
the free tier when nothing does, and a refusal — not a silent fallback —
when the stored key cannot be read, because an import that quietly fell
back to the free tier off a different account would hide exactly the
rotated-credential problem the registry exists to expose.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.llm.secrets import encrypt_connection_secret
from app.core.module_settings import resolve_jina_api_key_async
from app.models.ai_connection import AiConnection
from app.models.organization import Organization


@pytest.fixture
async def household(real_async_db_session: AsyncSession) -> Organization:
    org = Organization(
        name=f'Reader {__name__[-6:]}', enabled_modules=['core', 'items', 'recipes']
    )
    real_async_db_session.add(org)
    await real_async_db_session.flush()
    return org


async def _reader_connection(
    db: AsyncSession, org: Organization, *, api_key_enc: str
) -> AiConnection:
    conn = AiConnection(
        organization_id=org.id,
        name='Jina Reader',
        provider='jina',
        capabilities=['url_fetch'],
        api_key_enc=api_key_enc,
    )
    db.add(conn)
    await db.flush()
    return conn


@pytest.mark.integration
@pytest.mark.asyncio
class TestTheReaderKeyComesFromTheRegistry:
    async def test_a_bound_connection_hands_out_its_key(
        self, real_async_db_session: AsyncSession, household: Organization
    ) -> None:
        conn = await _reader_connection(
            real_async_db_session,
            household,
            api_key_enc=encrypt_connection_secret('jina-test-key'),
        )
        household.settings = {'ai': {'defaults': {'recipes.url_fetch': str(conn.id)}}}
        await real_async_db_session.flush()

        assert (
            await resolve_jina_api_key_async(real_async_db_session, household.id)
            == 'jina-test-key'
        )

    async def test_without_a_binding_the_reader_runs_on_the_free_tier(
        self, real_async_db_session: AsyncSession, household: Organization
    ) -> None:
        await _reader_connection(
            real_async_db_session,
            household,
            api_key_enc=encrypt_connection_secret('jina-test-key'),
        )

        assert (
            await resolve_jina_api_key_async(real_async_db_session, household.id)
            is None
        )

    async def test_a_bound_connection_without_a_key_is_still_the_free_tier(
        self, real_async_db_session: AsyncSession, household: Organization
    ) -> None:
        """The row exists, the binding names it, the key column is empty —
        a connection saved as a placeholder must not read as a key that
        exists but decrypts to nothing."""
        conn = await _reader_connection(
            real_async_db_session, household, api_key_enc=''
        )
        household.settings = {'ai': {'defaults': {'recipes.url_fetch': str(conn.id)}}}
        await real_async_db_session.flush()

        assert (
            await resolve_jina_api_key_async(real_async_db_session, household.id)
            is None
        )

    async def test_a_binding_to_another_orgs_connection_is_not_a_key(
        self, real_async_db_session: AsyncSession, household: Organization
    ) -> None:
        """The tenant guard: a settings value pointing across organizations
        reads as unbound, exactly as it does for every other purpose."""
        foreign = Organization(name='Foreign reader', enabled_modules=['core'])
        real_async_db_session.add(foreign)
        await real_async_db_session.flush()
        conn = await _reader_connection(
            real_async_db_session, foreign, api_key_enc=encrypt_connection_secret('x')
        )
        household.settings = {'ai': {'defaults': {'recipes.url_fetch': str(conn.id)}}}
        await real_async_db_session.flush()

        assert (
            await resolve_jina_api_key_async(real_async_db_session, household.id)
            is None
        )

    async def test_an_undecryptable_key_refuses_instead_of_falling_back(
        self, real_async_db_session: AsyncSession, household: Organization
    ) -> None:
        sealed = encrypt_connection_secret('jina-test-key')
        # Keep the 'enc:' marker, corrupt the body: the value claims to be
        # a sealed secret but does not open — the shape a key or salt
        # rotation leaves behind. Losing the marker entirely would read as
        # legacy plaintext and pass through, which is a different (legal)
        # state, not the refusal under test.
        tampered = sealed[:8] + ('A' if sealed[8] != 'A' else 'B') + sealed[9:]
        conn = await _reader_connection(
            real_async_db_session, household, api_key_enc=tampered
        )
        household.settings = {'ai': {'defaults': {'recipes.url_fetch': str(conn.id)}}}
        await real_async_db_session.flush()

        with pytest.raises(PermissionError, match='cannot be decrypted'):
            await resolve_jina_api_key_async(real_async_db_session, household.id)
