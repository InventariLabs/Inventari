"""An import fills the product fields the row's location asks for.

A location's fields are its own plus those of every location above it — a
field set on a warehouse applies to each shelf inside. The form asks for
them; the import used to know only its fixed system columns, so a sheet
carrying "Supplier" saved every product with no supplier and reported no
failure. A mapped field column now lands in the product's metadata wherever
the row's location has that field, typed the way the form stores it.
"""

import pandas as pd
import pytest
from sqlalchemy import select

from app.core.contracts import UserContextDTO
from app.models.category import Category
from app.models.item import Item
from app.models.storage_location import StorageLocation
from app.services.items._import import import_items


def _csv(rows: list[dict]) -> bytes:
    return pd.DataFrame(rows).to_csv(index=False).encode()


def _ctx(user) -> UserContextDTO:
    return UserContextDTO(
        id=user.id, organization_id=user.organization_id, role='admin'
    )


MAPPING = {
    'name': 'Name',
    'location': 'Storage',
    'field:supplier': 'Supplier',
    'field:opened_on': 'Opened',
    'field:colour': 'Colour',
    'field:fragile': 'Fragile',
    'field:depth': 'Depth',
}


async def _location(db, user, storage_type, name, parent=None, fields=()):
    location = StorageLocation(
        organization_id=user.organization_id,
        created_by=user.id,
        storage_type_id=storage_type.id,
        name=name,
        parent_id=parent.id if parent else None,
        field_definitions=list(fields),
    )
    db.add(location)
    await db.flush()
    return location


async def _metadata_of(db, name: str) -> dict:
    item = (await db.execute(select(Item).where(Item.name == name))).scalar_one()
    return item.meta_data or {}


async def _grow_a_tree(db, user, storage_type):
    """Review Warehouse → Review Rack → Review Shelf, a field on each level."""
    warehouse = await _location(
        db,
        user,
        storage_type,
        'Review Warehouse',
        fields=[
            {'key': 'supplier', 'label': 'Supplier', 'type': 'text'},
            {'key': 'depth', 'label': 'Depth', 'type': 'number'},
        ],
    )
    rack = await _location(
        db,
        user,
        storage_type,
        'Review Rack',
        parent=warehouse,
        fields=[
            {'key': 'opened_on', 'label': 'Opened on', 'type': 'date'},
            {'key': 'fragile', 'label': 'Fragile', 'type': 'boolean'},
        ],
    )
    shelf = await _location(
        db,
        user,
        storage_type,
        'Review Shelf',
        parent=rack,
        fields=[
            {
                'key': 'colour',
                'label': 'Colour',
                'type': 'select',
                'options': ['Blue', 'Red'],
            }
        ],
    )
    return warehouse, rack, shelf


