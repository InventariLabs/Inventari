from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import (
    CUSTOMER_ROLE_TYPES,
    SUPPLIER_ROLE_TYPES,
    PartnerDTO,
)
from app.core.exceptions import ServiceRejectionError
from app.core.public_api import core_api

from . import document_types as dt
from .schemas import DocumentCreate


async def validate_location_async(
    db: AsyncSession,
    org_id: UUID,
    location_id: UUID,
    *,
    internal_only: bool = False,
    active_only: bool = False,
) -> None:
    """Confirm a location exists in this organization — optionally that it
    is a real shelf and still on the lists.

    ``internal_only`` refuses the virtual counterparts (consumed, inventory
    loss, production): goods belong on shelves. ``active_only`` refuses
    archived locations, which the lists and pickers hide. Both questions are
    asked of every destination a person names for receipt goods — a line's
    own target and a putaway rule's target — through this one function, so
    none of them can grow its own notion of what a valid shelf is. A foreign
    id answers exactly what a missing id answers: existence elsewhere is not
    ours to confirm.
    """
    loc = await core_api.locations.get_async(db, org_id, location_id)
    if not loc:
        raise ServiceRejectionError('storage_not_found')
    if internal_only and loc.usage != 'internal':
        raise ServiceRejectionError('location_not_internal', name=loc.name)
    if active_only and (loc.settings or {}).get('archived') is True:
        raise ServiceRejectionError('location_archived', name=loc.name)


async def validate_locations_async(
    db: AsyncSession,
    org_id: UUID,
    doc_type: str,
    source_id: UUID | None,
    target_id: UUID | None,
) -> None:
    if dt.requires_target(doc_type):
        if not target_id:
            raise ServiceRejectionError('document_type_requires_target_location')
        await validate_location_async(db, org_id, target_id)
    elif target_id:
        await validate_location_async(db, org_id, target_id)

    if dt.requires_source(doc_type):
        if not source_id:
            raise ServiceRejectionError('document_type_requires_source_location')
        await validate_location_async(db, org_id, source_id)
    elif source_id:
        await validate_location_async(db, org_id, source_id)


# Roles each document type accepts for its partner; other types are
# unrestricted (internal moves carry no partner at all). Kept in sync with
# the role filters the UI applies to the partner dropdown.:
# the canonical role sets live in Core (app/schemas/partner.py).
#
# The OUT asymmetry is intentional and must stay: the dropdown offers
# CUSTOMER_ROLE_TYPES ({CUSTOMER, BOTH}), while the backend additionally
# accepts SUPPLIER because returns to suppliers copy the partner from the
# source document (document_return_service).
PARTNER_TYPES_BY_DOC_TYPE = {
    # A receipt comes from a supplier or a manufacturer — and back from a
    # customer: goods a customer returns are received on a receipt of their
    # own, and that receipt names the customer, not their supplier.
    'IN': SUPPLIER_ROLE_TYPES | CUSTOMER_ROLE_TYPES,
    'OUT': CUSTOMER_ROLE_TYPES | frozenset({'SUPPLIER'}),
}

#: What the refusal says for each restricted type — the roles in words.
_PARTNER_ROLE_REFUSALS = {
    'IN': 'document_partner_must_be_supplier_or_manufacturer',
    'OUT': 'document_partner_must_be_customer_or_supplier',
}


async def validate_partner_async(
    db: AsyncSession, org_id: UUID, partner_id: UUID, doc_type: str | None = None
) -> PartnerDTO | None:
    """Refuse a partner this document type does not accept, and hand it back.

    The caller gets the row it just had to read: the create path writes the
    partner's name beside its id in the journal, and the journal is opened
    months later — `Partner: 7c65b0dd` is not an answer to who the goods came
    from. Read here rather than a second time a line below.
    """
    partner = await core_api.partners.get_async(db, org_id, partner_id)
    if not partner:
        raise ServiceRejectionError('partner_not_found')
    allowed = PARTNER_TYPES_BY_DOC_TYPE.get(doc_type or '')
    if allowed and partner.type not in allowed:
        raise ServiceRejectionError(_PARTNER_ROLE_REFUSALS[doc_type or ''])
    return partner


async def validate_lines_async(
    db: AsyncSession, org_id: UUID, data: DocumentCreate
) -> None:
    await validate_lines_data_async(db, org_id, data.lines, data.type)


async def validate_lines_data_async(
    db: AsyncSession,
    org_id: UUID,
    lines: list[Any],
    doc_type: str,
) -> None:
    for line in lines:
        if line.item_id:
            item = await core_api.items.get_async(db, org_id, line.item_id)
            if not item:
                raise ServiceRejectionError('item_not_found')
        if line.product_template_id:
            tpl = await core_api.product_templates.get_async(
                db, org_id, line.product_template_id
            )
            if not tpl:
                raise ServiceRejectionError('product_template_not_found')


async def validate_unit_prices_async(
    db: AsyncSession,
    org_id: UUID,
    lines: list[Any],
    doc_type: str,
) -> None:
    """enforce value completeness when the profile requires it.

    Every line must carry a positive unit price — on the documents that
    show one. A transfer, a correction or a scrap is offered no price
    field (see ``document_types.carries_value``), so a rule demanding a
    price of every line would refuse a document whose writer had no way to
    answer it. Called from the create/update paths only when
    ``profile.require_unit_price`` is on.
    """
    if not dt.carries_value(doc_type):
        return

    from .document_profile_service import get_profile

    profile = await get_profile(db, org_id)
    if profile is None or not profile.require_unit_price:
        return
    missing = [
        idx + 1
        for idx, line in enumerate(lines)
        if getattr(line, 'unit_price', None) is None
    ]
    if missing:
        numbers = ', '.join(str(n) for n in missing[:5])
        raise ServiceRejectionError('document_unit_price_required', lines=numbers)
