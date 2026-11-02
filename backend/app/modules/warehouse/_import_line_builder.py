"""Row-pipeline helpers for document import.

Split out of :mod:`document_import_service` to keep that module focused on the
public import entry points (``analyze_*`` / ``parse_*`` / ``import_*``). The
helpers here turn a single DataFrame row into a :class:`DocumentLine`,
resolving UoM symbols and ProductTemplate barcodes along the way.

They are re-imported by ``document_import_service`` and consumed by
``import_lines_from_dataframe``; not part of the module's public API.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID, uuid4

import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ServiceRejectionError
from app.core.import_sheet import cell_text
from app.core.logging import get_logger
from app.core.public_api import core_api
from app.core.uom_resolver import UomResolverAsync

from .models import DocumentLine

logger = get_logger(__name__)


def _extract_string(row: pd.Series, col_name: str | None) -> str | None:
    """Read a string column value as the reader typed it, or None when blank.

    Through the shared cell reader: a blank in a column pandas made numeric
    is NaN, not None, and ``str()`` of it is the word "nan" — which then
    passed for a product name, a barcode and a lot. A whole float goes back
    to its digits, so a barcode column with one blank keeps its barcodes.
    """
    if not col_name:
        return None
    return cell_text(row.get(col_name))


def _extract_decimal(
    row: pd.Series, col_name: str | None, *, default: Decimal | None = None
) -> Decimal | None:
    """Read a decimal column value, or ``default`` when the cell is blank.

    A cell that holds something other than a number refuses the row and
    names the column and the cell. It used to fall back to the default in
    silence, so "abc" in the quantity column imported as 1 and "tanio" in the
    price column as no price — and an opening balance built on that is wrong
    in a way nobody is told about.

    The refusal is a translated one: the screen showing it writes the row
    number in the reader's language and used to hand the rest of the line
    back in English.
    """
    if not col_name or row.get(col_name) is None:
        return default
    raw = row[col_name]
    if isinstance(raw, float) and raw != raw:  # NaN: a blank in a numeric column
        return default
    try:
        return Decimal(str(raw).strip())
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ServiceRejectionError(
            'import_column_not_a_number', column=col_name, value=raw
        ) from exc


def _extract_date(row: pd.Series, col_name: str | None) -> Any:
    """Read a date column value; accepts datetime, date string, or anything pd.to_datetime handles."""
    if not col_name:
        return None
    val = row.get(col_name)
    if val is None or pd.isna(val):
        return None
    if isinstance(val, datetime):
        return val.date()
    try:
        return pd.to_datetime(str(val)).date()
    except (ValueError, TypeError):
        logger.debug('Invalid %s value: %s', col_name, row.get(col_name))
        return None


async def _resolve_template_for_barcode(
    db: AsyncSession, org_id: UUID, barcode: str | None
) -> tuple[UUID | None, dict[str, Any] | None, UUID | None]:
    """Return (template_id, product_snapshot, template_uom_id) for a matching barcode.

    Returns (None, None, None) when no barcode is supplied or no template matches.
    """
    if not barcode:
        return None, None, None
    from app.core.barcode import normalize_barcode

    normalized = normalize_barcode(barcode) or barcode
    template = await core_api.product_templates.lookup_by_barcode_async(
        db, org_id, normalized
    )
    if not template:
        return None, None, None
    return (
        template.id,
        {
            'name': template.name,
            'brand': template.brand,
            'barcode': template.barcode,
            'uom_id': str(template.uom_id) if template.uom_id else None,
            'uom_symbol': None,
            'image_url': template.image_url,
        },
        template.uom_id,
    )


def _snapshot_of(template: Any) -> dict[str, Any]:
    return {
        'name': template.name,
        'brand': template.brand,
        'barcode': template.barcode,
        'uom_id': str(template.uom_id) if template.uom_id else None,
        'uom_symbol': None,
        'image_url': template.image_url,
    }


async def _resolve_template(
    db: AsyncSession,
    org_id: UUID,
    *,
    barcode: str | None,
    sku: str | None,
    name: str,
) -> tuple[UUID | None, dict[str, Any] | None, UUID | None]:
    """The product a row names: by barcode, then by SKU, then by its exact name.

    A sheet kept outside this app rarely carries barcodes; it carries the
    company's own codes and the names people use. Matching stopped at the
    barcode, so every such row imported as "unmatched" and, once posted,
    reached the shelf without a product, a movement or a cost layer.
    """
    found = await _resolve_template_for_barcode(db, org_id, barcode)
    if found[0] is not None:
        return found
    if sku:
        template = await core_api.product_templates.lookup_by_sku_async(db, org_id, sku)
        if template is None:
            # A code is a code whatever case the sheet keeps it in.
            template = await _ranked_exact(db, org_id, sku, field='sku')
        if template is not None:
            return template.id, _snapshot_of(template), template.uom_id
        # The app calls the barcode "Product code", so a column headed
        # "code" is read as the SKU and may hold barcodes all the same.
        found = await _resolve_template_for_barcode(db, org_id, sku)
        if found[0] is not None:
            return found
    template = await _ranked_exact(db, org_id, name, field='name')
    if template is not None:
        return template.id, _snapshot_of(template), template.uom_id
    return None, None, None


async def _ranked_exact(
    db: AsyncSession, org_id: UUID, wanted: str, *, field: str
) -> Any:
    """The template whose *field* equals *wanted* in any letter case, if one does."""
    key = wanted.strip().lower()
    for template in await core_api.product_templates.search_ranked_async(
        db, org_id, wanted, limit=5
    ):
        if (getattr(template, field, None) or '').strip().lower() == key:
            return template
    return None


async def _build_document_line(
    db: AsyncSession,
    org_id: UUID,
    doc_id: UUID | None,
    row: pd.Series,
    line_number: int,
    column_mapping: dict[str, Any],
    uom_resolver: UomResolverAsync,
    *,
    allow_negative_quantity: bool = False,
) -> tuple[DocumentLine, bool]:
    """Build one DocumentLine from a row. Returns (line, matched_template).

    Raises ``ValueError`` when the row cannot become a line — no name, or a
    cell that is not the number its column promises — so the caller reports
    the row instead of skipping it in silence.
    ``matched_template`` is True when a ProductTemplate was resolved.
    """
    barcode = _extract_string(row, column_mapping.get('barcode'))
    sku = _extract_string(row, column_mapping.get('sku'))
    # A sheet kept by code alone ("code,quantity") has no name column; the
    # code names the row until the catalogue says what the product is called.
    given_name = _extract_string(row, column_mapping.get('name'))
    name = given_name or sku or barcode
    if not name:
        raise ServiceRejectionError('import_line_name_missing')

    brand = _extract_string(row, column_mapping.get('brand'))
    quantity = _extract_decimal(
        row, column_mapping.get('quantity'), default=Decimal('1')
    )
    # The same question the form's own field asks. ``DocumentLineCreate``
    # declares ``expected_quantity`` as ``Field(gt=0)``, and the field on
    # screen carries a ``min`` from its unit — so a line of -5 was only ever
    # reachable through this door. Whether a type may hold one at all is the
    # type's own business (``document_types.allows_negative_quantity``): a
    # correction's lines are deltas, everywhere else they are amounts that
    # "Plan" and "received X of Y" add up.
    if not allow_negative_quantity and quantity is not None and quantity <= 0:
        raise ServiceRejectionError(
            'import_quantity_not_positive',
            column=column_mapping.get('quantity'),
            value=quantity,
        )
    # Through the same cell reader as the other columns: the resolver takes
    # text, and a blank in a numeric column arrives as NaN.
    uom_id = await uom_resolver.resolve(
        _extract_string(row, column_mapping.get('uom_symbol'))
    )
    unit_price = _extract_decimal(row, column_mapping.get('unit_price'))
    tax_rate = _extract_decimal(row, column_mapping.get('tax_rate'))
    batch_number = _extract_string(row, column_mapping.get('batch_number'))
    expiry_date = _extract_date(row, column_mapping.get('expiry_date'))

    (
        product_template_id,
        product_snapshot,
        template_uom_id,
    ) = await _resolve_template(
        db,
        org_id,
        barcode=barcode,
        sku=sku,
        name=name,
    )
    matched = product_template_id is not None
    if not given_name and product_snapshot and product_snapshot.get('name'):
        name = product_snapshot['name']

    if product_snapshot:
        # Backfill brand/uom from the template when the row did not provide them.
        if not brand and product_snapshot.get('brand'):
            brand = product_snapshot['brand']
        if not uom_id and template_uom_id:
            uom_id = template_uom_id

    line = DocumentLine(
        id=uuid4(),
        document_id=doc_id,
        product_template_id=product_template_id,
        name=name,
        brand=brand,
        barcode=barcode,
        quantity=quantity,
        expected_quantity=quantity,
        done_quantity=Decimal('0'),
        uom_id=uom_id,
        unit_price=unit_price,
        tax_rate=tax_rate,
        batch_number=batch_number,
        expiry_date=expiry_date,
        line_number=line_number,
        product_snapshot=product_snapshot,
    )
    return line, matched
