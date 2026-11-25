"""Grocy's database file reads the way Grocy wrote it.

Grocy writes no export, so a move from it reads ``data/grocy.db``. The
reader turns the file into plain rows — every batch of stock with its own
date, price and shelf; the products with all their barcodes; the places,
groups, stores and units by id — and counts what a move leaves behind. It
is built here on Grocy's own schema (``tests/fixtures/grocy_schema.sql``).
"""

import sqlite3
from datetime import date
from decimal import Decimal

import pytest

from app.core.exceptions import ServiceRejectionError
from app.core.grocy_file import read_grocy_file
from tests.integration._grocy import GrocyDb

pytestmark = pytest.mark.unit


def _pantry() -> tuple[GrocyDb, dict[str, int]]:
    g = GrocyDb()
    ids = {
        'pantry': g.location('Pantry'),
        'freezer': g.location('Freezer', is_freezer=True),
        'sweets': g.group('01 Sweets'),
        'shop': g.store('Corner shop'),
        'piece': g.unit('Piece', 'Pieces'),
        'pack': g.unit('Pack', 'Packs'),
    }
    ids['cookies'] = g.product(
        'Cookies',
        location=ids['pantry'],
        unit=ids['piece'],
        purchase_unit=ids['pack'],
        group=ids['sweets'],
        store=ids['shop'],
        description='Chocolate chip',
        min_stock=4,
    )
    g.barcode(ids['cookies'], '5901234123457')
    g.barcode(ids['cookies'], '5901234123464')
    g.conversion(ids['cookies'], ids['pack'], ids['piece'], 6)
    g.stock(
        ids['cookies'],
        3,
        best_before='2027-03-05',
        purchased='2026-11-02',
        price=1.25,
        location=ids['pantry'],
        store=ids['shop'],
        note='top shelf',
        stock_id='5ccc6b2421979',
    )
    g.stock(
        ids['cookies'],
        0.5,
        location=ids['freezer'],
        opened='2026-11-20 08:15:00',
    )
    return g, ids


class TestTheRowsAMoveNeeds:
    def test_every_batch_keeps_its_own_amount_dates_price_and_shelf(self) -> None:
        g, ids = _pantry()

        grocy = read_grocy_file(g.content())

        first, second = grocy.stock
        assert first.product_id == ids['cookies']
        assert first.amount == Decimal('3')
        assert first.best_before == date(2027, 3, 5)
        assert first.purchased == date(2026, 11, 2)
        assert first.price == Decimal('1.25')
        assert first.location_id == ids['pantry']
        assert first.store_id == ids['shop']
        assert first.note == 'top shelf'
        assert first.stock_id == '5ccc6b2421979'
        assert first.opened is None
        # Grocy writes 2999-12-31 for "never goes off": no date at all.
        assert second.best_before is None
        assert second.amount == Decimal('0.5')
        assert second.opened == date(2026, 11, 20)

    def test_a_product_carries_every_barcode_in_the_order_grocy_added_them(
        self,
    ) -> None:
        g, ids = _pantry()

        product = read_grocy_file(g.content()).products[ids['cookies']]

        assert product.name == 'Cookies'
        assert product.description == 'Chocolate chip'
        assert product.barcodes == ('5901234123457', '5901234123464')
        assert product.min_stock == Decimal('4')
        assert product.unit_id == ids['piece']
        assert product.group_id == ids['sweets']
        assert product.location_id == ids['pantry']
        assert product.store_id == ids['shop']
        assert product.active is True

    def test_places_groups_stores_and_units_read_by_id(self) -> None:
        g, ids = _pantry()

        grocy = read_grocy_file(g.content())

        assert grocy.locations[ids['freezer']].name == 'Freezer'
        assert grocy.locations[ids['freezer']].is_freezer is True
        assert grocy.locations[ids['pantry']].is_freezer is False
        assert grocy.groups[ids['sweets']].name == '01 Sweets'
        assert grocy.stores[ids['shop']].name == 'Corner shop'
        assert grocy.units[ids['pack']].name == 'Pack'
        assert grocy.units[ids['pack']].plural == 'Packs'

    def test_an_inactive_row_reads_as_inactive(self) -> None:
        g, ids = _pantry()
        g.product('Old jam', location=ids['pantry'], unit=ids['piece'], active=False)
        g.location('Cellar', active=False)

        grocy = read_grocy_file(g.content())

        assert [p.name for p in grocy.products.values() if not p.active] == ['Old jam']
        assert [loc.name for loc in grocy.locations.values() if not loc.active] == [
            'Cellar'
        ]

    def test_shopping_list_entries_keep_their_list_and_product(self) -> None:
        g, ids = _pantry()
        weekly = g.shopping_list('Weekly')
        g.shopping_item(
            product=ids['cookies'], amount=2, unit=ids['pack'], list_id=weekly
        )
        g.shopping_item(note='Birthday candles', done=True)

        entries = read_grocy_file(g.content()).shopping_list

        assert [
            (e.list_name, e.product_id, e.amount, e.unit_id, e.note, e.done)
            for e in entries
        ] == [
            ('Weekly', ids['cookies'], Decimal('2'), ids['pack'], None, False),
            ('Default', None, Decimal('1'), None, 'Birthday candles', True),
        ]


