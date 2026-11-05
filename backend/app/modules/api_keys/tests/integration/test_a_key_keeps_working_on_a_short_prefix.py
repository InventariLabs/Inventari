"""A key already issued shows the short prefix after the upgrade, and still works.

The stored prefix carried 11 of a key's 32 random characters onto the API keys
page and into the journal. Nothing ever authenticated by it — a key is found by
the hash of its whole value — so cutting it costs the key nothing. The
characters it loses are stored nowhere else, which is what the downgrade has to
admit.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import uuid
from collections.abc import Iterator
from typing import cast

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.db_isolation import isolated_db_url as _isolated_db_url
from app.core.module_migrations import run_module_migrations
from app.modules.api_keys.api_key_service import validate_api_key

_BEFORE = '007_scope_names_replace_scope'


@pytest.fixture
def before_the_cut() -> Iterator[str]:
    """An empty database with ``api_keys`` as the last revision before it left it."""
    from app.database import Base

    # Every table the metadata knows has to be registered before it is read.
    for module in (
        'app.core.template_models',
        'app.models',
        'app.modules.api_keys.models',
    ):
        importlib.import_module(module)

    with _isolated_db_url('ak') as url:
        engine = create_engine(url)
        Base.metadata.create_all(
            engine,
            tables=[t for t in Base.metadata.sorted_tables if t.name != 'api_keys'],
        )
        engine.dispose()
        run_module_migrations('api_keys', 'upgrade', db_url=url, revision=_BEFORE)
        yield url


def _seed(url: str) -> dict[str, tuple[uuid.UUID, str]]:
    """An active key and a revoked one, stored the way they used to be issued."""
    org, user = uuid.uuid4(), uuid.uuid4()
    keys = {
        name: (uuid.uuid4(), f'inv_live_{uuid.uuid4().hex}')
        for name in ('active', 'revoked')
    }
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(
            text(
                'INSERT INTO organizations (id, name, enabled_modules, settings, created_at) '
                'VALUES (:id, \'keys\', \'["core","api_keys"]\'::json, '
                "'{}'::json, now())"
            ),
            {'id': org},
        )
        conn.execute(
            text(
                'INSERT INTO users (id, email, hashed_password, is_active, organization_id, '
                "role, created_at, updated_at) VALUES (:id, 'ak@example.com', 'x', true, "
                ":org, 'admin', now(), now())"
            ),
            {'id': user, 'org': org},
        )
        for name, (key_id, raw) in keys.items():
            conn.execute(
                text(
                    'INSERT INTO api_keys (id, organization_id, user_id, name, hashed_key, '
                    'key_prefix, is_active, created_at) VALUES (:id, :org, :user, :name, '
                    ':hash, :prefix, :active, now())'
                ),
                {
                    'id': key_id,
                    'org': org,
                    'user': user,
                    'name': name,
                    'hash': hashlib.sha256(raw.encode()).hexdigest(),
                    'prefix': raw[:20],
                    'active': name == 'active',
                },
            )
    engine.dispose()
    return keys


def _prefixes(url: str) -> dict[uuid.UUID, str]:
    engine = create_engine(url)
    with engine.connect() as conn:
        rows = conn.execute(text('SELECT id, key_prefix FROM api_keys'))
        stored = {row.id: row.key_prefix for row in rows}
    engine.dispose()
    return stored


def _column_length(url: str) -> int:
    engine = create_engine(url)
    with engine.connect() as conn:
        length: int = conn.execute(
            text(
                'SELECT character_maximum_length FROM information_schema.columns '
                "WHERE table_name = 'api_keys' AND column_name = 'key_prefix'"
            )
        ).scalar_one()
    engine.dispose()
    return length


def _authenticated_as(url: str, raw_key: str) -> uuid.UUID | None:
    """The key the authentication path finds for *raw_key*, in that database."""

    async def check() -> uuid.UUID | None:
        engine = create_async_engine(
            make_url(url).set(drivername='postgresql+asyncpg'), poolclass=NullPool
        )
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as db:
                key = await validate_api_key(db, raw_key)
                return None if key is None else cast('uuid.UUID', key.id)
        finally:
            await engine.dispose()

    return asyncio.run(check())


@pytest.mark.integration
class TestTheUpgrade:
    def test_every_stored_prefix_is_cut_to_the_marker_and_six_characters(
        self, before_the_cut: str
    ) -> None:
        keys = _seed(before_the_cut)

        run_module_migrations('api_keys', 'upgrade', db_url=before_the_cut)

        # A revoked key too: its row stays in the table.
        assert _prefixes(before_the_cut) == {
            key_id: raw[:15] for key_id, raw in keys.values()
        }

    def test_the_column_holds_no_more_than_the_short_prefix(
        self, before_the_cut: str
    ) -> None:
        run_module_migrations('api_keys', 'upgrade', db_url=before_the_cut)

        assert _column_length(before_the_cut) == 15

    def test_a_key_issued_before_it_still_authenticates(
        self, before_the_cut: str
    ) -> None:
        keys = _seed(before_the_cut)
        key_id, raw = keys['active']

        run_module_migrations('api_keys', 'upgrade', db_url=before_the_cut)

        assert _authenticated_as(before_the_cut, raw) == key_id
        # Its shown prefix is no way in, and a revoked key stays revoked.
        assert _authenticated_as(before_the_cut, raw[:15]) is None
        assert _authenticated_as(before_the_cut, keys['revoked'][1]) is None


@pytest.mark.integration
class TestTheDowngrade:
    def test_the_column_widens_and_the_cut_characters_stay_gone(
        self, before_the_cut: str
    ) -> None:
        keys = _seed(before_the_cut)
        run_module_migrations('api_keys', 'upgrade', db_url=before_the_cut)

        run_module_migrations(
            'api_keys', 'downgrade', db_url=before_the_cut, revision=_BEFORE
        )

        assert _column_length(before_the_cut) == 20
        assert _prefixes(before_the_cut) == {
            key_id: raw[:15] for key_id, raw in keys.values()
        }
        key_id, raw = keys['active']
        assert _authenticated_as(before_the_cut, raw) == key_id
