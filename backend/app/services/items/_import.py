"""Bulk item import — XLSX/CSV parsing, row resolution, per-row processing.

Every row goes through ``create_item_async``, the same door the form and a
document use: that is where a product gets its template, its unit and its
stock entry. An importer that built ``Item(**data)`` itself produced
products the products list counted and the stock screen had never heard of.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.core.exceptions import ServiceRejectionError
from app.core.import_sheet import SheetColumns, read_rows
from app.core.import_sheet import cell_text as _cell_text
from app.core.import_sheet import explain as _explain
from app.core.import_sheet import row_get as _row_get
from app.core.logging import get_logger
from app.core.refused_rows import refused_rows_file
from app.i18n.service import get_unit_label
from app.models.category import Category
from app.models.item import Item
from app.schemas.category import CategoryFieldDefinition
from app.schemas.item import ItemCreate, ItemUpdate
from app.services.fields.validation import FieldValueError, validate_field_value

from ._create import create_item_async
from ._import_existing import (
    STOCK_AT_PREFIX,
    ExistingStock,
    RowIdentity,
    StockRecord,
    row_identity,
)
from ._import_locations import LocationSlash, SheetLocations
from ._import_products import add_product_without_stock, product_of_a_record
from ._update import update_item

if TYPE_CHECKING:
    from app.core.uom_resolver import UomResolverAsync

logger = get_logger(__name__)

#: What a row does when its Label Code, SKU or barcode names stock the
#: organization already has. 'add' adds the row whatever it names; 'skip'
#: leaves what is there alone; 'overwrite' writes the row's other columns
#: onto the record it names.
LabelMatch = Literal['add', 'skip', 'overwrite']

#: Plain-text fields an overwrite writes back. Quantity is deliberately
#: absent from every overwrite: stock moves through the ledger (a receipt, a
#: count), never through a spreadsheet cell overwriting a number the movement
#: ledger and the valuation layers also account for.
_OVERWRITABLE_TEXT = ('brand', 'barcode', 'serial_number')

#: A mapping key naming a product field a location sets ("field:supplier"),
#: as opposed to one of the fixed system columns above.
_FIELD_PREFIX = 'field:'

#: What the description column of a product and of a record holds.
_DESCRIPTION_LIMIT = 500

#: Odoo writes a category as its whole path, "All / Saleable / Food".
_CATEGORY_PATH_SEPARATOR = ' / '

#: How a sheet says yes or no to a yes/no field, in every maintained language.
#: The accented and unaccented Portuguese spellings both appear in sheets.
_YES = frozenset({'1', 'true', 'yes', 'y', 'x', 'tak', 'ja', 'oui', 'si', 'sí', 'sim'})
_NO = frozenset({'0', 'false', 'no', 'n', 'nie', 'nein', 'non', 'não', 'nao'})


#: Rows imported between two progress reports.
_BATCH_ROWS = 50


async def import_items(
    db: AsyncSession,
    file_content: bytes,
    filename: str,
    mapping: dict[str, Any],
    user: UserContextDTO,
    create_missing_locations: bool = True,
    create_missing_categories: bool = True,
    on_label_match: LabelMatch = 'add',
    on_batch: Callable[[int], Awaitable[None]] | None = None,
    location_slash: LocationSlash = 'path',
    count_as_one: bool = False,
) -> dict[str, Any]:
    """Import items from XLSX or CSV file based on column mapping.

    ``on_batch`` is told how many rows have been read each time a batch is
    done, for a caller that shows the import's progress. Nothing here
    commits: a caller that holds a session of its own (the background job)
    commits the batch there, a request commits the import with its response.

    ``on_label_match`` decides what happens to a row naming stock the
    organization had before the upload — by Label Code (the code the export
    sheet carries), else by SKU, else by barcode: it is added anyway ('add'),
    left alone ('skip') or written onto the record ('overwrite'). A row that
    names none of it is always added.

    A sheet with no quantity column adds products without stock, unless
    ``count_as_one`` asks for a record of one per row. ``location_slash``
    says how a "/" in a location cell reads.
    """
    df = read_rows(file_content, filename)

    ctx = _ImportContext(
        db=db,
        user=user,
        mapping=mapping,
        sheet=SheetColumns(df),
        locations=await SheetLocations.load(
            db, user, create_missing=create_missing_locations, slash=location_slash
        ),
        category_cache=await _preload_category_cache(db, user.organization_id),
        category_fields=await _preload_category_fields(db, user.organization_id),
        count_as_one=count_as_one,
        create_missing_categories=create_missing_categories,
        on_label_match=on_label_match,
        existing=await ExistingStock.load(db, user.organization_id)
        if on_label_match != 'add'
        else ExistingStock(),
    )

    imported = 0
    joined_existing = 0
    updated = 0
    skipped = 0
    failed = 0
    written_rows = 0
    extra_records = 0
    errors: list[dict[str, Any]] = []

    for index, row in df.iterrows():
        row_result = await _process_import_row(ctx, row, index)
        if row_result.error is not None:
            failed += 1
            errors.append(row_result.error)
        if row_result.outcome == 'skipped':
            skipped += 1
        elif row_result.outcome in ('imported', 'updated'):
            if row_result.outcome == 'imported':
                imported += row_result.records
                joined_existing += row_result.joined_existing
                extra_records += row_result.records - 1
            else:
                updated += 1
            written_rows += 1
            if written_rows % _BATCH_ROWS == 0 and on_batch is not None:
                await on_batch(int(index) + 1)

    return {
        # A row holding stock at several locations is several records, and
        # the counts below it add up to this one.
        'total': len(df) + extra_records,
        'imported': imported,
        'joined_existing': joined_existing,
        'updated': updated,
        'skipped': skipped,
        'failed': failed,
        'errors': errors[:10],
        'refused_file': refused_rows_file(df, errors, filename, ctx.sheet),
        'created_locations': ctx.locations.created,
        'created_categories': ctx.created_categories,
    }


async def _preload_category_cache(
    db: AsyncSession, org_id: UUID | None
) -> dict[str, UUID]:
    """Return a lowercase-name -> id map of all categories in the org."""
    cache: dict[str, UUID] = {}
    if org_id is None:
        return cache
    result = await db.execute(
        select(Category).where(Category.organization_id == org_id)
    )
    for c in result.scalars().all():
        cache[c.name.lower()] = c.id
    return cache


async def _preload_category_fields(
    db: AsyncSession, org_id: UUID | None
) -> dict[UUID, dict[str, dict[str, Any]]]:
    """Each category's own product fields, by category id and field key.

    A category asks for fields of its own ("Thread size" on Fasteners), and
    the writer refuses a product of that category that leaves a required one
    empty — so the import has to be able to fill them. Platform fields (the
    ones with a column of their own) are not metadata and stay out; so do
    money and file fields, which a cell cannot carry — the writer's own
    refusal of a value that does not fit them still applies.
    """
    fields: dict[UUID, dict[str, dict[str, Any]]] = {}
    if org_id is None:
        return fields
    result = await db.execute(
        select(Category.id, Category.field_definitions).where(
            Category.organization_id == org_id
        )
    )
    for category_id, definitions in result.all():
        own = {
            definition['key']: definition
            for definition in definitions or []
            if isinstance(definition, dict)
            and definition.get('key')
            and not definition.get('is_system')
            and definition.get('type') not in ('money', 'file')
        }
        if own:
            fields[category_id] = own
    return fields


async def _resolve_or_create_category(
    ctx: '_ImportContext', row: pd.Series
) -> UUID | None:
    """The category_id for a row, founding one when allowed — else refusing.

    An unknown category with founding off is refused: ``None`` would import the
    row with no category at all and count it a success, while a sheet naming
    an unknown shelf is refused. One question,
    one answer — the refusal names the column and the cell, as the
    location's does.
    """
    cat_col = ctx.mapping.get('category')
    c_name = _cell_text(row.get(cat_col)) if cat_col and cat_col in row else None
    if not c_name:
        return None
    if c_name.lower() not in ctx.category_cache:
        # A category named with the whole text wins; otherwise the text is a
        # path and the product belongs in its last step.
        c_name = c_name.rsplit(_CATEGORY_PATH_SEPARATOR, 1)[-1].strip()
    if c_name.lower() in ctx.category_cache:
        return ctx.category_cache[c_name.lower()]
    if not ctx.create_missing_categories:
        raise ServiceRejectionError(
            'import_column_category_not_found', column=cat_col, value=c_name
        )
    new_cat = Category(
        name=c_name,
        organization_id=ctx.user.organization_id,
    )
    ctx.db.add(new_cat)
    await ctx.db.flush()
    ctx.category_cache[c_name.lower()] = new_cat.id
    ctx.row_categories.append(c_name.lower())
    ctx.created_categories.append(c_name)
    return new_cat.id


def _number_from_cell(
    row: pd.Series,
    mapping: dict[str, Any],
    key: str,
    default: Decimal | None,
    sheet: SheetColumns,
) -> Decimal | None:
    """Parse a mapped numeric cell, or fall back to ``default`` when empty.

    An empty cell in a numeric column reads as ``float('nan')`` — not None:
    pandas keeps numeric columns numeric, so the ``df.where(pd.notnull(df),
    None)`` at the top of import_items never reaches them. A None-only gate
    let ``Decimal('NaN')`` reach the column, where Postgres stored it and
    every Pydantic read of the row then refused the whole result page.
    Anything unparseable refuses the row and names the column and the cell.
    """
    text = _cell_text(_row_get(row, mapping, key))
    if text is None:
        return default
    try:
        return sheet.number(text, mapping[key])
    except ValueError:
        raise ServiceRejectionError(
            'import_column_not_a_number', column=mapping[key], value=text
        ) from None


def _quantity_from_cell(
    row: pd.Series, mapping: dict[str, Any], sheet: SheetColumns
) -> Decimal:
    """The row's quantity: 1 when the sheet has no quantity column at all.

    A column the reader mapped to quantity and left blank in this row is a
    gap, not an answer: it does not import as 1 with no word in the result,
    a stock figure nobody typed. The row is refused and says so.
    """
    if not mapping.get('quantity'):
        return Decimal('1.0')
    quantity = _number_from_cell(row, mapping, 'quantity', None, sheet)
    if quantity is None:
        raise ServiceRejectionError(
            'import_column_quantity_blank', column=mapping['quantity']
        )
    return quantity


async def _resolve_unit(ctx: '_ImportContext', row: pd.Series) -> UUID | None:
    """The unit the sheet names: its symbol, a synonym or any language's label."""
    from app.core.uom_resolver import UomResolverAsync
    from app.services.uom_service import get_uom_by_symbol_async

    col = ctx.mapping.get('unit')
    symbol = _cell_text(row.get(col)) if col and col in row else None
    if not symbol:
        return None
    org_id = ctx.user.organization_id
    if symbol not in ctx.uom_cache:
        # The symbol as written first: an organization's own unit may differ
        # from a system one only by its letter case.
        uom = await get_uom_by_symbol_async(ctx.db, symbol, org_id)
        if uom is None and org_id is not None:
            if ctx.uom_resolver is None:
                ctx.uom_resolver = UomResolverAsync(ctx.db, org_id)
            ctx.uom_cache[symbol] = await ctx.uom_resolver.resolve(symbol)
        else:
            ctx.uom_cache[symbol] = uom.id if uom else None
    uom_id = ctx.uom_cache[symbol]
    if uom_id is None:
        raise ServiceRejectionError(
            'import_unknown_unit',
            column=col,
            value=symbol,
            units=await _known_units(ctx),
        )
    return uom_id