class TestWhatAMoveLeavesBehind:
    def test_the_file_counts_what_has_no_place_in_a_product_import(self) -> None:
        g, ids = _pantry()
        g.product(
            'Biscuit crumbs',
            location=ids['pantry'],
            unit=ids['piece'],
            picture='crumbs.jpg',
            parent=ids['cookies'],
            default_days=30,
        )
        cake = g.recipe('Cheesecake')
        g.recipe('2026-47', kind='mealplan-week')
        g.meal('2026-11-26', cake)
        g.chore('Vacuum')
        g.battery('Smoke alarm')
        g.task('Defrost the freezer')
        g.equipment('Dishwasher')
        g.own_field('products', 'origin', ids['cookies'], 'Belgium')

        left = read_grocy_file(g.content()).left_behind

        assert left == {
            'unit_conversions': 1,
            'own_field_values': 1,
            'recipes': 1,
            'meal_plan': 1,
            'chores': 1,
            'batteries': 1,
            'tasks': 1,
            'equipment': 1,
        }


class TestAFileThatIsNotGrocys:
    def test_bytes_that_are_not_sqlite_are_refused(self) -> None:
        with pytest.raises(ServiceRejectionError) as exc:
            read_grocy_file(b'name,amount\nCookies,3\n')

        assert exc.value.key == 'grocy_file_unreadable'

    def test_a_sqlite_file_without_grocys_tables_is_refused(self) -> None:
        con = sqlite3.connect(':memory:')
        con.execute('CREATE TABLE notes (id INTEGER PRIMARY KEY, body TEXT)')

        with pytest.raises(ServiceRejectionError) as exc:
            read_grocy_file(con.serialize())

        assert exc.value.key == 'grocy_file_not_grocy'

    def test_an_older_grocy_without_the_active_column_reads_every_row_as_active(
        self,
    ) -> None:
        con = sqlite3.connect(':memory:')
        con.executescript(
            """
            CREATE TABLE locations (id INTEGER PRIMARY KEY, name TEXT, description TEXT);
            CREATE TABLE quantity_units (id INTEGER PRIMARY KEY, name TEXT, description TEXT);
            CREATE TABLE products (id INTEGER PRIMARY KEY, name TEXT, description TEXT,
                location_id INTEGER, qu_id_purchase INTEGER, qu_id_stock INTEGER,
                min_stock_amount INTEGER, barcode TEXT);
            CREATE TABLE stock (id INTEGER PRIMARY KEY, product_id INTEGER, amount DECIMAL,
                best_before_date DATE, purchased_date DATE, stock_id TEXT, price DECIMAL);
            INSERT INTO locations VALUES (1, 'Pantry', NULL);
            INSERT INTO quantity_units VALUES (1, 'Piece', NULL);
            INSERT INTO products VALUES (1, 'Tea', NULL, 1, 1, 1, 0, '4001234567890');
            INSERT INTO stock VALUES (1, 1, 2, '2027-01-01', NULL, 'abc', NULL);
            """
        )

        grocy = read_grocy_file(con.serialize())

        tea = grocy.products[1]
        assert tea.active is True
        # Before product_barcodes, a product carried one barcode of its own.
        assert tea.barcodes == ('4001234567890',)
        assert grocy.locations[1].active is True
        assert grocy.stock[0].location_id is None
        assert grocy.shopping_list == []
