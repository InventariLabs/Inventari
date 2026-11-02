"""A list hidden by ``is_active`` must not reappear when the column goes.

``shopping_lists.is_active`` was a second copy of "is this list still shown"
beside ``status``. The module now reads ``status`` only, so the migration
archives the rows only the old column kept off the screens before dropping
it.

The column the revision drops no longer exists on the head test database, so
the test puts it back for its duration, writes the legacy state through raw
SQL, runs the revision's own rewrite and takes the column away again in a
``finally`` — leaving the shared worker's schema at head.
"""

import importlib

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.user import User
from app.modules.shopping_lists.models import ShoppingList

_migration = importlib.import_module(
    'app.modules.shopping_lists.migrations.versions.006_status_is_the_only_state'
)

pytestmark = pytest.mark.integration


def test_a_list_only_is_active_hid_becomes_archived(
    db_session: Session, test_user: User
) -> None:
    db_session.execute(
        text(
            'ALTER TABLE shopping_lists ADD COLUMN is_active '
            'BOOLEAN NOT NULL DEFAULT true'
        )
    )
    try:
        hidden = ShoppingList(
            organization_id=test_user.organization_id,
            created_by=test_user.id,
            name='Hidden by is_active',
            status='active',
        )
        completed = ShoppingList(
            organization_id=test_user.organization_id,
            created_by=test_user.id,
            name='Completed',
            status='completed',
        )
        visible = ShoppingList(
            organization_id=test_user.organization_id,
            created_by=test_user.id,
            name='Still active',
            status='active',
        )
        db_session.add_all([hidden, completed, visible])
        db_session.commit()

        db_session.execute(
            text(
                'UPDATE shopping_lists SET is_active = false '
                'WHERE id IN (:hidden, :completed)'
            ),
            {'hidden': hidden.id, 'completed': completed.id},
        )
        db_session.commit()

        _migration.archive_lists_hidden_by_is_active(db_session.connection())
        db_session.commit()
        db_session.expire_all()

        hidden_row = db_session.get(ShoppingList, hidden.id)
        completed_row = db_session.get(ShoppingList, completed.id)
        visible_row = db_session.get(ShoppingList, visible.id)
        assert hidden_row is not None
        assert completed_row is not None
        assert visible_row is not None

        assert hidden_row.status == 'archived'
        assert hidden_row.archived_at is not None
        # A completed list is frozen but readable, and stays that way: the
        # old column was not what made it visible.
        assert completed_row.status == 'completed'
        assert completed_row.archived_at is None
        assert visible_row.status == 'active'
        assert visible_row.archived_at is None
    finally:
        db_session.execute(text('ALTER TABLE shopping_lists DROP COLUMN is_active'))
        db_session.commit()