async def _known_units(ctx: '_ImportContext') -> str:
    """The units a sheet may name, as the app writes them, for the refusal."""
    from app.services.uom_service import list_uoms_for_org_async

    org_id = ctx.user.organization_id
    if org_id is None:
        return ''
    uoms = await list_uoms_for_org_async(ctx.db, org_id)
    return ', '.join(sorted({get_unit_label(u.symbol) for u in uoms}))


def _description_from_cell(row: pd.Series, mapping: dict[str, Any]) -> str | None:
    text = _cell_text(_row_get(row, mapping, 'description'))
    if text is not None and len(text) > _DESCRIPTION_LIMIT:
        raise ServiceRejectionError(
            'import_column_too_long',
            column=mapping['description'],
            limit=_DESCRIPTION_LIMIT,
        )
    return text


def _min_quantity_from_cell(
    row: pd.Series, mapping: dict[str, Any], sheet: SheetColumns
) -> float | None:
    value = _number_from_cell(row, mapping, 'min_quantity', None, sheet)
    if value is None:
        return None
    if value < 0:
        raise ServiceRejectionError(
            'import_column_below_zero', column=mapping['min_quantity'], value=value
        )
    return float(value)


def _parse_date_cell(
    row: pd.Series, mapping: dict[str, Any], key: str, sheet: SheetColumns
) -> date | None:
    """Read and parse a mapped date column (expiry, freeze), or refuse the cell.

    Not app.core.datetimes.parse_iso_date: the input is a spreadsheet cell,
    which may already be a datetime and otherwise is read the way its
    column writes dates (``sheet`` decides day-first or month-first from the
    whole column).

    A cell the parser cannot read refuses the row with the column and the
    cell, the way quantity and location word theirs: a cell logged and dropped
    would let the term the reader had typed vanish under a report of zero
    failures, and the product would stay off every expiring-soon screen.
    """
    raw = _row_get(row, mapping, key)
    text = _cell_text(raw)
    if text is None:
        return None
    column = mapping[key]
    try:
        return sheet.date(raw, column)
    except (KeyError, ValueError, TypeError, OSError) as exc:
        logger.warning('Failed to parse %s: %s', key, exc)
        raise ServiceRejectionError(
            'import_date_invalid', column=column, value=text
        ) from None


