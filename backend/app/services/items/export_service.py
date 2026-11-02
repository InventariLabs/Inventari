from collections.abc import Iterable, Iterator
from decimal import Decimal
from typing import Any
from uuid import UUID

import pandas as pd
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.xlsx_export import rows_to_xlsx_response
from app.models.category import Category
from app.models.item import Item
from app.models.storage_location import StorageLocation

#: What a tracked field names on the product, where the two vocabularies do
#: not say a field in the same words. A location's tracked-field toggles call
#: the product's description "Notes" and its purchase price "Price" — the keys
#: they store in ``context_schema`` — while the sheet names its columns after
#: the product's own fields. Product code and Shelf / position already carry
#: the product's key. Both spellings are taken for the same field; matching
#: the tracked keys straight against the columns dropped the Description
#: column from every sheet of an organization whose locations track Notes.
_TRACKED_FIELD_ALIASES = {'notes': 'description', 'price': 'purchase_price'}


def _org_currency(db: Session, organization_id: UUID | None) -> str:
    if not organization_id:
        return 'USD'
    from app.models.organization import Organization

    org = db.scalars(
        select(Organization).where(Organization.id == organization_id)
    ).first()
    return (org.currency or 'USD') if org else 'USD'


#: How many records one read of the export fetches.
_PAGE_SIZE = 2_000


def _iter_items(
    db: Session,
    organization_id: UUID | None,
    user_storage_ids: list[UUID] | None,
    filters: dict[str, Any],
) -> Iterator[Item]:
    """The rows the list would show for the same filters, all pages at once.

    Same builder as ``GET /items`` — the sheet a reader downloads from under
    "Showing 1–50 of 102" holds those 102 rows, not the whole organization.
    The records are read a page at a time, keyed on the id, and handed on
    one by one: the export used to hold every record with its category,
    template, shelf and unit in one list, which at 100 000 products grew the
    worker until the container killed it.
    """
    from app.services.items._query_get import _apply_item_filters

    query = (
        select(Item)
        .join(StorageLocation)
        .options(
            joinedload(Item.category),
            joinedload(Item.template),
            joinedload(Item.uom),
            joinedload(Item.storage_location).joinedload(StorageLocation.storage_type),
        )
    )
    query = _apply_item_filters(
        query,
        organization_id=organization_id,
        user_storage_ids=user_storage_ids,
        **filters,
    )
    last_id: UUID | None = None
    while True:
        page_query = query.order_by(Item.id).limit(_PAGE_SIZE)
        if last_id is not None:
            page_query = page_query.where(Item.id > last_id)
        page = db.scalars(page_query).unique().all()
        yield from page
        if len(page) < _PAGE_SIZE:
            return
        last_id = page[-1].id


def _active_field_keys(
    db: Session, organization_id: UUID | None, categories: Iterable[Category]
) -> tuple[set[str], bool, dict[str, str]]:
    """Which tracking fields this export shows, and the header for each.

       Keys come from the organisation's storage schemas and from the categories
    of the exported items (: equipment locations carry empty schemas, so
       location-only gating hid Price/description/weight from every equipment
       export).

       One label per field key for the WHOLE sheet: a header taken from the row's
       own category split the same field across two columns ("Status" for
       categorised assets, "Equipment Status" for the rest), which broke
       re-importing the sheet (audit 2026-08-16). Categories are visited in a
       stable order so the chosen label does not depend on row order.
    """
    # Only the two JSONB schema columns are needed — avoid loading
    # full StorageLocation rows (including nested relations).
    schema_rows = db.execute(
        select(
            StorageLocation.context_schema,
            StorageLocation.field_definitions,
        ).where(StorageLocation.organization_id == organization_id)
    ).all()

    active_keys: set[str] = set()
    # The same rule the form reads a schema by: an empty context_schema is
    # "no restriction", not "no fields". A location without one allows every
    # field, so a key any exported item carries travels — a home with expiry
    # dates on the list used to get a sheet without the column, and the
    # round trip through that sheet forgot the dates.
    unrestricted = False
    for context_schema, field_definitions in schema_rows:
        if context_schema:
            active_keys.update(
                _TRACKED_FIELD_ALIASES.get(key, key) for key in context_schema
            )
        else:
            unrestricted = True
        if field_definitions:
            for f in field_definitions:
                if isinstance(f, dict) and f.get('key'):
                    active_keys.add(f['key'])

    field_labels: dict[str, str] = {}
    for category in sorted(categories, key=lambda c: c.name):
        if category.field_definitions:
            for f in category.field_definitions:
                if isinstance(f, dict) and f.get('key'):
                    active_keys.add(f['key'])
                    if f.get('label'):
                        field_labels.setdefault(f['key'], f['label'])

    return active_keys, unrestricted, field_labels


