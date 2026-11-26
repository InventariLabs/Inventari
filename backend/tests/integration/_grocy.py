"""A Grocy database file for tests, built on Grocy's own schema.

Grocy writes no export of its own; a move from it reads its SQLite file,
``data/grocy.db``. The tables come from ``tests/fixtures/grocy_schema.sql``,
the statements Grocy's own migrations leave behind, so a column the import
reads is a column Grocy writes. Each method adds one row the way Grocy's
screens would and returns its id; :meth:`GrocyDb.content` is the file's bytes,
what an upload carries.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = Path(__file__).resolve().parents[1] / 'fixtures' / 'grocy_schema.sql'

#: Grocy's own spelling of "this never goes off".
NEVER = '2999-12-31'


class GrocyDb:
    def __init__(self) -> None:
        self.con = sqlite3.connect(':memory:')
        self.con.executescript(SCHEMA.read_text())
        # Grocy's migrations found the first shopping list themselves.
        self.con.execute("INSERT INTO shopping_lists (id, name) VALUES (1, 'Default')")
        self._stock_ids = 0

    def _insert(self, table: str, **values: object) -> int:
        columns = ', '.join(values)
        marks = ', '.join('?' for _ in values)
        cursor = self.con.execute(
            f'INSERT INTO {table} ({columns}) VALUES ({marks})',
            tuple(values.values()),
        )
        return int(cursor.lastrowid or 0)

    def location(
        self, name: str, *, is_freezer: bool = False, active: bool = True
    ) -> int:
        return self._insert(
            'locations', name=name, is_freezer=int(is_freezer), active=int(active)
        )

    def group(self, name: str, *, active: bool = True) -> int:
        return self._insert('product_groups', name=name, active=int(active))

    def store(self, name: str, *, active: bool = True) -> int:
        return self._insert('shopping_locations', name=name, active=int(active))

    def unit(self, name: str, plural: str | None = None) -> int:
        return self._insert('quantity_units', name=name, name_plural=plural or name)

    def product(
        self,
        name: str,
        *,
        location: int,
        unit: int,
        purchase_unit: int | None = None,
        group: int | None = None,
        store: int | None = None,
        description: str | None = None,
        min_stock: float = 0,
        active: bool = True,
        picture: str | None = None,
        parent: int | None = None,
        default_days: int = 0,
    ) -> int:
        return self._insert(
            'products',
            name=name,
            description=description,
            product_group_id=group,
            active=int(active),
            location_id=location,
            shopping_location_id=store,
            qu_id_purchase=purchase_unit or unit,
            qu_id_stock=unit,
            qu_id_consume=unit,
            qu_id_price=unit,
            min_stock_amount=min_stock,
            default_best_before_days=default_days,
            picture_file_name=picture,
            parent_product_id=parent,
        )

    def barcode(self, product: int, code: str) -> int:
        return self._insert('product_barcodes', product_id=product, barcode=code)

    def conversion(
        self, product: int, from_unit: int, to_unit: int, factor: float
    ) -> int:
        return self._insert(
            'quantity_unit_conversions',
            product_id=product,
            from_qu_id=from_unit,
            to_qu_id=to_unit,
            factor=factor,
        )

    def stock(
        self,
        product: int,
        amount: float,
        *,
        best_before: str = NEVER,
        purchased: str | None = None,
        price: float | None = None,
        location: int | None = None,
        store: int | None = None,
        opened: str | None = None,
        note: str | None = None,
        stock_id: str | None = None,
    ) -> int:
        self._stock_ids += 1
        return self._insert(
            'stock',
            product_id=product,
            amount=amount,
            best_before_date=best_before,
            purchased_date=purchased,
            price=price,
            location_id=location,
            shopping_location_id=store,
            open=int(opened is not None),
            opened_date=opened,
            note=note,
            stock_id=stock_id or f'5f00{self._stock_ids:09x}',
        )

    def shopping_list(self, name: str) -> int:
        return self._insert('shopping_lists', name=name)

    def shopping_item(
        self,
        *,
        product: int | None = None,
        note: str | None = None,
        amount: float = 1,
        unit: int | None = None,
        list_id: int = 1,
        done: bool = False,
    ) -> int:
        return self._insert(
            'shopping_list',
            product_id=product,
            note=note,
            amount=amount,
            qu_id=unit,
            shopping_list_id=list_id,
            done=int(done),
        )

    def recipe(self, name: str, *, kind: str = 'normal') -> int:
        return self._insert('recipes', name=name, type=kind)

    def meal(self, day: str, recipe: int) -> int:
        return self._insert('meal_plan', day=day, recipe_id=recipe, type='recipe')

    def chore(self, name: str) -> int:
        return self._insert('chores', name=name, period_type='manually')

    def battery(self, name: str) -> int:
        return self._insert('batteries', name=name)

    def task(self, name: str) -> int:
        return self._insert('tasks', name=name)

    def equipment(self, name: str) -> int:
        return self._insert('equipment', name=name)

    def own_field(self, entity: str, name: str, object_id: int, value: str) -> int:
        field = self._insert(
            'userfields',
            entity=entity,
            name=name,
            caption=name,
            type='text-single-line',
        )
        return self._insert(
            'userfield_values', field_id=field, object_id=str(object_id), value=value
        )

    def content(self) -> bytes:
        self.con.commit()
        return self.con.serialize()
