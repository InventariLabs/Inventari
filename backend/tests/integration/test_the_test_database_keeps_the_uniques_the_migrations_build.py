"""The test database refuses what the migrated one refuses.

The test databases are built from the models (``create_all``), and four unique
indexes used to exist only in a migration: a barcode per organization on the
records, a barcode and a SKU per organization on the catalogue, and one
reference unit per category. The models declared nothing — or a plain index
under the same columns — so every test that was meant to prove one of these
refusals passed for the wrong reason, and an assertion could rest on a
duplicate that production cannot hold.

The comparison against the migrated schema keeps the names in step; this file
pins that they are unique, partial the way the migration made them, and that
the database acts on them.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.storage_location import StorageLocation
from app.models.user import User

pytestmark = pytest.mark.integration

#: index name -> the predicate its migration gave it.
_PARTIAL_UNIQUES = {
    'uq_items_org_barcode_active': 'barcode IS NOT NULL AND is_deleted = false',
    'uq_templates_org_barcode': 'barcode IS NOT NULL',
    'uq_templates_org_sku': 'sku IS NOT NULL',
    'uq_uom_category_reference': 'is_reference = true',
}


@pytest.mark.parametrize('name', sorted(_PARTIAL_UNIQUES))
def test_the_unique_index_a_migration_builds_exists_here(
    db_session: Session, name: str
) -> None:
    row = db_session.execute(
        text(
            'SELECT i.indisunique, pg_get_expr(i.indpred, i.indrelid) '
            'FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid '
            'WHERE c.relname = :name'
        ),
        {'name': name},
    ).one_or_none()

    assert row is not None, f'{name} is missing from the test database'
    unique, predicate = row
    assert unique, f'{name} exists but does not enforce uniqueness'
    # Postgres prints the predicate its own way (brackets, casts); compare
    # without the whitespace and the grouping it adds.
    squeezed = ''.join(predicate.replace('(', '').replace(')', '').split()).lower()
    wanted = ''.join(_PARTIAL_UNIQUES[name].split()).lower()
    assert squeezed == wanted, f'{name} is partial on {predicate}'


def test_a_second_active_record_with_the_same_barcode_is_refused(
    db_session: Session,
    test_user: User,
    test_storage_location: StorageLocation,
) -> None:
    barcode = f'DUP-{uuid4().hex[:8]}'

    def record(*, deleted: bool = False) -> Item:
        return Item(
            name=f'Twin {uuid4().hex[:6]}',
            organization_id=test_user.organization_id,
            storage_location_id=test_storage_location.id,
            barcode=barcode,
            quantity=Decimal('1'),
            is_deleted=deleted,
        )

    db_session.add(record())
    db_session.commit()

    # A soft-deleted twin is not in the index, so it is not a duplicate.
    db_session.add(record(deleted=True))
    db_session.commit()

    db_session.add(record())
    with pytest.raises(IntegrityError, match='uq_items_org_barcode_active'):
        db_session.commit()
    db_session.rollback()
