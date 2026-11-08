from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.exc import MissingGreenlet

from app.core.exceptions import ServiceRejectionError

# Generic alias: the canonical cursor envelope lives in
# app.schemas.pagination; re-exporting it here gives community modules a
# legal import path with zero duplication/drift.
from app.schemas.pagination import (  # noqa: F401
    CursorPaginatedResponse as CursorPaginatedDTO,
)
from app.schemas.validators import (
    QUANTITY_MAX,
    RemovalStrategy,
    decimal_from_int_float,
)

if TYPE_CHECKING:
    from ._system_dtos import StorageTypeDTO


class CategoryDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID | None = None
    name: str
    code: str | None = None
    icon: str | None = None
    sort_order: int | None = None
    is_active: bool = True
    context_tag: str | None = Field(
        None, description='Neutral context label, e.g. "equipment", "food"'
    )
    group_label: str | None = Field(
        None,
        description=(
            'Free-form group label chosen by the organisation; the categories '
            'filter groups by it. A label, not a code — stored verbatim.'
        ),
    )
    default_removal_strategy: RemovalStrategy | None = Field(
        None,
        description='The removal strategy a product created under this '
        'category starts with; the product keeps its own afterwards.',
    )
    module_name: str | None = Field(None, description='Module that owns this category')
    field_definitions: list[dict[str, Any]] | None = Field(
        None, description='Custom field schema for items in this category'
    )
    # Category Visual Identity v2 (2026-07-04). Both optional — NULL
    # means "frontend should resolve via cascade".
    emoji: str | None = Field(
        None, description='User-overridable single-glyph emoji (e.g. "🥚")'
    )
    color: str | None = Field(
        None,
        description=(
            'Tailwind palette key (e.g. "indigo"), not a hex value. '
            'See frontend CategoryAvatar.FALLBACK_COLORS for valid keys.'
        ),
    )
    items_count: int | None = Field(
        None,
        description=(
            'Products filed under this category, each counted once however many '
            'records it has. None unless the caller '
            'asked for counts — computing it costs an extra grouped query.'
        ),
    )
    is_module_owned: bool = Field(
        False,
        description=(
            'Whether a vertical module claims this category via its '
            'context_tag, computed at read time from the module registry — '
            'the same rule that isolates the general lists. A screen that '
            'offers such a category can say before the save that the record '
            'will be filed under that module.'
        ),
    )


class StorageDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    name: str
    usage: str = Field(
        description='Location usage, e.g. "internal", "customer", "production"'
    )
    short_code: str | None = None
    sequence: int | None = Field(
        None, description='Ordering number among locations, lowest first'
    )
    behavior_mode: str | None = Field(
        None, description='Tracking mode: "STOCK", "EXPIRY", "FREEZING"'
    )
    context_tag: str | None = Field(
        None, description='Neutral context label, e.g. "equipment", "food"'
    )
    description: str | None = None
    parent_id: UUID | None = Field(
        None, description='Parent storage location ID for hierarchy'
    )
    warehouse_config: dict[str, Any] | None = Field(
        None,
        description='WMS configuration for this location (outgoing chains, putaway rules, etc.)',
    )
    settings: dict[str, Any] | None = None
    location_details: str | None = None
    context_schema: list[str] | None = None
    field_definitions: list[dict[str, Any]] | None = None
    created_at: datetime | None = None
    location_type_id: UUID | None = None
    location_type: StorageTypeDTO | None = None  # forward ref → _system_dtos


class StorageTypeCreateDTO(BaseModel):
    """Input DTO for CoreStorageTypesAPI.create — mirrors StorageTypeCreate fields.

    ``field_definitions`` uses ``list[dict[str, Any]]`` (not the internal
    ``CategoryFieldDefinition`` model) to stay contracts-legal; the CoreAPI maps
    to the internal schema which coerces dicts to typed FieldDefinitions.
    """

    name: str
    type_code: str
    behavior_mode: str = 'STOCK'
    icon: str | None = None
    default_settings: dict[str, Any] | None = None
    context_schema: list[str] | None = None
    field_definitions: list[dict[str, Any]] | None = None