def _field_value(
    definition: dict[str, Any],
    row: pd.Series,
    mapping: dict[str, Any],
    key: str,
    text: str,
    sheet: SheetColumns,
) -> object:
    """One field cell as the form stores the value, or refuse the cell.

    Text, choices and dates go in as text — a date in ISO form, as the date
    picker writes it; a number as its digits with a decimal point; a yes/no
    as a boolean; a multiple choice as the list of its comma-separated
    entries. A choice outside the field's options refuses the row the way
    the form would never have offered it.
    """
    kind = definition.get('type') or 'text'
    column = mapping[key]
    value: object = text
    if kind == 'number':
        try:
            value = str(sheet.number(text, column))
        except ValueError:
            raise ServiceRejectionError(
                'import_column_not_a_number', column=column, value=text
            ) from None
    elif kind == 'date':
        parsed = _parse_date_cell(row, mapping, key, sheet)
        value = parsed.isoformat() if parsed else None
    elif kind == 'boolean':
        if text.lower() not in _YES | _NO:
            raise ServiceRejectionError(
                'import_column_not_yes_no', column=column, value=text
            )
        value = text.lower() in _YES
    elif kind == 'multi-select':
        value = [part.strip() for part in text.split(',') if part.strip()]
    if kind in ('select', 'multi-select'):
        allowed = definition.get('options') or []
        for choice in value if isinstance(value, list) else [value]:
            if choice not in allowed:
                raise ServiceRejectionError(
                    'import_column_not_in_options',
                    column=column,
                    value=choice,
                    options=', '.join(allowed),
                )
    try:
        validate_field_value(CategoryFieldDefinition.model_validate(definition), value)
    except FieldValueError as exc:
        raise _field_value_refusal(mapping, exc) from None
    return value


