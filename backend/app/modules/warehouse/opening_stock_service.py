"""Opening stock — a spreadsheet becomes one draft receipt.

The moment a company leaves its spreadsheet is the moment it types its whole
stock into the app, one receipt line at a time. This takes the sheet instead:
every row becomes a line of one draft receipt flagged as opening stock, each
row's product found by barcode, SKU or name or founded on the way, so that
posting the draft carries every price into the cost layers and every lot in
the sheet into the lot register. A row the importer cannot read is reported
with its reason and holds nothing else up.

The draft is a receipt like any other from here on — reviewed, confirmed and
completed by the same hands — except that it names no supplier: nobody sold
the company its own stock.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import AuditAction, AuditTargetType
from app.core.import_sheet import read_rows
from app.core.public_api import core_api

from . import document_types as dt
from ._document_workflow_helpers import _apply_line_tax_rates
from .document_import_service import import_lines_from_dataframe
from .document_numbering_service import temporary_number
from .document_profile_service import get_or_create_profile, resolve_document_currency
from .document_validation_service import validate_locations_async
from .document_value_service import recompute_document_values
from .inventory_period_service import check_period_not_closed_async
from .models import Document, DocumentStatus


async def import_opening_stock(
    db: AsyncSession,
    org_id: UUID,
    user_id: UUID,
    *,
    file_content: bytes,
    filename: str,
    mapping: dict[str, Any],
    target_location_id: UUID,
    create_stubs_for_unmatched: bool = True,
    scheduled_date: date | None = None,
) -> dict[str, Any]:
    """One draft receipt out of the sheet, or none when no row could be read."""
    df = read_rows(file_content, filename)
    await check_period_not_closed_async(
        db, org_id, scheduled_date or datetime.now(UTC).date()
    )
    await validate_locations_async(db, org_id, dt.IN, None, target_location_id)

    # One draft receipt out of the sheet: an identifier until confirmation
    # draws the number, in the period the sheet's own date names.
    number = temporary_number()
    profile = await get_or_create_profile(db, org_id)
    doc = Document(
        organization_id=org_id,
        type=dt.IN,
        number=number,
        status=DocumentStatus.DRAFT.value,
        target_location_id=target_location_id,
        scheduled_date=scheduled_date,
        created_by=user_id,
        currency=await resolve_document_currency(db, org_id, profile),
        is_opening=True,
    )
    db.add(doc)
    await db.flush()

    result = await import_lines_from_dataframe(
        db,
        doc.id,
        df,
        mapping,
        org_id,
        create_stubs_for_unmatched=create_stubs_for_unmatched,
        stubs_need_barcode=False,
        user_id=user_id,
    )
    result['total'] = len(df)
    result.pop('lines', None)

    if result['imported'] == 0:
        # Nothing to review: a draft with no lines would only be found empty.
        # The caller's commit applies the delete — nothing of this import
        # can survive it.
        await db.delete(doc)
        return {**result, 'document_id': None, 'number': None}

    await db.refresh(doc, attribute_names=['lines'])
    # The profile's tax rate goes on every line the way the form's path puts
    # it there; without it the gross is None and the list shows a draft of
    # fifty priced lines worth nothing.
    await _apply_line_tax_rates(db, org_id, profile, doc.lines)
    recompute_document_values(doc)
    await core_api.audit_log.log_action_async(
        db,
        organization_id=org_id,
        user_id=user_id,
        action=AuditAction.CREATE,
        target_type=AuditTargetType.DOCUMENT,
        target_id=doc.id,
        snapshot={'number': doc.number, 'type': doc.type, 'opening_stock': True},
    )
    # One unit of work: the draft, its lines and the entry above land with
    # the caller's commit, or none of them do.
    await db.flush()
    return {**result, 'document_id': str(doc.id), 'number': doc.number}
