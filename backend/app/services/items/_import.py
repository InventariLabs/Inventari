"""Bulk item import — XLSX/CSV parsing, row resolution, per-row processing.

Every row goes through ``create_item_async``, the same door the form and a
document use: that is where a product gets its template, its unit and its
stock entry. An importer that built ``Item(**data)`` itself produced
products the products list counted and the stock screen had never heard of.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Literal
from uuid import UUID

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.core.exceptions import ServiceRejectionError
from app.core.import_sheet import cell_text as _cell_text
from app.core.import_sheet import explain as _explain
from app.core.import_sheet import read_rows
from app.core.import_sheet import row_get as _row_get
from app.core.logging import get_logger
from app.i18n.service import get_unit_label
from app.models.category import Category
from app.models.item import Item
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.schemas.category import CategoryFieldDefinition
from app.schemas.item import ItemCreate, ItemUpdate
from app.services.fields.validation import FieldValueError, validate_field_value

from ._create import create_item_async
from ._template import find_template_async
from ._update import update_item

logger = get_logger(__name__)

#: The app writes a location as "Pantry → Dry Goods → Shelf A"; a keyboard
#: writes the arrow as "->" or ">". All three read as the same path.
_PATH_SEPARATORS = ('→', '->', '>')
_PATH_ARROW = ' → '

#: What a row does when its Label Code names a product the organization
#: already has. 'add' is what the import always did — the code is ignored and
#: the row becomes a new product; 'skip' leaves the product alone; 'overwrite'
#: writes the row's other columns onto it.
LabelMatch = Literal['add', 'skip', 'overwrite']

#: Plain-text fields an overwrite writes back. Quantity is deliberately
#: absent from every overwrite: stock moves through the ledger (a receipt, a
#: count), never through a spreadsheet cell overwriting a number the movement
#: ledger and the valuation layers also account for.
_OVERWRITABLE_TEXT = ('brand', 'barcode', 'serial_number')

#: A mapping key naming a product field a location sets ("field:supplier"),
#: as opposed to one of the fixed system columns above.
_FIELD_PREFIX = 'field:'

#: How a sheet says yes or no to a yes/no field, in the five languages.
_YES = frozenset({'1', 'true', 'yes', 'y', 'x', 'tak', 'ja', 'oui', 'si', 'sí'})
_NO = frozenset({'0', 'false', 'no', 'n', 'nie', 'nein', 'non'})


#: Rows imported between two progress reports.
_BATCH_ROWS = 50


async def import_items(
    db: AsyncSession,
    file_content: bytes,
    filename: str,
    mapping: dict,
    user: UserContextDTO,
    create_missing_locations: bool = True,
    create_missing_categories: bool = True,
    on_label_match: LabelMatch = 'add',
    on_batch: Callable[[int], Awaitable[None]] | None = None,
) -> dict:
    """Import items from XLSX or CSV file based on column mapping.

    ``on_batch`` is told how many rows have been read each time a batch is
    done, for a caller that shows the import's progress. Nothing here
    commits: a caller that holds a session of its own (the background job)
    commits the batch there, a request commits the import with its response.

    ``on_label_match`` decides what happens to a row whose Label Code — the
    code the export sheet carries — names a product already in the
    organization: nothing ('add', the historical behaviour), leave it alone
    ('skip') or write the row's other columns onto it ('overwrite'). A row
    without a code, or with one the organization does not know, always
    becomes a new product.
    """
    df = read_rows(file_content, filename)

    ctx = _ImportContext(
        db=db,
        user=user,
        mapping=mapping,
        storages=await _preload_storage_index(db, user.organization_id),
        category_cache=await _preload_category_cache(db, user.organization_id),
        category_fields=await _preload_category_fields(db, user.organization_id),
        default_storage_type_id=await _default_storage_type_id(
            db, user.organization_id
        ),
        create_missing_locations=create_missing_locations,
        create_missing_categories=create_missing_categories,
        on_label_match=on_label_match,
        labels=await _preload_label_codes(db, user.organization_id)
        if on_label_match != 'add'
        else {},
    )

    imported = 0
    joined_existing = 0
    updated = 0
    skipped = 0
    failed = 0
    errors: list[dict] = []

    for index, row in df.iterrows():
        row_result = await _process_import_row(ctx, row, index)
        if row_result.error is not None:
            failed += 1
            errors.append(row_result.error)
        if row_result.outcome == 'skipped':
            skipped += 1
        elif row_result.outcome in ('imported', 'updated'):
            if row_result.outcome == 'imported':
                imported += 1
                joined_existing += row_result.joined_existing
            else:
                updated += 1
            if (imported + updated) % _BATCH_ROWS == 0 and on_batch is not None:
                await on_batch(int(index) + 1)

    return {
        'total': len(df),
        'imported': imported,
        'joined_existing': joined_existing,
        'updated': updated,
        'skipped': skipped,
        'failed': failed,
        'errors': errors[:10],
        'created_locations': ctx.created_locations,
        'created_categories': ctx.created_categories,
    }


class _StorageIndex:
    """The organization's locations, by name and by place in the tree.

    A bare name matches any location carrying it (the first one seen), a
    path matches segment by segment from the root — so "Shelf A" and
    "Pantry → Dry Goods → Shelf A" both find the shelf, and a path whose
    tail is missing knows which parent to grow it under.
    """

    def __init__(self) -> None:
        self._children: dict[tuple[UUID | None, str], UUID] = {}
        self._by_name: dict[str, UUID] = {}
        self._name: dict[UUID, str] = {}
        self._parent: dict[UUID, UUID | None] = {}
        self._fields: dict[UUID, list[dict]] = {}

    @staticmethod
    def _key(name: str) -> str:
        return name.strip().lower()

    def add(
        self,
        loc_id: UUID,
        name: str,
        parent_id: UUID | None,
        fields: list[dict] | None = None,
    ) -> None:
        self._children[(parent_id, self._key(name))] = loc_id
        self._by_name.setdefault(self._key(name), loc_id)
        self._name[loc_id] = name
        self._parent[loc_id] = parent_id
        self._fields[loc_id] = fields or []

    def remove(self, loc_id: UUID) -> None:
        """Forget a location whose INSERT was rolled back."""
        name = self._name.pop(loc_id, None)
        parent_id = self._parent.pop(loc_id, None)
        self._fields.pop(loc_id, None)
        if name is None:
            return
        self._children.pop((parent_id, self._key(name)), None)
        if self._by_name.get(self._key(name)) == loc_id:
            del self._by_name[self._key(name)]

    def child(self, parent_id: UUID | None, name: str) -> UUID | None:
        return self._children.get((parent_id, self._key(name)))

    def by_name(self, name: str) -> UUID | None:
        return self._by_name.get(self._key(name))

    def path_of(self, loc_id: UUID) -> str:
        names: list[str] = []
        seen: set[UUID] = set()
        current: UUID | None = loc_id
        while current is not None and current not in seen:
            seen.add(current)
            names.append(self._name.get(current, ''))
            current = self._parent.get(current)
        return _PATH_ARROW.join(reversed(names))

    def fields_of(self, loc_id: UUID) -> dict[str, dict]:
        """The product fields a location asks for: its own and every level's above.

        The rule the storages listing and the form follow: the nearest level
        that defines a key gives it, so the location's own definition wins
        over its rack's and the rack's over the warehouse's. A location this
        import founds sets nothing itself and still inherits.
        """
        fields: dict[str, dict] = {}
        seen: set[UUID] = set()
        current: UUID | None = loc_id
        while current is not None and current not in seen:
            seen.add(current)
            for definition in self._fields.get(current, []):
                key = definition.get('key') if isinstance(definition, dict) else None
                if key:
                    fields.setdefault(key, definition)
            current = self._parent.get(current)
        return fields


async def _preload_storage_index(
    db: AsyncSession, org_id: UUID | None
) -> _StorageIndex:
    index = _StorageIndex()
    if org_id is None:
        return index
    result = await db.execute(
        select(StorageLocation)
        .where(StorageLocation.organization_id == org_id)
        .order_by(StorageLocation.created_at, StorageLocation.name)
    )
    for s in result.scalars().all():
        index.add(s.id, s.name, s.parent_id, s.field_definitions)
    return index


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
) -> dict[UUID, dict[str, dict]]:
    """Each category's own product fields, by category id and field key.

    A category asks for fields of its own ("Thread size" on Fasteners), and
    the writer refuses a product of that category that leaves a required one
    empty — so the import has to be able to fill them. Platform fields (the
    ones with a column of their own) are not metadata and stay out; so do
    money and file fields, which a cell cannot carry — the writer's own
    refusal of a value that does not fit them still applies.
    """
    fields: dict[UUID, dict[str, dict]] = {}
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


async def _preload_label_codes(
    db: AsyncSession, org_id: UUID | None
) -> dict[str, UUID]:
    """Every label code in the org, lowercased, to the product carrying it.

    Read once so a thousand-row sheet asks the database once, the way the
    barcode and category caches do.
    """
    if org_id is None:
        return {}
    result = await db.execute(
        select(Item.label_code, Item.id).where(
            Item.organization_id == org_id,
            Item.label_code.is_not(None),
            Item.is_deleted.is_(False),
        )
    )
    return {code.strip().lower(): item_id for code, item_id in result.all() if code}


async def _default_storage_type_id(
    db: AsyncSession, org_id: UUID | None
) -> UUID | None:
    """The StorageType a freshly-founded location gets.

    Prefers the org's own types; falls back to a global (org_id IS NULL) type;
    None when no type exists at all.
    """
    if org_id is None:
        return None
    own = await db.scalar(
        select(StorageType.id).where(StorageType.organization_id == org_id).limit(1)
    )
    if own:
        return own
    return await db.scalar(
        select(StorageType.id).where(StorageType.organization_id.is_(None)).limit(1)
    )


def _split_path(text: str) -> list[str]:
    for separator in _PATH_SEPARATORS:
        text = text.replace(separator, '\x00')
    return [part.strip() for part in text.split('\x00') if part.strip()]


async def _resolve_storage(ctx: '_ImportContext', row: pd.Series) -> UUID:
    """Where the row's product goes; raises a refusal when nowhere."""
    col = ctx.mapping.get('location')
    text = _cell_text(row.get(col)) if col and col in row else None
    if text:
        found = await _walk_path(ctx, _split_path(text), create=False)
        if found is not None:
            return found
        if ctx.create_missing_locations:
            return await _walk_path(ctx, _split_path(text), create=True)  # type: ignore[return-value]
        raise ServiceRejectionError(
            'import_column_location_not_found', column=col, value=text
        )

    if ctx.default_storage_id is None:
        ctx.default_storage_id = await ctx.db.scalar(
            select(StorageLocation.id)
            .where(StorageLocation.organization_id == ctx.user.organization_id)
            .order_by(StorageLocation.created_at)
        )
    if ctx.default_storage_id is None:
        raise ServiceRejectionError('import_location_unresolved')
    return ctx.default_storage_id