def _field_value_refusal(
    mapping: dict[str, Any], exc: FieldValueError
) -> ServiceRejectionError:
    """A refused field value, worded for the reader in the session language.

    The shared field contract raises English sentences meant for a log or an
    API client; the writer applies it again, against the row's category,
    after the importer's own check, so a category that narrows the choices
    a location offers arrives here too.
    """
    column = mapping.get(_FIELD_PREFIX + exc.field_key) or exc.field_key
    if exc.options is not None:
        return ServiceRejectionError(
            'import_column_not_in_options',
            column=column,
            value=exc.value,
            options=', '.join(exc.options),
        )
    return ServiceRejectionError('import_column_field_shape', column=column)


def _field_values(
    ctx: '_ImportContext',
    row: pd.Series,
    storage_id: UUID,
    category_id: UUID | None = None,
    *,
    require_filled: bool = False,
) -> dict[str, Any]:
    """The mapped field columns the row's location and category ask for, typed.

    A field set on a warehouse applies to every shelf inside it, so the
    fields come from the location and every level above; the row's category
    adds its own, and where both define a key the category's definition wins,
    as it does when the writer checks the product. A mapped column
    for a field the row's location does not have is not this product's: a
    sheet spanning two warehouses carries the columns of both. Money and
    file fields are not offered for mapping — a cell has no currency or
    upload to give them.

    ``require_filled`` is what a new product owes the form that would have
    created it: a field left empty refuses the row rather than import a
    product the form's own required check refuses. That check asks for the
    fields the form shows and requires both — a hidden field is never
    offered, so no product can be asked for it — and the definition here is
    the effective one (the nearest level that sets the key), the same list
    the form reads. An update writes the columns it is given and leaves the
    rest as they stand, so it leaves the requirement off — a half sheet is
    a half update, not a wipe the form would have refused row by row.
    """
    mapped = {
        key.removeprefix(_FIELD_PREFIX): key
        for key, column in ctx.mapping.items()
        if key.startswith(_FIELD_PREFIX) and column
    }
    values: dict[str, object] = {}
    definitions = {
        **ctx.locations.index.fields_of(storage_id),
        **(ctx.category_fields.get(category_id, {}) if category_id else {}),
    }
    for key, definition in definitions.items():
        mapping_key = mapped.get(key)
        unfillable = definition.get('type') in ('money', 'file')
        if mapping_key is not None and not unfillable:
            text = _cell_text(_row_get(row, ctx.mapping, mapping_key))
            if text is not None:
                values[key] = _field_value(
                    definition, row, ctx.mapping, mapping_key, text, ctx.sheet
                )
                continue
        # What the row owes is what the form asks for: the form's own
        # required check runs over shown and required together, so a field
        # the definition hides is never offered and no row can leave it
        # empty. `visible` reads as shown where a definition never set it —
        # the wire fills it so.
        if (
            require_filled
            and definition.get('required')
            and definition.get('visible', True)
        ):
            label = definition.get('label') or key
            if unfillable:
                raise ServiceRejectionError(
                    'import_field_required_unreadable', field=label
                )
            if mapping_key is None:
                raise ServiceRejectionError(
                    'import_field_required_no_column', field=label
                )
            raise ServiceRejectionError(
                'import_column_field_required', column=ctx.mapping[mapping_key]
            )
    return values


