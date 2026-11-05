"""A field seeded before the seed carried its option words gets them.

The seed only inserts, so an organization older than ``options_i18n`` shows the
label of "lactose free" in its language and the options in stored English. This
runs the revision's ``upgrade`` over the categories it meets: the seed's own,
and the ones it has to leave alone because an organization wrote them.
"""

from __future__ import annotations

import uuid

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy.orm import Session

from app.models.category import Category
from app.models.organization import Organization
from migrations.versions import fieldwords01_fill_the_seeded_option_words as revision

pytestmark = pytest.mark.integration

WORDS = {
    'No': 'items:fieldOptions.lactose_free.No',
    'Yes': 'items:fieldOptions.lactose_free.Yes',
}


def _as_seeded_then(**overrides) -> dict:
    """The field as the seed wrote it before it carried the words."""
    return {
        'key': 'lactose_free',
        'is_system': True,
        'label': 'Lactose free',
        'type': 'select',
        'options': ['No', 'Yes'],
        'visible': True,
        'required': False,
        **overrides,
    }


def _category(
    db: Session, organization: Organization, code: str, definitions: list[dict]
) -> uuid.UUID:
    category = Category(
        name=code,
        code=code,
        organization_id=organization.id,
        field_definitions=definitions,
    )
    db.add(category)
    db.flush()
    return category.id


def _upgrade_and_read(db: Session, category_id: uuid.UUID) -> list[dict]:
    with Operations.context(MigrationContext.configure(db.connection())):
        revision.upgrade()
    db.expire_all()
    return db.get(Category, category_id).field_definitions


@pytest.mark.parametrize('code', ['dairy', 'cheese'])
def test_the_seeds_field_gets_the_words_and_keeps_the_rest(
    db_session, test_household, code
):
    other_field = {'key': 'note', 'type': 'text', 'label': 'Note'}
    category_id = _category(
        db_session, test_household, code, [_as_seeded_then(), other_field]
    )

    assert _upgrade_and_read(db_session, category_id) == [
        _as_seeded_then(options_i18n=WORDS),
        other_field,
    ]


@pytest.mark.parametrize(
    ('code', 'definition'),
    [
        pytest.param('wine', _as_seeded_then(), id='a code outside the seed'),
        pytest.param(
            'dairy',
            _as_seeded_then(key='vegan'),
            id='a key outside the seed',
        ),
        pytest.param(
            'dairy',
            _as_seeded_then(options=['Without', 'With']),
            id='options the organization wrote',
        ),
        pytest.param(
            'dairy',
            _as_seeded_then(options_i18n={'No': 'custom:no'}),
            id='words already there',
        ),
    ],
)
def test_what_the_seed_did_not_write_is_left_alone(
    db_session, test_household, code, definition
):
    category_id = _category(db_session, test_household, code, [definition])

    assert _upgrade_and_read(db_session, category_id) == [definition]


def test_a_second_run_and_a_downgrade_change_nothing(db_session, test_household):
    category_id = _category(db_session, test_household, 'dairy', [_as_seeded_then()])

    once = _upgrade_and_read(db_session, category_id)
    assert _upgrade_and_read(db_session, category_id) == once

    with Operations.context(MigrationContext.configure(db_session.connection())):
        revision.downgrade()
    db_session.expire_all()
    assert db_session.get(Category, category_id).field_definitions == once
