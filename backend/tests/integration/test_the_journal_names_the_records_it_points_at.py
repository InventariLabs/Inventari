"""The journal writes a name beside every record it points at.

The screen that answers "where did this go" answered with eight characters of
a UUID: `Location: 67d57628` on one row, `Parent: 67d57628` on the next, and
after "Show the whole change" a `Category: 84f70f85` — not a value a reader
can act on, or even paste into a search. The entry already named the record it
was *about* (`snapshot['name']`); the records it merely referenced it left as
bare ids.

The name cannot be resolved when the journal is read — one query per row makes
the screen useless, and a settings page may not reach into the inventory
modules for their dictionaries — so it is written with the entry, from the row
as it read in the same transaction. That is also the only truthful answer: a
shelf renamed next week must not change what last month's entry says.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.services.token_service import create_access_token

pytestmark = pytest.mark.integration


def _auth(user) -> dict:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


async def _entries(client, user, **params) -> list[dict]:
    response = await client.get('/api/v1/audit-log', headers=_auth(user), params=params)
    assert response.status_code == 200
    return response.json()['items']


async def _latest(client, user, target_type: str, action: str) -> dict:
    entries = await _entries(client, user, target_type=target_type)
    matching = [e for e in entries if e['action'] == action]
    assert matching, f'no {action} entry for {target_type} in the journal'
    return matching[0]


@pytest.fixture
async def admin(real_async_db_session, async_test_household, async_test_user):
    """The org and its user, committed — the HTTP client uses its own session."""
    await real_async_db_session.commit()
    return async_test_user


@pytest.fixture
async def shelves(real_async_db_session, async_test_household, admin):
    """Two places to move records between, committed for the HTTP client."""
    from app.models.storage_location import StorageLocation

    rows = [
        StorageLocation(
            organization_id=async_test_household.id,
            created_by=admin.id,
            name=name,
        )
        for name in ('Shelf A', 'Shelf B')
    ]
    real_async_db_session.add_all(rows)
    await real_async_db_session.commit()
    for row in rows:
        await real_async_db_session.refresh(row)
    return rows


@pytest.fixture
async def stored_item(real_async_client, admin, shelves):
    """A record on the first shelf, created the way a person creates one."""
    response = await real_async_client.post(
        '/api/v1/items',
        json={
            'name': 'QA Item',
            'location_id': str(shelves[0].id),
            'quantity': 2,
        },
        headers=_auth(admin),
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _store_item(client, admin, shelves, name: str) -> dict:
    """A second record on the first shelf, for the batch paths."""
    response = await client.post(
        '/api/v1/items',
        json={
            'name': name,
            'location_id': str(shelves[0].id),
            'quantity': 1,
        },
        headers=_auth(admin),
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
async def categories(real_async_db_session, async_test_household):
    """Two categories of this organization, with the codes the app reads them by."""
    from app.models.category import Category

    rows = [
        Category(organization_id=async_test_household.id, name=name, code=code)
        for name, code in (('Dairy', 'dairy'), ('Cheese', 'cheese'))
    ]
    real_async_db_session.add_all(rows)
    await real_async_db_session.commit()
    for row in rows:
        await real_async_db_session.refresh(row)
    return rows


@pytest.fixture
async def storage_types(real_async_db_session, async_test_household, admin):
    """Two kinds of place this organization may file a location under."""
    from app.models.storage_type import StorageType

    rows = [
        StorageType(
            organization_id=async_test_household.id,
            name=name,
            type_code=code,
            created_by=admin.id,
        )
        for name, code in (('Shelf', 'qa_shelf'), ('Cold room', 'qa_cold_room'))
    ]
    real_async_db_session.add_all(rows)
    await real_async_db_session.commit()
    for row in rows:
        await real_async_db_session.refresh(row)
    return rows


@pytest.mark.asyncio
class TestAnItemNamesWhereItIs:
    async def test_creating_one_names_the_shelf_it_landed_on(
        self, real_async_client, admin, stored_item, shelves
    ):
        entry = await _latest(real_async_client, admin, 'item', 'CREATE')

        assert entry['snapshot']['storage_location_id'] == str(shelves[0].id)
        assert entry['snapshot']['storage_location_name'] == 'Shelf A'

    async def test_moving_it_names_the_shelf_it_left_and_the_one_it_reached(
        self, real_async_client, admin, stored_item, shelves
    ):
        moved = await real_async_client.put(
            f'/api/v1/items/{stored_item["id"]}',
            json={'location_id': str(shelves[1].id)},
            headers=_auth(admin),
        )
        assert moved.status_code == 200, moved.text

        entry = await _latest(real_async_client, admin, 'item', 'UPDATE')
        snapshot = entry['snapshot']
        # The move is the whole entry, which is why the two names are what
        # the reader has to work with.
        assert snapshot['fields'] == ['storage_location_id']
        assert snapshot['before']['storage_location_id'] == str(shelves[0].id)
        assert snapshot['before']['storage_location_name'] == 'Shelf A'
        assert snapshot['after']['storage_location_id'] == str(shelves[1].id)
        assert snapshot['after']['storage_location_name'] == 'Shelf B'


@pytest.mark.asyncio
class TestTheNameIsTheOneWrittenDown:
    async def test_renaming_the_shelf_afterwards_leaves_the_entry_alone(
        self, real_async_client, admin, stored_item, shelves
    ):
        """A name resolved at read time would follow the rename. This one is a
        record of what the shelf was called when the goods were carried."""
        moved = await real_async_client.put(
            f'/api/v1/items/{stored_item["id"]}',
            json={'location_id': str(shelves[1].id)},
            headers=_auth(admin),
        )
        assert moved.status_code == 200, moved.text
        renamed = await real_async_client.put(
            f'/api/v1/locations/{shelves[1].id}',
            json={'name': 'Shelf B (renamed)'},
            headers=_auth(admin),
        )
        assert renamed.status_code == 200, renamed.text

        entry = await _latest(real_async_client, admin, 'item', 'UPDATE')
        assert entry['snapshot']['after']['storage_location_name'] == 'Shelf B'


@pytest.mark.asyncio
class TestALocationNamesItsParent:
    async def test_creating_one_under_a_shelf_names_that_shelf(
        self, real_async_client, admin, shelves
    ):
        response = await real_async_client.post(
            '/api/v1/locations',
            json={'name': f'Drawer {uuid4().hex[:6]}', 'parent_id': str(shelves[0].id)},
            headers=_auth(admin),
        )
        assert response.status_code == 201, response.text

        entry = await _latest(real_async_client, admin, 'storage', 'CREATE')
        assert entry['snapshot']['parent_id'] == str(shelves[0].id)
        assert entry['snapshot']['parent_name'] == 'Shelf A'

    async def test_moving_one_names_the_parent_it_left_and_the_one_it_reached(
        self, real_async_client, admin, shelves
    ):
        created = await real_async_client.post(
            '/api/v1/locations',
            json={'name': f'Drawer {uuid4().hex[:6]}', 'parent_id': str(shelves[0].id)},
            headers=_auth(admin),
        )
        assert created.status_code == 201, created.text
        drawer = created.json()

        moved = await real_async_client.put(
            f'/api/v1/locations/{drawer["id"]}',
            json={'parent_id': str(shelves[1].id)},
            headers=_auth(admin),
        )
        assert moved.status_code == 200, moved.text

        entry = await _latest(real_async_client, admin, 'storage', 'UPDATE')
        snapshot = entry['snapshot']
        assert snapshot['before']['parent_id'] == str(shelves[0].id)
        assert snapshot['before']['parent_name'] == 'Shelf A'
        assert snapshot['after']['parent_id'] == str(shelves[1].id)
        assert snapshot['after']['parent_name'] == 'Shelf B'

    async def test_deleting_one_keeps_the_name_of_the_shelf_above_it(
        self, real_async_client, admin, shelves
    ):
        """The row is gone after the delete; the journal is where it survives."""
        created = await real_async_client.post(
            '/api/v1/locations',
            json={'name': f'Drawer {uuid4().hex[:6]}', 'parent_id': str(shelves[0].id)},
            headers=_auth(admin),
        )
        assert created.status_code == 201, created.text
        drawer = created.json()

        deleted = await real_async_client.delete(
            f'/api/v1/locations/{drawer["id"]}',
            headers=_auth(admin),
        )
        assert deleted.status_code in (200, 204), deleted.text

        entries = await _entries(real_async_client, admin, target_type='storage')
        entry = next(
            e
            for e in entries
            if e['action'] == 'HARD_DELETE' and e['target_id'] == drawer['id']
        )
        assert entry['snapshot']['parent_id'] == str(shelves[0].id)
        assert entry['snapshot']['parent_name'] == 'Shelf A'


@pytest.mark.asyncio
class TestABatchNamesWhatItMoves:
    async def test_the_bulk_edit_names_the_shelf_and_the_category_it_changed(
        self, real_async_client, admin, stored_item, shelves, categories
    ):
        """The batch was the one path still writing ids alone.

        Measured on the screen as `Location: 405d91ba → 134990cc, Category: —
        → de779d5b` — the symptom this task was opened for, on the same fields
        the single edit had already stopped writing, reached by the other
        button. The name belongs to the side it describes, and a side that
        held nothing keeps holding nothing.
        """
        second = await _store_item(real_async_client, admin, shelves, 'QA Item 2')

        response = await real_async_client.patch(
            '/api/v1/items/bulk',
            json={
                'item_ids': [stored_item['id'], second['id']],
                'update_data': {
                    'location_id': str(shelves[1].id),
                    'category_id': str(categories[0].id),
                },
            },
            headers=_auth(admin),
        )
        assert response.status_code == 200, response.text
        assert response.json()['updated'] == 2

        entries = await _entries(
            real_async_client,
            admin,
            target_type='item',
            target_id=stored_item['id'],
        )
        entry = next(e for e in entries if e['action'] == 'UPDATE')
        assert entry['meta_data']['bulk'] is True

        snapshot = entry['snapshot']
        assert snapshot['before']['storage_location_id'] == str(shelves[0].id)
        assert snapshot['before']['storage_location_name'] == 'Shelf A'
        assert snapshot['after']['storage_location_id'] == str(shelves[1].id)
        assert snapshot['after']['storage_location_name'] == 'Shelf B'
        # It had no category, so that side names nothing — and the record it
        # moved to is named by its name *and* the code the app reads it by.
        assert 'category_name' not in snapshot['before']
        assert snapshot['after']['category_id'] == str(categories[0].id)
        assert snapshot['after']['category_name'] == 'Dairy'
        assert snapshot['after']['category_code'] == 'dairy'


@pytest.mark.asyncio
class TestALocationNamesTheKindOfPlaceItIs:
    async def test_changing_the_type_names_the_one_it_left_and_the_one_it_reached(
        self, real_async_client, admin, shelves, storage_types
    ):
        """`Storage type: 4a2e2c4b → 820fdc2a` sat on the same row as the parent.

        The empty description the edit form posts is not a change either: a
        line reading `Description: — →` says nothing, and it was the line that
        pushed the parent of a move under "Show the whole change".
        """
        created = await real_async_client.post(
            '/api/v1/locations',
            json={
                'name': f'Drawer {uuid4().hex[:6]}',
                'parent_id': str(shelves[0].id),
                'location_type_id': str(storage_types[0].id),
            },
            headers=_auth(admin),
        )
        assert created.status_code == 201, created.text
        drawer = created.json()

        moved = await real_async_client.put(
            f'/api/v1/locations/{drawer["id"]}',
            json={
                'parent_id': str(shelves[1].id),
                'location_type_id': str(storage_types[1].id),
                'description': '',
            },
            headers=_auth(admin),
        )
        assert moved.status_code == 200, moved.text

        entry = await _latest(real_async_client, admin, 'storage', 'UPDATE')
        snapshot = entry['snapshot']
        assert snapshot['before']['storage_type_id'] == str(storage_types[0].id)
        assert snapshot['before']['storage_type_name'] == 'Shelf'
        assert snapshot['after']['storage_type_id'] == str(storage_types[1].id)
        assert snapshot['after']['storage_type_name'] == 'Cold room'
        assert 'description' not in snapshot['before']
        assert 'description' not in snapshot['after']
        # What moved first is what the row leads with, so the parent of a move
        # is on the row rather than behind the expander.
        assert list(snapshot['before'])[0] == 'parent_id'
        assert snapshot['before']['parent_name'] == 'Shelf A'
        assert snapshot['after']['parent_name'] == 'Shelf B'


@pytest.mark.asyncio
class TestAUnitWeightNamesItsUnit:
    """The unit of a piece weight is named the way every other unit is.

    A product edit that moves the piece weight goes to the card, and the card's
    unit is a reference like the shelf is: `Weight uom: — → ac76d1cb` sent the
    reader hunting for a unit they cannot see on the journal screen. The word
    is the symbol the product screen and the shelf label print (`g`), never the
    catalogue name (`Gram`).
    """

    @pytest.fixture
    async def units(self, real_async_db_session):
        """Two units of the seeded catalogue, grams and kilograms."""
        from sqlalchemy import select

        from app.models.uom import Uom

        rows = (
            await real_async_db_session.scalars(
                select(Uom).where(Uom.symbol.in_(('g', 'kg')))
            )
        ).all()
        await real_async_db_session.commit()
        for row in rows:
            await real_async_db_session.refresh(row)
        by_symbol = {row.symbol: row for row in rows}
        assert 'g' in by_symbol and 'kg' in by_symbol
        return by_symbol

    async def test_changing_the_unit_weight_writes_the_symbol_beside_the_id(
        self, real_async_client, admin, shelves, units
    ):
        created = await real_async_client.post(
            '/api/v1/items',
            json={
                'name': f'QA Weight {uuid4().hex[:6]}',
                'location_id': str(shelves[0].id),
                'quantity': 1,
                'weight_value': 250,
                'weight_uom_id': str(units['g'].id),
            },
            headers=_auth(admin),
        )
        assert created.status_code == 201, created.text

        changed = await real_async_client.put(
            f'/api/v1/items/{created.json()["id"]}',
            json={'weight_value': 1, 'weight_uom_id': str(units['kg'].id)},
            headers=_auth(admin),
        )
        assert changed.status_code == 200, changed.text

        entry = await _latest(real_async_client, admin, 'item', 'UPDATE')
        snapshot = entry['snapshot']
        assert snapshot['before']['weight_uom_id'] == str(units['g'].id)
        assert snapshot['before']['weight_uom_name'] == 'g'
        assert snapshot['after']['weight_uom_id'] == str(units['kg'].id)
        assert snapshot['after']['weight_uom_name'] == 'kg'


@pytest.mark.asyncio
class TestAPurgeNamesTheRecordsItOutlives:
    """A purge row is the only place its references survive — so it names them.

    The row that outlives the record carried `organization_id` as a bare id
    beside the shelf it had already learned to name. The organization is a
    reference like the shelf: deletable rows leave the journal opened months
    later against a word, not eight characters.
    """

    async def test_the_purge_entry_names_the_organization_and_the_shelf(
        self,
        real_async_client,
        real_async_db_session,
        async_test_household,
        admin,
        shelves,
    ):
        from app.models.organization import Organization

        org = await real_async_db_session.get(Organization, async_test_household.id)
        org.settings = {'allow_permanent_delete': True}
        await real_async_db_session.commit()
        await real_async_db_session.refresh(org)
        org_name = org.name

        created = await real_async_client.post(
            '/api/v1/items',
            json={
                'name': f'QA Purge {uuid4().hex[:6]}',
                'location_id': str(shelves[0].id),
                'quantity': 1,
            },
            headers=_auth(admin),
        )
        assert created.status_code == 201, created.text
        item_id = created.json()['id']

        archived = await real_async_client.delete(
            f'/api/v1/items/{item_id}', headers=_auth(admin)
        )
        assert archived.status_code in (200, 204), archived.text

        purged = await real_async_client.delete(
            f'/api/v1/items/{item_id}/purge',
            params={'reason': 'TEST_DATA'},
            headers=_auth(admin),
        )
        assert purged.status_code == 204, purged.text

        entries = await _entries(
            real_async_client, admin, target_type='item', target_id=item_id
        )
        entry = next(e for e in entries if e['action'] == 'PURGE')
        snapshot = entry['snapshot']
        assert snapshot['organization_id'] == str(async_test_household.id)
        assert snapshot['organization_name'] == org_name
        assert snapshot['storage_location_id'] == str(shelves[0].id)
        assert snapshot['storage_location_name'] == 'Shelf A'


@pytest.mark.asyncio
class TestACategoryIsNamedByItsCode:
    async def test_creating_an_item_writes_the_code_beside_the_name(
        self, real_async_client, admin, shelves, categories
    ):
        """A seeded category is named by its seed in English and *read* by code.

        Every screen prints `Nabiał` for `dairy`; a journal that writes only
        the record's own name speaks a word the product screen never uses.
        """
        response = await real_async_client.post(
            '/api/v1/items',
            json={
                'name': f'QA Item {uuid4().hex[:6]}',
                'location_id': str(shelves[0].id),
                'category_id': str(categories[0].id),
                'quantity': 1,
            },
            headers=_auth(admin),
        )
        assert response.status_code == 201, response.text

        entry = await _latest(real_async_client, admin, 'item', 'CREATE')
        assert entry['snapshot']['category_id'] == str(categories[0].id)
        assert entry['snapshot']['category_name'] == 'Dairy'
        assert entry['snapshot']['category_code'] == 'dairy'

    async def test_recategorising_names_and_codes_both_sides(
        self, real_async_client, admin, shelves, categories
    ):
        created = await real_async_client.post(
            '/api/v1/items',
            json={
                'name': f'QA Item {uuid4().hex[:6]}',
                'location_id': str(shelves[0].id),
                'category_id': str(categories[0].id),
                'quantity': 1,
            },
            headers=_auth(admin),
        )
        assert created.status_code == 201, created.text

        moved = await real_async_client.put(
            f'/api/v1/items/{created.json()["id"]}',
            json={'category_id': str(categories[1].id)},
            headers=_auth(admin),
        )
        assert moved.status_code == 200, moved.text

        entry = await _latest(real_async_client, admin, 'item', 'UPDATE')
        snapshot = entry['snapshot']
        assert snapshot['before']['category_name'] == 'Dairy'
        assert snapshot['before']['category_code'] == 'dairy'
        assert snapshot['after']['category_name'] == 'Cheese'
        assert snapshot['after']['category_code'] == 'cheese'
