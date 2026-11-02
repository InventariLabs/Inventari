from datetime import datetime
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.contracts._core_dtos import ISO_3166_ALPHA2_CODES
from app.core.exceptions import ServiceRejectionError
from app.core.print_page_size import PAGE_SIZES


def _validated_timezone(v: object) -> str:
    """Coerce and check a timezone string: IANA name or empty → UTC.

    A zone the backend cannot read degrades every org-clock read to UTC
    (with a warning log) — refusing it at the door is cheaper than the
    silent shift it would cause in expiry buckets and period guards.
    """
    name = str(v).strip() if v is not None else ''
    if not name:
        return 'UTC'
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ServiceRejectionError('invalid_timezone') from exc
    return name


def validated_country_code(v: object) -> str | None:
    """Coerce and check an ISO 3166-1 alpha-2 code: empty → no country."""
    if v is None or v == '':
        return None
    code = str(v).strip().upper()
    if code not in ISO_3166_ALPHA2_CODES:
        raise ServiceRejectionError('invalid_country_code')
    return code


class OrganizationBase(BaseModel):
    name: str
    currency: str = 'USD'
    timezone: str = 'UTC'

    @field_validator('timezone', mode='before')
    @classmethod
    def validate_timezone(cls, v: object) -> str:
        return _validated_timezone(v)


class OrganizationCreate(OrganizationBase):
    settings: dict | None = None


class OrganizationAddress(BaseModel):
    """Structured issuer address.

    ``country`` is deliberately absent: the organization already has its own
    ISO column — duplicating it here would recreate the free-text drift the
    partner address migration removed.
    """

    model_config = ConfigDict(extra='forbid')

    street: str | None = Field(None, max_length=255)
    city: str | None = Field(None, max_length=255)
    postal_code: str | None = Field(None, max_length=20)


class OrganizationUpdate(BaseModel):
    name: str | None = None
    currency: str | None = None
    timezone: str | None = None
    settings: dict | None = None
    # Issuer identity: the fields already existed on the model but
    # were never exposed — a document profile cannot be completed without them.
    tax_id: str | None = Field(None, max_length=50)
    country: str | None = Field(None, max_length=2)
    address: OrganizationAddress | None = None
    # The paper the office prints on — absent/empty means the country
    # answers, so an organization moving countries has nothing to clear.
    print_page_size: str | None = Field(None, max_length=10)

    @field_validator('timezone', mode='before')
    @classmethod
    def validate_timezone(cls, v: object) -> str | None:
        if v is None:
            return None
        return _validated_timezone(v)

    @field_validator('country', mode='before')
    @classmethod
    def validate_country_code(cls, v: object) -> str | None:
        return validated_country_code(v)

    @field_validator('print_page_size', mode='before')
    @classmethod
    def validate_print_page_size(cls, v: object) -> str | None:
        if v is None or v == '':
            return None
        value = str(v).strip().lower()
        if value not in PAGE_SIZES:
            raise ServiceRejectionError('invalid_print_page_size')
        return value


class Organization(OrganizationBase):
    id: UUID
    short_id: str | None = None
    created_at: datetime
    created_by: UUID | None = None
    currency: str
    timezone: str
    settings: dict | None = None
    member_count: int | None = None
    active_profile_id: str | None = None
    onboarding_completed: bool | None = None
    # Issuer identity: surfaced so the settings UI can edit and the
    # PDF service can print them.
    tax_id: str | None = None
    country: str | None = None
    address: dict[str, Any] | None = None
    logo_url: str | None = None
    # The paper the office prints on, or None where the country answers.
    print_page_size: str | None = None
    # Whether anything this organization sends can actually leave. Resolved
    # the way the send path resolves it — the organization's own SMTP if it
    # has one, the installation's otherwise — so a screen offering to email
    # somebody is offering what the server will really do.
    can_send_email: bool = False

    model_config = ConfigDict(from_attributes=True)


class InvitationSummary(BaseModel):
    """One issued invitation, as the settings screen lists them."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    role: str
    role_id: UUID | None = None
    is_used: bool
    expires_at: datetime
    created_at: datetime
    invited_email: str | None = None
    #: Who walked through and when. The address is not repeated here: a code
    #: opens only for the address it was issued for, so `invited_email`
    #: already names the account — the id is for linking to the member.
    used_by_user_id: UUID | None = None
    used_at: datetime | None = None
    #: How the mail carrying this code ended: 'sent', 'failed', or still in
    #: flight ('pending'/'sending'). NULL when there was no mail to send — a
    #: bearer code, or an installation without SMTP where the administrator
    #: hands the link over themselves. The queue's own vocabulary, passed
    #: through rather than re-spelled: a second spelling of it here would be
    #: a vocabulary to keep in step, and the cost of drift is a 500 on this
    #: list.
    email_status: str | None = None


class FailedEmailSummary(BaseModel):
    """One message the queue gave up on, as the email screen lists them.

    Deliberately not the body: an administrator answering for a message
    that never arrived needs the address, the subject, when it was written
    and what the relay said — not the rendered invitation itself, which on
    this screen would only be a link anyone reading over their shoulder
    could redeem.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    to_email: str
    subject: str
    attempts: int
    max_attempts: int
    #: What the relay said on the last attempt. NULL only for rows written
    #: before the queue recorded the reason at all.
    last_error: str | None = None
    created_at: datetime


class OrganizationMemberCustomRole(BaseModel):
    """The org-scoped custom role a member holds, if any."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    permissions: list[str] = []


class OrganizationMember(BaseModel):
    id: UUID
    email: str
    full_name: str | None = None
    role: str
    custom_role: OrganizationMemberCustomRole | None = None