def _location_paths(db: Session, organization_id: UUID | None) -> dict[UUID, str]:
    """Every location of the organization by its full path, root first.

    The arrow is the one the import reads a path by, so a sheet's Location
    column names one place unambiguously — two locations called "Server Room"
    are told apart by what they sit in — and still reads back.
    """
    rows = db.execute(
        select(
            StorageLocation.id, StorageLocation.name, StorageLocation.parent_id
        ).where(StorageLocation.organization_id == organization_id)
    ).all()
    by_id = {row.id: row for row in rows}
    paths: dict[UUID, str] = {}
    for location_id in by_id:
        names: list[str] = []
        seen: set[UUID] = set()
        current: UUID | None = location_id
        while current is not None and current in by_id and current not in seen:
            seen.add(current)
            names.append(by_id[current].name)
            current = by_id[current].parent_id
        paths[location_id] = ' → '.join(reversed(names))
    return paths


def _code_of(item: Item) -> str | None:
    """The code the list shows: the record's own, else the product card's."""
    return item.barcode or (item.template.barcode if item.template else None)


def _cell_value(item: Item, key: str) -> object:
    """Read one tracking field off the item, wherever it actually lives."""
    if key == 'sku':
        return item.template.sku if item.template else None
    if key == 'freeze_date':
        return (item.meta_data or {}).get('food', {}).get('freeze_date')
    if key == 'weight':
        # Computed from the template's unit weight; the item no longer
        # carries one of its own (ADR-015).
        return item.total_weight
    return getattr(item, key, None)


def _format_cell(value: object) -> object:
    if value is None:
        return None
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    return float(value) if isinstance(value, (int, float, Decimal)) else value


def _meta_entries(item: Item) -> Iterator[tuple[str, str, object]]:
    """The columns ``meta_data`` spreads into: ``(kind, key, value)`` each."""
    for k, v in (item.meta_data or {}).items():
        if k == 'nutrition' and isinstance(v, dict):
            for nutry_k, nutry_v in v.items():
                yield 'nutrition', nutry_k, nutry_v
        elif k == 'equipment' and isinstance(v, dict):
            for eq_k, eq_v in v.items():
                yield 'equipment', eq_k, eq_v
        elif k not in ['off_enriched', 'nutrition_source', 'food']:
            yield 'custom', k, v


def _meta_header(kind: str, key: str, field_labels: dict[str, str]) -> str:
    """The header of a ``meta_data`` column.

    Equipment meta columns use the declared field labels (the same source
    the import analyzer suggests) instead of raw database keys, so a sheet
    can be re-imported without mapping.
    """
    if kind == 'nutrition':
        return f'Nutri: {key}'
    if kind == 'equipment':
        return field_labels.get(key) or key.replace('_', ' ').title()
    return f'Custom: {field_labels.get(key) or key}'


#: What the list and the product page show about a product, so the sheet
#: carries it whenever any exported row has a value — whatever the locations
#: track. A location that tracks no notes still has products with a
#: description on screen, and a copy of the catalogue that loses it is not one.
_ALWAYS_WHEN_CARRIED = frozenset({'sku', 'min_quantity', 'description'})