class StorageTypeUpdateDTO(BaseModel):
    """Input DTO for CoreStorageTypesAPI.update — all fields optional (PATCH-style).

    Mirrors StorageTypeUpdate; unset fields are excluded from the update via
    ``model_dump(exclude_unset=True)`` inside CoreAPI.
    """

    name: str | None = None
    icon: str | None = None
    behavior_mode: str | None = None
    default_settings: dict[str, Any] | None = None
    context_schema: list[str] | None = None
    field_definitions: list[dict[str, Any]] | None = None


class ItemDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    location_id: UUID
    location_name: str | None = None
    template_id: UUID | None = None
    template_name: str | None = None
    category_id: UUID | None = None
    category: CategoryDTO | None = None
    name: str
    brand: str | None = None
    uom_id: UUID | None = None
    uom_symbol: str | None = None
    uom: UomDTO | None = Field(
        None, description='Unit of measure (eager-loaded by list_by_expiry_async)'
    )
    shelf_location: str | None = None
    quantity: Decimal | None = None
    barcode: str | None = None
    purchase_price: Decimal | None = None
    currency: str | None = None
    added_date: date | None = None
    expiry_date: date | None = None
    image_url: str | None = None
    meta_data: dict[str, Any] | None = Field(
        None,
        description='Namespaced dict — modules use their own key, e.g. meta_data["equipment"]',
    )
    serial_number: str | None = Field(
        None, description='GS1/WMS serial number (tracked items only)'
    )
    lot_id: UUID | None = Field(
        None, description='The batch whose stock this record holds, if any'
    )
    owner_id: UUID | None = Field(
        None, description='The partner whose goods these are (consignment), if any'
    )
    is_deleted: bool
    created_at: datetime
    updated_at: datetime


class ItemCreateDTO(BaseModel):
    """Input DTO for CoreItemsAPI.create_async — mirrors ItemCreate fields.

    Field-level normalization (barcode, empty strings → None, currency
    default) runs in the internal ``ItemCreate`` construction inside
    CoreAPI, so this DTO only mirrors fields + constraints (the one
    validator that must act before coercion — quantity — is mirrored).
    """

    name: str
    brand: str | None = None
    description: str | None = None
    uom_id: UUID | None = None
    quantity: Decimal = Field(default=Decimal('1.0'), ge=0, le=QUANTITY_MAX)
    barcode: str | None = None
    serial_number: str | None = None
    expiry_date: date | None = None
    freeze_date: date | None = None
    #: The receipt date of the goods, for a caller that knows it — a split
    #: carrying stock off an older record. Left unset it stays the record's
    #: birth day (the column default), which is what every ordinary create
    #: wants; an explicit ``None`` means the same and is dropped before the
    #: row is built, because the column is NOT NULL.
    added_date: date | None = None
    shelf_location: str | None = None
    metadata: dict[str, Any] | None = None
    weight_value: float | None = None
    weight_uom_id: UUID | None = None
    #: The product's reorder threshold — a card-level field the payload can
    #: name, written to the card the record joins (ADR-015), like
    #: ``weight_value``. It was read off the payload without ever being
    #: declared on the input schemas, so a caller that named it lost it at
    #: the edge (mirrors ``ItemCreate.min_quantity``).
    min_quantity: float | None = None
    volume_value: float | None = None
    volume_uom_id: UUID | None = None
    purchase_price: Decimal | None = None
    currency: str | None = None
    location_id: UUID
    category_id: UUID | None = None
    #: The card the record is a record *of*, when the caller names it: the
    #: record binds to this card directly and no barcode or name matching
    #: runs — two cards of one name must not answer instead (mirrors
    #: ``ItemCreate.template_id``).
    template_id: UUID | None = None
    image_url: str | None = None
    #: The batch and the owner the new record's stock is in — for a caller
    #: that knows them, such as a receipt that named a batch. Not part of the
    #: request body a client sends.
    lot_id: UUID | None = None
    owner_id: UUID | None = None

    @field_validator('quantity', mode='before')
    @classmethod
    def quantity_to_decimal(cls, v: Any) -> Any:
        return decimal_from_int_float(v)


