"""A test that changes the shared demo seed leaves the next test its own copy.

The demo tests no longer seed an organization each: it is seeded once per run
and copied in before every test (``tests/integration/_demo_world.py``). That
is only sound while a copy is private. This test plays two tests of the same
worker back to back -- the one that changes everything it can reach, the
clean-up between them, and the one that only reads -- and holds the second to
the seed as it was built.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

import tests._db_hygiene as hygiene
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.stock_reservation import StockReservation
from app.modules.recipes.models.recipe import Recipe
from app.modules.warehouse.models import Document
from tests.integration._demo_world import _storage_files, ids, seeded_organization

pytestmark = pytest.mark.integration


def _fingerprint(db: Session) -> dict[str, tuple[int, str]]:
    """Row count and content hash of every table that holds a row."""
    return {
        table: tuple(
            db.execute(
                text(
                    f"SELECT count(*), md5(coalesce(string_agg(t::text, ',' "
                    f"ORDER BY t::text), '')) FROM {table} t"
                )
            ).one()
        )
        for table in sorted(hygiene.dirty_tables(db.connection()))
    }


def test_what_one_test_changes_in_the_seed_the_next_does_not_see(
    db_session: Session, demo_world
) -> None:
    build = seeded_organization(items=60)

    org_id, _admin_id = ids(demo_world('org-60', build))
    built = _fingerprint(db_session)
    assert built['items'][0] > 0

    # A test that does its worst: renames, edits, deletes the holds, and edits the system data
    # the seed extended.
    db_session.get(Organization, org_id).name = 'Changed by the first test'
    db_session.query(StockReservation).delete()
    db_session.query(Document).update({Document.notes: 'Edited by the first test'})
    db_session.query(Partner).update({Partner.notes: 'Edited by the first test'})
    db_session.execute(text("UPDATE uoms SET name = name || ' (changed)'"))
    db_session.commit()
    assert _fingerprint(db_session) != built

    # What the fixture does after every test, and then for the next one.
    db_session.expire_all()
    hygiene.restore_pristine(db_session.connection())
    db_session.commit()
    demo_world('org-60', build)

    assert _fingerprint(db_session) == built


def test_what_one_test_does_to_the_seeded_files_the_next_does_not_see(
    db_session: Session, demo_world
) -> None:
    build = seeded_organization(items=60, dress=True)

    demo_world('org-60-dressed', build)
    stored = _storage_files()
    covers = sorted(
        key
        for (key,) in db_session.query(Recipe.image_key).filter(
            Recipe.image_key.is_not(None)
        )
        if key in stored
    )
    assert len(covers) >= 2, (
        'the dressed demo stores covers; without them this proves nothing'
    )
    built = {key: stored[key].read_bytes() for key in covers}

    # One test deletes a cover, another overwrites one.
    stored[covers[0]].unlink()
    stored[covers[1]].write_bytes(b'overwritten by the first test')

    db_session.expire_all()
    hygiene.restore_pristine(db_session.connection())
    db_session.commit()
    demo_world('org-60-dressed', build)

    restored = _storage_files()
    assert {key: restored[key].read_bytes() for key in covers} == built