async def _walk_path(
    ctx: '_ImportContext', segments: list[str], *, create: bool
) -> UUID | None:
    """Follow a path down the tree, founding what is missing when allowed.

    The first segment may sit anywhere in the tree (a reader may start the
    path below the root); every later one must be a child of the one before.
    """
    parent_id: UUID | None = None
    for position, name in enumerate(segments):
        found = ctx.storages.child(parent_id, name)
        if found is None and position == 0:
            found = ctx.storages.by_name(name)
        if found is None:
            if not create:
                return None
            found = await _found_location(ctx, name, parent_id)
        parent_id = found
    return parent_id


async def _found_location(
    ctx: '_ImportContext', name: str, parent_id: UUID | None
) -> UUID:
    location = StorageLocation(
        name=name,
        organization_id=ctx.user.organization_id,
        storage_type_id=ctx.default_storage_type_id,
        created_by=ctx.user.id,
        parent_id=parent_id,
    )
    ctx.db.add(location)
    await ctx.db.flush()
    ctx.storages.add(location.id, name, parent_id)
    ctx.row_locations.append(location.id)
    ctx.created_locations.append(ctx.storages.path_of(location.id))
    return location.id


async def _resolve_or_create_category(
    ctx: '_ImportContext', row: pd.Series
) -> UUID | None:
    """The category_id for a row, founding one when allowed — else refusing.

    An unknown category with founding off used to come back as ``None``:
    the row imported with no category at all and was counted a success,
    while the same sheet naming an unknown shelf was refused. One question,
    one answer — the refusal names the column and the cell, as the
    location's does.
    """
    cat_col = ctx.mapping.get('category')
    c_name = _cell_text(row.get(cat_col)) if cat_col and cat_col in row else None
    if not c_name:
        return None
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
    row: pd.Series, mapping: dict, key: str, default: Decimal | None
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
        return Decimal(text)
    except InvalidOperation:
        raise ServiceRejectionError(
            'import_column_not_a_number', column=mapping[key], value=text
        ) from None