class ItemUpdateDTO(BaseModel):
    """Input DTO for CoreItemsAPI.update_async — all fields optional (PATCH-style).

    Mirrors ItemUpdate; unset fields are excluded from the update via
    ``model_dump(exclude_unset=True)`` inside CoreAPI.
    """

    name: str | None = None
    brand: str | None = None
    description: str | None = None
    uom_id: UUID | None = None
    quantity: Decimal | None = Field(default=None, ge=0, le=QUANTITY_MAX)
    barcode: str | None = None
    serial_number: str | None = None
    location_id: UUID | None = None
    expiry_date: date | None = None
    freeze_date: date | None = None
    shelf_location: str | None = None
    category_id: UUID | None = None
    metadata: dict[str, Any] | None = None
    image_url: str | None = None
    purchase_price: Decimal | None = None
    currency: str | None = None
    min_quantity: float | None = None

    @field_validator('quantity', mode='before')
    @classmethod
    def quantity_to_decimal(cls, v: Any) -> Any:
        return decimal_from_int_float(v)


class ProductTemplateDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID | None = Field(
        None, description='None for global templates, UUID for org-specific'
    )
    name: str
    brand: str | None = None
    barcode: str | None = None
    sku: str | None = None
    removal_strategy: str | None = Field(
        None, description='FIFO or FEFO; None follows the default (FIFO)'
    )
    uom_id: UUID | None = None
    image_url: str | None = None
    description: str | None = None
    min_quantity: float | None = Field(
        None, description='Minimum stock threshold for low-stock alerts'
    )
    meta_data: dict[str, Any] | None = Field(
        None, description='Namespaced dict — modules use their own key'
    )
    weight_value: float | None = Field(
        None, description='Original full-pack weight (for opened-pack detection)'
    )
    weight_uom_id: UUID | None = None
    weight_uom: UomDTO | None = Field(
        default=None,
        alias='_weight_uom_dto',
        description='Eager-loaded weight UOM (opened-pack detection); '
        'None when the relationship is not loaded',
    )
    volume_value: float | None = None
    volume_uom_id: UUID | None = None

    @model_validator(mode='before')
    @classmethod
    def _extract_weight_uom_safely(cls, data: Any) -> Any:
        """Populate ``weight_uom`` without triggering a lazy load.

        ``weight_uom`` is a ``selectin`` relationship, so a template that
        came from a query carries it. One that did not — just added to the
        session, or with its relationships expired by a commit or refresh —
        would load it lazily, which an async context refuses
        (``MissingGreenlet``). The field carries a private alias so
        ``from_attributes`` never touches the attribute directly; we then
        read it via ``getattr`` and map only the async-IO error to ``None``
        (real exceptions propagate).
        """
        if isinstance(data, dict):
            # Accept the public field name in dicts too (kwargs construction).
            if 'weight_uom' in data and '_weight_uom_dto' not in data:
                data['_weight_uom_dto'] = data.pop('weight_uom')
            return data
        data_dict: dict[str, Any] = {}
        for name in cls.model_fields:
            if name == 'weight_uom':
                # Read the (possibly lazy) relationship; None when unloaded.
                data_dict['_weight_uom_dto'] = cls._attr_or_none(data, name)
                continue
            data_dict[name] = cls._attr_or_none(data, name)
        return data_dict

    @staticmethod
    def _attr_or_none(data: Any, name: str) -> Any:
        """Read *name*, mapping only async lazy-load failures to None."""
        try:
            return getattr(data, name, None)
        except MissingGreenlet:
            return None


