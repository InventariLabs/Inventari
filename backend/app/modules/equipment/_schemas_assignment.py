from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.schemas.pagination import PaginatedResponse


class AssignmentCreate(BaseModel):
    item_id: UUID
    # An assignment either hands the asset to a person or deploys it to a
    # place, and only the first of those has a name. The form has offered
    # both modes since it shipped, but this field demanded a name
    # unconditionally (``min_length=1``), so every deployment to a location
    # was refused — and refused by naming a field the reader had never been
    # shown. Measured on dev: zero of the stored assignments carried a
    # ``checkout_location_id``, so that path never once produced a record.
    #
    # An empty name is a body this endpoint accepts; whether it is allowed
    # is a business rule about who may hold an asset, and that is answered
    # once, in ``checkout()``, where the module's other refusals live and
    # where a rejection can still be translated.
    assigned_to_name: str = Field('', max_length=255)
    # Validate email format so malformed addresses are rejected
    # at the ingress point. AssignmentCreate is the only inbound path; the
    # attestation campaign launches SMTP from this same stored field.
    assigned_to_email: EmailStr | None = Field(None, max_length=255)
    assignee_partner_id: UUID | None = None
    checkout_location_id: UUID | None = None
    expected_return_at: datetime | None = None
    checkout_notes: str | None = None


class AssignmentCheckin(BaseModel):
    checkin_notes: str | None = None
    checkin_condition: str | None = Field(None, pattern='^(GOOD|DAMAGED|NEEDS_REPAIR)$')
    # Where the asset goes back to. The form fills in the asset's own location
    # (its home, which a checkout to a place never moves); a different one
    # records a return that lands somewhere else, without a separate move.
    return_location_id: UUID | None = None


class AssignmentSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    item_id: UUID
    item_name: str
    item_serial: str | None = None
    """Which unit, not which model.

    Six rows reading "OptiPlex 7010" name a model the organization owns six
    of; the person sent to collect one of them needs the number on the case.
    """
    item_asset_tag: str | None = None
    assignee_partner_id: UUID | None
    partner_name: str | None
    checkout_location_id: UUID | None
    checkout_location_name: str | None
    assigned_to_name: str
    assigned_to_email: str | None
    # Who or what holds the asset, resolved once for every display surface:
    # the person's name, or the place a deployment stands in. ``holder_kind``
    # says which, because the screens word the two differently.
    holder_name: str | None = None
    holder_kind: Literal['person', 'location'] | None = None
    checked_out_at: datetime
    expected_return_at: datetime | None
    checked_in_at: datetime | None
    checked_out_by: UUID
    checked_in_by: UUID | None
    # The accounts behind the two operator ids, named for the reader. A
    # timeline that can only name the person the asset was with cannot tell
    # "the holder returned it" from "someone checked the return off for
    # them" — which is the one thing an audit trail of handovers is for.
    checked_out_by_name: str | None = None
    checked_in_by_name: str | None = None
    checkout_notes: str | None
    checkin_notes: str | None
    checkin_condition: str | None
    created_at: datetime


class AssignmentListResponse(PaginatedResponse[AssignmentSchema]):
    """Paginated response for the active-assignments list endpoint."""


class OverdueAssignmentItem(BaseModel):
    assignment_id: UUID
    item_id: UUID
    item_name: str
    item_barcode: str | None
    item_serial: str | None = None
    item_asset_tag: str | None = None
    # The holder, person or place, resolved by the one definition; the
    # e-mail only exists for the person half.
    holder_name: str | None = None
    holder_kind: Literal['person', 'location'] | None = None
    assigned_to_email: str | None
    checked_out_at: datetime
    expected_return_at: datetime | None
    days_overdue: int


class OverdueAssignmentListResponse(PaginatedResponse[OverdueAssignmentItem]):
    """Paginated response for the overdue-assignments list endpoint."""