@pytest.mark.integration
@pytest.mark.asyncio
class TestAnImportFillsTheFieldsItsLocationAsksFor:
    async def test_fields_from_every_level_above_land_in_the_metadata(
        self, real_async_db_session, async_test_user, async_test_storage_type
    ):
        db = real_async_db_session
        await _grow_a_tree(db, async_test_user, async_test_storage_type)

        result = await import_items(
            db,
            _csv(
                [
                    {
                        'Name': 'Glue',
                        'Storage': 'Review Shelf',
                        'Supplier': 'Acme',
                        'Opened': '2026-10-20',
                        'Colour': 'Blue',
                        'Fragile': 'yes',
                        'Depth': '12,5',
                    }
                ]
            ),
            'stock.csv',
            MAPPING,
            _ctx(async_test_user),
        )

        assert result['imported'] == 1, result
        assert await _metadata_of(db, 'Glue') == {
            'supplier': 'Acme',
            'opened_on': '2026-10-20',
            'colour': 'Blue',
            'fragile': True,
            'depth': '12.5',
        }

    async def test_a_location_without_the_field_does_not_take_its_column(
        self, real_async_db_session, async_test_user, async_test_storage_type
    ):
        db = real_async_db_session
        _, rack, _ = await _grow_a_tree(db, async_test_user, async_test_storage_type)
        await _location(db, async_test_user, async_test_storage_type, 'Loose Bin')

        result = await import_items(
            db,
            _csv(
                [
                    {'Name': 'Tape', 'Storage': 'Review Rack', 'Colour': 'Blue'},
                    {'Name': 'Nails', 'Storage': 'Loose Bin', 'Supplier': 'Acme'},
                ]
            ),
            'stock.csv',
            MAPPING,
            _ctx(async_test_user),
        )

        assert result['imported'] == 2, result
        # The shelf's own Colour is not the rack's; the bin sits outside the
        # warehouse and asks for nothing.
        assert 'colour' not in await _metadata_of(db, 'Tape')
        assert 'supplier' not in await _metadata_of(db, 'Nails')

    async def test_a_value_the_field_cannot_hold_refuses_the_row_by_column(
        self, real_async_db_session, async_test_user, async_test_storage_type
    ):
        db = real_async_db_session
        await _grow_a_tree(db, async_test_user, async_test_storage_type)

        result = await import_items(
            db,
            _csv(
                [
                    {'Name': 'Paint', 'Storage': 'Review Shelf', 'Colour': 'Green'},
                    {'Name': 'Brush', 'Storage': 'Review Shelf', 'Opened': 'soon'},
                    {'Name': 'Board', 'Storage': 'Review Shelf', 'Depth': 'deep'},
                ]
            ),
            'stock.csv',
            MAPPING,
            _ctx(async_test_user),
        )

        assert result['imported'] == 0, result
        messages = [e['error'] for e in result['errors']]
        assert 'Column "Colour"' in messages[0] and 'Green' in messages[0]
        assert messages[1] == 'Column "Opened": "soon" is not a date'
        assert messages[2] == 'Column "Depth": "deep" is not a number'

    async def test_an_overwrite_adds_the_fields_to_what_the_product_holds(
        self, real_async_db_session, async_test_user, async_test_storage_type
    ):
        db = real_async_db_session
        await _grow_a_tree(db, async_test_user, async_test_storage_type)
        await import_items(
            db,
            _csv([{'Name': 'Wax', 'Storage': 'Review Shelf', 'Colour': 'Red'}]),
            'stock.csv',
            MAPPING,
            _ctx(async_test_user),
        )
        item = (await db.execute(select(Item).where(Item.name == 'Wax'))).scalar_one()
        item.label_code = 'SHELF-07'
        await db.commit()

        result = await import_items(
            db,
            _csv([{'Name': 'Wax', 'Code': 'SHELF-07', 'Supplier': 'Acme'}]),
            'stock.csv',
            {**MAPPING, 'label_code': 'Code'},
            _ctx(async_test_user),
            on_label_match='overwrite',
        )

        assert result['updated'] == 1, result
        assert await _metadata_of(db, 'Wax') == {'colour': 'Red', 'supplier': 'Acme'}

    async def test_a_row_that_leaves_a_required_field_empty_is_refused(
        self, real_async_db_session, async_test_user, async_test_storage_type
    ):
        """The form refuses a product its location's required field leaves
        empty; the import used to skip the field and create it anyway."""
        db = real_async_db_session
        await _location(
            db,
            async_test_user,
            async_test_storage_type,
            'Strict Warehouse',
            fields=[
                {
                    'key': 'supplier',
                    'label': 'Supplier',
                    'type': 'text',
                    'required': True,
                }
            ],
        )

        result = await import_items(
            db,
            _csv(
                [
                    {
                        'Name': 'Glue',
                        'Storage': 'Strict Warehouse',
                        'Supplier': 'Acme',
                    },
                    {
                        'Name': 'Tape',
                        'Storage': 'Strict Warehouse',
                        'Supplier': '',
                    },
                ]
            ),
            'stock.csv',
            MAPPING,
            _ctx(async_test_user),
        )

        assert result['imported'] == 1, result
        assert [e['error'] for e in result['errors']] == [
            'Column "Supplier": the field is required'
        ]

    async def test_a_required_field_the_sheet_has_no_column_for_refuses_the_row(
        self, real_async_db_session, async_test_user, async_test_storage_type
    ):
        """A required field is required whether or not the sheet offers it."""
        db = real_async_db_session
        await _location(
            db,
            async_test_user,
            async_test_storage_type,
            'Strict Warehouse',
            fields=[
                {
                    'key': 'supplier',
                    'label': 'Supplier',
                    'type': 'text',
                    'required': True,
                }
            ],
        )

        result = await import_items(
            db,
            _csv([{'Name': 'Tape', 'Storage': 'Strict Warehouse'}]),
            'stock.csv',
            {'name': 'Name', 'location': 'Storage'},
            _ctx(async_test_user),
        )

        assert result['imported'] == 0, result
        assert [e['error'] for e in result['errors']] == [
            'Field "Supplier" is required and the sheet has no column for it'
        ]

    async def test_an_update_leaves_a_required_field_it_was_not_given(
        self, real_async_db_session, async_test_user, async_test_storage_type
    ):
        """An update writes the columns it has and leaves the rest as they
        stand — a half sheet is a half update, not a wipe the form would
        have refused row by row."""
        db = real_async_db_session
        await _location(
            db,
            async_test_user,
            async_test_storage_type,
            'Strict Warehouse',
            fields=[
                {
                    'key': 'supplier',
                    'label': 'Supplier',
                    'type': 'text',
                    'required': True,
                }
            ],
        )
        await import_items(
            db,
            _csv(
                [
                    {
                        'Name': 'Wax',
                        'Storage': 'Strict Warehouse',
                        'Supplier': 'Acme',
                    }
                ]
            ),
            'stock.csv',
            MAPPING,
            _ctx(async_test_user),
        )
        item = (await db.execute(select(Item).where(Item.name == 'Wax'))).scalar_one()
        item.label_code = 'STRICT-01'
        await db.commit()

        result = await import_items(
            db,
            _csv([{'Name': 'Wax', 'Code': 'STRICT-01', 'Supplier': ''}]),
            'stock.csv',
            {**MAPPING, 'label_code': 'Code'},
            _ctx(async_test_user),
            on_label_match='overwrite',
        )

        assert result['updated'] == 1, result
        assert await _metadata_of(db, 'Wax') == {'supplier': 'Acme'}

    async def test_a_required_field_the_form_hides_is_not_owed_by_a_row(
        self, real_async_db_session, async_test_user, async_test_storage_type
    ):
        """The form's own required check runs over visible and required
        together, so a field its definition hides is never asked of a
        product and no row can leave it empty. The hidden fields here stand
        on the warehouse above the shelf and on the shelf itself — the two
        ways a location carries a definition."""
        db = real_async_db_session
        warehouse = await _location(
            db,
            async_test_user,
            async_test_storage_type,
            'Hidden Warehouse',
            fields=[
                {
                    'key': 'hidden_supplier',
                    'label': 'Hidden Supplier',
                    'type': 'text',
                    'required': True,
                    'visible': False,
                }
            ],
        )
        await _location(
            db,
            async_test_user,
            async_test_storage_type,
            'Hidden Shelf',
            parent=warehouse,
            fields=[
                {
                    'key': 'hidden_colour',
                    'label': 'Hidden Colour',
                    'type': 'text',
                    'required': True,
                    'visible': False,
                }
            ],
        )

        result = await import_items(
            db,
            _csv([{'Name': 'Glue', 'Storage': 'Hidden Shelf'}]),
            'stock.csv',
            {'name': 'Name', 'location': 'Storage'},
            _ctx(async_test_user),
        )

        assert result['imported'] == 1, result
        assert await _metadata_of(db, 'Glue') == {}

    async def test_an_inherited_required_field_the_form_shows_is_still_owed(
        self, real_async_db_session, async_test_user, async_test_storage_type
    ):
        """What the form shows and requires is owed whether the location
        sets it or takes it from a level above — the eligibility runs over
        the effective definition, not the level it came from."""
        db = real_async_db_session
        warehouse = await _location(
            db,
            async_test_user,
            async_test_storage_type,
            'Strict Warehouse',
            fields=[
                {
                    'key': 'supplier',
                    'label': 'Supplier',
                    'type': 'text',
                    'required': True,
                }
            ],
        )
        await _location(
            db,
            async_test_user,
            async_test_storage_type,
            'Strict Shelf',
            parent=warehouse,
        )

        result = await import_items(
            db,
            _csv([{'Name': 'Tape', 'Storage': 'Strict Shelf'}]),
            'stock.csv',
            {'name': 'Name', 'location': 'Storage'},
            _ctx(async_test_user),
        )

        assert result['imported'] == 0, result
        assert [e['error'] for e in result['errors']] == [
            'Field "Supplier" is required and the sheet has no column for it'
        ]

    @pytest.mark.parametrize('kind', ['money', 'file'])
    async def test_a_required_field_a_cell_cannot_carry_refuses_the_row(
        self, real_async_db_session, async_test_user, async_test_storage_type, kind
    ):
        """A money or file field has no currency or upload a cell could give,
        so a sheet cannot fill one that is required and shown: the row is
        refused with a message that says why, whatever the sheet holds. The
        same field not required imports."""
        db = real_async_db_session
        await _location(
            db,
            async_test_user,
            async_test_storage_type,
            'Costed Shelf',
            fields=[{'key': 'paid', 'label': 'Paid', 'type': kind, 'required': True}],
        )
        await _location(
            db,
            async_test_user,
            async_test_storage_type,
            'Free Shelf',
            fields=[{'key': 'paid', 'label': 'Paid', 'type': kind}],
        )
        sheet = _csv(
            [
                {'Name': 'Costed', 'Storage': 'Costed Shelf', 'Paid': '12'},
                {'Name': 'Free', 'Storage': 'Free Shelf', 'Paid': '12'},
            ]
        )

        result = await import_items(
            db,
            sheet,
            'stock.csv',
            {'name': 'Name', 'location': 'Storage', 'field:paid': 'Paid'},
            _ctx(async_test_user),
        )

        assert result['imported'] == 1, result
        assert [e['error'] for e in result['errors']] == [
            'Field "Paid" is required and cannot be read from a cell'
        ]
        assert await _metadata_of(db, 'Free') == {}

    async def test_a_category_field_is_filled_from_its_own_column(
        self, real_async_db_session, async_test_user, async_test_storage_type
    ):
        """A category asks for fields of its own, a required one among them.

        Rows of that category were all refused with 'The field "Thread size"
        is required' because the mapping could name no column for it.
        """
        db = real_async_db_session
        await _location(db, async_test_user, async_test_storage_type, 'Plain Bin')
        db.add(
            Category(
                organization_id=async_test_user.organization_id,
                name='Fasteners',
                field_definitions=[
                    {
                        'key': 'thread_size',
                        'label': 'Thread size',
                        'type': 'text',
                        'required': True,
                    },
                    {
                        'key': 'finish',
                        'label': 'Finish',
                        'type': 'select',
                        'options': ['Zinc', 'Black'],
                    },
                ],
            )
        )
        await db.flush()
        mapping = {
            'name': 'Name',
            'location': 'Storage',
            'category': 'Category',
            'field:thread_size': 'Thread',
            'field:finish': 'Finish',
        }

        result = await import_items(
            db,
            _csv(
                [
                    {
                        'Name': 'Socket screw',
                        'Storage': 'Plain Bin',
                        'Category': 'Fasteners',
                        'Thread': 'M6',
                        'Finish': 'Zinc',
                    },
                    {
                        'Name': 'Washer',
                        'Storage': 'Plain Bin',
                        'Category': 'Fasteners',
                        'Thread': '',
                        'Finish': 'Zinc',
                    },
                    {
                        'Name': 'Glue',
                        'Storage': 'Plain Bin',
                        'Category': '',
                        'Thread': 'M8',
                        'Finish': '',
                    },
                ]
            ),
            'stock.csv',
            mapping,
            _ctx(async_test_user),
        )

        assert result['imported'] == 2, result
        assert await _metadata_of(db, 'Socket screw') == {
            'thread_size': 'M6',
            'finish': 'Zinc',
        }
        # Another category asks for none of it, so the column is not its own.
        assert 'thread_size' not in await _metadata_of(db, 'Glue')
        assert [e['error'] for e in result['errors']] == [
            'Column "Thread": the field is required'
        ]