class ProductTemplateCandidateDTO(BaseModel):
    """A template proposed for a name search, not yet chosen.

    Deliberately just an id and a name: batch name search hands back what
    it found so the caller can rank it, and the caller ranks by name. A
    full :class:`ProductTemplateDTO` would suggest the other columns were
    loaded when the query never asked for them.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str


# Official ISO 3166-1 alpha-2 codes (all 249 assigned). Single source of truth
# for country validation: the API must reject fabricated codes such as "ZZ",
# not merely accept any two uppercase letters.
ISO_3166_ALPHA2_CODES: frozenset[str] = frozenset(
    {
        'AD',
        'AE',
        'AF',
        'AG',
        'AI',
        'AL',
        'AM',
        'AO',
        'AQ',
        'AR',
        'AS',
        'AT',
        'AU',
        'AW',
        'AX',
        'AZ',
        'BA',
        'BB',
        'BD',
        'BE',
        'BF',
        'BG',
        'BH',
        'BI',
        'BJ',
        'BL',
        'BM',
        'BN',
        'BO',
        'BQ',
        'BR',
        'BS',
        'BT',
        'BV',
        'BW',
        'BY',
        'BZ',
        'CA',
        'CC',
        'CD',
        'CF',
        'CG',
        'CH',
        'CI',
        'CK',
        'CL',
        'CM',
        'CN',
        'CO',
        'CR',
        'CU',
        'CV',
        'CW',
        'CX',
        'CY',
        'CZ',
        'DE',
        'DJ',
        'DK',
        'DM',
        'DO',
        'DZ',
        'EC',
        'EE',
        'EG',
        'EH',
        'ER',
        'ES',
        'ET',
        'FI',
        'FJ',
        'FK',
        'FM',
        'FO',
        'FR',
        'GA',
        'GB',
        'GD',
        'GE',
        'GF',
        'GG',
        'GH',
        'GI',
        'GL',
        'GM',
        'GN',
        'GP',
        'GQ',
        'GR',
        'GS',
        'GT',
        'GU',
        'GW',
        'GY',
        'HK',
        'HM',
        'HN',
        'HR',
        'HT',
        'HU',
        'ID',
        'IE',
        'IL',
        'IM',
        'IN',
        'IO',
        'IQ',
        'IR',
        'IS',
        'IT',
        'JE',
        'JM',
        'JO',
        'JP',
        'KE',
        'KG',
        'KH',
        'KI',
        'KM',
        'KN',
        'KP',
        'KR',
        'KW',
        'KY',
        'KZ',
        'LA',
        'LB',
        'LC',
        'LI',
        'LK',
        'LR',
        'LS',
        'LT',
        'LU',
        'LV',
        'LY',
        'MA',
        'MC',
        'MD',
        'ME',
        'MF',
        'MG',
        'MH',
        'MK',
        'ML',
        'MM',
        'MN',
        'MO',
        'MP',
        'MQ',
        'MR',
        'MS',
        'MT',
        'MU',
        'MV',
        'MW',
        'MX',
        'MY',
        'MZ',
        'NA',
        'NC',
        'NE',
        'NF',
        'NG',
        'NI',
        'NL',
        'NO',
        'NP',
        'NR',
        'NU',
        'NZ',
        'OM',
        'PA',
        'PE',
        'PF',
        'PG',
        'PH',
        'PK',
        'PL',
        'PM',
        'PN',
        'PR',
        'PS',
        'PT',
        'PW',
        'PY',
        'QA',
        'RE',
        'RO',
        'RS',
        'RU',
        'RW',
        'SA',
        'SB',
        'SC',
        'SD',
        'SE',
        'SG',
        'SH',
        'SI',
        'SJ',
        'SK',
        'SL',
        'SM',
        'SN',
        'SO',
        'SR',
        'SS',
        'ST',
        'SV',
        'SX',
        'SY',
        'SZ',
        'TC',
        'TD',
        'TF',
        'TG',
        'TH',
        'TJ',
        'TK',
        'TL',
        'TM',
        'TN',
        'TO',
        'TR',
        'TT',
        'TV',
        'TW',
        'TZ',
        'UA',
        'UG',
        'UM',
        'US',
        'UY',
        'UZ',
        'VA',
        'VC',
        'VE',
        'VG',
        'VI',
        'VN',
        'VU',
        'WF',
        'WS',
        'YE',
        'YT',
        'ZA',
        'ZM',
        'ZW',
    }
)


class PartnerAddressDTO(BaseModel):
    """Input address for CorePartnersAPI (mirrors ``PartnerAddress``).

       ``extra='forbid'`` rejects unknown keys so dead data never reaches the
       JSONB column. ``country`` is an ISO 3166-1 alpha-2 code (two uppercase
    letters). Legacy free-text country values stored earlier are read
       through :class:`PartnerDTO.address`, which stays a plain dict.
    """

    model_config = ConfigDict(extra='forbid')

    street: str | None = Field(None, max_length=255)
    city: str | None = Field(None, max_length=255)
    postal_code: str | None = Field(None, max_length=20)
    country: str | None = Field(None, max_length=2)

    @field_validator('country', mode='before')
    @classmethod
    def validate_country_code(cls, v: Any) -> str | None:
        if v is None or v == '':
            return None
        code = str(v).strip().upper()
        if code not in ISO_3166_ALPHA2_CODES:
            raise ServiceRejectionError('invalid_country_code')
        return code


class PartnerDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    name: str
    code: str | None = None
    type: str = Field(
        description='Partner type: SUPPLIER, CUSTOMER, BOTH, SERVICE_PROVIDER, MANUFACTURER, EMPLOYEE'
    )
    tax_id: str | None = None
    is_consumer: bool = False
    email: str | None = None
    phone: str | None = None
    website: str | None = None
    contact_person: str | None = None
    address: dict[str, Any] | None = None
    notes: str | None = None
    is_active: bool
    created_at: datetime | None = None
    updated_at: datetime | None = None


_ALLOWED_PARTNER_TYPES = frozenset(
    {'SUPPLIER', 'CUSTOMER', 'BOTH', 'SERVICE_PROVIDER', 'MANUFACTURER', 'EMPLOYEE'}
)

#: The partner types that answer "who supplies us?" and "who do we sell to?".
#: Document validation, the purchase-order workflow, the pricelist and both
#: partner dropdowns ask these sets, so they live on the contract surface
#: rather than in the core schemas a module may not import. A manufacturer
#: also delivers goods, and BOTH covers "we buy from and sell to the same
#: entity".
SUPPLIER_ROLE_TYPES = frozenset({'SUPPLIER', 'BOTH', 'MANUFACTURER'})
CUSTOMER_ROLE_TYPES = frozenset({'CUSTOMER', 'BOTH'})


class PartnerCreateDTO(BaseModel):
    """Input DTO for CorePartnersAPI.create_async — mirrors PartnerCreate fields."""

    name: str = Field(max_length=255)
    code: str | None = Field(None, max_length=50)
    type: str = Field(
        max_length=30,
        description='SUPPLIER | CUSTOMER | BOTH | SERVICE_PROVIDER | MANUFACTURER | EMPLOYEE',
    )
    tax_id: str | None = Field(None, max_length=50)
    email: str | None = Field(None, max_length=255)
    phone: str | None = Field(None, max_length=50)
    website: str | None = Field(None, max_length=500)
    contact_person: str | None = Field(None, max_length=255)
    address: PartnerAddressDTO | None = None
    notes: str | None = None

    @field_validator('type')
    @classmethod
    def validate_type(cls, v: str) -> str:
        upper = v.upper()
        if upper not in _ALLOWED_PARTNER_TYPES:
            raise ServiceRejectionError('invalid_partner_type')
        return upper

    @field_validator('website')
    @classmethod
    def validate_website(cls, v: str | None) -> str | None:
        """Normalize: prepend https:// if missing (mirrors PartnerBase.validate_website)."""
        if v is None:
            return v
        if not re.match(r'^https?://', v):
            return f'https://{v}'
        return v


