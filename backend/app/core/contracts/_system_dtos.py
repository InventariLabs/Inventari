from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
)


class AnnouncementDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    content: str
    type: str = 'info'
    active_from: datetime
    active_until: datetime | None = None
    is_active: bool = True
    created_at: datetime
    created_by: UUID | None = None


_ALLOWED_ANNOUNCEMENT_TYPES = frozenset({'info', 'warning', 'critical', 'downtime'})


class AnnouncementCreateDTO(BaseModel):
    """Input DTO for CoreAnnouncementsAPI.create — mirrors AnnouncementCreate fields.

    ``type`` uses ``str`` (not the internal ``AnnouncementType`` enum) to stay
    contracts-legal; validated against the allowed set.
    """

    title: str
    content: str
    type: str = 'info'
    active_until: datetime | None = None

    @field_validator('type')
    @classmethod
    def validate_type(cls, v: str) -> str:
        from app.core.exceptions import ServiceRejectionError

        if v not in _ALLOWED_ANNOUNCEMENT_TYPES:
            raise ServiceRejectionError(
                'announcement_type_invalid',
                allowed=', '.join(sorted(_ALLOWED_ANNOUNCEMENT_TYPES)),
            )
        return v


class NotificationDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    title: str
    content: str
    type: str = 'info'
    is_read: bool = False
    created_at: datetime
    link: str | None = None
    meta_data: dict[str, Any] | None = None


class NotificationDedupKey(BaseModel):
    """Natural key for deduplicating periodic alert notifications.

    Identifies one logical alert instance — which reference (item,
    assignment, maintenance log…) of which notification type — so periodic
    workers can probe for an existing unread copy before inserting a
    duplicate. Bundles the (meta_type, ref_key, ref_id) triple that travels
    through the notifications dedup API.
    """

    model_config = ConfigDict(frozen=True)

    meta_type: str
    ref_key: str
    ref_id: str


class StorageTypeDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID | None = None
    name: str
    type_code: str
    behavior_mode: str = 'STOCK'
    context_schema: list[str] = Field(default_factory=list)
    field_definitions: list[dict[str, Any]] = Field(default_factory=list)
    icon: str | None = None
    is_system: bool = False
    created_by: UUID | None = None
    default_settings: dict[str, Any] | None = None


class LabelPoolDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    short_code: str
    is_assigned: bool = False
    assigned_at: datetime | None = None
    item_id: UUID | None = None
    organization_id: UUID
    label_type: str = 'GENERIC'
    description: str | None = None
    target_location_id: UUID | None = None
    created_at: datetime
    printed_at: datetime | None = None
    scan_count: int = 0
    context_tag: str | None = None
    is_item_deleted: bool | None = None
    assigned_item_name: str | None = None
    assigned_item_quantity: float | None = None
    assigned_item_unit: str | None = None
    assigned_item_context_tag: str | None = None
    #: The assigned product's expiry, which a printed caption reads as
    #: "<name> <month>.<year>" when nothing was typed for the label.
    assigned_item_expiry: date | None = None


class LabelPoolCreateDTO(BaseModel):
    """Input DTO for CoreLabelsAPI.generate_pool — mirrors LabelPoolCreate fields."""

    count: int = Field(50, ge=1, le=500, description='Number of labels to generate')
    prefix: str = Field(
        'STM',
        min_length=1,
        max_length=5,
        pattern=r'^[A-Za-z0-9]+$',
        description='Alphanumeric prefix for the short code (1-5 chars, e.g. STM, A, B12)',
    )
    label_type: str = 'GENERIC'
    description: str | None = None
    target_location_id: UUID | None = None
    context_tag: str | None = None


class LabelCodeItemDTO(BaseModel):
    """Input DTO for CoreLabelsAPI.create_from_codes — mirrors LabelCodeItem.

    A single explicit short_code to register in the LabelPool.
    """

    short_code: str = Field(min_length=1, max_length=20)
    description: str | None = None


class UserDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    full_name: str | None = None
    role: str = 'user'
    organization_id: UUID | None = None
    is_active: bool = True
    is_blocked: bool = False
    is_superuser: bool = False
    preferred_language: str | None = None
    created_at: datetime | None = None


class ItemAttachmentDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    item_id: UUID
    file_path: str
    file_name: str
    file_type: str
    file_size: int = 0
    created_at: datetime