_SYSTEM_COLS = [
    'Name',
    'Quantity',
    'Unit',
    'Location',
    'Category',
    'Barcode',
    'Serial Number',
    'Label Code',
]

#: Headers the import wizard maps back onto a product, with the field each
#: one feeds. Everything else in the sheet is written for the reader and
#: does not come back — the second sheet of the workbook says which is which.
_READ_BACK_ON_IMPORT = {
    'Name': 'product name',
    'Quantity': 'quantity',
    'Unit': 'unit',
    'Location': 'location',
    'Category': 'category',
    'Barcode': 'barcode',
    'Serial Number': 'serial number',
    'Brand': 'brand',
    'Expiry Date': 'expiry date',
    'Freeze Date': 'freeze date',
}
_NOT_READ_BECAUSE = {
    'Currency': "the organization's currency applies",
}

#: The one column that is read only when the reader asks for it: in the
#: import wizard's update mode it says which product a row is about.
_LABEL_CODE_NOTE = (
    'in update mode, names the product this row is about; '
    'otherwise ignored, and a new product gets its own code'
)


def _read_me(columns: list[str], price_header: str) -> pd.DataFrame:
    """Which columns of the sheet come back on import, and which do not."""
    read_back = {**_READ_BACK_ON_IMPORT, price_header: 'purchase price per unit'}
    rows = []
    for column in columns:
        if column == 'Label Code':
            rows.append(
                {
                    'Column': column,
                    'On import': 'read in update mode',
                    'Note': _LABEL_CODE_NOTE,
                }
            )
        elif column in read_back:
            rows.append(
                {
                    'Column': column,
                    'On import': 'read',
                    'Note': f'becomes the {read_back[column]}',
                }
            )
        else:
            rows.append(
                {
                    'Column': column,
                    'On import': 'not read',
                    'Note': _NOT_READ_BECAUSE.get(
                        column, 'written for the reader; import ignores it'
                    ),
                }
            )
    rows.append(
        {
            'Column': '',
            'On import': '',
            'Note': 'Import adds products: a row whose barcode, or name '
            'and brand, matches a product you already have becomes '
            'another record of that product — stock and history add up. '
            'Two rows are refused instead: one whose serial number is '
            'already on a record you have, and one whose barcode is worn '
            'by a live record of a different product. A row that matches '
            'nothing becomes a new product. To update instead of adding, '
            'map the Label Code column and pick a match mode: rows '
            'carrying a code of an existing product are skipped or '
            'overwritten; a row without a code always adds. Quantity is '
            'never overwritten, stock moves through a receipt or a count.',
        }
    )
    return pd.DataFrame(rows, columns=['Column', 'On import', 'Note'])


class _Scan:
    """What one pass over the exported records says about the sheet's shape.

    The columns of the sheet depend on every row — a column exists when any
    row carries a value for it — so the shape is read in a pass of its own,
    keeping only these few sets and flags, and the rows are written in a
    second pass. Neither pass holds the records.
    """

    def __init__(self, tracked_keys: Iterable[str]) -> None:
        self.categories: dict[UUID, Category] = {}
        self.has_purchase_price = False
        self.include_currency = False
        self.carries_value = dict.fromkeys(tracked_keys, False)
        self.meta_specs: dict[tuple[str, str], None] = {}

    def see(self, item: Item) -> None:
        if item.category is not None:
            self.categories.setdefault(item.category.id, item.category)
        if item.purchase_price is not None:
            self.has_purchase_price = True
            self.include_currency = True
        elif item.currency is not None:
            self.include_currency = True
        for key, carried in self.carries_value.items():
            if not carried and _cell_value(item, key) is not None:
                self.carries_value[key] = True
        for kind, key, _ in _meta_entries(item):
            self.meta_specs.setdefault((kind, key))


