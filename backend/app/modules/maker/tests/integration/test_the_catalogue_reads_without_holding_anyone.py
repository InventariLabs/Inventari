"""The recipe catalogue reads without holding anyone, at a price set by depth.

Two ways the catalogue made people pay for each other.

The module's settings were fetched under the row lock by default — an
advisory lock plus ``SELECT ... FOR UPDATE``, held to the end of the
request — and a missing row was written on the spot. The catalogue and the
settings screen both read through that default, so two people opening the
catalogue queued behind each other, and the first visit of an organization
wrote a row from a GET. A read now takes no lock and writes nothing; the
paths that change a setting or act on one ask for the lock themselves.

The never-run recipes' estimate exploded the page in one batch, but only the
page's own lines were resolved up front: every deeper level was met one
recipe at a time, so a page of three-level formulas with different
intermediates paid a query per recipe per level. The page is now resolved a
level at a time, and its query count does not move with the number of rows.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select, text
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.modules.maker.models import MakerModuleSettings
from app.modules.maker.tests.integration.test_a_run_opens_the_card_at_its_cost import (
    _template,
)
from app.modules.maker.tests.integration.test_the_catalog_names_its_number import (
    _recipe_with_yield,
)

pytestmark = pytest.mark.integration

#: How long a read may take before it counts as waiting on the lock. The
#: read itself answers in well under a second; a read that waits never ends
#: until the holder lets go.
_PATIENCE_S = 10


@contextmanager
def _statements(async_engine: Any) -> Iterator[list[str]]:
    """Every statement a request sends through the client's async engine."""
    sent: list[str] = []

    def capture(_conn: Any, _cursor: Any, statement: str, *_args: Any) -> None:
        sent.append(' '.join(statement.split()))

    engine = async_engine.sync_engine
    event.listen(engine, 'before_cursor_execute', capture)
    try:
        yield sent
    finally:
        event.remove(engine, 'before_cursor_execute', capture)


def _three_level_formulas(db: Session, org: Organization, count: int, tag: str) -> None:
    """*count* formulas, each over its own two intermediates and its own leaf.

    top → middle → base → leaf: two levels below the page's own lines, and
    no intermediate shared between formulas, so nothing one formula resolves
    serves another. Only the top recipe's name says "top", so a search for it
    lists the formulas without their intermediates — which, listed on the
    same page, would hand their own lines to the page's first lookup.
    """
    for i in range(count):
        leaf = _template(db, org, f'{tag} leaf {i}')
        base = _template(db, org, f'{tag} base {i}')
        middle = _template(db, org, f'{tag} middle {i}')
        top = _template(db, org, f'{tag} top {i}')
        for output, child, level in (
            (base, leaf, 'base'),
            (middle, base, 'middle'),
            (top, middle, 'top'),
        ):
            _recipe_with_yield(
                db,
                org,
                output_id=output.id,
                child_id=child.id,
                name=f'{tag} {level} {i}',
                yield_qty='1',
                qty_per_batch='2',
            )


def _chain(db: Session, org: Organization, levels: int, tag: str) -> None:
    """One formula *levels* recipes deep, each level made from the next.

    Nothing on the write side bounds nesting, so a chain past the walk's
    limit is reachable. Only the first recipe's name says "top".
    """
    templates = [_template(db, org, f'{tag} part {i}') for i in range(levels + 1)]
    for i in range(levels):
        _recipe_with_yield(
            db,
            org,
            output_id=templates[i].id,
            child_id=templates[i + 1].id,
            name=f'{tag} top' if i == 0 else f'{tag} level {i}',
            yield_qty='1',
            qty_per_batch='1',
        )


def _catalogue_answer(
    client: TestClient, headers: dict[str, str], async_engine: Any, search: str
) -> tuple[list[str], Any]:
    with _statements(async_engine) as sent:
        listed = client.get(
            '/api/v1/maker/recipes', params={'search': search}, headers=headers
        )
    return list(sent), listed


def _catalogue_statements(
    client: TestClient, headers: dict[str, str], async_engine: Any
) -> tuple[list[str], int]:
    sent, listed = _catalogue_answer(client, headers, async_engine, 'top')
    assert listed.status_code == 200, listed.text
    return sent, listed.json()['total']


def _settings_rows(db: Session, org_id: UUID) -> int:
    db.expire_all()
    count = db.scalar(
        select(func.count())
        .select_from(MakerModuleSettings)
        .where(MakerModuleSettings.organization_id == org_id)
    )
    return count or 0


