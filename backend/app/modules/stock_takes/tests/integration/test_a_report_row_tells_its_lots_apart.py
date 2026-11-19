"""A report row of a counted parent place names the lot it stands for.

Two records of one product on one sub-shelf differ only by their expiry and by
when they were added. The counting screen prints both, so the report, which
is read after the count and answers "which of the two was short", prints
them too: each row carries the record's expiry and the moment it was added.
"""

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from fastapi import status
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.category import Category
from app.models.item import Item
from app.models.storage_location import StorageLocation
from app.models.user import User

pytestmark = pytest.mark.integration


def test_a_row_on_a_sub_location_carries_its_expiry_and_when_it_was_added(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
    test_storage_location: StorageLocation,
    test_category: Category,
    test_user: User,
) -> None:
    child = StorageLocation(
        organization_id=test_storage_location.organization_id,
        created_by=test_user.id,
        storage_type_id=test_storage_location.storage_type_id,
        name='Dock',
        parent_id=test_storage_location.id,
    )
    db_session.add(child)
    db_session.flush()
    added = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)
    records: list[Item] = []
    for index, expiry in enumerate((date(2027, 3, 1), date(2027, 6, 1))):
        record = Item(
            organization_id=test_storage_location.organization_id,
            storage_location_id=child.id,
            category_id=test_category.id,
            name='USB-C cable',
            quantity=3,
            expiry_date=expiry,
            created_at=added + timedelta(hours=index),
        )
        db_session.add(record)
        records.append(record)
    db_session.commit()

    created = client.post(
        '/api/v1/stock-takes',
        headers=auth_headers,
        json={'name': 'Parent count', 'location_id': str(test_storage_location.id)},
    )
    assert created.status_code == status.HTTP_201_CREATED, created.text

    response = client.get(
        f'/api/v1/stock-takes/{created.json()["id"]}/report', headers=auth_headers
    )

    assert response.status_code == status.HTTP_200_OK, response.text
    rows: list[dict[str, Any]] = [
        row
        for row in response.json()['all_items']
        if row['item_id'] in {str(r.id) for r in records}
    ]
    assert len(rows) == 2
    by_item = {row['item_id']: row for row in rows}
    assert by_item[str(records[0].id)]['expiry_date'] == '2027-03-01'
    assert by_item[str(records[1].id)]['expiry_date'] == '2027-06-01'
    for record in records:
        assert by_item[str(record.id)]['record_added_at'] is not None
