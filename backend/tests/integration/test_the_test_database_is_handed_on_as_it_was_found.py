"""A worker's database goes from one test to the next as the snapshot left it.

Every test on a worker shares one database, and the fixtures that keep it
clean run on every test, so they are made to answer "nothing to do" in one
round trip: the schema is compared by a fingerprint, the tables holding rows
are named by a function generated once per worker, and the system data is
left alone while it is exactly what the snapshot replayed. A shortcut like
that is only as good as what it still notices, so each thing it must notice
has a test here:

* DDL a test leaves behind is dropped and named, whatever its kind;
* a module's start-up subscriptions do not pile up on the shared bus;
* a session factory set on the database facade does not outlive the test;
* rows one test wrote — in an ordinary table, or by changing the system data
  — are gone before the next one starts, and system data nobody touched is
  not replayed for nothing.

The tests drive the same functions the fixtures call, on connections of their
own, because a fixture cannot be asked what it would have done to a test that
has not ended.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

import app.database
from app.core import db_facade
from app.core.events import event_bus
from app.models.category import Category
from app.models.organization import Organization
from app.models.user import User
from tests import _db_hygiene as hygiene

pytestmark = pytest.mark.integration


def _scalar(engine, sql: str):
    with engine.connect() as conn:
        return conn.execute(text(sql)).scalar_one()


def _settle(engine) -> bool:
    with engine.begin() as conn:
        return hygiene.restore_pristine(conn)


@pytest.fixture
def pristine(db_session: Session, engine):
    """The database as ``db_session`` found it, for a test that changes it."""
    return engine


# --- DDL a test leaves behind ------------------------------------------------

_LEFT_BEHIND = {
    'table': (
        'CREATE TABLE a_stray_table (id integer)',
        ['table a_stray_table'],
    ),
    'column': (
        'ALTER TABLE organizations ADD COLUMN a_stray_column integer',
        ['column organizations.a_stray_column'],
    ),
    'index': (
        'CREATE INDEX a_stray_index ON organizations (name)',
        ['index a_stray_index'],
    ),
    'function': (
        'CREATE FUNCTION a_stray_function() RETURNS integer '
        'LANGUAGE sql AS $$ SELECT 1 $$',
        ['function a_stray_function()'],
    ),
    'trigger': (
        'CREATE FUNCTION a_stray_trigger_body() RETURNS trigger '
        'LANGUAGE plpgsql AS $$ BEGIN RETURN NEW; END $$; '
        'CREATE TRIGGER a_stray_trigger BEFORE INSERT ON organizations '
        'FOR EACH ROW EXECUTE FUNCTION a_stray_trigger_body()',
        [
            'trigger organizations → a_stray_trigger',
            'function a_stray_trigger_body()',
        ],
    ),
}


@pytest.mark.parametrize('kind', list(_LEFT_BEHIND))
def test_ddl_a_test_leaves_behind_is_dropped_and_named(pristine, kind: str) -> None:
    ddl, expected = _LEFT_BEHIND[kind]
    with pristine.begin() as conn:
        conn.exec_driver_sql(ddl)

    with pristine.begin() as conn:
        named = hygiene.drop_leftover_ddl(conn)

    assert sorted(named) == sorted(expected)
    with pristine.begin() as conn:
        assert hygiene.drop_leftover_ddl(conn) == []


def test_a_schema_nobody_changed_costs_no_comparison(pristine) -> None:
    with pristine.begin() as conn:
        assert hygiene.drop_leftover_ddl(conn) == []


# --- Subscriptions on the shared bus -----------------------------------------


def test_what_a_start_subscribed_comes_off_and_nothing_else_does() -> None:
    def kept(payload):  # subscribed by someone else, must survive
        return None

    def started_by_the_module(payload):
        return None

    event = 'a_hygiene_test_event'
    event_bus.subscribe(event, kept)
    try:
        before = hygiene.subscriptions(event_bus)
        event_bus.subscribe(event, started_by_the_module)
        started = hygiene.subscriptions(event_bus) - before
        assert len(started) == 1

        hygiene.release_subscriptions(event_bus, started)

        left = [entry[0] for entry in event_bus._listeners[event]]
        assert left == [kept]
    finally:
        event_bus._listeners.pop(event, None)


def test_starting_a_module_for_every_test_does_not_pile_up_listeners() -> None:
    event = 'a_hygiene_test_event'
    try:
        for _ in range(3):
            before = hygiene.subscriptions(event_bus)
            event_bus.subscribe(event, lambda payload: None)
            hygiene.release_subscriptions(
                event_bus, hygiene.subscriptions(event_bus) - before
            )
        assert event_bus._listeners.get(event, []) == []
    finally:
        event_bus._listeners.pop(event, None)


# --- Rows one test wrote -----------------------------------------------------


def test_a_factory_set_on_the_facade_stops_shadowing_the_live_one(
    monkeypatch,
) -> None:
    """A facade patched directly keeps the patch's leftover for the next test.

    ``monkeypatch.setattr`` on the facade restores by setting the value it
    read, so the facade then holds a real attribute — once the engine of an
    earlier client's lifespan, whose pool belongs to a closed event loop. A
    later webhook test pointed ``app.database`` at its own engine, reached
    that pool through the facade and failed with "attached to a different
    loop", on whichever worker the files happened to meet.
    """
    left_over = object()
    with monkeypatch.context() as patch:
        patch.setattr(db_facade, 'AsyncSessionLocal', left_over, raising=False)
    own = object()
    monkeypatch.setattr(app.database, 'AsyncSessionLocal', own)
    assert db_facade.AsyncSessionLocal is not own

    assert hygiene.unfreeze_db_facade() == ['AsyncSessionLocal']

    assert db_facade.AsyncSessionLocal is own


def test_rows_in_an_ordinary_table_are_gone_for_the_next_test(pristine) -> None:
    with Session(pristine) as session:
        session.add(Organization(name='Left by an earlier test'))
        session.commit()
    assert _scalar(pristine, 'SELECT count(*) FROM organizations') == 1

    assert _settle(pristine) is True

    assert _scalar(pristine, 'SELECT count(*) FROM organizations') == 0


def test_a_system_row_a_test_changed_is_put_back(pristine) -> None:
    original = _scalar(pristine, 'SELECT min(name) FROM uoms')
    with pristine.begin() as conn:
        conn.execute(text("UPDATE uoms SET name = 'renamed by a test'"))

    assert _settle(pristine) is True

    assert _scalar(pristine, 'SELECT min(name) FROM uoms') == original
    assert (
        _scalar(pristine, "SELECT count(*) FROM uoms WHERE name = 'renamed by a test'")
        == 0
    )


def test_a_system_row_a_test_deleted_comes_back(pristine) -> None:
    count = _scalar(pristine, 'SELECT count(*) FROM categories')
    with pristine.begin() as conn:
        conn.execute(
            text(
                'DELETE FROM categories WHERE id = (SELECT id FROM categories LIMIT 1)'
            )
        )

    assert _settle(pristine) is True

    assert _scalar(pristine, 'SELECT count(*) FROM categories') == count


def test_a_category_a_test_added_is_gone_for_the_next_test(pristine) -> None:
    count = _scalar(pristine, 'SELECT count(*) FROM categories')
    with Session(pristine) as session:
        session.add(Category(name='Added by a test'))
        session.commit()

    assert _settle(pristine) is True

    assert _scalar(pristine, 'SELECT count(*) FROM categories') == count


def test_system_data_nobody_touched_is_left_where_it_is(pristine) -> None:
    written_by = _scalar(pristine, 'SELECT min(xmin::text) FROM uoms')

    assert _settle(pristine) is False

    assert _scalar(pristine, 'SELECT min(xmin::text) FROM uoms') == written_by


@pytest.mark.parametrize('may_skip_constraints', [True, False])
def test_rows_that_reference_one_another_go_together(
    pristine, monkeypatch, may_skip_constraints: bool
) -> None:
    """An organization and its user name each other; both must go in one pass.

    Without the privilege to switch constraints off, the only way to empty such
    a pair is the single statement ``clear_statement`` builds.
    """
    monkeypatch.setattr(hygiene, '_may_skip_constraints', may_skip_constraints)
    with Session(pristine) as session:
        organization = Organization(name='Left by an earlier test')
        session.add(organization)
        session.flush()
        session.add(
            User(
                email='left@example.com',
                hashed_password='x',
                full_name='Left Behind',
                organization_id=organization.id,
            )
        )
        session.flush()
        organization.created_by = session.query(User).one().id
        session.commit()

    assert _settle(pristine) is True

    assert _scalar(pristine, 'SELECT count(*) FROM organizations') == 0
    assert _scalar(pristine, 'SELECT count(*) FROM users') == 0
