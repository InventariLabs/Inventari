"""CSV/XLSX import for equipment assets — panda-based parsing + core_api writes."""

import re
import unicodedata
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

import pandas as pd
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import ItemCreateDTO, ItemUpdateDTO, UserContextDTO
from app.core.datetimes import DATE_FORMAT
from app.core.exceptions import (
    ServiceRejectionError,
    is_reader_facing_value_error,
    refusal_row,
)
from app.core.file_import import (
    analyze_import_file,
    resolve_category_async,
    resolve_storage_location_async,
)
from app.core.import_sheet import read_rows, row_text
from app.core.logging import get_logger

from ._import_dedup_service import find_item_by_serial_async
from ._serial import serial_of, without_serial
from .status_machine import validate_transition

logger = get_logger(__name__)

# Header aliases across the module's five languages plus
# common English variants. Matching is case-, diacritics- and space-insensitive.
_FIELD_ALIASES: dict[str, list[str]] = {
    'name': [
        'name',
        'asset name',
        'nazwa',
        'nazwa zasobu',
        'bezeichnung',
        'nom',
        'nombre',
    ],
    'serial_number': [
        'serial number',
        'serial',
        'sn',
        'numer seryjny',
        'nr seryjny',
        'seriennummer',
        'numéro de série',
        'numero de serie',
        'n.º de serie',
    ],
    'asset_tag': [
        'asset tag',
        'tag',
        'inventory number',
        'numer inwentarzowy',
        'inventarnummer',
        'étiquette',
        'etiqueta',
    ],
    # Brand and manufacturer name the same thing about an asset, and the
    # detail screen shows one field. A file may head that column either way.
    'brand': [
        'brand',
        'marka',
        'marke',
        'marque',
        'marca',
        'manufacturer',
        'producent',
        'hersteller',
        'fabricant',
        'fabricante',
    ],
    'model': ['model', 'modell', 'modèle', 'modelo'],
    'location': [
        'storage location',
        'location',
        'lokalizacja',
        'standort',
        'emplacement',
        'ubicación',
        'ubicacion',
    ],
    'category': [
        'category',
        'kategoria',
        'kategorie',
        'catégorie',
        'categoría',
        'categoria',
    ],
    'purchase_price': [
        'purchase price',
        'price',
        'cena zakupu',
        'kaufpreis',
        "prix d'achat",
        'precio de compra',
    ],
    'purchase_date': [
        'purchase date',
        'data zakupu',
        'kaufdatum',
        "date d'achat",
        'fecha de compra',
    ],
    'warranty_until': [
        'warranty until',
        'warranty',
        'gwarancja do',
        'garantie bis',
        "garantie jusqu'à",
        'garantía hasta',
        'garantia hasta',
    ],
    'notes': ['notes', 'notatki', 'notizen', 'remarques', 'notas'],
    'equipment_status': [
        'status',
        'equipment status',
        'état de l’équipement',
        'estado del equipo',
        'gerätestatus',
    ],
}


def _normalize_header(value: str) -> str:
    """Lowercase, strip diacritics and any non-alphanumeric characters."""
    decomposed = unicodedata.normalize('NFKD', value)
    ascii_only = ''.join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r'[^a-z0-9]', '', ascii_only.lower())


_FIELD_ALIAS_INDEX: dict[str, str] = {
    _normalize_header(alias): field
    for field, aliases in _FIELD_ALIASES.items()
    for alias in aliases
}


# A status cell as a person writes it: the stored code, or the label the
# list, the detail page and the add form print, in any language the app
# ships (frontend ``equipment`` catalogs, ``status.*``). An exported,
# edited and re-imported sheet carries the label, and every row of it was
# refused while only the upper-case code was understood. The catalogs are
# the source; a test reads each of them back through this list, so a label
# changed there and not here fails before it reaches a sheet.
_STATUS_WORDS: dict[str, list[str]] = {
    'AVAILABLE': ['available', 'dostępny', 'verfügbar', 'disponible', 'disponível'],
    'DEPLOYED': [
        'checked out',
        'wydany',
        'wydano',
        'ausgeliehen',
        'emprunté',
        'prestado',
        'entregue',
    ],
    'MAINTENANCE': [
        'maintenance',
        'w serwisie',
        'serwis',
        'wartung',
        'mantenimiento',
        'manutenção',
    ],
    'RETIRED': ['retired', 'wycofany', 'ausgemustert', 'retiré', 'retirado', 'baixado'],
}

_STATUS_INDEX: dict[str, str] = {
    _normalize_header(word): code
    for code, words in _STATUS_WORDS.items()
    for word in [code, *words]
}


