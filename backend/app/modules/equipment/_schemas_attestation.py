from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

#: What a campaign can be narrowed to, and the states it moves through. Named
#: as literals so the contract carries the set to the screens instead of a
#: bare ``string`` they have to narrow by hand.
CampaignScopeType = Literal['ALL', 'STORAGE', 'CATEGORY']
CampaignStatus = Literal['DRAFT', 'ACTIVE', 'COMPLETED', 'CANCELLED']


class CampaignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    scope_type: CampaignScopeType = 'ALL'
    scope_filter_id: UUID | None = None
    # Whether the deadline lies in the future is decided where the
    # organization's clock is known (create_campaign, after the arrival is
    # re-pinned to the end of the picked day): a schema validator sees only
    # the instant, and the form's arrival is noon of the picked day on the
    # org's clock — compared with "now" it refused a legitimately picked
    # "today" for the whole afternoon of the organization's day.
    deadline: datetime
    reminder_days_before: int = Field(default=3, ge=0, le=30)
    email_subject: str | None = Field(None, max_length=255)
    email_body: str | None = None


class CampaignSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    name: str
    description: str | None
    scope_type: CampaignScopeType
    scope_filter_id: UUID | None
    launched_at: datetime | None
    deadline: datetime
    reminder_days_before: int
    last_reminder_sent_at: datetime | None
    status: CampaignStatus
    email_subject: str | None
    email_body: str | None
    created_by: UUID
    created_at: datetime
    updated_at: datetime


class CampaignStats(BaseModel):
    total: int = 0
    confirmed: int = 0
    disputed: int = 0
    pending: int = 0
    expired: int = 0
    # Unanswered, but every asset it asked about has been returned.
    returned: int = 0


class ReminderRunResult(BaseModel):
    """What one press of Send Reminders did, and why it did no more."""

    reminders_sent: int
    # Still waiting for an answer: not answered, not expired, assets still out.
    awaiting_reply: int
    # Of those, skipped because a reminder went out within the last 24 hours.
    reminded_recently: int
    # Of those, handed to the mail system and refused there.
    not_delivered: int
    # No mail server is configured, so nothing was sent to anyone.
    email_unavailable: bool


class ScopePreview(BaseModel):
    """What a scope holds before a campaign exists: the numbers the picker
    and the launch confirmation both owe the reader, and the holders' names
    a draft shows so the audience is more than a count."""

    assets: int = 0
    people: int = 0
    without_email: int = 0
    holders: list[str] = Field(default_factory=list)


class AuditResponseItemSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    response_id: UUID
    assignment_id: UUID
    item_id: UUID
    item_name: str
    serial_number: str | None
    status: str
    dispute_type: str | None
    dispute_reason: str | None
    # Returned since the request went out: shown as returned, not offered for
    # confirmation (the AuditResponseItem property of the same name).
    returned: bool = False


class AuditResponseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    campaign_id: UUID
    # grouped responses (one per person) have no single assignment.
    assignment_id: UUID | None
    assignee_email: str
    assignee_name: str
    # Surface the asset the attester is being asked about, so the
    # public page can show "what am I confirming?" and the campaign detail
    # table can render an Asset column. Both fields are sourced from the
    # assignment.item relationship via the AuditResponse ORM properties
    # of the same name.
    item_name: str = ''
    serial_number: str | None = None
    items: list[AuditResponseItemSchema] = []
    status: str
    responded_at: datetime | None
    dispute_reason: str | None
    dispute_type: str | None
    email_sent_at: datetime | None
    reminder_sent_at: datetime | None
    created_at: datetime
    # Why the public link can no longer take an answer, in the same
    # vocabulary the confirm/dispute refusals use ('expired',
    # 'assignment_already_returned', 'campaign_closed'). ``None`` while
    # the link is open; only the public GET fills it, and a read never
    # writes — the status it sits next to stays PENDING until a write
    # attempt moves it.
    closed_reason: str | None = None


class CampaignResponseSchema(AuditResponseSchema):
    """A response as the campaign's own page lists it."""

    # Every asset it asks about is back: an unanswered response is closed,
    # not waiting (read from the AuditResponse property of the same name).
    # Staff-side only — the public answer is told by ``closed_reason``.
    assets_returned: bool = False


class CampaignDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    name: str
    description: str | None
    scope_type: CampaignScopeType
    scope_filter_id: UUID | None
    launched_at: datetime | None
    deadline: datetime
    reminder_days_before: int
    last_reminder_sent_at: datetime | None
    status: CampaignStatus
    email_subject: str | None
    email_body: str | None
    created_by: UUID
    created_at: datetime
    updated_at: datetime
    stats: CampaignStats
    responses: list[CampaignResponseSchema]


class DisputeForm(BaseModel):
    dispute_type: str = Field(pattern='^(MISSING|DAMAGED|WRONG_ITEM|OTHER)$')
    reason: str = Field(min_length=1, max_length=1000)
    # with several assets per response the dispute names one of them.
    assignment_id: UUID | None = None
