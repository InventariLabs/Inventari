from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.public_api import core_api

from .models import DocumentLine
from .schemas import DocumentLineCreate


async def _build_product_snapshot(
    db: AsyncSession,
    line_data: DocumentLineCreate,
    org_id: UUID | None = None,
) -> dict[str, Any] | None:
    template = None
    if line_data.product_template_id and org_id:
        template = await core_api.product_templates.get_async(
            db, org_id, line_data.product_template_id
        )
    elif line_data.barcode and org_id:
        template = await core_api.product_templates.lookup_by_barcode_async(
            db, org_id, line_data.barcode
        )
    if not template:
        return None
    return {
        'name': template.name,
        'brand': template.brand,
        'barcode': template.barcode,
        'sku': template.sku,
        'uom_id': str(template.uom_id) if template.uom_id else None,
        'uom_symbol': None,
        'image_url': template.image_url,
    }


async def build_document_line(
    line_data: DocumentLineCreate,
    line_number: int,
    *,
    document_id: UUID | None = None,
    currency: str | None = None,
    db: AsyncSession | None = None,
    org_id: UUID | None = None,
) -> DocumentLine:
    product_snapshot = None
    if db is not None:
        product_snapshot = await _build_product_snapshot(db, line_data, org_id=org_id)
    uom_id = line_data.uom_id
    if uom_id is None and product_snapshot is not None:
        snapshot_uom_id = product_snapshot.get('uom_id')
        uom_id = UUID(snapshot_uom_id) if snapshot_uom_id else None
    item_name = None
    if (
        db is not None
        and org_id
        and line_data.item_id
        and (uom_id is None or not line_data.name)
    ):
        # A line that names a record on a shelf takes that record's unit when
        # nothing else named one. Otherwise the quantity travels alone all the
        # way to the picker's row, where "3" says nothing — three pieces,
        # three packs and three kilograms are three different picks. Stock
        # standing outside the catalogue has no other source for the unit.
        # The same record names the line when the caller sent no name, so a
        # draft written through the API reads as the item on every screen.
        item = await core_api.items.get_async(db, org_id, line_data.item_id)
        if item is not None:
            item_name = item.name
            if uom_id is None:
                uom_id = item.uom_id
    if db is not None and uom_id is not None and org_id is not None:
        await core_api.uoms.validate_quantity_precision_async(
            db, uom_id, line_data.expected_quantity, org_id
        )
    # when a product template is linked and resolved, the line name
    # is the template's authoritative name — never a stale search query. Free-text
    # names are only valid for ad-hoc lines without a product_template_id.
    name = line_data.name or item_name
    if product_snapshot is not None and product_snapshot.get('name'):
        name = product_snapshot['name']
    line = DocumentLine(
        document_id=document_id,
        item_id=line_data.item_id,
        product_template_id=line_data.product_template_id,
        name=name,
        brand=line_data.brand,
        barcode=line_data.barcode,
        quantity=line_data.expected_quantity,
        expected_quantity=line_data.expected_quantity,
        done_quantity=Decimal('0.000'),
        uom_id=uom_id,
        batch_number=line_data.batch_number,
        serial_number=line_data.serial_number,
        expiry_date=line_data.expiry_date,
        notes=line_data.notes,
        line_number=line_number,
        unit_price=line_data.unit_price,
        tax_rate=line_data.tax_rate,
        currency=currency,
        product_snapshot=product_snapshot,
        source_po_line_id=line_data.source_po_line_id,
        target_location_id=line_data.target_location_id,
        meta_data=line_data.meta_data or None,
        expected_is_count=bool(line_data.expected_is_count),
    )
    return line