class PartnerUpdateDTO(BaseModel):
    """Input DTO for CorePartnersAPI.update_async — all fields optional (PATCH-style)."""

    name: str | None = Field(None, max_length=255)
    code: str | None = Field(None, max_length=50)
    type: str | None = Field(None, max_length=30)
    tax_id: str | None = Field(None, max_length=50)
    email: str | None = Field(None, max_length=255)
    phone: str | None = Field(None, max_length=50)
    website: str | None = Field(None, max_length=500)
    contact_person: str | None = Field(None, max_length=255)
    address: PartnerAddressDTO | None = None
    notes: str | None = None

    @field_validator('type')
    @classmethod
    def validate_type(cls, v: str | None) -> str | None:
        if v is None:
            return v
        upper = v.upper()
        if upper not in _ALLOWED_PARTNER_TYPES:
            raise ServiceRejectionError('invalid_partner_type')
        return upper

    @field_validator('website')
    @classmethod
    def validate_website(cls, v: str | None) -> str | None:
        """Normalize: prepend https:// if missing (mirrors PartnerBase.validate_website)."""
        if v is None:
            return v
        if not re.match(r'^https?://', v):
            return f'https://{v}'
        return v


class OrganizationDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    short_id: str | None = None
    settings: dict[str, Any] | None = None
    allowed_modules: list[str] | None = None
    enabled_modules: list[str] | None = None
    currency: str | None = None
    tax_id: str | None = None
    country: str | None = None
    # Issuer identity: structured address and org-scoped logo path,
    # printed on document PDFs.
    address: dict[str, Any] | None = None
    logo_url: str | None = None
    # The paper this organization's office prints on; None means the
    # country answers (resolved in ``app.core.print_page_size``).
    print_page_size: str | None = None
    created_by: UUID | None = None
    timezone: str = 'UTC'
    created_at: datetime
    member_count: int | None = None
    active_profile_id: str | None = None
    onboarding_completed: bool | None = None