@dataclass
class _Shelf:
    """One record a row asks for: where, and how much."""

    cells: list[tuple[str, str]]
    #: ``None`` reads the mapped quantity column.
    quantity: Decimal | None = None


def _location_cells(ctx: '_ImportContext', row: pd.Series) -> list[tuple[str, str]]:
    """The row's filled location cells, as (column, text), outermost first."""
    cells = []
    for key in ('location', 'sublocation'):
        column = ctx.mapping.get(key)
        text = _cell_text(row.get(column)) if column and column in row else None
        if column and text:
            cells.append((column, text))
    return cells


def _shelves(ctx: '_ImportContext', row: pd.Series) -> list[_Shelf]:
    """The records a row asks for; none when it names a product without stock.

    A sheet with a quantity column per location gives one record for every
    column that holds some. Otherwise the row is one record, unless the sheet
    has no quantity column and the reader did not ask for one of each.
    """
    per_location = [
        (key.removeprefix(STOCK_AT_PREFIX), column)
        for key, column in ctx.mapping.items()
        if key.startswith(STOCK_AT_PREFIX) and column
    ]
    if not per_location:
        if ctx.mapping.get('quantity') or ctx.count_as_one:
            return [_Shelf(_location_cells(ctx, row))]
        return []
    shelves = []
    for location, column in per_location:
        quantity = _number_from_cell(
            row,
            ctx.mapping,
            f'{STOCK_AT_PREFIX}{location}',
            None,
            ctx.sheet,
        )
        if quantity:
            shelves.append(_Shelf([(column, location)], quantity))
    return shelves


