"""Reading Grocy's own database file.

Grocy (grocy.info) keeps everything it knows in one SQLite file,
``data/grocy.db``, and writes no export of its own — no CSV, no spreadsheet —
so a move from Grocy reads that file. This module turns its bytes into plain
rows: the tables a move needs, by id, and the count of each kind of record a
move leaves behind. Where the rows go is the importers' business — the
product import here in the core, the shopping lists in their module.

The file comes from outside, so it is opened in memory and read in SQLite's
defensive mode with ``trusted_schema`` off and ``query_only`` on: no view or
trigger in it runs a function, nothing is written, and only tables — never
views of the same name — are read, by a plain ``SELECT`` of named columns.
Columns are read where they exist: a Grocy of a few years ago lacks
``active`` and the later columns, and its rows read as active, with nothing
in what is missing.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from app.core.exceptions import ServiceRejectionError
from app.core.upload_validation import MAX_IMPORT_ROWS

#: The first sixteen bytes of every SQLite database file.
_SQLITE_HEADER = b'SQLite format 3\x00'

#: Grocy's spelling of "this never goes off".
_NEVER = date(2999, 12, 31)

#: The tables without which a file is not a Grocy database.
_REQUIRED = ('products', 'stock', 'locations', 'quantity_units')

#: Every table read, with the one statement that reads it. The statements are
#: written out rather than built from names, so nothing the file says ever
#: becomes part of one.
_SELECT: dict[str, str] = {
    'locations': 'SELECT * FROM "locations" ORDER BY "id"',
    'product_groups': 'SELECT * FROM "product_groups" ORDER BY "id"',
    'shopping_locations': 'SELECT * FROM "shopping_locations" ORDER BY "id"',
    'quantity_units': 'SELECT * FROM "quantity_units" ORDER BY "id"',
    'products': 'SELECT * FROM "products" ORDER BY "id"',
    'product_barcodes': 'SELECT * FROM "product_barcodes" ORDER BY "id"',
    'stock': 'SELECT * FROM "stock" ORDER BY "id"',
    'shopping_lists': 'SELECT * FROM "shopping_lists" ORDER BY "id"',
    'shopping_list': 'SELECT * FROM "shopping_list" ORDER BY "id"',
}

#: What a move leaves behind, by kind: the table that holds it and the
#: statement that counts it. A conversion Grocy keeps for one product (a pack
#: of six) counts, not the general ones every unit table knows; a recipe a
#: person wrote counts, not the shadow recipes Grocy keeps for its meal plan
#: (a Grocy older than the ``type`` column has none, and counts every row).
_LEFT_BEHIND: dict[str, tuple[str, tuple[str, ...]]] = {
    'unit_conversions': (
        'quantity_unit_conversions',
        (
            'SELECT count(*) FROM "quantity_unit_conversions" WHERE "product_id" IS NOT NULL',
        ),
    ),
    'own_field_values': (
        'userfield_values',
        ('SELECT count(*) FROM "userfield_values"',),
    ),
    'recipes': (
        'recipes',
        (
            'SELECT count(*) FROM "recipes" WHERE coalesce("type", \'normal\') = \'normal\'',
            'SELECT count(*) FROM "recipes"',
        ),
    ),
    'meal_plan': ('meal_plan', ('SELECT count(*) FROM "meal_plan"',)),
    'chores': ('chores', ('SELECT count(*) FROM "chores"',)),
    'batteries': ('batteries', ('SELECT count(*) FROM "batteries"',)),
    'tasks': ('tasks', ('SELECT count(*) FROM "tasks"',)),
    'equipment': ('equipment', ('SELECT count(*) FROM "equipment"',)),
}

_COUNT_ROWS = {
    'products': 'SELECT count(*) FROM "products"',
    'stock': 'SELECT count(*) FROM "stock"',
}


@dataclass(frozen=True)
class GrocyNamed:
    """A place, product group, store or unit: Grocy's named lists."""

    id: int
    name: str
    description: str | None
    active: bool
    is_freezer: bool = False
    plural: str | None = None


@dataclass(frozen=True)
class GrocyProduct:
    id: int
    name: str
    description: str | None
    active: bool
    group_id: int | None
    location_id: int | None
    store_id: int | None
    #: The unit Grocy counts the product's stock in; every stock amount is in it.
    unit_id: int | None
    min_stock: Decimal
    #: In the order they were added; the first is the one a scan finds first.
    barcodes: tuple[str, ...]
    has_picture: bool
    has_parent: bool
    has_default_days: bool


