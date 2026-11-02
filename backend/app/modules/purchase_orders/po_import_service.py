from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    ServiceRejectionError,
    is_reader_facing_value_error,
    refusal_row,
)
from app.core.file_import import analyze_import_file
from app.core.import_sheet import read_rows
from app.core.logging import get_logger
from app.core.public_api import core_api
from app.core.uom_resolver import UomResolverAsync

logger = get_logger(__name__)


analyze_po_import_file = analyze_import_file


class _RowSkippedError(ServiceRejectionError):
    """This row cannot become a line; the catalogue key says why."""


@dataclass(frozen=True)
class _Columns:
    """Where each field lives in the uploaded sheet."""

    name: str
    sku: str
    barcode: str
    quantity: str
    uom: str
    price: str
    tax: str

    @classmethod
    def from_mapping(cls, mapping: dict[str, Any]) -> '_Columns':
        return cls(
            name=mapping.get('name', 'name'),
            sku=mapping.get('sku', 'sku'),
            barcode=mapping.get('barcode', 'barcode'),
            quantity=mapping.get('quantity_ordered', 'quantity_ordered'),
            uom=mapping.get('uom_symbol', 'uom_symbol'),
            price=mapping.get('unit_price', 'unit_price'),
            tax=mapping.get('tax_rate', 'tax_rate'),
        )


def _parse_quantity(raw: Any, column: str) -> Decimal:
    """A row without a usable positive quantity is not a line."""
    try:
        quantity = Decimal(str(raw))
    except (ValueError, TypeError, InvalidOperation) as exc:
        raise _RowSkippedError(
            'import_column_not_a_number', column=column, value=raw
        ) from exc
    if quantity <= 0:
        raise _RowSkippedError('import_quantity_not_positive', column=column, value=raw)
    return quantity


def _optional_decimal(raw: Any) -> Decimal | None:
    """Money and tax are optional: anything unreadable simply stays empty."""
    try:
        return Decimal(str(raw)) if raw else None
    except (ValueError, TypeError, InvalidOperation):
        return None


async def _match_product_template(
    db: AsyncSession, org_id: UUID, sku: Any, barcode: Any
) -> UUID | None:
    """SKU first, barcode second — the same order the manual form uses."""
    if sku:
        pt = await core_api.product_templates.lookup_by_sku_async(db, org_id, str(sku))
        if pt:
            return pt.id
    if barcode:
        pt = await core_api.product_templates.lookup_by_barcode_async(
            db, org_id, str(barcode)
        )
        if pt:
            return pt.id
    return None


async def import_lines_into_po(
    db: AsyncSession,
    po_id: UUID,
    file_content: bytes,
    filename: str,
    column_mapping: dict[str, Any],
    org_id: UUID,
) -> dict[str, Any]:
    """Append lines from an uploaded sheet to a DRAFT purchase order.

    A row that cannot be read is counted and reported, never fatal — the
    import either lands what it can or tells the user what it dropped.
    """
    from app.modules.purchase_orders.models import PurchaseOrder, PurchaseOrderLine

    result = await db.execute(
        select(PurchaseOrder)
        .where(PurchaseOrder.id == po_id, PurchaseOrder.organization_id == org_id)
        .with_for_update()
    )
    po = result.scalars().first()
    if not po:
        raise ServiceRejectionError('purchase_order_not_found')
    if po.status != 'DRAFT':
        raise ServiceRejectionError('po_import_not_draft')

    df = read_rows(file_content, filename)
    columns = _Columns.from_mapping(column_mapping)

    imported = 0
    matched = 0
    unmatched = 0
    skipped = 0
    errors: list[dict[str, Any]] = []

    next_line_number = len(po.lines) + 1
    uom_resolver = UomResolverAsync(db, org_id)

    for idx, row in df.iterrows():
        try:
            name = row.get(columns.name)
            if not name:
                raise _RowSkippedError('import_line_name_missing')

            product_template_id = await _match_product_template(
                db, org_id, row.get(columns.sku), row.get(columns.barcode)
            )
            quantity = _parse_quantity(row.get(columns.quantity, '1'), columns.quantity)
            uom_id = await uom_resolver.resolve(row.get(columns.uom))

            db.add(
                PurchaseOrderLine(
                    purchase_order=po,
                    product_template_id=product_template_id,
                    name=str(name),
                    quantity_ordered=quantity,
                    quantity_received=Decimal('0'),
                    unit_price=_optional_decimal(row.get(columns.price)),
                    uom_id=uom_id,
                    tax_rate=_optional_decimal(row.get(columns.tax)),
                    line_number=next_line_number,
                )
            )
            next_line_number += 1
            imported += 1
            if product_template_id:
                matched += 1
            else:
                unmatched += 1

        except _RowSkippedError as exc:
            skipped += 1
            errors.append(refusal_row(exc, row=idx + 1))
        except (ValueError, KeyError, TypeError, AttributeError) as e:
            if isinstance(e, ValueError) and is_reader_facing_value_error(e):
                errors.append(refusal_row(e, row=idx + 1))
            else:
                # A library's text (a missing key, a type name) is not the
                # reader's to see: the traceback goes to the log.
                logger.exception('Purchase order import row %d failed', idx + 1)
                errors.append(
                    refusal_row(ServiceRejectionError('internal_error'), row=idx + 1)
                )
            continue

    await db.flush()

    return {
        'imported': imported,
        'matched': matched,
        'unmatched': unmatched,
        'skipped': skipped,
        'errors': errors[:20],
        'total_errors': len(errors),
    }
