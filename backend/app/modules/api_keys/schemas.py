"""Pydantic schemas for the API Keys module."""

from datetime import datetime
from uuid import UUID

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class ApiKeyCreate(BaseModel):
    """Create payload.

    A field it does not name is refused with 422 — the single ``scope``
    string of earlier releases included; send ``scopes`` instead.
    """

    # Dropping an unknown field would issue a broader key than was asked for:
    # an old printing-key request would come back as an ordinary key.
    model_config = ConfigDict(extra='forbid')

    name: str = Field(..., min_length=1, max_length=255)
    expires_at: datetime | None = None
    #: What the key may do, from the ``grantable`` list of
    #: ``/api-keys/capabilities``. Left out, the key gets the default: its
    #: scopes' permissions, or ``default_permissions`` for an ordinary key.
    permissions: list[str] | None = Field(None, max_length=200)
    #: Leave empty for an ordinary key; name scopes from
    #: ``/api-keys/capabilities`` to confine the key to the endpoints that
    #: guard their permissions.
    scopes: list[str] = Field(default_factory=list, max_length=20)


class ApiKeyResponse(BaseModel):
    """Listed key — NEVER includes raw key or hash.

    ``permissions`` and ``scopes`` are what the server enforces for this key,
    read off the same row the authentication path reads.
    """

    model_config = {'from_attributes': True}

    id: UUID
    name: str
    key_prefix: str
    is_active: bool
    last_used_at: datetime | None
    expires_at: datetime | None
    created_at: datetime
    created_by_email: str | None = None
    permissions: list[str]
    #: Stored as ``scope_names`` (see the model).
    scopes: list[str] = Field(validation_alias=AliasChoices('scope_names', 'scopes'))

    @classmethod
    def from_orm_with_email(cls, api_key: object) -> 'ApiKeyResponse':
        obj = cls.model_validate(api_key)
        user = getattr(api_key, 'user', None)
        obj.created_by_email = getattr(user, 'email', None)
        return obj


class ApiKeyCreatedResponse(BaseModel):
    """Returned ONCE at creation — contains the raw key."""

    id: UUID
    name: str
    key_prefix: str
    raw_key: str  # Full key, shown only here — never stored
    expires_at: datetime | None
    created_at: datetime
    permissions: list[str]
    scopes: list[str]


class ApiKeyPermissionOption(BaseModel):
    """One permission a key can name, with the labels the roles editor uses."""

    key: str
    label_key: str
    description_key: str | None = None


class ApiKeyScope(BaseModel):
    """A scope a key can be issued for, and the permissions it is bound to."""

    name: str
    permissions: list[str]


class ApiKeyCapabilities(BaseModel):
    """What a key issued here may carry, and how to send it.

    Read off the constants and registries the authentication path uses, and
    off the reader's own permissions, so the screen cannot offer what the
    server would refuse.
    """

    #: Every permission a key in this organization could name, labelled —
    #: what a listed key's permissions are read against.
    catalog: list[ApiKeyPermissionOption]
    #: The keys of ``catalog`` the reader may put on a key: what they hold,
    #: minus ``withheld_permissions``.
    grantable: list[str]
    #: What a key gets when its creator names nothing.
    default_permissions: list[str]
    #: Never on a key, whoever issues it.
    withheld_permissions: list[str]
    #: Administrative areas are closed to keys by a role check, not by a
    #: missing permission — so it cannot be read off the lists above.
    admin_areas_blocked: bool
    #: The header a key travels in.
    header: str
    #: The scopes a key can be issued for; a scoped key reaches only the
    #: endpoints that guard their permissions.
    scopes: list[ApiKeyScope] = []
