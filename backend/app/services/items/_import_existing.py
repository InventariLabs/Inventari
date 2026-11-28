"""Which stock already here an import row is about.

Read once, before the first row is written: a row matches what stood in stock
before the upload, so two rows of one sheet about one product are both
imported whatever the mode.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.barcode import normalize_barcode
from app.core.contracts import UserContextDTO
from app.core.exceptions import ServiceRejectionError
from app.core.import_sheet import cell_text, read_rows, row_get, sku_from_cell
from app.models.item import Item
from app.models.product_template import ProductTemplate
from app.services._product_template_writes import PLACEHOLDER_SKU_PREFIX

from ._import_products import read_reference

#: A mapping key naming a column that holds the quantity at one location
#: ("stock_at:Shop"), for a sheet with a quantity column per location.
STOCK_AT_PREFIX = 'stock_at:'


@dataclass(frozen=True)
class RowIdentity:
    """What a row says it is about."""

    #: ``None`` for a row that names nothing, which the import refuses.
    name: str | None
    sku: str | None
    barcode: str | None
    brand: str | None
    label_code: str | None


async def row_identity(
    db: AsyncSession, org_id: UUID | None, mapping: dict[str, Any], row: pd.Series
) -> RowIdentity:
    """The row's name and codes in the shape the catalogue keeps them.

    A SKU cell that is no SKU refuses the row.
    """

    def text(key: str) -> str | None:
        return cell_text(row_get(row, mapping, key))

    name = text('name')
    sku_column = mapping.get('sku')
    sku_text = text('sku')
    sku = sku_from_cell(sku_text, sku_column) if sku_column and sku_text else None
    if name and sku is None and org_id is not None:
        name, sku = await read_reference(db, org_id, name, mapping['name'])
    barcode = text('barcode')
    return RowIdentity(
        name=name,
        sku=sku,
        barcode=normalize_barcode(barcode) if barcode else None,
        brand=text('brand'),
        label_code=text('label_code'),
    )


@dataclass(frozen=True)
class StockRecord:
    item_id: UUID
    location_id: UUID | None
    quantity: Decimal
    sku: str | None
    brand: str | None


@dataclass
class ExistingStock:
    """The organization's live records, by every way a row may name them."""

    by_label: dict[str, list[StockRecord]] = field(
        default_factory=lambda: defaultdict(list)
    )
    by_sku: dict[str, list[StockRecord]] = field(
        default_factory=lambda: defaultdict(list)
    )
    by_barcode: dict[str, list[StockRecord]] = field(
        default_factory=lambda: defaultdict(list)
    )
    by_name: dict[str, list[StockRecord]] = field(
        default_factory=lambda: defaultdict(list)
    )

    @classmethod
    async def load(cls, db: AsyncSession, org_id: UUID | None) -> ExistingStock:
        """Read once, so a thousand-row sheet asks the database once."""
        stock = cls()
        if org_id is None:
            return stock
        rows = await db.execute(
            select(
                Item.id,
                Item.storage_location_id,
                Item.quantity,
                Item.label_code,
                Item.barcode,
                Item.name,
                Item.brand,
                ProductTemplate.sku,
                ProductTemplate.barcode,
                ProductTemplate.name,
                ProductTemplate.brand,
            )
            .outerjoin(ProductTemplate, ProductTemplate.id == Item.template_id)
            .where(Item.organization_id == org_id, Item.is_deleted.is_(False))
        )
        for (
            item_id,
            location_id,
            quantity,
            label,
            barcode,
            name,
            brand,
            sku,
            product_barcode,
            product_name,
            product_brand,
        ) in rows.all():
            record = StockRecord(
                item_id,
                location_id,
                quantity or Decimal('0'),
                sku,
                product_brand if product_name else brand,
            )
            if label:
                stock.by_label[label.strip().lower()].append(record)
            if sku:
                stock.by_sku[sku].append(record)
            for code in {barcode, product_barcode} - {None, ''}:
                stock.by_barcode[code].append(record)
            stock.by_name[product_name or name].append(record)
        return stock

    def named_by_label(self, row: RowIdentity) -> list[StockRecord]:
        """The record the row's Label Code names: one object, wherever it stands."""
        if not row.label_code:
            return []
        return self.by_label.get(row.label_code.strip().lower(), [])

    def named_by_code(self, row: RowIdentity) -> list[StockRecord]:
        """The records the row's Label Code names, else its SKU, else its barcode."""
        if found := self.named_by_label(row):
            return found
        if row.sku and row.sku in self.by_sku:
            return self.by_sku[row.sku]
        if row.barcode:
            return self.by_barcode.get(row.barcode, [])
        return []

    def joined_by(self, row: RowIdentity) -> list[StockRecord]:
        """The records of the product a new record of the row would join.

        By a code, else by name and brand, as the import itself matches; a
        product carrying another SKU than the row's is a variant, not this one.
        """
        found = self.named_by_code(row)
        if found or not row.name:
            return found
        return [
            record
            for record in self.by_name.get(row.name, [])
            if (not row.brand or record.brand == row.brand)
            and (
                not row.sku
                or not record.sku
                or record.sku.startswith(PLACEHOLDER_SKU_PREFIX)
            )
        ]


async def count_rows_in_stock_async(
    db: AsyncSession,
    file_content: bytes,
    filename: str,
    mapping: dict[str, Any],
    user: UserContextDTO,
    count_as_one: bool = False,
) -> dict[str, int]:
    """How many rows of a sheet would add to a product already in stock.

    A sheet that carries no stock adds none, and counts none.
    """
    df = read_rows(file_content, filename)
    carries_stock = count_as_one or any(
        column and (key == 'quantity' or key.startswith(STOCK_AT_PREFIX))
        for key, column in mapping.items()
    )
    if not carries_stock:
        return {'rows': 0, 'rows_in_stock': 0}
    existing = await ExistingStock.load(db, user.organization_id)
    in_stock = 0
    for _, row in df.iterrows():
        try:
            identity = await row_identity(db, user.organization_id, mapping, row)
        except ServiceRejectionError:  # the import will refuse the row
            continue
        in_stock += any(record.quantity > 0 for record in existing.joined_by(identity))
    return {'rows': len(df), 'rows_in_stock': in_stock}
