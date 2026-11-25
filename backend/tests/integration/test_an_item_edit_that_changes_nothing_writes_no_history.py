"""An item edit that moves nothing leaves no history row, and a weight the
column cannot hold is refused as a validation error rather than a 500."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.item_history import ItemAction, ItemHistory

pytestmark = pytest.mark.integration

ITEM_URL = '/api/v1/items'


def _updated_rows(db: Session, item: Item) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(ItemHistory)
            .where(
                ItemHistory.item_id == item.id,
                ItemHistory.action == ItemAction.UPDATED.value,
            )
        )
        or 0
    )


def test_resaving_a_value_unchanged_writes_no_history_row(
    client, auth_headers, db_session: Session, test_item: Item
) -> None:
    first = client.put(
        f'{ITEM_URL}/{test_item.id}',
        headers=auth_headers,
        json={'min_quantity': 1234.567},
    )
    assert first.status_code == 200, first.text
    db_session.expire_all()
    rows = _updated_rows(db_session, test_item)

    again = client.put(
        f'{ITEM_URL}/{test_item.id}',
        headers=auth_headers,
        json={'min_quantity': 1234.5670},
    )
    assert again.status_code == 200, again.text

    db_session.expire_all()
    assert _updated_rows(db_session, test_item) == rows


@pytest.mark.parametrize('weight', [1e30, 100_000_000, 1e8])
def test_an_oversized_weight_is_refused_not_a_server_error(
    client, auth_headers, test_item: Item, weight: float
) -> None:
    response = client.put(
        f'{ITEM_URL}/{test_item.id}',
        headers=auth_headers,
        json={'weight_value': weight},
    )
    assert response.status_code == 422, response.text