def _sheet_status(row: Any, column: str | None) -> str | None:
    """A status cell as the stored code; an unknown word goes on as written,
    for the status gate to refuse by name.

    A blank cell, or no status column, is ``None``: the sheet says nothing
    about the status. It used to read as Available, so an update-mode import
    without the column took every matched asset out of maintenance; a new
    asset still arrives Available, seeded by the item interceptor.
    """
    text = row_text(row, column)
    if not text:
        return None
    return _STATUS_INDEX.get(_normalize_header(text), text)


def _sheet_date(row: Any, column: str | None) -> str | None:
    """A date column as a date, or a refusal naming the cell.

    The two date columns used to travel into ``meta_data`` as whatever text
    the sheet held, so "kiedys w maju" ended up in a field the rest of the
    module reads as a date — and the warranty column then printed "—", which
    is also what an asset with no warranty prints. A row the importer cannot
    read is a failed row, not a silent one.
    """
    text = row_text(row, column)
    if not text:
        return None
    try:
        return str(pd.to_datetime(text).date().strftime(DATE_FORMAT))
    except (ValueError, TypeError, OSError) as exc:
        raise ServiceRejectionError(
            'import_date_invalid', column=column, value=text
        ) from exc


def _sheet_price(row: Any, column: str | None) -> Decimal | None:
    """A price column as a number, or a refusal naming the cell.

    "ABC" used to be swallowed by an ``except InvalidOperation: pass`` and
    the row counted as imported, so the asset arrived with no price and
    nobody was told which cell was dropped.
    """
    text = row_text(row, column)
    if not text:
        return None
    try:
        return Decimal(text.replace(',', '.'))
    except InvalidOperation as exc:
        raise ServiceRejectionError(
            'import_price_invalid', column=column, value=text
        ) from exc


def _suggested_mapping(headers: list[str]) -> dict[str, str]:
    """Map canonical field names to the first header that matches an alias."""
    suggested: dict[str, str] = {}
    for header in headers:
        field = _FIELD_ALIAS_INDEX.get(_normalize_header(header))
        if field and field not in suggested:
            suggested[field] = header
    return suggested


async def analyze_equipment_import(content: bytes, filename: str) -> dict[str, Any]:
    """Headers, preview and row count, as every module's analyze reports them.

    The shared analyze parses the file once — the nrows preview plus a full
    second read for the count was the shape the core grew out of — and the
    suggested mapping rides on top, which is the only equipment-specific
    part of it.
    """
    base = await analyze_import_file(content, filename)
    return {**base, 'suggested_mapping': _suggested_mapping(base['headers'])}


async def execute_equipment_import(
    db: AsyncSession,
    content: bytes,
    filename: str,
    mapping: dict[str, Any],
    org_id: UUID,
    user: UserContextDTO,
    default_location_id: str | None = None,
    default_category_id: str | None = None,
) -> dict[str, Any]:
    """Import equipment items from a file with column mapping."""
    df = read_rows(content, filename)

    imported = 0
    failed = 0
    skipped = 0
    updated = 0
    errors: list[dict[str, Any]] = []
    skipped_serials: list[str] = []

    duplicate_mode = str(mapping.get('duplicate_mode') or 'create_only')

    location_cache: dict[str, str] = {}
    category_cache: dict[str, str] = {}

    for index, row in df.iterrows():
        # The row as the mapping preview numbers it: data rows from 1, the
        # header not counted. One numbering for the whole import screen —
        # the preview the reader picks the mapping on, and the refusals the
        # result screen lists.
        row_num = int(index) + 1
        try:
            outcome = await _process_row(
                db=db,
                row=row,
                mapping=mapping,
                org_id=org_id,
                user=user,
                default_location_id=default_location_id,
                default_category_id=default_category_id,
                duplicate_mode=duplicate_mode,
                location_cache=location_cache,
                category_cache=category_cache,
            )
        except (ValueError, SQLAlchemyError, InvalidOperation) as exc:
            if isinstance(exc, ValueError) and is_reader_facing_value_error(exc):
                # A refusal this codebase wrote, in the request's language.
                errors.append(refusal_row(exc, row=row_num))
            else:
                # A library's text (SQL, a DTO's name, echoed input) is not the
                # reader's to see: the traceback goes to the log, the row gets
                # the generic sentence.
                logger.exception('Import row %d failed', row_num)
                errors.append(
                    refusal_row(ServiceRejectionError('internal_error'), row=row_num)
                )
            failed += 1
            continue

        if outcome == 'failed_missing_name':
            errors.append(
                refusal_row(
                    ServiceRejectionError('import_asset_name_missing'), row=row_num
                )
            )
            failed += 1
        elif outcome == 'failed_missing_location':
            errors.append(
                refusal_row(
                    ServiceRejectionError('import_location_unresolved'), row=row_num
                )
            )
            failed += 1
        elif outcome == 'created':
            imported += 1
        elif outcome == 'updated':
            updated += 1
        elif outcome == 'skipped':
            skipped += 1
            serial = row_text(row, mapping.get('serial_number'))
            if serial:
                skipped_serials.append(serial)

    return {
        'imported': imported,
        'failed': failed,
        'skipped': skipped,
        'updated': updated,
        'errors': errors[:20],
        'skipped_serials': skipped_serials[:20],
    }


