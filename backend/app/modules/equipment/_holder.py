"""Who or what holds an asset — one answer for every reader.

An assignment hands an asset to a person or stands it in a place. The record
keeps the two apart on purpose: ``assigned_to_name`` is the person field
``my_assets`` matches on and the handover protocol prints above its signature
line, so a deployment stores it empty rather than writing the location's name
into a field that means a human. Five readers then showed that emptiness —
the list's "held by" column, the timeline card, the overdue row, the overdue
notification and the export cell — each about to invent its own fallback.

This module is the one fallback. The answer is a name plus which of the two
it is, because the screens word them differently: a rack does not *possess*
a laptop. The reader picks its wording from ``kind``; it never re-derives the
holder from the raw columns. Whitespace is emptiness — the location mode
posts an empty name on purpose, and a caller that sends spaces instead must
not produce a blank holder either.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Final, Literal
from uuid import UUID

from .models import EquipmentAssignment

PERSON: Final = 'person'
PLACE: Final = 'location'

HolderKind = Literal['person', 'location']


@dataclass(frozen=True)
class Holder:
    """The asset's holder: a person's name, or the place it stands in."""

    name: str
    kind: HolderKind
    #: The place's id when ``kind`` is a place: while the asset stands there,
    #: that place is where the list and the asset page say it is.
    place_id: UUID | None = None


def holder_of_parts(
    *,
    partner_name: str | None = None,
    assigned_to_name: str | None = None,
    checkout_location_name: str | None = None,
) -> Holder | None:
    """Resolve the holder from the three raw fields, in one order.

    The live partner record outranks the free-text copy captured at checkout
    (a renamed employee keeps their current name on the card); a person
    outranks a place, because an assignment never means both.
    """
    person = (partner_name or '').strip() or (assigned_to_name or '').strip()
    if person:
        return Holder(name=person, kind=PERSON)
    place = (checkout_location_name or '').strip()
    if place:
        return Holder(name=place, kind=PLACE)
    return None


def holder_of_assignment(assignment: EquipmentAssignment) -> Holder | None:
    """The holder of a loaded assignment row — the relationship-aware read."""
    partner = assignment.assignee_partner
    location = assignment.checkout_location
    holder = holder_of_parts(
        partner_name=partner.name if partner is not None else None,
        assigned_to_name=assignment.assigned_to_name,
        checkout_location_name=location.name if location is not None else None,
    )
    if holder is not None and holder.kind == PLACE:
        return replace(holder, place_id=assignment.checkout_location_id)
    return holder