class TestTheCatalogueReadsWithoutHoldingAnyone:
    def test_opening_the_catalogue_and_the_settings_locks_and_writes_nothing(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
        async_engine_fixture: Any,
    ) -> None:
        _three_level_formulas(db_session, mk_org, 1, 'Quiet')
        assert _settings_rows(db_session, mk_org.id) == 0

        with _statements(async_engine_fixture) as sent:
            settings = client.get('/api/v1/maker/settings', headers=mk_auth_headers)
            listed = client.get('/api/v1/maker/recipes', headers=mk_auth_headers)

        assert settings.status_code == 200, settings.text
        assert listed.status_code == 200, listed.text
        # An organization nobody configured reads as the defaults.
        body = settings.json()
        assert body['reference_direction'] == 'MARGIN'
        assert body['availability_check_scope'] == 'GLOBAL'
        assert body['allow_overproduction'] is True
        assert {item['reference_direction'] for item in listed.json()['items']} == {
            'MARGIN'
        }

        locking = [
            statement
            for statement in sent
            if 'pg_advisory' in statement or 'FOR UPDATE' in statement
        ]
        assert locking == []
        writing = [
            statement
            for statement in sent
            if 'maker_module_settings' in statement
            and not statement.startswith('SELECT')
        ]
        assert writing == []
        assert _settings_rows(db_session, mk_org.id) == 0

    def test_a_read_does_not_wait_for_a_settings_change_in_flight(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        _three_level_formulas(db_session, mk_org, 1, 'Busy')
        db_session.add(MakerModuleSettings(organization_id=mk_org.id))
        db_session.commit()

        answers: dict[str, int] = {}

        def read(name: str, url: str) -> None:
            answers[name] = client.get(url, headers=mk_auth_headers).status_code

        # Two people open the catalogue while a third opens the settings, all
        # at once: had a read taken the lock, each would queue behind the
        # holder and behind each other.
        readers = [
            threading.Thread(target=read, args=(name, url))
            for name, url in (
                ('settings', '/api/v1/maker/settings'),
                ('catalogue', '/api/v1/maker/recipes'),
                ('catalogue again', '/api/v1/maker/recipes'),
            )
        ]

        # Another request holds what a settings change holds — the advisory
        # lock and the row — and has not committed yet.
        with db_session.get_bind().engine.connect() as holder:
            transaction = holder.begin()
            holder.execute(
                text('SELECT pg_advisory_xact_lock(hashtext(:k))'),
                {'k': f'maker_settings:{mk_org.id}'},
            )
            holder.execute(
                select(MakerModuleSettings)
                .where(MakerModuleSettings.organization_id == mk_org.id)
                .with_for_update()
            )
            for reader in readers:
                reader.start()
            deadline = time.monotonic() + _PATIENCE_S
            for reader in readers:
                reader.join(timeout=max(0.0, deadline - time.monotonic()))
            finished_while_held = not any(reader.is_alive() for reader in readers)
            transaction.rollback()
        for reader in readers:
            reader.join()

        assert finished_while_held, 'a read waited for a settings change to commit'
        assert answers == {'settings': 200, 'catalogue': 200, 'catalogue again': 200}

    def test_the_page_costs_the_same_at_two_formulas_and_at_eight(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
        async_engine_fixture: Any,
    ) -> None:
        _three_level_formulas(db_session, mk_org, 2, 'Few')
        few, few_rows = _catalogue_statements(
            client, mk_auth_headers, async_engine_fixture
        )
        _three_level_formulas(db_session, mk_org, 6, 'Many')
        many, many_rows = _catalogue_statements(
            client, mk_auth_headers, async_engine_fixture
        )

        # Only the tops are listed, every one of them never run, so every
        # row on the page is estimated through the batch explosion.
        assert (few_rows, many_rows) == (2, 8)
        assert len(many) == len(few), (len(few), len(many))

    def test_a_chain_past_the_depth_limit_is_refused_before_it_is_read_to_its_end(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
        async_engine_fixture: Any,
    ) -> None:
        # Both chains are deeper than the walk accepts; the second is twice
        # as deep as the first. Resolving the page level by level must stop
        # where the walk refuses, or the deeper chain costs a query per level
        # of nesting nobody will ever read.
        _chain(db_session, mk_org, 15, 'Shallow')
        _chain(db_session, mk_org, 30, 'Deep')

        shallow, shallow_answer = _catalogue_answer(
            client, mk_auth_headers, async_engine_fixture, 'Shallow top'
        )
        deep, deep_answer = _catalogue_answer(
            client, mk_auth_headers, async_engine_fixture, 'Deep top'
        )

        for answer in (shallow_answer, deep_answer):
            assert answer.status_code == 400, answer.text
            assert answer.json()['detail']['code'] == 'BOM_DEPTH_EXCEEDED'
        assert len(deep) == len(shallow), (len(shallow), len(deep))