def _parse_id(value: str, error_key: str) -> UUID:
    """``UUID(value)``, with a malformed id refused in our words, not the library's."""
    try:
        return UUID(value)
    except (ValueError, TypeError, AttributeError):
        raise ServiceRejectionError(error_key) from None


async def _process_row(
    *,
    db: AsyncSession,
    row: Any,
    mapping: dict[str, Any],
    org_id: UUID,
    user: UserContextDTO,
    default_location_id: str | None,
    default_category_id: str | None,
    duplicate_mode: str,
    location_cache: dict[str, str],
    category_cache: dict[str, str],
) -> str:
    """Process one import row; returns the outcome as a string."""
    from app.core.public_api import core_api

    name = row_text(row, mapping.get('name'))
    if not name:
        return 'failed_missing_name'

    storage_location_id = await resolve_storage_location_async(
        db, org_id, row, mapping, default_location_id, location_cache
    )
    if not storage_location_id:
        location_text = row_text(row, mapping.get('location'))
        if location_text:
            # Name the cell: "could not resolve" alone left the reader to
            # guess which spelling of which place the sheet carried.
            raise ServiceRejectionError(
                'import_location_not_found', value=location_text
            )
        return 'failed_missing_location'

    category_id = await resolve_category_async(
        db, org_id, row, mapping, default_category_id, category_cache
    )

    equipment_meta: dict[str, Any] = {}
    for field in ('serial_number', 'asset_tag', 'model', 'notes'):
        val = row_text(row, mapping.get(field))
        if val:
            equipment_meta[field] = val

    for field in ('purchase_date', 'warranty_until'):
        parsed = _sheet_date(row, mapping.get(field))
        if parsed:
            equipment_meta[field] = parsed

    status = _sheet_status(row, mapping.get('equipment_status'))
    if status is not None:
        # The gate the other three write paths already ask. An imported asset
        # whose status is not one of the four reaches the list and the detail
        # card as a state badge spelling the raw cell, which is exactly what
        # UNKNOWN_STATUS was written to keep off a screen.
        validate_transition(None, status)
        equipment_meta['equipment_status'] = status

    purchase_price = _sheet_price(row, mapping.get('purchase_price'))

    # 'manufacturer' was a separate target until the two were merged; a
    # mapping saved before that still means the same column.
    brand = row_text(row, mapping.get('brand') or mapping.get('manufacturer'))

    # Match by serial number within the org before
    # writing. `duplicate` keeps the historical behaviour (blind copy).
    serial_number = equipment_meta.get('serial_number')
    if serial_number and duplicate_mode in ('create_only', 'update'):
        existing_item = await find_item_by_serial_async(db, org_id, serial_number)
        if existing_item is not None:
            if duplicate_mode == 'create_only':
                return 'skipped'
            await _apply_update_async(
                db,
                org_id,
                existing_item,
                name=name.strip(),
                brand=brand,
                equipment_meta=equipment_meta,
                purchase_price=purchase_price,
                user=user,
            )
            return 'updated'

    payload = ItemCreateDTO(
        name=name.strip(),
        location_id=_parse_id(storage_location_id, 'import_location_unresolved'),
        category_id=_parse_id(category_id, 'internal_error') if category_id else None,
        brand=brand or None,
        quantity=Decimal(1),
        purchase_price=purchase_price,
        serial_number=serial_number,
        metadata={'equipment': without_serial(equipment_meta)},
    )

    # The default writes the asset's movement and cost layer beside the
    # record, exactly as bulk create and POST /items do: an imported asset
    # without its movement reads as a reconciliation mismatch for the rest
    # of its life.
    await core_api.items.create_async(
        db,
        organization_id=org_id,
        data=payload,
        user=user,
    )
    return 'created'


async def _apply_update_async(
    db: AsyncSession,
    org_id: UUID,
    item: Any,
    *,
    name: str,
    brand: str | None,
    equipment_meta: dict[str, Any],
    purchase_price: Decimal | None,
    user: UserContextDTO,
) -> None:
    """update mode: merge imported equipment meta over the existing one."""
    from app.core.public_api import core_api

    existing_meta = dict(item.meta_data or {})
    existing_equipment = dict(existing_meta.get('equipment') or {})
    existing_equipment.update(equipment_meta)
    existing_meta['equipment'] = without_serial(existing_equipment)

    serial_number = equipment_meta.get('serial_number') or serial_of(item)

    await core_api.items.update_async(
        db,
        org_id,
        item.id,
        ItemUpdateDTO(
            name=name,
            brand=brand,
            metadata=existing_meta,
            purchase_price=purchase_price,
            serial_number=serial_number,
        ),
        user,
    )