def _quantity_from_cell(row: pd.Series, mapping: dict) -> Decimal:
    """The row's quantity: 1 when the sheet has no quantity column at all.

    A column the reader mapped to quantity and left blank in this row is a
    gap, not an answer: it used to import as 1 with no word in the result,
    a stock figure nobody typed. The row is refused and says so.
    """
    if not mapping.get('quantity'):
        return Decimal('1.0')
    quantity = _number_from_cell(row, mapping, 'quantity', None)
    if quantity is None:
        raise ServiceRejectionError(
            'import_column_quantity_blank', column=mapping['quantity']
        )
    return quantity


async def _resolve_unit(ctx: '_ImportContext', row: pd.Series) -> UUID | None:
    """The unit the sheet names, by symbol — 'kg', 'pcs', the org's own."""
    from app.core.uom_resolver import UomResolverAsync
    from app.services.uom_service import get_uom_by_symbol_async

    col = ctx.mapping.get('unit')
    symbol = _cell_text(row.get(col)) if col and col in row else None
    if not symbol:
        return None
    if symbol not in ctx.uom_cache:
        uom = await get_uom_by_symbol_async(
            ctx.db, symbol, ctx.user.organization_id
        ) or await get_uom_by_symbol_async(
            ctx.db, symbol.lower(), ctx.user.organization_id
        )
        # The app writes a piece as "szt." and a keyboard writes "szt": the
        # resolver the other imports use reads both, and the aliases too.
        org_id = ctx.user.organization_id
        if uom is None and org_id is not None:
            found = await UomResolverAsync(ctx.db, org_id).resolve(symbol)
        else:
            found = uom.id if uom else None
        # The refusal lists units by the label the app shows ("Packung"), so
        # that spelling has to import too.
        if found is None:
            found = (await _unit_labels(ctx)).get(_label_key(symbol))
        ctx.uom_cache[symbol] = found
    uom_id = ctx.uom_cache[symbol]
    if uom_id is None:
        raise ServiceRejectionError(
            'import_unknown_unit',
            column=col,
            value=symbol,
            units=await _known_units(ctx),
        )
    return uom_id


