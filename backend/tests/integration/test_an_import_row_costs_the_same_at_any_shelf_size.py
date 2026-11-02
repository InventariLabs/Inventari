"""An import row asks the database the same questions however full its shelf is.

An import of ten thousand rows into one shelf ran 62 ms a row for the first
file and 73 ms for the fourth: something a row did grew with what the shelf
already held. The statements a row sends are the part a test can pin — the
same count for the thirtieth row as for the fifth — while the lookups that
decide how long each takes are indexed in the schema.
"""

import pandas as pd
import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.services.items import import_items

pytestmark = pytest.mark.asyncio

MAPPING = {'name': 'Name', 'quantity': 'Quantity', 'location': 'Location'}


async def test_a_row_on_a_full_shelf_sends_as_many_statements_as_on_a_small_one(
    real_async_db_session: AsyncSession,
    async_test_user,
    async_test_storage_location,
) -> None:
    db = real_async_db_session
    user = UserContextDTO(
        id=async_test_user.id, organization_id=async_test_user.organization_id
    )
    statements: list[str] = []

    def _count(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    async def _statements_for(first: int, count: int) -> int:
        sheet = pd.DataFrame(
            [
                {
                    'Name': f'Same shelf {n}',
                    'Quantity': 1,
                    'Location': async_test_storage_location.name,
                }
                for n in range(first, first + count)
            ]
        )
        statements.clear()
        engine = db.get_bind()
        event.listen(engine, 'before_cursor_execute', _count)
        try:
            result = await import_items(
                db,
                sheet.to_csv(index=False).encode(),
                'shelf.csv',
                MAPPING,
                user,
                create_missing_locations=False,
                create_missing_categories=False,
            )
        finally:
            event.remove(engine, 'before_cursor_execute', _count)
        assert result['imported'] == count
        return len(statements)

    # The first rows warm the unit and category caches; what is compared is
    # the cost of a row once they are warm, at two sizes of the shelf.
    for batch in range(0, 20, 5):
        await _statements_for(batch, 5)
    early_rows = await _statements_for(20, 5)
    for batch in range(25, 100, 5):  # fill the shelf
        await _statements_for(batch, 5)
    later_rows = await _statements_for(100, 5)

    assert later_rows == early_rows, (
        f'five rows sent {early_rows} statements on a shelf of 20 and '
        f'{later_rows} on a shelf of 100'
    )
