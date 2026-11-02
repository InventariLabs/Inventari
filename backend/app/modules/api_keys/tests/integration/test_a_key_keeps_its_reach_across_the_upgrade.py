"""A key issued before keys had permission lists keeps what it could do.

Every key used to carry one fixed set, the agent endpoints of the printing
module asked for no permission, and a ``printing`` key was confined by path.
The upgrade writes each existing key the list it effectively had, so nothing
that worked the day before stops working the day after — and nothing that was
refused starts to work.
"""

from __future__ import annotations

import importlib
import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, inspect, text

from app.core.contracts import SystemPermission
from app.core.db_isolation import isolated_db_url as _isolated_db_url
from app.core.module_migrations import run_module_migrations

_ORDINARY_BEFORE = [
    'categories:read',
    'items:read',
    'items:write',
    'locations:read',
    'org:read',
]


@pytest.fixture
def before_the_lists() -> Iterator[str]:
    """An empty database with ``api_keys`` as revision 004 left it."""
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
        run_module_migrations(
            'api_keys',
            'upgrade',
            db_url=url,
            revision='004_timestamps_carry_their_zone',
        )
        yield url


def _seed(url: str) -> dict[str, uuid.UUID]:
    ids = {
        name: uuid.uuid4() for name in ('org', 'user', 'ordinary', 'printing', 'gone')
    }
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(
            text(
                'INSERT INTO organizations (id, name, enabled_modules, settings, created_at) '
                'VALUES (:id, \'keys\', \'["core","api_keys","printing"]\'::json, '
                "'{}'::json, now())"
            ),
            {'id': ids['org']},
        )
        conn.execute(
            text(
                'INSERT INTO users (id, email, hashed_password, is_active, organization_id, '
                "role, created_at, updated_at) VALUES (:id, 'ak@example.com', 'x', true, "
                ":org, 'admin', now(), now())"
            ),
            {'id': ids['user'], 'org': ids['org']},
        )
        # An ordinary key, a print agent's key, and a key of a scope whose
        # module has since gone — which opened no path at all.
        for key, scope in (
            ('ordinary', None),
            ('printing', 'printing'),
            ('gone', 'garden'),
        ):
            conn.execute(
                text(
                    'INSERT INTO api_keys (id, organization_id, user_id, name, hashed_key, '
                    'key_prefix, scope, is_active, created_at) VALUES (:id, :org, :user, '
                    ':name, :hash, :prefix, :scope, true, now())'
                ),
                {
                    'id': ids[key],
                    'org': ids['org'],
                    'user': ids['user'],
                    'name': key,
                    'hash': uuid.uuid4().hex + uuid.uuid4().hex,
                    'prefix': f'inv_live_{key}'[:20],
                    'scope': scope,
                },
            )
    engine.dispose()
    return ids


def _stored(url: str) -> dict[uuid.UUID, tuple[list[str], list[str]]]:
    engine = create_engine(url)
    with engine.connect() as conn:
        rows = conn.execute(text('SELECT id, permissions, scope_names FROM api_keys'))
        stored = {row.id: (row.permissions, row.scope_names) for row in rows}
    engine.dispose()
    return stored


@pytest.mark.integration
class TestTheUpgrade:
    def test_an_ordinary_key_keeps_its_set_and_can_still_act_as_an_agent(
        self, before_the_lists: str
    ) -> None:
        ids = _seed(before_the_lists)

        run_module_migrations('api_keys', 'upgrade', db_url=before_the_lists)

        assert _stored(before_the_lists)[ids['ordinary']] == (
            sorted([*_ORDINARY_BEFORE, 'printing:agent']),
            [],
        )

    def test_every_permission_written_is_one_the_server_knows(
        self, before_the_lists: str
    ) -> None:
        # A misspelt key would be written without complaint and grant nothing.
        _seed(before_the_lists)

        run_module_migrations('api_keys', 'upgrade', db_url=before_the_lists)

        known = {p.value for p in SystemPermission} | {'printing:agent'}
        written = {p for perms, _ in _stored(before_the_lists).values() for p in perms}
        assert written <= known

    def test_a_printing_key_keeps_the_agent_and_nothing_else(
        self, before_the_lists: str
    ) -> None:
        ids = _seed(before_the_lists)

        run_module_migrations('api_keys', 'upgrade', db_url=before_the_lists)

        assert _stored(before_the_lists)[ids['printing']] == (
            ['printing:agent'],
            ['printing'],
        )

    def test_a_key_of_a_vanished_scope_still_reaches_nothing(
        self, before_the_lists: str
    ) -> None:
        ids = _seed(before_the_lists)

        run_module_migrations('api_keys', 'upgrade', db_url=before_the_lists)

        assert _stored(before_the_lists)[ids['gone']] == ([], ['garden'])

    def test_the_single_scope_column_is_gone_and_the_lists_are_required(
        self, before_the_lists: str
    ) -> None:
        _seed(before_the_lists)

        run_module_migrations('api_keys', 'upgrade', db_url=before_the_lists)

        engine = create_engine(before_the_lists)
        columns = {c['name']: c for c in inspect(engine).get_columns('api_keys')}
        engine.dispose()
        assert 'scope' not in columns
        assert columns['permissions']['nullable'] is False
        assert columns['scope_names']['nullable'] is False

    def test_a_downgrade_gives_each_key_its_single_scope_back(
        self, before_the_lists: str
    ) -> None:
        ids = _seed(before_the_lists)
        run_module_migrations('api_keys', 'upgrade', db_url=before_the_lists)

        run_module_migrations(
            'api_keys',
            'downgrade',
            db_url=before_the_lists,
            revision='004_timestamps_carry_their_zone',
        )

        engine = create_engine(before_the_lists)
        with engine.connect() as conn:
            scopes = {
                row.id: row.scope
                for row in conn.execute(text('SELECT id, scope FROM api_keys'))
            }
        engine.dispose()
        assert scopes == {
            ids['ordinary']: None,
            ids['printing']: 'printing',
            ids['gone']: 'garden',
        }