class AuditLogDTO(BaseModel):
    """Immutable audit-trail entry (SOX / GDPR compliance)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    user_id: UUID | None = None
    user_email: str | None = None
    action: str
    target_type: str
    target_id: UUID
    snapshot: dict[str, Any] | None = None
    reason: str | None = None
    meta_data: dict[str, Any] | None = None
    created_at: datetime


class AuditAction(StrEnum):
    """Canonical audit-action verbs.

    Lives here (not in app/models) so the public CoreAPI surface can
    expose it without violating the architecture rule that says
    ``app/core/public_api/`` files cannot import from ``app.models``.
    Re-exported from ``app.models.audit_log`` for backward compatibility
    with any callers that already use that import path.
    """

    CREATE = 'CREATE'
    UPDATE = 'UPDATE'
    QUANTITY_CHANGE = 'QUANTITY_CHANGE'
    MOVE = 'MOVE'
    USE = 'USE'
    DISPOSE = 'DISPOSE'
    RESTORE = 'RESTORE'
    SOFT_DELETE = 'SOFT_DELETE'
    PURGE = 'PURGE'
    HARD_DELETE = 'HARD_DELETE'


class AuditTargetType(StrEnum):
    """What an audit entry is about, and what earns one.

    A ``StrEnum``, so it is interchangeable with the plain strings older call
    sites pass. It exists because a set of hand-typed literals spread across
    four routers is how the next one goes missing — which it did: two values
    reached the log for months without ever appearing here.

    The screen does not read this list. Its filter is built from the target
    types the log actually contains, which is the only list that cannot offer
    a filter matching nothing.

    **What belongs in the organization log.** Four kinds of act, plus one
    rule that cuts across them:

    - *Stock* — what there is and how much: quantities, moves, consumption,
      the closing of a count.
    - *Catalogue* — the definitions everything else is written against:
      products, categories, locations, templates, product profiles.
    - *Access* — who may do any of it: members, invitations, API keys,
      modules, organization settings.
    - *Custody* — who holds a thing, where it is, whether it is fit to use.
      Handing an asset to somebody is not an edit to a note; it changes a
      fact about an object in the world, and it is the question the log is
      opened to answer months later.

    And, whatever the kind: **every irreversible deletion**, because the
    record that would have explained it is the one that just went away.

    **What does not belong.** Somebody's own working note — a recipe, a meal
    plan, a shopping list. Those change weekly, belong to the person who
    wrote them, and would bury the four kinds above in noise. Deleting one
    still logs, under the deletion rule: ``RECIPE``, ``MEAL_PLAN`` and
    ``SHOPPING_LIST`` below name the three, and a deletion is the only entry
    any of them ever writes.

    **The line against item history.** The two answer different questions and
    both are needed. This log answers "what happened in this organization" —
    one row per act, legible without opening the record it names. Item
    history answers "what happened to this thing" — the full sequence for a
    single record, including the small movements that would drown the log. A
    quantity change earns a row in both: in history with its full context, in
    the log with the reason and what caused it.
    """

    # Records
    ITEM = 'item'
    DOCUMENT = 'document'
    PURCHASE_ORDER = 'purchase_order'
    STORAGE = 'storage'
    CATEGORY = 'category'
    STOCK_TAKE = 'stock_take'
    INVENTORY_PERIOD = 'inventory_period'
    APPROVAL_REQUEST = 'approval_request'
    MAKER_PRODUCTION_ORDER = 'maker_production_order'
    #: A *production* recipe — the formula, not the cookery note. It decides
    #: what a run takes off the shelf and at what cost, and the run reads it
    #: live at completion, so a line edited while an order is open changes
    #: what that order will consume. That is the catalogue kind above, and
    #: the exclusion of "somebody's own working note" below is about the
    #: culinary recipe of the ``recipes`` module, which is a different table
    #: and cannot reach production except through a one-way frozen copy.
    MAKER_RECIPE = 'maker_recipe'
    # A product template and an equipment model are the same row in the same
    # table, reached from two screens. One word for it, so the journal does
    # not depend on which screen was open.
    PRODUCT_TEMPLATE = 'product_template'
    #: Historical. Nothing writes it any more — the equipment module logged
    #: its models under this word before they were recognised as the product
    #: templates they are. The rows are already in organizations' journals
    #: and the journal is immutable, so the word has to stay readable.
    EQUIPMENT_MODEL = 'equipment_model'
    DOCUMENT_TEMPLATE = 'document_template'
    # The rule a recurring count follows, not a count itself: it gets a
    # target of its own so the journal cannot read it as a stock take that
    # never existed (a schedule's id answers no lookup on the stock takes).
    CYCLE_COUNT_SCHEDULE = 'cycle_count_schedule'
    #: A To do task's overlay: who a derived task was given to, or a task the
    #: boss typed in. Assigning work is the manager's decision about people,
    #: so it is journalled; the task list itself is read from other records.
    WORK_ITEM = 'work_item'
    #: A supplier or customer: the catalogue a delivery and an order are
    #: written against, and the name an outsider is known by.
    PARTNER = 'partner'
    #: A printed code and what it is stuck on. Binding one to a product,
    #: freeing it and deleting it change what a scan will answer; printing a
    #: blank sheet of them only reserves codes and writes nothing here.
    LABEL = 'label'

    # Working notes — the exception the docstring names. Their edits are the
    # author's own business and write nothing; the deletion of the record is
    # the one act that earns a row, because no other table holds a copy and
    # after it there is nothing left to look the name up from. The name
    # therefore travels in the snapshot.
    RECIPE = 'recipe'
    MEAL_PLAN = 'meal_plan'
    SHOPPING_LIST = 'shopping_list'

    # Custody
    #: Whether a batch is fit to use — held on a supplier's word, released
    #: on the lab's. The rule above says so in as many words, and this was
    #: the one custody act that reached no journal at all.
    STOCK_LOT = 'stock_lot'
    EQUIPMENT_ASSIGNMENT = 'equipment_assignment'
    EQUIPMENT_ASSET = 'equipment_asset'
    EQUIPMENT_MAINTENANCE = 'equipment_maintenance'
    EQUIPMENT_ATTESTATION = 'equipment_attestation'

    # Administration
    API_KEY = 'api_key'
    #: A channel organization data leaves by, signed with a secret the
    #: receiver may treat as proof of origin. Who opened one, where it
    #: pointed and when it went away used to be nowhere -- and the delivery
    #: history, the module's only other trace, is cascaded away with the
    #: endpoint it belonged to.
    WEBHOOK_ENDPOINT = 'webhook_endpoint'
    ORG_MEMBER = 'org_member'
    #: A named bundle of permissions, and the catalogue it is drawn from.
    #: `system:config:write` is administrator access precisely because the
    #: holder can write this catalogue and then hand themselves what they
    #: wrote (docs/subsystems/ROLES.md); the journal is what tells that act
    #: from ordinary delegation afterwards.
    ROLE = 'role'
    INVITATION = 'invitation'
    MODULE = 'module'
    ORGANIZATION = 'organization'
    PRODUCT_PROFILE = 'product_profile'


class ItemAction(StrEnum):
    """Canonical item-history action verbs.

    Lives here (not in ``app.models``) so the public CoreAPI surface can
    expose it without importing from ``app.models``. Re-exported from
    ``app.models.item_history``.
    """

    CREATED = 'CREATED'
    UPDATED = 'UPDATED'
    MOVED = 'MOVED'
    USED = 'USED'
    DISPOSED = 'DISPOSED'
    QUANTITY_CHANGED = 'QUANTITY_CHANGED'
    RESTORED = 'RESTORED'
    DELETED = 'DELETED'
    STATUS_CHANGED = 'STATUS_CHANGED'  # General lifecycle status change
    #: The scan's own two verbs: a record that arrived by scanning, and a
    #: delivery added by scanning an existing product's barcode.
    CREATED_VIA_SCAN = 'CREATED_VIA_SCAN'
    QUANTITY_INCREASED_VIA_SCAN = 'QUANTITY_INCREASED_VIA_SCAN'
    #: A package was opened: the record is the opened unit, split off from
    #: the sealed ones when it held several.
    OPENED = 'OPENED'


class RoleDTO(BaseModel):
    """Named bundle of permissions assignable to a user."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID | None = None
    name: str
    permissions: list[str] = Field(default_factory=list)
    is_system: bool = False
    created_at: datetime | None = None
    #: How many people hold this role. Shown on the roles list so an
    #: administrator sees a deletion will be refused before trying it.
    member_count: int = 0