async def _build_item(
    ctx: '_ImportContext',
    row: pd.Series,
    identity: RowIdentity,
    storage_id: UUID,
    category_id: UUID | None,
    quantity: Decimal | None,
) -> tuple[ItemCreate, bool]:
    """One record of a row as the create endpoint would have received it.

    Also says whether the record joins a product that already existed.
    """
    mapping = ctx.mapping
    org_id = ctx.user.organization_id
    if org_id is None:
        raise ServiceRejectionError('user_has_no_organization')
    assert identity.name is not None
    barcode, brand = identity.barcode, identity.brand
    description = _description_from_cell(row, mapping)
    uom_id = await _resolve_unit(ctx, row)
    product = await product_of_a_record(
        ctx.db,
        ctx.user,
        org_id,
        name=identity.name,
        brand=brand,
        barcode=barcode,
        sku=identity.sku,
        description=description,
        uom_id=uom_id,
    )
    item_in = ItemCreate(
        name=product.name,
        location_id=storage_id,
        category_id=category_id,
        template_id=product.template_id,
        sku=product.sku,
        description=description,
        min_quantity=_min_quantity_from_cell(row, mapping, ctx.sheet),
        quantity=quantity
        if quantity is not None
        else _quantity_from_cell(row, mapping, ctx.sheet),
        brand=brand,
        barcode=barcode,
        serial_number=_cell_text(_row_get(row, mapping, 'serial_number')),
        purchase_price=_number_from_cell(
            row, mapping, 'purchase_price', None, ctx.sheet
        ),
        uom_id=uom_id,
        expiry_date=_parse_date_cell(row, mapping, 'expiry_date', ctx.sheet),
        freeze_date=_parse_date_cell(row, mapping, 'freeze_date', ctx.sheet),
        # A new product owes the form's required check: a row that leaves a
        # field its location requires empty is refused, not imported.
        metadata=_field_values(ctx, row, storage_id, category_id, require_filled=True)
        or None,
    )
    return item_in, product.exists


@dataclass
class _ImportContext:
    """Per-call shared state for the import loop: caches, mapping, user, db."""

    db: AsyncSession
    user: UserContextDTO
    mapping: dict[str, Any]
    sheet: SheetColumns
    locations: SheetLocations
    category_cache: dict[str, UUID]
    category_fields: dict[UUID, dict[str, dict[str, Any]]]
    create_missing_categories: bool
    count_as_one: bool = False
    on_label_match: LabelMatch = 'add'
    existing: ExistingStock = field(default_factory=ExistingStock)
    uom_cache: dict[str, UUID | None] = field(default_factory=dict)
    uom_resolver: 'UomResolverAsync | None' = None
    created_categories: list[str] = field(default_factory=list)
    # What the row in progress added to the shared caches. The savepoint
    # rolls back its INSERTs, not these in-memory maps — a stale id would
    # FK-fail every later row reusing the same name.
    row_categories: list[str] = field(default_factory=list)

    def begin_row(self) -> None:
        self.locations.row_founded.clear()
        self.row_categories.clear()

    def discard_row(self) -> None:
        self.locations.discard_row()
        for key in self.row_categories:
            self.category_cache.pop(key, None)
        if self.row_categories:
            del self.created_categories[-len(self.row_categories) :]
        self.begin_row()


class _RowResult:
    """What one import row became: a product, an update, a pass, a refusal."""

    __slots__ = ('outcome', 'error', 'records', 'joined_existing')

    def __init__(
        self,
        *,
        outcome: Literal['imported', 'updated', 'skipped', 'failed'],
        error: dict[str, Any] | None = None,
        records: int = 1,
        joined_existing: int = 0,
    ) -> None:
        self.outcome = outcome
        self.error = error
        #: How many records the row became (a product without stock counts one).
        self.records = records
        #: How many of them joined a product that already existed.
        self.joined_existing = joined_existing


