"""A location deleted while the list is being read is not a 500.

The list read the locations it matches in one statement and the
organization's tree (parents, names, the field lists a level passes down) in
the next. A location deleted by another request between the two was on the
first answer and missing from the second, and the lookup into the tree
raised ``KeyError``: ``GET /api/v1/locations`` answered 500 to whoever was
listing while somebody else tidied up. Both now come from one statement, so
the rows the list matches and the tree they are looked up in are one picture
of the table.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.storage_location import StorageLocation
from app.services.storage_query_service import list_storages_with_counts_async


@pytest.fixture
async def shelves(real_async_db_session: AsyncSession, async_test_user):
    db = real_async_db_session
    org_id = async_test_user.organization_id
    by = async_test_user.id
    fields = [{'key': 'opened_on', 'label': 'Opened on', 'type': 'date'}]
    rack = StorageLocation(
        organization_id=org_id, created_by=by, name='Rack', field_definitions=fields
    )
    db.add(rack)
    await db.flush()
    own = [{'key': 'batch', 'label': 'Batch', 'type': 'text'}]
    kept = StorageLocation(
        organization_id=org_id,
        created_by=by,
        name='Kept shelf',
        parent_id=rack.id,
        field_definitions=own,
    )
    doomed = StorageLocation(
        organization_id=org_id,
        created_by=by,
        name='Doomed shelf',
        parent_id=rack.id,
        field_definitions=own,
    )
    db.add_all([kept, doomed])
    await db.flush()
    return {'org_id': org_id, 'kept': kept, 'doomed': doomed}


def _delete_after_the_first_read(db: AsyncSession, monkeypatch, location_id):
    """Another request deletes *location_id* right after the list's first read."""
    original = db.execute
    calls = 0

    async def execute(statement, *args, **kwargs):
        nonlocal calls
        result = await original(statement, *args, **kwargs)
        calls += 1
        if calls == 1:
            await original(
                text('DELETE FROM storage_locations WHERE id = :id'),
                {'id': location_id},
            )
        return result

    monkeypatch.setattr(db, 'execute', execute)


@pytest.mark.integration
@pytest.mark.asyncio
class TestALocationDeletedWhileTheListReads:
    @pytest.mark.parametrize('with_fields', [False, True])
    async def test_the_list_answers_without_the_deleted_location(
        self, real_async_db_session: AsyncSession, shelves, monkeypatch, with_fields
    ):
        db = real_async_db_session
        db.expunge(shelves['doomed'])
        _delete_after_the_first_read(db, monkeypatch, shelves['doomed'].id)

        rows, _total = await list_storages_with_counts_async(
            db, shelves['org_id'], None, with_fields=with_fields
        )

        names = {row.name for row in rows}
        assert 'Doomed shelf' not in names
        assert 'Kept shelf' in names
        kept = next(row for row in rows if row.name == 'Kept shelf')
        assert kept.inherited_field_definitions[0].key == 'opened_on'
