from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.item import Item
from app.schemas.pagination import PaginatedResponse

from ._serial import serial_of

# Alias for annotations inside a class that also has a field named ``date``:
# within that class body the name resolves to the field, not this type.
IsoDate = date


class EquipmentAssetItem(Item):
    """Core Item payload extended with the equipment list columns.

    ``location_name`` and the open assignment's holder are filled by
    the module list endpoint — they stay out of the core Item schema, which
    must remain vertical-agnostic. The holder travels as a name plus its
    kind (``person`` / ``location``): a deployment names the place, and the
    reader words the two differently.
    """

    location_name: str | None = None
    holder_name: str | None = None
    holder_kind: Literal['person', 'location'] | None = None

    @model_validator(mode='before')
    @classmethod
    def attach_list_columns(cls, data: Any) -> Any:
        """Surface the location-name property before the core Item validator.

        The core validator copies only the ORM ``__dict__`` — the read-only
        ``location_name`` property and the ``location_id`` synonym never
        reach it, so they are injected here. The holder fields are set on the
        DTO by the router from the holder map resolved by the list service.
        """
        if isinstance(data, BaseModel) or isinstance(data, dict):
            return data
        if hasattr(data, '__dict__'):
            d = data.__dict__.copy()
            d['location_id'] = getattr(data, 'location_id', None)
            d['location_name'] = getattr(data, 'location_name', None)
            # ``image_url`` is computed from the stored key, so it is absent
            # from the ORM ``__dict__`` this copy starts from.
            d['image_url'] = getattr(data, 'image_url', None)
            # One answer for "what is this asset's number", whether the row
            # predates the move into the core column or not.
            d['serial_number'] = serial_of(data)
            return d
        return data


class EquipmentAssetListResponse(PaginatedResponse[EquipmentAssetItem]):
    """Paginated response for GET /equipment/assets."""

    limit: int = 50
    offset: int = 0
    has_more: bool = False


class BulkEquipmentEntry(BaseModel):
    serial_number: str = Field(min_length=1, max_length=255)
    asset_tag: str | None = Field(None, max_length=255)


class BulkEquipmentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    category_id: UUID | None = None
    location_id: UUID
    brand: str | None = Field(None, max_length=255)
    description: str | None = None
    purchase_price: Decimal | None = Field(None, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)
    entries: list[BulkEquipmentEntry] = Field(min_length=1, max_length=200)


class BulkEquipmentError(BaseModel):
    index: int
    serial_number: str
    error: str
    # The refusal's catalogue code, so a client can branch without the sentence.
    code: str | None = None


class BulkEquipmentResponse(BaseModel):
    created: int
    failed: int
    items: list[str]
    errors: list[BulkEquipmentError] = []


class ImportAnalyzeResult(BaseModel):
    headers: list[str]
    preview_rows: list[dict[str, object]]
    total_rows: int
    # canonical field name → matched header (aliases across the
    # module's five languages). Empty dict when nothing matched.
    suggested_mapping: dict[str, str] = Field(default_factory=dict)


class ImportExecuteResult(BaseModel):
    imported: int
    failed: int
    errors: list[dict[str, object]] = []
    # duplicate handling outcome — skipped (create_only) and
    # updated (update mode) rows.
    skipped: int = 0
    updated: int = 0
    # The serial numbers of the rows skipped as duplicates (the first twenty,
    # as with ``errors``): a bare count leaves the reader to find which rows
    # of a long sheet it is.
    skipped_serials: list[str] = []


class AttachmentSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    item_id: UUID
    original_name: str
    file_type: str
    content_type: str
    size_bytes: int
    url: str
    uploaded_by: UUID
    created_at: datetime


class BulkEditRequest(BaseModel):
    item_ids: list[UUID] = Field(min_length=1, max_length=500)
    action: str = Field(pattern='^(change_status|change_location|assign_to)$')
    data: dict[str, Any] = Field(default_factory=dict)


class AssetFilter(BaseModel):
    """The asset list's filters, as the scope of a bulk action.

    The same five parameters ``GET /equipment/assets`` takes, so "everything
    that matches" means exactly what the reader is looking at.
    """

    search: str | None = None
    category_id: UUID | None = None
    location_id: UUID | None = None
    status: str | None = None
    checked_out: bool = False