async def _record_to_overwrite(
    ctx: _ImportContext, row: pd.Series, found: list[StockRecord], name: str
) -> UUID:
    """The one record of those the row names that it is written onto.

    Several records of one product are told apart by the location the row
    names, an empty one set aside; a row that cannot tell them apart is
    refused.
    """
    records = [record for record in found if record.quantity > 0] or found
    if len(records) > 1 and (cells := _location_cells(ctx, row)):
        location_id = await ctx.locations.resolve(cells)
        records = [record for record in records if record.location_id == location_id]
    if len(records) != 1:
        raise ServiceRejectionError(
            'import_overwrite_several_records', name=name, count=len(found)
        )
    return records[0].item_id


async def _overwrite_existing(
    ctx: _ImportContext, row: pd.Series, item_id: UUID, name: str, sku: str | None
) -> _RowResult:
    """Write the row's columns onto the record the row names.

    Only mapped columns carrying a value are written — an unmapped or empty
    cell leaves the field as it was, so a sheet holding half the columns is
    a half update rather than a wipe. Quantity never travels this way (see
    ``_OVERWRITABLE``); a location or unit does, and ``update_item`` moves
    the stock or refuses the swap the same as it would for the form.
    """
    item = await ctx.db.get(Item, item_id)
    if item is None:  # deleted between the preload and this row
        return _RowResult(outcome='skipped')

    changes: dict[str, object] = {'name': name}
    for key in _OVERWRITABLE_TEXT:
        value = _cell_text(_row_get(row, ctx.mapping, key))
        if value is not None:
            changes[key] = value
    if _cell_text(_row_get(row, ctx.mapping, 'purchase_price')) is not None:
        changes['purchase_price'] = _number_from_cell(
            row, ctx.mapping, 'purchase_price', None, ctx.sheet
        )
    if sku is not None:
        changes['sku'] = sku
    description = _description_from_cell(row, ctx.mapping)
    if description is not None:
        changes['description'] = description
    min_quantity = _min_quantity_from_cell(row, ctx.mapping, ctx.sheet)
    if min_quantity is not None:
        changes['min_quantity'] = min_quantity
    for key in ('expiry_date', 'freeze_date'):
        parsed = _parse_date_cell(row, ctx.mapping, key, ctx.sheet)
        if parsed is not None:
            changes[key] = parsed
    uom_id = await _resolve_unit(ctx, row)
    if uom_id is not None:
        changes['uom_id'] = uom_id
    category_id = await _resolve_or_create_category(ctx, row)
    if category_id is not None:
        changes['category_id'] = category_id
    storage_id = item.storage_location_id
    if cells := _location_cells(ctx, row):
        storage_id = await ctx.locations.resolve(cells)
        changes['location_id'] = storage_id
    fields = _field_values(ctx, row, storage_id, category_id or item.category_id)
    if fields:
        changes['metadata'] = {**(item.meta_data or {}), **fields}

    await update_item(ctx.db, item, ItemUpdate(**changes), ctx.user)
    return _RowResult(outcome='updated')


async def _process_import_row(
    ctx: _ImportContext, row: pd.Series, index: int
) -> _RowResult:
    """Process one import row. Captures per-row errors so the batch can continue."""
    # Data rows from 1, the header not counted — the way the preview above
    # the result numbers them, so "row 3" names the same row on both screens.
    row_num = index + 1
    ctx.begin_row()
    try:
        # Wrap the whole row in a savepoint (pattern: _bulk_update.py).
        # A failure after the item was flushed rolls the flushed row back: left
        # in the session, the batch commit would persist it while the per-row
        # ``except`` reports the row as failed — a phantom item with no
        # StockQuant. A failed row rolls back its item; storage and
        # category rows founded by it persist only on the refusal paths
        # inside (by design — they are shared org data), never on the
        # exception path.
        async with ctx.db.begin_nested():
            result = await _import_one_row(ctx, row, row_num)
    except Exception as e:  # noqa: BLE001 — per-row import errors are captured so the batch can continue
        ctx.discard_row()
        if isinstance(e, FieldValueError):
            e = _field_value_refusal(ctx.mapping, e)
        return _RowResult(
            outcome='failed',
            error={'row': row_num, 'error': _explain(e, ctx.mapping)},
        )
    return result