def _label_key(text: str) -> str:
    return text.strip().rstrip('.').lower()


async def _unit_labels(ctx: '_ImportContext') -> dict[str, UUID]:
    """Unit id by the label the app shows for it, in the session language."""
    from app.services.uom_service import list_uoms_for_org_async

    org_id = ctx.user.organization_id
    if org_id is None:
        return {}
    uoms = await list_uoms_for_org_async(ctx.db, org_id)
    # Organization units win over a system unit that shares the label.
    uoms.sort(key=lambda u: u.organization_id is not None)
    return {_label_key(get_unit_label(u.symbol)): u.id for u in uoms}


async def _known_units(ctx: '_ImportContext') -> str:
    """The units a sheet may name, as the app writes them, for the refusal."""
    from app.services.uom_service import list_uoms_for_org_async

    org_id = ctx.user.organization_id
    if org_id is None:
        return ''
    uoms = await list_uoms_for_org_async(ctx.db, org_id)
    return ', '.join(sorted({get_unit_label(u.symbol) for u in uoms}))


def _parse_date_cell(row: pd.Series, mapping: dict, key: str) -> date | None:
    """Read and parse a mapped date column (expiry, freeze), or refuse the cell.

    Not app.core.datetimes.parse_iso_date: the input is a spreadsheet cell,
    which may already be a datetime and otherwise needs pandas' lenient
    parsing of whatever the user typed. Item import is its only caller.

    A cell the parser cannot read refuses the row with the column and the
    cell, the way quantity and location word theirs: it used to be logged
    and dropped, so the term the reader had typed vanished under a report
    of zero failures and the product stayed off every expiring-soon screen.
    """
    raw = _row_get(row, mapping, key)
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    text = _cell_text(raw)
    if text is None:
        return None
    column = mapping[key]
    try:
        parsed = pd.to_datetime(text)
    except (KeyError, ValueError, TypeError, OSError) as exc:
        logger.warning('Failed to parse %s: %s', key, exc)
        raise ServiceRejectionError(
            'import_date_invalid', column=column, value=text
        ) from None
    if pd.isna(parsed):
        raise ServiceRejectionError('import_date_invalid', column=column, value=text)
    return parsed.date()