class UomInfoDTO(BaseModel):
    """The compact unit a response embeds beside a quantity.

    ``rounding`` travels with the symbol because precision belongs to the
    unit and to nothing else: quantity is stored in ``numeric(10,3)``, so a
    piece serializes as "1.000", and a reader printing that string has no
    way to know a piece does not divide unless the step comes with it. The
    shape is the one a document line carries; ``UomDTO`` is the full unit a
    lookup returns.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    symbol: str
    name: str
    rounding: Decimal = Field(
        Decimal('0.01'),
        description='The smallest step this unit is counted in — 1 for pieces',
    )


class UomDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID | None = None
    category_id: UUID
    name: str
    symbol: str
    factor: Decimal = Field(
        Decimal('1'),
        description='Conversion factor relative to the reference UoM in this category',
    )
    is_reference: bool = Field(
        False, description='True if this is the base unit of the category'
    )
    is_system: bool = False
    rounding: Decimal = Field(Decimal('0.01'), description='Decimal rounding precision')


class UomCategoryDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID | None = None
    name: str
    uoms: list[UomDTO] = Field(default_factory=list)


class CategoryCreateDTO(BaseModel):
    """Input DTO for CoreCategoriesAPI.create — mirrors CategoryCreate fields.

    ``field_definitions`` uses ``list[dict[str, Any]]`` (not the internal
    ``FieldDefinitionCreate`` model) to stay contracts-legal; the CoreAPI
    maps to the internal schema which applies per-type validators.
    """

    name: str
    code: str | None = None
    context_tag: str | None = None
    # max_length mirrors the String(50) column — an over-long label is a 422
    # at the boundary, not a DB error.
    group_label: str | None = Field(default=None, max_length=50)
    icon: str | None = None
    emoji: str | None = None
    color: str | None = None
    sort_order: int | None = 0
    default_removal_strategy: RemovalStrategy | None = None
    meta_data: dict[str, Any] | None = None
    field_definitions: list[dict[str, Any]] | None = []


class CategoryUpdateDTO(BaseModel):
    """Input DTO for CoreCategoriesAPI.update — all fields optional (PATCH-style).

    Mirrors CategoryUpdate; unset fields are excluded from the update via
    ``model_dump(exclude_unset=True)`` inside CoreAPI.
    """

    name: str | None = None
    context_tag: str | None = None
    group_label: str | None = Field(default=None, max_length=50)
    icon: str | None = None
    emoji: str | None = None
    color: str | None = None
    sort_order: int | None = None
    default_removal_strategy: RemovalStrategy | None = None
    meta_data: dict[str, Any] | None = None
    is_active: bool | None = None
    field_definitions: list[dict[str, Any]] | None = None