class BulkEditResult(BaseModel):
    updated: int
    errors: list[dict[str, str]] = []


class EquipmentModelSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    brand: str | None
    image_url: str | None
    description: str | None
    category_id: UUID | None
    category_name: str | None
    equipment_meta: dict[str, Any] = Field(default_factory=dict)


class EquipmentModelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    brand: str | None = Field(None, max_length=255)
    description: str | None = Field(None, max_length=500)
    image_url: str | None = Field(None, max_length=500)
    category_id: UUID | None = None
    equipment_meta: dict[str, Any] = Field(default_factory=dict)

    @field_validator('name')
    @classmethod
    def validate_name(cls, v: str) -> str:
        if '\x00' in v:
            raise ValueError('name must not contain null bytes')
        return v


class EquipmentModelUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    brand: str | None = Field(None, max_length=255)
    description: str | None = Field(None, max_length=500)
    image_url: str | None = Field(None, max_length=500)
    category_id: UUID | None = None
    equipment_meta: dict[str, Any] | None = None


class MyAssetItem(BaseModel):
    assignment_id: UUID
    item_id: UUID
    item_name: str
    item_barcode: str | None
    category_name: str | None
    # Stable declaration code so the UI can translate the label; the name is
    # the English literal persisted at install time.
    category_code: str | None = None
    checked_out_at: datetime
    expected_return_at: datetime | None
    checkout_notes: str | None
    equipment_status: str | None
    warranty_until: date | None
    serial_number: str | None
    image_url: str | None
    # Shown when the unit has none of its own — the picture belongs to the
    # model it was created from, and the UI says so.
    model_image_url: str | None = None
    # The holder, resolved by the one definition (``_holder``): the person
    # the unit is with, or the place it stands in. My Assets shows it back
    # on the check-in dialog instead of demanding a second fallback there.
    holder_name: str | None = None
    holder_kind: Literal['person', 'location'] | None = None


class MyAssetHistoryItem(BaseModel):
    assignment_id: UUID
    item_id: UUID
    item_name: str
    checked_out_at: datetime
    checked_in_at: datetime | None
    checkin_condition: str | None


class EquipmentApprovalStatus(BaseModel):
    has_workflow: bool
    request_id: UUID | None
    status: str | None
    #: An APPROVED request that has already authorised a checkout reads the
    #: same as one still waiting unless this says otherwise: the card shows
    #: a waiting approval as approved-for-the-next-checkout and a spent one
    #: as needing a new request.
    consumed: bool = False


class AssetValuation(BaseModel):
    item_id: str
    item_name: str
    serial_number: str | None
    purchase_price: Decimal | None
    book_value: Decimal
    depreciation_pct: Decimal
    useful_life_years: int
    is_depreciable: bool


class FleetValuationByCategory(BaseModel):
    category_name: str
    # Stable declaration code so the UI can translate the row label; the
    # name is the English literal persisted at install time.
    category_code: str | None = None
    purchase_value: Decimal
    book_value: Decimal
    depreciation: Decimal
    asset_count: int
    # Of the counted assets, the ones carrying both a purchase date and a
    # useful life — the rows the book/depreciation figures are about. A
    # category at zero shows no number for them.
    depreciable_count: int = 0


class ApprovalActionResponse(BaseModel):
    request_id: str
    status: str


class CheckoutApprovalAsk(BaseModel):
    """The checkout an approval request asks for, from the checkout dialog.

    The approver decides about a hand-out to somebody until some day, and the
    approval covers that hand-out: a checkout to a different holder needs a
    request of its own. The fields are the dialog's, as the checkout itself
    takes them.
    """

    assigned_to_name: str = Field('', max_length=255)
    assignee_partner_id: UUID | None = None
    checkout_location_id: UUID | None = None
    expected_return_at: datetime | None = None