async def _import_one_row(
    ctx: _ImportContext, row: pd.Series, row_num: int
) -> _RowResult:
    if not _cell_text(_row_get(row, ctx.mapping, 'name')):
        return _RowResult(
            outcome='failed',
            error={
                'row': row_num,
                'error': str(ServiceRejectionError('import_line_name_missing')),
            },
        )

    identity = await row_identity(ctx.db, ctx.user.organization_id, ctx.mapping, row)
    name = identity.name
    assert name is not None
    if ctx.on_label_match != 'add' and (found := ctx.existing.named_by_code(identity)):
        if ctx.on_label_match == 'skip':
            return _RowResult(outcome='skipped')
        record_id = await _record_to_overwrite(ctx, row, found, name)
        return await _overwrite_existing(ctx, row, record_id, name, identity.sku)

    shelves = _shelves(ctx, row)
    if not shelves:
        return await _import_product_alone(ctx, row, identity)

    category_id = await _resolve_or_create_category(ctx, row)
    joined = 0
    for shelf in shelves:
        storage_id = await ctx.locations.resolve(shelf.cells)
        item_in, exists = await _build_item(
            ctx, row, identity, storage_id, category_id, shelf.quantity
        )
        await _file_the_record(ctx, item_in)
        joined += exists
    return _RowResult(outcome='imported', records=len(shelves), joined_existing=joined)


async def _import_product_alone(
    ctx: _ImportContext, row: pd.Series, identity: RowIdentity
) -> _RowResult:
    """A row without stock: the product only, nothing on a shelf.

    Location, category, price, serial number and dates describe stock, so
    they are not read.
    """
    if ctx.user.organization_id is None:
        raise ServiceRejectionError('user_has_no_organization')
    assert identity.name is not None
    added = await add_product_without_stock(
        ctx.db,
        ctx.user,
        ctx.user.organization_id,
        name=identity.name,
        brand=identity.brand,
        barcode=identity.barcode,
        sku=identity.sku,
        description=_description_from_cell(row, ctx.mapping),
        uom_id=await _resolve_unit(ctx, row),
        min_quantity=_min_quantity_from_cell(row, ctx.mapping, ctx.sheet),
    )
    return _RowResult(outcome='imported' if added else 'skipped')


async def _file_the_record(ctx: _ImportContext, item_in: ItemCreate) -> None:
    """Create one record through the door the form uses."""
    from app.core.period_guard import check_period_not_closed
    from app.services.analytics._common import org_today_async

    # A code names the product, not the row: two rows may carry one code and
    # become two states of the shared template, at two shelves or one. The
    # shared door below refuses the real collision — a code worn by another
    # product's live record — by name, the same refusal the form gives.
    #
    # Import adds new stock — block when the current period is closed so
    # month-end reconciliation isn't undermined by late CSV imports. Closed
    # is decided on the organization's day, not the server's. The check
    # runs BEFORE the item exists — a closed period must reject the row
    # before anything is written.
    if ctx.user.organization_id is not None:
        await check_period_not_closed(
            ctx.db,
            ctx.user.organization_id,
            await org_today_async(ctx.db, ctx.user.organization_id),
        )

    # A sheet column that names a unit is the importer's own explicit choice,
    # not a field nobody filled: it is the same deliberate answer the form
    # collects a confirmation for. The create path records it in the record's
    # history only where it actually differs from the matched template's unit —
    # a flag spent on a row that agrees is not a choice and writes no row.
    await create_item_async(
        ctx.db, item_in, ctx.user, unit_confirmed_over_template=True
    )
