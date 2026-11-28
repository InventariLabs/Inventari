"""A product sheet exported from another tool moves in with what it carries.

Each shape below is the header row a tool writes, imported with the mapping
the dialog suggests for it (the frontend's ``importMapping`` test holds the
same pairs), so nothing is chosen by hand.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from io import BytesIO

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.core.location_path import join_location_path
from app.core.uom_resolver import UomResolverAsync
from app.models.category import Category
from app.models.item import Item
from app.models.product_template import ProductTemplate
from app.models.storage_location import LocationUsage, StorageLocation
from app.services.items._import import import_items

pytestmark = pytest.mark.integration


def _csv(rows: list[dict]) -> bytes:
    return pd.DataFrame(rows).to_csv(index=False).encode()


def _ctx(user) -> UserContextDTO:
    return UserContextDTO(
        id=user.id, organization_id=user.organization_id, role='admin'
    )


async def _import(
    db: AsyncSession, user, rows: list[dict], mapping: dict, **options
) -> dict:
    return await import_items(
        db, _csv(rows), 'export.csv', mapping, _ctx(user), **options
    )


async def _records(db: AsyncSession, user, name: str) -> list[Item]:
    rows = await db.execute(
        select(Item)
        .where(Item.organization_id == user.organization_id, Item.name == name)
        .order_by(Item.quantity)
    )
    return list(rows.scalars().all())


async def _products(db: AsyncSession, user) -> list[ProductTemplate]:
    rows = await db.execute(
        select(ProductTemplate)
        .where(ProductTemplate.organization_id == user.organization_id)
        .order_by(ProductTemplate.name, ProductTemplate.sku)
    )
    return list(rows.scalars().all())


async def _path(db: AsyncSession, location_id) -> str:
    names: list[str] = []
    current = await db.get(StorageLocation, location_id)
    while current is not None:
        names.append(current.name)
        current = (
            await db.get(StorageLocation, current.parent_id)
            if current.parent_id
            else None
        )
    return join_location_path(reversed(names))


async def _seen(db: AsyncSession, item: Item) -> dict:
    """What the import stored for one record, as the reader would name it."""
    await db.refresh(item, ['uom', 'category', 'template'])
    return {
        'quantity': item.quantity,
        'unit': item.uom.symbol,
        'location': await _path(db, item.storage_location_id),
        'category': item.category.name if item.category else None,
        'barcode': item.barcode or item.template.barcode,
        'price': item.purchase_price,
        'sku': item.template.sku,
        'description': item.description,
    }


class TestEachToolsShapeMovesIn:
    async def test_odoo_products(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ):
        db = real_async_db_session
        result = await _import(
            db,
            async_test_user,
            [
                {
                    'Name': 'Odoo Cheese',
                    'Internal Reference': 'CHE-001',
                    'Barcode': '5900000000017',
                    'Sales Price': '9.50',
                    'Cost': '4.20',
                    'Product Category': 'All / Saleable / Food',
                    'Unit of Measure': 'Units',
                    'Quantity On Hand': '12',
                }
            ],
            {
                'name': 'Name',
                'sku': 'Internal Reference',
                'barcode': 'Barcode',
                'purchase_price': 'Cost',
                'category': 'Product Category',
                'unit': 'Unit of Measure',
                'quantity': 'Quantity On Hand',
            },
        )

        assert result['failed'] == 0, result
        assert result['created_categories'] == ['Food']
        [item] = await _records(db, async_test_user, 'Odoo Cheese')
        seen = await _seen(db, item)
        assert seen['quantity'] == Decimal('12')
        assert seen['unit'] == 'pcs'
        assert seen['category'] == 'Food'
        assert seen['barcode'] == '5900000000017'
        assert seen['price'] == Decimal('4.20')
        assert seen['sku'] == 'CHE-001'

    async def test_odoo_stock_finds_the_product_by_its_reference(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ):
        db = real_async_db_session
        # The product export moves the catalogue in first: the stock sheet's
        # brackets name a reference only where a product already carries it.
        await _import(
            db,
            async_test_user,
            [
                {'Name': 'Odoo Gouda', 'Internal Reference': 'CHE-002'},
                {'Name': 'Odoo Brie', 'Internal Reference': 'CHE-003'},
            ],
            {'name': 'Name', 'sku': 'Internal Reference'},
        )
        result = await _import(
            db,
            async_test_user,
            [
                {
                    'Location': 'WH/Stock/Cold Room/Shelf 1',
                    'Product': '[CHE-002] Odoo Gouda renamed in Odoo',
                    'Product Category': 'All / Saleable / Food',
                    'Lot/Serial Number': '',
                    'Package': '',
                    'Owner': '',
                    'On Hand Quantity': '3',
                    'Reserved Quantity': '1',
                    'Unit of Measure': 'Unit(s)',
                },
                {
                    'Location': 'WH/Stock/Cold Room/Shelf 2',
                    'Product': '[CHE-003] Odoo Brie',
                    'Product Category': 'All / Saleable / Food',
                    'Lot/Serial Number': '',
                    'Package': '',
                    'Owner': '',
                    'On Hand Quantity': '5',
                    'Reserved Quantity': '0',
                    'Unit of Measure': 'Units',
                },
            ],
            {
                'location': 'Location',
                'name': 'Product',
                'category': 'Product Category',
                'quantity': 'On Hand Quantity',
                'unit': 'Unit of Measure',
            },
        )

        assert result['failed'] == 0, result
        assert [p.name for p in await _products(db, async_test_user)] == [
            'Odoo Brie',
            'Odoo Gouda',
        ]
        [gouda] = await _records(db, async_test_user, 'Odoo Gouda')
        assert (await _seen(db, gouda))['location'] == join_location_path(
            ['WH', 'Stock', 'Cold Room', 'Shelf 1']
        )
        [brie] = await _records(db, async_test_user, 'Odoo Brie')
        assert (await _seen(db, brie))['sku'] == 'CHE-003'

    async def test_sortly(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ):
        db = real_async_db_session
        result = await _import(
            db,
            async_test_user,
            [
                {
                    'Entry Name': 'Sortly Drill',
                    'Entry Type': 'Item',
                    'Folder Path': 'Workshop/Cabinet',
                    'Quantity': '2',
                    'Unit': 'each',
                    'Min Level': '1',
                    'Price': '199.00',
                    'Tags': 'tools',
                    'Notes': 'Blue case',
                    'Barcode/QR-1': '5900000000024',
                }
            ],
            {
                'name': 'Entry Name',
                'location': 'Folder Path',
                'quantity': 'Quantity',
                'unit': 'Unit',
                'min_quantity': 'Min Level',
                'purchase_price': 'Price',
                'description': 'Notes',
                'barcode': 'Barcode/QR-1',
            },
        )

        assert result['failed'] == 0, result
        [item] = await _records(db, async_test_user, 'Sortly Drill')
        seen = await _seen(db, item)
        assert seen['quantity'] == Decimal('2')
        assert seen['location'] == join_location_path(['Workshop', 'Cabinet'])
        assert seen['price'] == Decimal('199')
        assert seen['barcode'] == '5900000000024'
        assert seen['description'] == 'Blue case'
        assert item.template.min_quantity == 1

    async def test_inflow_stock_levels(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ):
        db = real_async_db_session
        expires = (date.today() + timedelta(days=400)).isoformat()
        mapping = {
            'name': 'ProductName',
            'sku': 'SKU',
            'location': 'Location',
            'sublocation': 'Sublocation',
            'quantity': 'Quantity',
            'serial_number': 'Serial',
            'expiry_date': 'ExpiryDate',
        }
        row = {
            'ProductName': 'inFlow Yoghurt',
            'SKU': 'yog-1',
            'Location': 'Main',
            'Sublocation': 'Aisle 2/Bin 4',
            'Quantity': '6',
            'Serial': '',
            'LotNumber': 'L1',
            'ExpiryDate': expires,
        }
        result = await _import(
            db,
            async_test_user,
            [row, {**row, 'Sublocation': 'Aisle 3', 'Quantity': '9'}],
            mapping,
        )

        assert result['failed'] == 0, result
        assert len(await _products(db, async_test_user)) == 1
        first, second = await _records(db, async_test_user, 'inFlow Yoghurt')
        assert (await _seen(db, first))['location'] == join_location_path(
            ['Main', 'Aisle 2', 'Bin 4']
        )
        assert (await _seen(db, second))['location'] == join_location_path(
            ['Main', 'Aisle 3']
        )
        assert first.template.sku == 'YOG-1'
        assert str(first.expiry_date) == expires

    async def test_zoho_items(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ):
        db = real_async_db_session
        result = await _import(
            db,
            async_test_user,
            [
                {
                    'Item Name': 'Zoho Paint',
                    'SKU': 'PNT-1',
                    'EAN': '5900000000031',
                    'Description': 'White, matt',
                    'Usage unit': 'pc',
                    'Rate': '30',
                    'Purchase Rate': '18.50',
                    'Reorder Level': '4',
                    'Category Name': 'Paints',
                    'Warehouse Name': 'North',
                    'Stock On Hand': '8',
                }
            ],
            {
                'name': 'Item Name',
                'sku': 'SKU',
                'barcode': 'EAN',
                'description': 'Description',
                'unit': 'Usage unit',
                'purchase_price': 'Purchase Rate',
                'min_quantity': 'Reorder Level',
                'category': 'Category Name',
                'location': 'Warehouse Name',
                'quantity': 'Stock On Hand',
            },
        )

        assert result['failed'] == 0, result
        [item] = await _records(db, async_test_user, 'Zoho Paint')
        seen = await _seen(db, item)
        assert seen == {
            'quantity': Decimal('8'),
            'unit': 'pcs',
            'location': 'North',
            'category': 'Paints',
            'barcode': '5900000000031',
            'price': Decimal('18.50'),
            'sku': 'PNT-1',
            'description': 'White, matt',
        }
        assert item.template.min_quantity == 4

    async def test_boxhero_quantity_columns_name_the_location(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ):
        db = real_async_db_session
        result = await _import(
            db,
            async_test_user,
            [
                {
                    'SKU': 'BOX-1',
                    'Item Name': 'BoxHero Tape',
                    'Barcode': '5900000000048',
                    'Cost': '2',
                    'Price': '5',
                    'Brand': 'Acme',
                    'Category': 'Packing',
                    'Qty(Warehouse)': '7',
                    'Qty(Shop)': '3',
                },
                {
                    'SKU': 'BOX-2',
                    'Item Name': 'BoxHero Glue',
                    'Barcode': '',
                    'Cost': '1',
                    'Price': '2',
                    'Brand': '',
                    'Category': 'Packing',
                    'Qty(Warehouse)': '0',
                    'Qty(Shop)': '',
                },
            ],
            {
                'sku': 'SKU',
                'name': 'Item Name',
                'barcode': 'Barcode',
                'purchase_price': 'Cost',
                'brand': 'Brand',
                'category': 'Category',
                'stock_at:Warehouse': 'Qty(Warehouse)',
                'stock_at:Shop': 'Qty(Shop)',
            },
        )

        assert result['failed'] == 0, result
        shop, warehouse = await _records(db, async_test_user, 'BoxHero Tape')
        assert (await _seen(db, shop))['location'] == 'Shop'
        assert (await _seen(db, warehouse))['location'] == 'Warehouse'
        assert (shop.quantity, warehouse.quantity) == (3, 7)
        assert shop.template_id == warehouse.template_id
        assert warehouse.purchase_price == Decimal('2')
        # A product with nothing on any shelf is a product without stock.
        assert await _records(db, async_test_user, 'BoxHero Glue') == []
        assert [p.sku for p in await _products(db, async_test_user)] == [
            'BOX-2',
            'BOX-1',
        ]
        # Two records of one new product and one product without stock.
        assert result['imported'] - result['joined_existing'] == 2
        assert result['total'] == result['imported'] == 3

    async def test_homebox(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ):
        db = real_async_db_session
        result = await _import(
            db,
            async_test_user,
            [
                {
                    'HB.name': 'Homebox Saw',
                    'HB.description': 'Hand saw',
                    'HB.notes': 'Bought used',
                    'HB.location': 'Garage / Workbench / Drawer 2',
                    'HB.tags': 'wood; tools',
                    'HB.quantity': '1',
                    'HB.manufacturer': 'Bahco',
                    'HB.serial_number': 'SN-77',
                    'HB.purchase_price': '45',
                    'HB.purchase_date': '2025-05-01',
                    'HB.warranty_expires': (
                        date.today() + timedelta(days=700)
                    ).isoformat(),
                }
            ],
            {
                'name': 'HB.name',
                'description': 'HB.description',
                'location': 'HB.location',
                'quantity': 'HB.quantity',
                'brand': 'HB.manufacturer',
                'serial_number': 'HB.serial_number',
                'purchase_price': 'HB.purchase_price',
            },
        )

        assert result['failed'] == 0, result
        [item] = await _records(db, async_test_user, 'Homebox Saw')
        seen = await _seen(db, item)
        assert seen['location'] == join_location_path(
            ['Garage', 'Workbench', 'Drawer 2']
        )
        assert seen['description'] == 'Hand saw'
        assert seen['price'] == Decimal('45')
        assert (item.brand, item.serial_number) == ('Bahco', 'SN-77')


class TestAFileThatNamesNoShelf:
    async def test_its_stock_lands_on_a_real_shelf_not_a_virtual_place(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ):
        """A sheet that names no location has nowhere of its own, and the
        places the app seeds first mean something else: the stock must not
        arrive already consumed, where the products list cannot show it."""
        db = real_async_db_session
        db.add(
            StorageLocation(
                name='Consumed (Virtual)',
                organization_id=async_test_user.organization_id,
                created_by=async_test_user.id,
                usage=LocationUsage.CUSTOMER,
                created_at=datetime.now(UTC) - timedelta(days=1),
            )
        )
        await db.flush()

        result = await _import(
            db,
            async_test_user,
            [{'Item Name': 'Tinned Beans', 'Stock On Hand': '3'}],
            {'name': 'Item Name', 'quantity': 'Stock On Hand'},
        )

        assert result['failed'] == 0, result
        [item] = await _records(db, async_test_user, 'Tinned Beans')
        assert item.storage_location_id == async_test_storage_location.id


class TestAListWithoutQuantities:
    async def test_it_adds_products_and_nothing_to_a_shelf(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ):
        db = real_async_db_session
        rows = [
            {
                'Name': 'Katana Flour',
                'SKU': 'FL-1',
                'Place': 'Mill',
                'Category': 'Raw',
                'UoM': 'kg',
                'Min': '5',
            }
        ]
        mapping = {
            'name': 'Name',
            'sku': 'SKU',
            'location': 'Place',
            'category': 'Category',
            'unit': 'UoM',
            'min_quantity': 'Min',
        }

        result = await _import(db, async_test_user, rows, mapping)
        again = await _import(db, async_test_user, rows, mapping)

        assert (result['imported'], result['failed']) == (1, 0), result
        assert (again['imported'], again['skipped']) == (0, 1), again
        assert result['created_locations'] == result['created_categories'] == []
        assert await _records(db, async_test_user, 'Katana Flour') == []
        [product] = await _products(db, async_test_user)
        await db.refresh(product, ['uom'])
        assert (product.sku, product.uom.symbol, product.min_quantity) == (
            'FL-1',
            'kg',
            5,
        )

    async def test_stock_loaded_later_joins_the_product_by_its_sku(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ):
        db = real_async_db_session
        await _import(
            db,
            async_test_user,
            [{'Name': 'Washer M6', 'SKU': 'WSH-6', 'Barcode': '5900000000055'}],
            {'name': 'Name', 'sku': 'SKU', 'barcode': 'Barcode'},
        )
        result = await _import(
            db,
            async_test_user,
            [{'Name': 'Washer, M6', 'SKU': 'wsh-6', 'Quantity': '40'}],
            {'name': 'Name', 'sku': 'SKU', 'quantity': 'Quantity'},
        )

        assert (result['imported'], result['joined_existing']) == (1, 1), result
        [item] = await _records(db, async_test_user, 'Washer M6')
        assert item.quantity == 40
        assert len(await _products(db, async_test_user)) == 1

    async def test_the_reader_may_ask_for_one_of_each(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ):
        db = real_async_db_session
        result = await _import(
            db,
            async_test_user,
            [{'Name': 'Ladder'}],
            {'name': 'Name'},
            count_as_one=True,
        )

        assert result['imported'] == 1, result
        [item] = await _records(db, async_test_user, 'Ladder')
        assert item.quantity == 1


class TestVariantsShareANameNotACode:
    async def test_two_codes_under_one_name_are_two_products(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ):
        db = real_async_db_session
        result = await _import(
            db,
            async_test_user,
            [
                {'Name': 'T-shirt', 'SKU': 'TS-S', 'Quantity': '1'},
                {'Name': 'T-shirt', 'SKU': 'TS-M', 'Quantity': '2'},
            ],
            {'name': 'Name', 'sku': 'SKU', 'quantity': 'Quantity'},
        )

        assert result['failed'] == 0, result
        assert [p.sku for p in await _products(db, async_test_user)] == [
            'TS-M',
            'TS-S',
        ]
        small, medium = await _records(db, async_test_user, 'T-shirt')
        assert (small.template.sku, medium.template.sku) == ('TS-S', 'TS-M')


class TestSlashesInALocation:
    MAPPING = {'name': 'Name', 'quantity': 'Quantity', 'location': 'Location'}

    async def test_read_as_part_of_the_name_when_the_reader_says_so(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ):
        db = real_async_db_session
        result = await _import(
            db,
            async_test_user,
            [{'Name': 'Peas', 'Quantity': '1', 'Location': 'Fridge/Freezer'}],
            self.MAPPING,
            location_slash='name',
        )

        assert result['created_locations'] == ['Fridge/Freezer'], result

    async def test_a_place_already_named_with_a_slash_is_found_as_itself(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ):
        db = real_async_db_session
        rows = [{'Name': 'Peas', 'Quantity': '1', 'Location': 'Fridge/Freezer'}]
        await _import(db, async_test_user, rows, self.MAPPING, location_slash='name')

        result = await _import(db, async_test_user, rows, self.MAPPING)

        assert result['created_locations'] == [], result

    async def test_a_path_written_the_apps_way_keeps_a_slash_in_a_name(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ):
        db = real_async_db_session
        result = await _import(
            db,
            async_test_user,
            [{'Name': 'Peas', 'Quantity': '1', 'Location': 'Kitchen > A/B'}],
            self.MAPPING,
        )

        assert result['created_locations'] == [
            'Kitchen',
            join_location_path(['Kitchen', 'A/B']),
        ], result


class TestACategoryPath:
    async def test_a_category_already_named_with_the_whole_text_wins(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ):
        db = real_async_db_session
        db.add(
            Category(
                name='Meat / Fish', organization_id=async_test_user.organization_id
            )
        )
        await db.flush()

        result = await _import(
            db,
            async_test_user,
            [{'Name': 'Cod', 'Quantity': '1', 'Category': 'Meat / Fish'}],
            {'name': 'Name', 'quantity': 'Quantity', 'category': 'Category'},
        )

        assert result['created_categories'] == [], result
        [item] = await _records(db, async_test_user, 'Cod')
        await db.refresh(item, ['category'])
        assert item.category.name == 'Meat / Fish'


class TestUnitsByTheirOtherNames:
    @pytest.mark.parametrize(
        ('written', 'symbol'),
        [
            ('Units', 'pcs'),
            ('unit', 'pcs'),
            ('Unit(s)', 'pcs'),
            ('ea', 'pcs'),
            ('EA.', 'pcs'),
            ('each', 'pcs'),
            ('pc', 'pcs'),
            ('Stk', 'pcs'),
            # The label the app shows, in each maintained language, whatever
            # language the importer reads.
            ('szt.', 'pcs'),
            ('Packung', 'pack'),
            ('caja', 'box'),
            ('garrafa', 'bottle'),
            ('bouteille', 'bottle'),
            ('Beutel', 'bag'),
        ],
    )
    async def test_the_word_names_the_unit(
        self, real_async_db_session, async_test_user, written, symbol
    ):
        resolver = UomResolverAsync(
            real_async_db_session, async_test_user.organization_id
        )

        found = await resolver.resolve(written)

        expected = await resolver.resolve(symbol)
        assert expected is not None
        assert found == expected, written


class TestABracketedNameIsAReferenceOnlyWhenItNamesOne:
    async def test_a_bracket_holding_words_is_the_products_own_name(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ):
        db = real_async_db_session
        result = await _import(
            db,
            async_test_user,
            [{'Name': '[2 pcs] Rv AA Batteries', 'Quantity': '3'}],
            {'name': 'Name', 'quantity': 'Quantity'},
        )

        assert (result['imported'], result['failed']) == (1, 0), result
        [product] = await _products(db, async_test_user)
        assert (product.name, product.sku) == ('[2 pcs] Rv AA Batteries', None)
        [item] = await _records(db, async_test_user, '[2 pcs] Rv AA Batteries')
        assert item.quantity == Decimal('3')

    async def test_a_bracket_holding_a_code_shaped_word_is_a_name_too(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ):
        db = real_async_db_session
        result = await _import(
            db,
            async_test_user,
            [{'Name': '[A4] Rv Paper', 'Quantity': '2'}],
            {'name': 'Name', 'quantity': 'Quantity'},
        )

        assert (result['imported'], result['failed']) == (1, 0), result
        [product] = await _products(db, async_test_user)
        assert (product.name, product.sku) == ('[A4] Rv Paper', None)

    async def test_a_bracket_naming_a_products_code_is_read_as_its_reference(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ):
        """The Odoo reading stays where it can be seen: the product carries the code."""
        db = real_async_db_session
        await _import(
            db,
            async_test_user,
            [{'Name': 'Odoo Gouda', 'Internal Reference': 'CHE-002'}],
            {'name': 'Name', 'sku': 'Internal Reference'},
        )
        result = await _import(
            db,
            async_test_user,
            [{'Name': '[CHE-002] Gouda renamed in Odoo', 'Quantity': '3'}],
            {'name': 'Name', 'quantity': 'Quantity'},
        )

        assert (result['imported'], result['failed']) == (1, 0), result
        [product] = await _products(db, async_test_user)
        assert (product.name, product.sku) == ('Odoo Gouda', 'CHE-002')
        [item] = await _records(db, async_test_user, 'Odoo Gouda')
        assert item.quantity == Decimal('3')


class TestASkuFromASheet:
    MAPPING = {'name': 'Name', 'sku': 'Ref', 'quantity': 'Quantity'}

    @pytest.mark.parametrize('code', ['LAMP.01', 'LAMP 01'])
    async def test_a_code_the_form_cannot_hold_refuses_the_row_by_name(
        self,
        real_async_db_session,
        async_test_user,
        async_test_storage_location,
        code,
    ):
        db = real_async_db_session
        row = (
            {'Name': code, 'Ref': '', 'Quantity': '1'}
            if code.startswith('[')
            else {'Name': 'Lamp', 'Ref': code, 'Quantity': '1'}
        )

        result = await _import(db, async_test_user, [row], self.MAPPING)

        assert (result['imported'], result['failed']) == (0, 1), result
        reason = result['errors'][0]['error']
        assert code.strip('[').split(']')[0] in reason
        assert 'SKU may contain only' in reason
        assert await _products(db, async_test_user) == []

    async def test_it_is_stored_trimmed_and_upper_case(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ):
        db = real_async_db_session
        await _import(
            db,
            async_test_user,
            [{'Name': 'Lamp', 'Ref': '  lamp-01 ', 'Quantity': '1'}],
            self.MAPPING,
        )

        [product] = await _products(db, async_test_user)
        assert product.sku == 'LAMP-01'


class TestTheAppsOwnExportComesBack:
    def test_sku_description_and_stock_alert_round_trip(
        self,
        client: TestClient,
        auth_headers: dict,
        test_storage_location,
    ):
        created = client.post(
            '/api/v1/items',
            json={
                'name': 'Round trip vise',
                'location_id': str(test_storage_location.id),
                'quantity': 2,
                'sku': 'VISE-1',
                'description': 'Bench vise',
                'min_quantity': 3,
            },
            headers=auth_headers,
        )
        assert created.status_code == 201, created.text
        sheet = client.get('/api/v1/items/export/xlsx', headers=auth_headers)
        book = pd.read_excel(BytesIO(sheet.content), sheet_name=None)
        readme = list(book.values())[1].set_index('Column')['On import']
        for column in ('SKU', 'Stock alert', 'Description'):
            assert readme[column] == 'read', column
        [row] = list(book.values())[0].to_dict(orient='records')
        row['Name'] = 'Round trip vise copy'
        row['SKU'] = 'VISE-2'

        response = client.post(
            '/api/v1/items/import',
            files={'file': ('back.csv', _csv([row]), 'text/csv')},
            data={
                'mapping_json': json.dumps(
                    {
                        'name': 'Name',
                        'quantity': 'Quantity',
                        'sku': 'SKU',
                        'min_quantity': 'Stock alert',
                        'description': 'Description',
                    }
                )
            },
            headers=auth_headers,
        )

        assert response.json()['imported'] == 1, response.text
        items = client.get(
            '/api/v1/items?search=Round trip vise copy', headers=auth_headers
        ).json()['items']
        [copy] = items
        assert copy['description'] == 'Bench vise'
        assert copy['template']['sku'] == 'VISE-2'
        assert copy['template']['min_quantity'] == 3

    def test_a_list_without_quantities_over_the_api(
        self, client: TestClient, auth_headers: dict, test_storage_location
    ):
        def _post(**form):
            return client.post(
                '/api/v1/items/import',
                files={'file': ('list.csv', _csv([{'Name': 'Bare'}]), 'text/csv')},
                data={'mapping_json': json.dumps({'name': 'Name'}), **form},
                headers=auth_headers,
            )

        def _records_named():
            return client.get('/api/v1/items?search=Bare', headers=auth_headers).json()[
                'items'
            ]

        assert _post().json()['imported'] == 1
        assert _records_named() == []
        assert _post(count_as_one='true').json()['imported'] == 1
        assert len(_records_named()) == 1