@dataclass(frozen=True)
class GrocyStockEntry:
    """One batch: Grocy keeps a row per purchase, each with its own date."""

    id: int
    product_id: int
    amount: Decimal
    best_before: date | None
    purchased: date | None
    price: Decimal | None
    location_id: int | None
    store_id: int | None
    is_open: bool
    opened: date | None
    note: str | None
    stock_id: str


@dataclass(frozen=True)
class GrocyShoppingListEntry:
    id: int
    list_id: int
    list_name: str
    product_id: int | None
    note: str | None
    amount: Decimal
    unit_id: int | None
    done: bool


@dataclass(frozen=True)
class GrocyFile:
    locations: dict[int, GrocyNamed]
    groups: dict[int, GrocyNamed]
    stores: dict[int, GrocyNamed]
    units: dict[int, GrocyNamed]
    products: dict[int, GrocyProduct]
    stock: list[GrocyStockEntry]
    shopping_list: list[GrocyShoppingListEntry]
    #: Records a move has no place for, by kind (``_LEFT_BEHIND``).
    left_behind: dict[str, int]


def read_grocy_file(content: bytes) -> GrocyFile:
    """The rows of a Grocy database file; refuses a file that is not one."""
    if not content.startswith(_SQLITE_HEADER):
        raise ServiceRejectionError('grocy_file_unreadable')
    con = _open(content)
    try:
        return _read(con)
    except sqlite3.DatabaseError as exc:
        raise ServiceRejectionError('grocy_file_unreadable') from exc
    finally:
        con.close()


def _open(content: bytes) -> sqlite3.Connection:
    con = sqlite3.connect(':memory:')
    con.setconfig(sqlite3.SQLITE_DBCONFIG_DEFENSIVE, True)
    con.execute('PRAGMA trusted_schema = OFF')
    try:
        con.deserialize(content)
        con.execute('PRAGMA query_only = ON')
    except sqlite3.DatabaseError as exc:
        con.close()
        raise ServiceRejectionError('grocy_file_unreadable') from exc
    return con


class _Tables:
    """The file's tables, and their rows by the statements above."""

    def __init__(self, con: sqlite3.Connection) -> None:
        self.con = con
        self.names = {
            row[0]
            for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }

    def columns(self, table: str) -> set[str]:
        return {
            row[0]
            for row in self.con.execute(
                'SELECT name FROM pragma_table_info(?)', (table,)
            )
        }

    def rows(self, table: str, wanted: Iterable[str]) -> list[dict[str, Any]]:
        """Every row of *table* by id, as the *wanted* columns.

        A column the table lacks reads as ``None`` in every row.
        """
        if table not in self.names:
            return []
        wanted = list(wanted)
        found = self.con.execute(_SELECT[table])
        present = [d[0] for d in found.description]
        rows = [dict(zip(present, values, strict=True)) for values in found]
        return [{c: row.get(c) for c in wanted} for row in rows]

    def count(self, table: str, statements: tuple[str, ...]) -> int:
        """The first of *statements* the table's columns can answer."""
        if table not in self.names:
            return 0
        for statement in statements:
            try:
                return int(self.con.execute(statement).fetchone()[0])
            except sqlite3.OperationalError:
                continue
        return 0


def _read(con: sqlite3.Connection) -> GrocyFile:
    tables = _Tables(con)
    if any(t not in tables.names for t in _REQUIRED) or not {
        'id',
        'name',
    } <= tables.columns('products'):
        raise ServiceRejectionError('grocy_file_not_grocy')

    rows = sum(
        tables.count(table, (statement,)) for table, statement in _COUNT_ROWS.items()
    )
    if rows > MAX_IMPORT_ROWS:
        raise ServiceRejectionError(
            'import_too_many_rows', count=rows, limit=MAX_IMPORT_ROWS
        )

    shopping_lists = {
        row['id']: row['name'] or ''
        for row in tables.rows('shopping_lists', ('id', 'name'))
    }
    return GrocyFile(
        locations=_named(tables, 'locations'),
        groups=_named(tables, 'product_groups'),
        stores=_named(tables, 'shopping_locations'),
        units=_named(tables, 'quantity_units'),
        products=_products(tables),
        stock=[_stock_entry(row) for row in _stock_rows(tables)],
        shopping_list=[
            GrocyShoppingListEntry(
                id=row['id'],
                list_id=row['shopping_list_id'] or 1,
                list_name=shopping_lists.get(row['shopping_list_id'] or 1, ''),
                product_id=row['product_id'],
                note=_text(row['note']),
                amount=_decimal(row['amount']) or Decimal(0),
                unit_id=row['qu_id'],
                done=_flag(row['done'], default=False),
            )
            for row in tables.rows(
                'shopping_list',
                (
                    'id',
                    'shopping_list_id',
                    'product_id',
                    'note',
                    'amount',
                    'qu_id',
                    'done',
                ),
            )
        ],
        left_behind={
            kind: tables.count(table, statements)
            for kind, (table, statements) in _LEFT_BEHIND.items()
        },
    )