class EquipmentCheckoutTargetSummaryDTO(BaseModel):
    """What an approver needs to see about an equipment checkout.

    The approvals target for an equipment checkout is the *item* (see
    ``_router_approvals``): the request asks "may this asset be checked out".
    ``number`` carries the asset's name — equipment has no document-style
    number — and ``serial_number`` names the specific unit. Who the asset
    goes to is a property of the request, not of the asset, so it travels in
    the request's own ``meta_data`` (``_approval_checkout``) rather than here.
    """

    id: UUID
    number: str
    serial_number: str | None = None

    model_config = ConfigDict(from_attributes=True)


class BulkRetireResult(BaseModel):
    retired: int
    errors: list[dict[str, str]] = []


class BulkArchiveResult(BaseModel):
    archived: int
    errors: list[dict[str, str]] = []


class BulkCheckinRequest(BaseModel):
    item_ids: list[UUID]
    checkin_condition: str | None = Field(None, pattern='^(GOOD|DAMAGED|NEEDS_REPAIR)$')
    checkin_notes: str | None = None
    # One place for the whole batch; empty sends each asset back to its own.
    return_location_id: UUID | None = None


class BulkCheckinResult(BaseModel):
    checked_in: int
    errors: list[dict[str, str]] = []


class BulkPurgeError(BaseModel):
    """One row a bulk purge refused, with the reason the caller can act on.

    ``code`` and ``blocks`` mirror what the single-item purge publishes in its
    409 envelope, so a batch does not force the client back to parsing
    ``error`` prose to tell a document block from a stock-take one. Both stay
    optional: rejections that are not an interceptor veto (not found, purge
    disabled for the organization) carry the message alone.
    """

    item_id: str
    error: str
    code: str | None = None
    blocks: list[dict[str, Any]] | None = None


class BulkPurgeResult(BaseModel):
    purged: int
    errors: list[BulkPurgeError] = []


class ValuationAssetWithoutStatus(BaseModel):
    id: UUID
    name: str


class FleetValuation(BaseModel):
    total_purchase_value: Decimal
    total_book_value: Decimal
    total_depreciation: Decimal
    by_category: list[FleetValuationByCategory]
    asset_count: int
    # Of the counted assets, the ones the book value and depreciation totals
    # are struck from: those with both a purchase date and a useful life.
    # When this is zero the interface shows purchase value alone — no
    # financial column is presented without a configuration behind it.
    depreciable_count: int = 0
    # number of non-retired assets not summed into the totals: they have no
    # purchase price, or their currency differs from the organization's.
    excluded_count: int = 0
    # Counted assets whose status has not been recorded.
    no_status_count: int = 0
    no_status_assets: list[ValuationAssetWithoutStatus] = Field(default_factory=list)


class AssetTimelineEvent(BaseModel):
    """One entry of the asset timeline, assembled server-side.

    Which fields an entry uses depends on ``kind``: a handover names the
    holder (and, on the way back, who actually checked the return in), a
    maintenance entry carries the service record's own columns, a status
    change names the two states. Optional per kind — one model carries the
    union without a discriminator, and the reader-facing labels live in the
    interface, not here.
    """

    kind: Literal[
        'created',
        'checkout',
        'checkin',
        'maintenance',
        'status_changed',
        'attestation_disputed',
    ]
    # Identity of the EVENT (the interface keys its cards by it): one
    # source row may stand for two events — an assignment is both its
    # checkout and its check-in — so the kind prefixes the row's id.
    id: str | None = None
    # A maintenance day is a DATE column and stays one here — coercing it
    # to midnight datetime would bury a same-day repair under every
    # timestamped event of that day. The reader orders it as the whole of
    # the day it names.
    date: datetime | IsoDate
    actor: str | None = None
    holder_name: str | None = None
    # ``person`` / ``location``: a deployment names a place, and the card
    # words it differently from a handover to a person.
    holder_kind: Literal['person', 'location'] | None = None
    holder_email: str | None = None
    operator_name: str | None = None
    issued_by_name: str | None = None
    expected_return_at: datetime | None = None
    condition: str | None = None
    notes: str | None = None
    maintenance_type: str | None = None
    title: str | None = None
    cost: Decimal | None = None
    currency: str | None = None
    description: str | None = None
    next_maintenance_at: IsoDate | None = None
    old_status: str | None = None
    new_status: str | None = None


class AssetTimelineResponse(BaseModel):
    events: list[AssetTimelineEvent]
