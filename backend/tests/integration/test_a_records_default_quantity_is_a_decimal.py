"""A record made without a quantity holds a ``Decimal`` one, like every other.

``Item.quantity`` is a ``Numeric`` column read back as ``Decimal``, and its
default was the float ``1.0``. The ORM keeps the default it sent on the
object after the insert, so a record created without a quantity carried a
float until it was read again, and the first sum with a ``Decimal`` raised
``TypeError``.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.storage_location import StorageLocation


@pytest.mark.integration
def test_a_record_made_without_a_quantity_holds_one_as_a_decimal(
    db_session: Session, test_storage_location: StorageLocation
) -> None:
    item = Item(
        organization_id=test_storage_location.organization_id,
        storage_location_id=test_storage_location.id,
        name='Counted later',
    )
    db_session.add(item)
    db_session.flush()

    assert type(item.quantity) is Decimal
    assert item.quantity + Decimal('2') == Decimal('3')
