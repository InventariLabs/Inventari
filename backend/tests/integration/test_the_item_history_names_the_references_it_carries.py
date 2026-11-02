"""The item's own history names the records its update points at.

The organization journal has carried a ``*_name`` beside every changed
``*_id`` since the naming was introduced; the record's history kept the ids
alone, so one event read "Category: ffb4a9cd → 7ab33755" on the item card
while the journal beside it spelled the words. Both readers now walk the
same snapshot shape, and the name is how the id reads — not a change of its
own, which is why it may never appear as a separate line.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.category import Category
from app.models.item import Item
from app.models.item_history import ItemAction, ItemHistory

pytestmark = pytest.mark.integration

ITEM_URL = '/api/v1/items'


def _latest_update_changes(db: Session, item_id: UUID) -> dict:
    row = db.scalars(
        select(ItemHistory)
        .where(
            ItemHistory.item_id == item_id,
            ItemHistory.action == ItemAction.UPDATED.value,
        )
        .order_by(ItemHistory.created_at.desc())
    ).first()
    assert row is not None, 'the update wrote no history row'
    return row.changes


def test_the_update_history_names_a_category_beside_its_id(
    client,
    auth_headers,
    db_session: Session,
    test_item: Item,
    test_category: Category,
) -> None:
    other = Category(name='Drinks')
    db_session.add(other)
    db_session.commit()

    response = client.put(
        f'{ITEM_URL}/{test_item.id}',
        headers=auth_headers,
        json={'category_id': str(other.id)},
    )
    assert response.status_code == 200, response.text

    db_session.expire_all()
    changes = _latest_update_changes(db_session, test_item.id)
    # The id that names the record stays; the name that reads it is what
    # the card had been missing.
    assert changes['old']['category_id'] == str(test_category.id)
    assert changes['new']['category_id'] == str(other.id)
    assert changes['old']['category_name'] == 'Pork'
    assert changes['new']['category_name'] == 'Drinks'
