"""Which checkout an approval was granted for.

A checkout request used to carry nothing but the asset: the approver
decided without knowing who would get it or until when, and the approval was
then spent by whichever checkout of the asset came next — granted on one
person's request, used by somebody else's hand-out to a third person.

So the request names the checkout it asks for — the holder and the expected
return, the fields of the checkout dialog — and the approval covers that
checkout: one to a different holder is refused and needs a request of its
own. A request raised without a holder (the generic approvals endpoint, or
one raised before requests carried it) names nobody, and covers the next
checkout as it always did.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from ._holder import holder_of_parts

#: Where in the request's ``meta_data`` the checkout it asks for is kept.
CHECKOUT_KEY = 'checkout'


async def checkout_request_meta(
    db: AsyncSession,
    org_id: UUID,
    *,
    assigned_to_name: str = '',
    assignee_partner_id: UUID | None = None,
    checkout_location_id: UUID | None = None,
    expected_return_at: datetime | None = None,
) -> dict[str, Any] | None:
    """The ``meta_data`` a checkout request carries, or None when it names nobody.

    ``holder`` is the name the approvals card shows — the person, or the
    place a deployment stands the asset in — resolved once here by the rule
    every equipment screen uses; the ids stay beside it so the checkout can be
    matched against the request without comparing display names.
    """
    from app.core.public_api import core_api

    partner_name = None
    if assignee_partner_id is not None:
        partner = await core_api.partners.get_async(db, org_id, assignee_partner_id)
        partner_name = partner.name if partner is not None else None
    location_name = None
    if checkout_location_id is not None:
        location = await core_api.locations.get_async(db, org_id, checkout_location_id)
        location_name = location.name if location is not None else None
    holder = holder_of_parts(
        partner_name=partner_name,
        assigned_to_name=assigned_to_name,
        checkout_location_name=location_name,
    )
    if holder is None:
        return None
    return {
        CHECKOUT_KEY: {
            'holder': holder.name,
            'holder_kind': holder.kind,
            'assigned_to_name': assigned_to_name.strip() or None,
            'assignee_partner_id': (
                str(assignee_partner_id) if assignee_partner_id else None
            ),
            'checkout_location_id': (
                str(checkout_location_id) if checkout_location_id else None
            ),
            'expected_return_at': (
                expected_return_at.isoformat() if expected_return_at else None
            ),
        }
    }


def _holder_identity(
    *,
    assigned_to_name: str | None,
    assignee_partner_id: UUID | str | None,
    checkout_location_id: UUID | str | None,
) -> tuple[str, str] | None:
    """Who a checkout hands the asset to, as the assignment will read it.

    The order is :func:`holder_of_parts`'s: the partner record outranks the
    name typed beside it, and a person outranks a place. Comparing each field
    on its own let a name copied from the request through beside another
    partner, and the asset then went to that partner.
    """
    if assignee_partner_id:
        return ('partner', str(assignee_partner_id))
    name = (assigned_to_name or '').strip().casefold()
    if name:
        return ('name', name)
    if checkout_location_id:
        return ('location', str(checkout_location_id))
    return None


def _same_checkout(
    asked: dict[str, Any],
    *,
    assigned_to_name: str | None,
    assignee_partner_id: UUID | None,
    checkout_location_id: UUID | None,
) -> bool:
    """Whether a checkout goes to the holder the request named."""
    wanted = _holder_identity(
        assigned_to_name=asked.get('assigned_to_name'),
        assignee_partner_id=asked.get('assignee_partner_id'),
        checkout_location_id=asked.get('checkout_location_id'),
    )
    given = _holder_identity(
        assigned_to_name=assigned_to_name,
        assignee_partner_id=assignee_partner_id,
        checkout_location_id=checkout_location_id,
    )
    return wanted is not None and wanted == given


async def ensure_approval_covers_checkout(
    db: AsyncSession,
    org_id: UUID,
    item_id: UUID,
    *,
    assigned_to_name: str | None,
    assignee_partner_id: UUID | None = None,
    checkout_location_id: UUID | None = None,
) -> None:
    """Refuse a checkout the live approval was not granted for.

    Asked after the approvals gate let the checkout past and before the
    approval is spent, so the request it reads is the one about to be spent:
    the newest approved one not yet used. A request naming no holder covers
    any checkout.
    """
    from app.modules.approvals.approvals_api import approvals_api
    from app.modules.approvals.exceptions import ApprovalRequiredError

    approved = [
        request
        for request in await approvals_api.list_requests(
            db,
            org_id,
            target_type='equipment_checkout',
            status='APPROVED',
            target_id=item_id,
        )
        if request.consumed_at is None
    ]
    if not approved:
        return
    newest = max(approved, key=lambda request: (request.created_at, str(request.id)))
    asked = (newest.meta_data or {}).get(CHECKOUT_KEY)
    if not asked or not asked.get('holder'):
        return
    if not _same_checkout(
        asked,
        assigned_to_name=assigned_to_name,
        assignee_partner_id=assignee_partner_id,
        checkout_location_id=checkout_location_id,
    ):
        raise ApprovalRequiredError.translated(
            'approval_granted_for_another_holder', holder=asked['holder']
        )