def _field_value(
    definition: dict, row: pd.Series, mapping: dict, key: str, text: str
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
        value = text.replace(',', '.')
        try:
            Decimal(value)
        except InvalidOperation:
            raise ServiceRejectionError(
                'import_column_not_a_number', column=column, value=text
            ) from None
    elif kind == 'date':
        parsed = _parse_date_cell(row, mapping, key)
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


def _field_value_refusal(mapping: dict, exc: FieldValueError) -> ServiceRejectionError:
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
) -> dict:
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
        **ctx.storages.fields_of(storage_id),
        **(ctx.category_fields.get(category_id, {}) if category_id else {}),
    }
    for key, definition in definitions.items():
        mapping_key = mapped.get(key)
        unfillable = definition.get('type') in ('money', 'file')
        if mapping_key is not None and not unfillable:
            text = _cell_text(_row_get(row, ctx.mapping, mapping_key))
            if text is not None:
                values[key] = _field_value(
                    definition, row, ctx.mapping, mapping_key, text
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


async def _build_item(
    ctx: '_ImportContext',
    row: pd.Series,
    name: str,
    storage_id: UUID,
    category_id: UUID | None,
) -> ItemCreate:
    """One row as the create endpoint would have received it."""
    mapping = ctx.mapping
    return ItemCreate(
        name=name,
        location_id=storage_id,
        category_id=category_id,
        quantity=_quantity_from_cell(row, mapping),
        brand=_cell_text(_row_get(row, mapping, 'brand')),
        barcode=_cell_text(_row_get(row, mapping, 'barcode')),
        serial_number=_cell_text(_row_get(row, mapping, 'serial_number')),
        purchase_price=_number_from_cell(row, mapping, 'purchase_price', None),
        uom_id=await _resolve_unit(ctx, row),
        expiry_date=_parse_date_cell(row, mapping, 'expiry_date'),
        freeze_date=_parse_date_cell(row, mapping, 'freeze_date'),
        # A new product owes the form's required check: a row that leaves a
        # field its location requires empty is refused, not imported.
        metadata=_field_values(ctx, row, storage_id, category_id, require_filled=True)
        or None,
    )


@dataclass
class _ImportContext:
    """Per-call shared state for the import loop: caches, mapping, user, db."""

    db: AsyncSession
    user: UserContextDTO
    mapping: dict
    storages: _StorageIndex
    category_cache: dict[str, UUID]
    category_fields: dict[UUID, dict[str, dict]]
    default_storage_type_id: UUID | None
    create_missing_locations: bool
    create_missing_categories: bool
    on_label_match: LabelMatch = 'add'
    labels: dict[str, UUID] = field(default_factory=dict)
    default_storage_id: UUID | None = None
    uom_cache: dict[str, UUID | None] = field(default_factory=dict)
    created_locations: list[str] = field(default_factory=list)
    created_categories: list[str] = field(default_factory=list)
    # What the row in progress added to the shared caches. The savepoint
    # rolls back its INSERTs, not these in-memory maps — a stale id would
    # FK-fail every later row reusing the same name.
    row_locations: list[UUID] = field(default_factory=list)
    row_categories: list[str] = field(default_factory=list)

    def begin_row(self) -> None:
        self.row_locations.clear()
        self.row_categories.clear()

    def discard_row(self) -> None:
        for loc_id in self.row_locations:
            self.storages.remove(loc_id)
        if self.row_locations:
            del self.created_locations[-len(self.row_locations) :]
        for key in self.row_categories:
            self.category_cache.pop(key, None)
        if self.row_categories:
            del self.created_categories[-len(self.row_categories) :]
        self.begin_row()


class _RowResult:
    """What one import row became: a product, an update, a pass, a refusal."""

    __slots__ = ('outcome', 'error', 'joined_existing')

    def __init__(
        self,
        *,
        outcome: Literal['imported', 'updated', 'skipped', 'failed'],
        error: dict | None = None,
        joined_existing: bool = False,
    ) -> None:
        self.outcome = outcome
        self.error = error
        #: The row became a record of a product that already existed.
        self.joined_existing = joined_existing


def _match_by_label(ctx: _ImportContext, row: pd.Series) -> UUID | None:
    """The product this row's Label Code names, when the mode asks for one.

    A row without a code, or with a code the organization does not know, has
    no match — it goes on to become a new product, exactly as before.
    """
    if ctx.on_label_match == 'add':
        return None
    code = _cell_text(_row_get(row, ctx.mapping, 'label_code'))
    if not code:
        return None
    return ctx.labels.get(code.strip().lower())


async def _overwrite_existing(
    ctx: _ImportContext, row: pd.Series, item_id: UUID, name: str
) -> _RowResult:
    """Write the row's columns onto the product its Label Code named.

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
            row, ctx.mapping, 'purchase_price', None
        )
    for key in ('expiry_date', 'freeze_date'):
        parsed = _parse_date_cell(row, ctx.mapping, key)
        if parsed is not None:
            changes[key] = parsed
    uom_id = await _resolve_unit(ctx, row)
    if uom_id is not None:
        changes['uom_id'] = uom_id
    category_id = await _resolve_or_create_category(ctx, row)
    if category_id is not None:
        changes['category_id'] = category_id
    storage_col = ctx.mapping.get('location')
    storage_id = item.storage_location_id
    if storage_col and _cell_text(row.get(storage_col)):
        storage_id = await _resolve_storage(ctx, row)
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
    row_num = index + 2  # +2 accounts for header row + 1-based numbering
    ctx.begin_row()
    try:
        # Wrap the whole row in a savepoint (pattern: _bulk_update.py).
        # A failure after the item was flushed used to leave the flushed row
        # in the session, where the batch commit silently persisted it while
        # the per-row ``except`` reported it as failed — a phantom item with
        # no StockQuant. A failed row now rolls back its item; storage and
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


async def _file_under_the_product_the_code_names(
    ctx: _ImportContext, item_in: ItemCreate
) -> bool:
    """A row matched to an existing product takes that product's name.

    Returns whether there was a match, so the result can say the row added
    stock to a product rather than making one.

    The create door joins a row to the product its barcode (or name and brand)
    names, and the record keeps the name the row happened to carry — a record
    called "Imported Tuna" filed under Plum Butter, on a list and in a search
    that show the name. The product's own name is the one every other record
    of it carries.
    """
    if ctx.user.organization_id is None:
        return False
    card = await find_template_async(
        ctx.db,
        ctx.user.organization_id,
        name=item_in.name,
        barcode=item_in.barcode,
        brand=item_in.brand,
    )
    if card is not None and card.name != item_in.name:
        item_in.name = card.name
    return card is not None


async def _import_one_row(
    ctx: _ImportContext, row: pd.Series, row_num: int
) -> _RowResult:
    from app.core.public_api import core_api
    from app.services.analytics._common import org_today_async

    name = _cell_text(_row_get(row, ctx.mapping, 'name'))
    if not name:
        return _RowResult(
            outcome='failed',
            error={
                'row': row_num,
                'error': str(ServiceRejectionError('import_line_name_missing')),
            },
        )

    matched = _match_by_label(ctx, row)
    if matched is not None:
        if ctx.on_label_match == 'skip':
            return _RowResult(outcome='skipped')
        return await _overwrite_existing(ctx, row, matched, name)

    storage_id = await _resolve_storage(ctx, row)
    category_id = await _resolve_or_create_category(ctx, row)
    item_in = await _build_item(ctx, row, name, storage_id, category_id)
    joined_existing = await _file_under_the_product_the_code_names(ctx, item_in)

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
        await core_api.periods.check_not_closed_async(
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
    return _RowResult(outcome='imported', joined_existing=joined_existing)