def export_items_to_xlsx(
    db: Session,
    current_user,
    filters: dict[str, Any] | None = None,
    enrichment: dict[UUID, dict[str, object]] | None = None,
    user_storage_ids: list[UUID] | None = None,
) -> StreamingResponse:
    """Export items to XLSX, dynamically including active tracking fields.

    ``filters`` are the list's own (``_apply_item_filters`` keywords), so the
    sheet covers exactly the rows the list shows. ``enrichment`` carries rows
    contributed by feature modules through :mod:`app.core.export_enrichers`
    (e.g. equipment's "Assigned To") — Core renders them without knowing the
    module.

    The workbook is written row by row to a temporary file and streamed back
    from it, so the memory it takes does not depend on how many records the
    sheet holds; a sheet that fills (a million rows) continues on the next
    one (:func:`app.core.xlsx_export.rows_to_xlsx_response`).
    """
    org_currency = _org_currency(db, current_user.organization_id)
    filters = filters or {}

    key_map = {
        'sku': 'SKU',
        'min_quantity': 'Stock alert',
        'expiry_date': 'Expiry Date',
        'freeze_date': 'Freeze Date',
        'brand': 'Brand',
        'weight': 'Weight',
        # The same name the form and the import mapper use. It read "Price"
        # here and "Purchase Price" there, and neither said the thing that
        # decides whether the number is right: it is a rate, not the invoice
        # total for the quantity in the row beside it.
        'purchase_price': f'Purchase price per unit ({org_currency})',
        'description': 'Description',
        'shelf_location': 'Shelf Location',
    }

    def _items() -> Iterator[Item]:
        return _iter_items(db, current_user.organization_id, user_storage_ids, filters)

    scan = _Scan(key for key in key_map if key != 'purchase_price')
    for item in _items():
        scan.see(item)

    active_keys, unrestricted, field_labels = _active_field_keys(
        db, current_user.organization_id, scan.categories.values()
    )

    def _exported(key: str) -> bool:
        if key == 'purchase_price':
            return scan.has_purchase_price
        if key in active_keys:
            return True
        return scan.carries_value[key] and (unrestricted or key in _ALWAYS_WHEN_CARRIED)

    exported_keys = {key: label for key, label in key_map.items() if _exported(key)}
    location_paths = _location_paths(db, current_user.organization_id)

    # The columns, in the order a row's dict would first have named them:
    # the system ones first, then the rest as the rows introduce them.
    columns = list(_SYSTEM_COLS)
    for column in (
        'Brand',
        *exported_keys.values(),
        *(['Currency'] if scan.include_currency else []),
        *dict.fromkeys(c for cells in (enrichment or {}).values() for c in cells),
        *(_meta_header(kind, key, field_labels) for kind, key in scan.meta_specs),
    ):
        if column not in columns:
            columns.append(column)

    def _rows() -> Iterator[list[object]]:
        for item in _items():
            row: dict = {
                'Name': item.name,
                'Brand': item.brand,
                'Quantity': float(item.quantity) if item.quantity else 0,
                'Unit': item.uom.symbol if item.uom else None,
                'Location': location_paths.get(item.storage_location_id)
                or (item.storage_location.name if item.storage_location else 'Unknown'),
                'Category': item.category.name if item.category else None,
                'Barcode': _code_of(item),
                'Serial Number': item.serial_number,
                'Label Code': item.label_code,
            }

            for key, label in exported_keys.items():
                row[label] = _format_cell(_cell_value(item, key))

            if scan.include_currency:
                row['Currency'] = item.currency or org_currency

            if enrichment:
                for column, value in (enrichment.get(item.id) or {}).items():
                    row[column] = value

            for kind, key, value in _meta_entries(item):
                row[_meta_header(kind, key, field_labels)] = value
            yield [row.get(column) for column in columns]

    return rows_to_xlsx_response(
        columns,
        _rows(),
        sheet_name='Inventory',
        filename_stem='inventari_export',
        readme=_read_me(columns, key_map['purchase_price']),
    )