class RoleHolderDTO(BaseModel):
    """Somebody who holds a role — enough to name them, and nothing more."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    full_name: str | None = None


class SystemPermission(StrEnum):
    """Granular permissions for modules and core functionality."""

    # Inventory
    ITEMS_READ = 'items:read'
    ITEMS_WRITE = 'items:write'
    ITEMS_DELETE = 'items:delete'
    ITEMS_PURGE = 'items:purge'

    # Categories
    CATEGORIES_READ = 'categories:read'
    CATEGORIES_WRITE = 'categories:write'

    # Locations — the members keep the table's word, the keys are the contract.
    STORAGES_READ = 'locations:read'
    STORAGES_WRITE = 'locations:write'

    # Partners — a Core register, so the keys live here rather than in a
    # manifest. Their absence is why nothing flagged the unguarded writes: the
    # gate that fails a manifest key with no enforcement point cannot see a
    # register that never declared a key at all.
    PARTNERS_READ = 'partners:read'
    PARTNERS_WRITE = 'partners:write'

    # Organization
    ORG_READ = 'org:read'
    ORG_SETTINGS_WRITE = 'org:settings:write'
    ORG_MEMBERS_WRITE = 'org:members:write'

    # Admin
    ADMIN_ACCESS = 'admin:access'
    SYSTEM_CONFIG_WRITE = 'system:config:write'


# --- What an API key carries -------------------------------------------------
#
# Every key carries its own permission list, chosen when it is issued from
# what its creator holds. Declared here, in the contract layer, because the
# authentication path, the issuing screen and the migration that gave existing
# keys their lists must not disagree about the two sets below.

#: The set every key carried before keys had lists of their own — what the
#: migration gave the keys that already existed.
API_KEY_PERMISSIONS: frozenset[SystemPermission] = frozenset(
    {
        SystemPermission.ITEMS_READ,
        SystemPermission.ITEMS_WRITE,
        SystemPermission.CATEGORIES_READ,
        SystemPermission.STORAGES_READ,
        SystemPermission.ORG_READ,
    }
)

#: The list a new key gets when its creator names none, and the ticks the
#: issuing dialog opens with: read only. The common uses — a dashboard, a home
#: automation — only look, so a write is a tick somebody puts there. Reading
#: the team list (`org:read` returns every member's name, e-mail and role) is
#: not in it: a script that only reads products has no business with people.
API_KEY_DEFAULT_PERMISSIONS: frozenset[SystemPermission] = frozenset(
    {
        SystemPermission.ITEMS_READ,
        SystemPermission.CATEGORIES_READ,
        SystemPermission.STORAGES_READ,
    }
)

# Never on a key, whoever issues it: an automation does not administer the
# organization it works in.
#
# What stands behind `org:settings:write`, read off the live route table, is
# administration end to end — the AI connections (who the organization's model
# provider is, whose key pays for it, and a test that spends it), the equipment
# document templates, the SKU naming schema, and the API key register itself.
# None of that is a machine's work, and a key that may write the register could
# mint its own successors. Members, roles and the installation's configuration
# are the same door. The admin areas are also closed to a key by its role, but
# a permission that cannot be granted cannot be granted by mistake either.
API_KEY_WITHHELD_PERMISSIONS: frozenset[SystemPermission] = frozenset(
    {
        SystemPermission.ORG_SETTINGS_WRITE,
        SystemPermission.ORG_MEMBERS_WRITE,
        SystemPermission.ADMIN_ACCESS,
        SystemPermission.SYSTEM_CONFIG_WRITE,
    }
)

#: The header a key travels in. A key is not a session token, and sharing
#: `Authorization: Bearer` with the JWT made the server tell them apart by
#: their first characters.
API_KEY_HEADER = 'X-API-Key'

#: How every key begins, defined once: the generator writes it, and the rate
#: limiter and the deprecated Bearer form recognise a key by it.
API_KEY_PREFIX = 'inv_live_'


@dataclass(frozen=True)
class UserProfileDTO:
    """User profile DTO for module consumers.

    A frozen dataclass (not Pydantic) — matches the original definition
    in ``app.core.public_api.users``. Re-exported from there for
    backward compatibility.
    """

    id: UUID
    email: str
    full_name: str | None
    role: str
    organization_id: UUID | None
    preferred_language: str


# ── AI Connections ────────────────────────────────────────────────────
#
# These mirror app.schemas.ai_connection but use plain ``str`` for provider
# and capabilities so community modules don't need to import LlmProvider /
# LlmCapability from app.core.llm.enums (though those are legally importable;
# str is simpler for the contract surface).


class AiConnectionDTO(BaseModel):
    """Read shape for AI connections — mirrors AiConnectionSchema."""

    id: UUID
    name: str
    provider: str
    api_key: str
    api_base_url: str
    model_name: str
    temperature: float | None = None
    max_tokens: int | None = None
    top_p: float | None = None
    capabilities: list[str] = Field(default_factory=list)
    #: What the connection test found, per capability:
    #: ``{"vision": {"ok": false, "at": "…", "purpose": "vision.extract"}}``.
    #: ``capabilities`` above is the claim; this is what happened when the
    #: model was actually asked. Absent means never asked.
    capability_checks: dict[str, dict[str, Any]] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class AiPurposeDTO(BaseModel):
    """Read shape for AI purposes — mirrors AiPurposeSchema.

    Two questions, two fields: ``bound_connection_id`` is the raw choice
    the organization made (what the binding select renders and the
    deletion guard protects), ``usable`` is the verdict on whether the
    purpose will actually run — the only field the promise sentences
    branch on.
    """

    key: str
    capability: str
    label_key: str
    description_key: str
    owner_module: str
    bound_connection_id: UUID | None = None
    usable: bool = False


class AiConnectionCreateDTO(BaseModel):
    """Input DTO for CoreAIConnectionsAPI.create — mirrors AiConnectionCreate.

    ``provider`` uses ``str`` (not ``LlmProvider`` enum) to stay contracts-legal;
    validated against the known set of LLM provider values.
    """

    name: str = Field(min_length=1, max_length=255)
    provider: str
    api_key: str | None = None
    api_base_url: str = ''
    model_name: str = ''
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1)
    top_p: float | None = Field(default=None, ge=0.0, le=1.0)
    capabilities: list[str] = Field(default_factory=list)

    @field_validator('api_base_url')
    @classmethod
    def _base_url_required_where_the_client_builds_the_url(
        cls, value: str, info: ValidationInfo
    ) -> str:
        """An OpenAI-compatible client glues its request URL out of this
        field; saved empty, the connection looks ready and the first call
        dies on a relative path with a transport error that never names
        the real cause. Providers reached through an SDK (anthropic,
        google) keep their fixed endpoints and may leave it blank. The
        protocol map is imported lazily: contracts stay import-light.

        A field validator, not a model validator, so the pydantic error's
        ``loc`` names ``api_base_url`` — a module author debugging a
        ``ValidationError`` sees the field, not a sentence to parse.
        ``provider`` sits earlier in the model, so ``info.data`` has it
        by the time this runs. Raised keyed, so pydantic's envelope
        carries the catalog's sentence in the session's language (the
        eager ``ServiceRejectionError`` translates before pydantic wraps
        it as "Value error, <str>", and the 422 handler strips the
        wrapper). The imports stay lazy: contracts stay import-light.
        """
        from app.core.exceptions import ServiceRejectionError
        from app.core.llm.enums import LlmProtocol, protocol_for

        provider = info.data.get('provider')
        if provider is None:
            return value
        if (
            protocol_for(provider) is LlmProtocol.OPENAI_COMPATIBLE
            and not value.strip()
        ):
            raise ServiceRejectionError('llm_base_url_required_for_http_provider')
        return value

    @field_validator('api_base_url', 'model_name', mode='before')
    @classmethod
    def _empty_means_unset(cls, value: object) -> object:
        """Read a form's null as "left empty", not as a type error.

        The create form drafts a blank input as null, and the strict `str`
        answered a raw 422 — "Input should be a valid string", no field
        named — while the identical request with `''` passed.
        """
        return '' if value is None else value

    @field_validator('provider')
    @classmethod
    def validate_provider(cls, v: str) -> str:
        from app.core.exceptions import ServiceRejectionError
        from app.core.llm.enums import LlmProvider

        valid = {p.value for p in LlmProvider}
        if v not in valid:
            raise ServiceRejectionError(
                'ai_provider_invalid', allowed=', '.join(sorted(valid))
            )
        return v


class AiConnectionUpdateDTO(BaseModel):
    """Input DTO for CoreAIConnectionsAPI.update — mirrors AiConnectionUpdate.

    All fields optional (PATCH semantics). ``api_key`` accepts
    ``MASKED_VALUE`` to mean "do not change".
    """

    name: str | None = Field(default=None, min_length=1, max_length=255)
    api_key: str | None = None
    api_base_url: str | None = None
    model_name: str | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1)
    top_p: float | None = Field(default=None, ge=0.0, le=1.0)
    capabilities: list[str] | None = None