def _named(tables: _Tables, table: str) -> dict[int, GrocyNamed]:
    return {
        row['id']: GrocyNamed(
            id=row['id'],
            name=_text(row['name']) or str(row['id']),
            description=_text(row['description']),
            active=_flag(row['active'], default=True),
            is_freezer=_flag(row['is_freezer'], default=False),
            plural=_text(row['name_plural']),
        )
        for row in tables.rows(
            table,
            ('id', 'name', 'description', 'active', 'is_freezer', 'name_plural'),
        )
    }


def _products(tables: _Tables) -> dict[int, GrocyProduct]:
    barcodes: dict[int, list[str]] = {}
    for row in tables.rows('product_barcodes', ('id', 'product_id', 'barcode')):
        code = _text(row['barcode'])
        if code and row['product_id'] is not None:
            barcodes.setdefault(row['product_id'], []).append(code)
    products: dict[int, GrocyProduct] = {}
    for row in tables.rows(
        'products',
        (
            'id',
            'name',
            'description',
            'active',
            'product_group_id',
            'location_id',
            'shopping_location_id',
            'qu_id_stock',
            'min_stock_amount',
            'picture_file_name',
            'parent_product_id',
            'default_best_before_days',
            'default_best_before_days_after_open',
            'default_best_before_days_after_freezing',
            'default_best_before_days_after_thawing',
            # Before product_barcodes, a product carried its codes itself,
            # separated by commas.
            'barcode',
        ),
    ):
        own = [c.strip() for c in (_text(row['barcode']) or '').split(',') if c.strip()]
        products[row['id']] = GrocyProduct(
            id=row['id'],
            name=_text(row['name']) or str(row['id']),
            description=_text(row['description']),
            active=_flag(row['active'], default=True),
            group_id=row['product_group_id'],
            location_id=row['location_id'],
            store_id=row['shopping_location_id'],
            unit_id=row['qu_id_stock'],
            min_stock=_decimal(row['min_stock_amount']) or Decimal(0),
            barcodes=tuple(own + barcodes.get(row['id'], [])),
            has_picture=bool(_text(row['picture_file_name'])),
            has_parent=row['parent_product_id'] is not None,
            has_default_days=any(
                (_decimal(row[k]) or 0) > 0
                for k in (
                    'default_best_before_days',
                    'default_best_before_days_after_open',
                    'default_best_before_days_after_freezing',
                    'default_best_before_days_after_thawing',
                )
            ),
        )
    return products


def _stock_rows(tables: _Tables) -> list[dict[str, Any]]:
    return tables.rows(
        'stock',
        (
            'id',
            'product_id',
            'amount',
            'best_before_date',
            'purchased_date',
            'price',
            'location_id',
            'shopping_location_id',
            'open',
            'opened_date',
            'note',
            'stock_id',
        ),
    )


def _stock_entry(row: dict[str, Any]) -> GrocyStockEntry:
    is_open = _flag(row['open'], default=False)
    return GrocyStockEntry(
        id=row['id'],
        product_id=row['product_id'],
        amount=_decimal(row['amount']) or Decimal(0),
        best_before=_date(row['best_before_date']),
        purchased=_date(row['purchased_date']),
        price=_decimal(row['price']),
        location_id=row['location_id'],
        store_id=row['shopping_location_id'],
        is_open=is_open,
        opened=_date(row['opened_date']) if is_open else None,
        note=_text(row['note']),
        stock_id=_text(row['stock_id']) or f'row-{row["id"]}',
    )


def _text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _flag(value: object, *, default: bool) -> bool:
    if value is None or value == '':
        return default
    try:
        return int(str(value)) != 0
    except ValueError:
        return default


def _decimal(value: object) -> Decimal | None:
    if value is None or value == '':
        return None
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def _date(value: object) -> date | None:
    text = _text(value)
    if text is None:
        return None
    try:
        day = date.fromisoformat(text[:10])
    except ValueError:
        return None
    return None if day >= _NEVER else day
