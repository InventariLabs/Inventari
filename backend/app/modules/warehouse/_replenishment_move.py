"""Carrying reserve stock to a pick face, from the alert's own proposal.

The purchase orders module decides that a location is short and what reserve
can cover; this module owns the move. The orders module hands over the
proposal it derived (``warehouse_api.post_reserve_replenishment_async``), the
shelf scan the profile asks for is checked here, and the transfer is created
and posted through the same one-step door as any typed Move — so the period,
approval and stock rules are the ones every transfer runs under.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import ReplenishmentProposalDTO
from app.core.exceptions import ServiceRejectionError
from app.core.public_api import core_api

from . import document_types as dt
from .document_profile_service import get_profile
from .models import Document
from .schemas import DocumentCreate, DocumentLineCreate


async def _check_the_shelf_scan_async(
    db: AsyncSession,
    org_id: UUID,
    source_location_id: UUID,
    scanned_code: str | None,
) -> None:
    """Refuse a move from a shelf nobody scanned, when the profile asks for it.

    The rule is the picking session's: once the organization asks for a shelf
    to be confirmed by scan, the straw that says "I am taking it off this
    shelf" is a scan, not a location id carried by a form.
    """
    profile = await get_profile(db, org_id)
    if profile is None or not profile.confirm_shelf_by_scan:
        return
    if not scanned_code:
        raise ServiceRejectionError('replenishment_shelf_scan_required')
    scanned = await core_api.locations.find_by_scanned_code_async(
        db, org_id, scanned_code
    )
    if scanned is None or scanned.id != source_location_id:
        raise ServiceRejectionError('replenishment_shelf_scan_mismatch')


async def post_reserve_replenishment_async(
    db: AsyncSession,
    org_id: UUID,
    user_id: UUID,
    proposal: ReplenishmentProposalDTO,
    *,
    scanned_code: str | None = None,
) -> Document:
    """Post the internal move a reorder rule's alert proposes.

    The proposal is derived by the caller from live stock: a task rendered
    minutes ago is a hint, not the quantity to move. An expired proposal —
    the shelf was filled meanwhile, or somebody else carried the reserve
    away — is refused in the reader's language instead of posting an empty
    or invented document.
    """
    from ._document_workflow_crud import create_document
    from ._document_workflow_transitions import post_document_now

    if not proposal.lines:
        raise ServiceRejectionError('replenishment_nothing_to_move')

    source_location_id = proposal.lines[0].source_location_id
    await _check_the_shelf_scan_async(db, org_id, source_location_id, scanned_code)
    doc = await create_document(
        db,
        org_id,
        DocumentCreate(
            type=dt.INT,
            source_location_id=source_location_id,
            target_location_id=proposal.target_location_id,
            lines=[
                DocumentLineCreate(
                    item_id=line.item_id,
                    product_template_id=line.product_template_id,
                    expected_quantity=line.quantity,
                    uom_id=line.uom_id,
                )
                for line in proposal.lines
            ],
        ),
        user_id,
    )
    return await post_document_now(db, org_id, doc.id, user_id)
