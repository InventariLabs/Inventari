from typing import Any, ClassVar, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.exceptions import ServiceRejectionError
from app.schemas.validators import RemovalStrategy

# Closed set of supported field types.
# Mirrored in frontend/src/types/.../FieldDefinition.ts (keep in sync).
#
# - text / number / date: scalar primitives
# - select:              one-of-N from a fixed options list
# - boolean:             true/false toggle
# - textarea:            long-form text (was implicit via extra='allow')
# - file:                file reference (same as textarea)
# - money:               structured {amount, currency} (deposit, price, insurance)
# - multi-select:        string[] from a fixed options list (allergens, hazard classes)
FieldType = Literal[
    'text',
    'number',
    'date',
    'select',
    'boolean',
    'textarea',
    'file',
    'money',
    'multi-select',
]


# Types that REQUIRE a non-empty ``options`` list. Stored explicitly so the
# validator runs once at construction time and never silently accepts a
# malformed definition.
_OPTIONS_REQUIRED_TYPES: frozenset[str] = frozenset({'select', 'multi-select'})


class CategoryFieldDefinition(BaseModel):
    """A single custom field definition on a category — read shape.

    Previously field_definitions was ``list[dict[str, Any]]`` with no key
    or type validation, letting malformed entries through and raising KeyError
    downstream. This typed model enforces a non-empty key and a closed type set
    on NEW definitions. ``type`` defaults to 'text' so legacy/system definitions
    that predate the type field (e.g. {'key':'category_id','is_system':True})
    are not rejected at response-serialization time.

    the type Literal is extended to include ``textarea``, ``file``,
    ``money`` and ``multi-select``. See the ``FieldType`` alias above.

    **Lenient on read paths.** This model does NOT enforce "select/multi-select
    must have a non-empty options list" because legacy data in
    ``categories.field_definitions`` JSONB was written before the rule existed
    (e.g. system categories with ``equipment_status`` and ``options=[]``).
    Strict validation lives in :class:`FieldDefinitionCreate` and is invoked at
    API write boundaries; the read model here accepts whatever the DB stored
    so /items and /categories endpoints keep serializing legacy rows.
    """

    # Expose the closed set as a class attribute for callers that want to
    # iterate (frontend FieldBuilder type selector, registry endpoint, etc.).
    # ClassVar tells Pydantic not to treat this as a model field.
    # Named FIELD_TYPES (not FieldType) to avoid shadowing the module-level
    # Literal alias, which Pydantic uses for the type annotation below.
    FIELD_TYPES: ClassVar[tuple[str, ...]] = (
        'text',
        'number',
        'date',
        'select',
        'boolean',
        'textarea',
        'file',
        'money',
        'multi-select',
    )

    key: str = Field(min_length=1)
    type: FieldType = 'text'
    label: str | None = None
    options: list[str] | None = None
    # A fully-qualified i18n key per option, for ``select``/``multi-select``.
    # The words belong to whoever declares the field — the same convention
    # ``label_key`` uses for permissions and AI purposes — so the equipment
    # module points its statuses at its own ``equipment:status.*`` instead of
    # the core form keeping a second dictionary of the same four words. An
    # option absent from this map is the user's own word and is rendered
    # verbatim; a user-defined field simply omits the map.
    options_i18n: dict[str, str] | None = None
    required: bool = False
    default: str | int | float | bool | None = None
    is_system: bool = False
    visible: bool = True
    # only meaningful for ``money``. Org-level currency is the
    # fallback when the field does not declare one. Kept as a plain field
    # (not a Literal of currencies) so new ISO 4217 codes don't need a
    # schema change; ``validate_field_value`` enforces the 3-letter shape.
    default_currency: str | None = None
    model_config = ConfigDict(extra='allow')


class FieldDefinitionCreate(CategoryFieldDefinition):
    """Strict write shape — enforces per-type structural rules.

    Used by CategoryCreate / CategoryUpdate so that NEW field_definitions
    pushed via the API are validated at the boundary, while legacy rows
    already in the DB still serialize fine through the lenient
    :class:`CategoryFieldDefinition`.
    """

    @model_validator(mode='after')
    def _validate_type_specific_requirements(self) -> 'FieldDefinitionCreate':
        if self.type in _OPTIONS_REQUIRED_TYPES:
            opts = self.options or []
            if not opts:
                raise ServiceRejectionError(
                    'field_options_required', type=str(self.type)
                )
        return self


class CategoryBase(BaseModel):
    name: str
    code: str | None = None
    context_tag: str | None = (
        None  # Neutral context label (e.g. 'cold_storage', 'equipment', 'media')
    )
    # Free-form group label chosen by the organisation (filter grouping on
    # CategoriesPage). A label, not a code: stored verbatim, no enum, no
    # upper(). max_length mirrors the String(50) column so an over-long
    # label is a 422, not a DB error.
    group_label: str | None = Field(default=None, max_length=50)
    icon: str | None = None
    # Category Visual Identity v2 (2026-07-04). Both optional —
    # NULL means "use cascade resolution" on the frontend.
    emoji: str | None = None
    color: str | None = None
    sort_order: int | None = 0
    #: The removal strategy a product minted under this category starts with.
    default_removal_strategy: RemovalStrategy | None = None
    meta_data: dict[str, Any] | None = None
    # Hardening: the API write boundary uses the strict
    # FieldDefinitionCreate so malformed ``select``/``multi-select`` entries
    # are rejected at POST/PATCH. The read path (``Category``) inherits the
    # lenient ``CategoryFieldDefinition`` from BaseModel so legacy rows serialize.
    field_definitions: list[FieldDefinitionCreate] | None = []
    organization_id: UUID | None = None
    is_active: bool = True


class CategoryCreate(CategoryBase):
    pass


class CategoryUpdate(BaseModel):
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
    field_definitions: list[FieldDefinitionCreate] | None = None


class CategoryGroupRename(BaseModel):
    """Rename the group every category in it carries, or take it away.

    ``new_name`` of ``None`` (or blank) leaves those categories ungrouped —
    which is a state the group filter already has a name for.
    """

    current_name: str = Field(min_length=1, max_length=50)
    new_name: str | None = Field(default=None, max_length=50)
    category_ids: list[UUID] | None = Field(
        default=None,
        max_length=1000,
        description='Act on exactly these categories instead of every one '
        'carrying `current_name` — how a removed group is put back.',
    )


class CategoryGroupRenameResult(BaseModel):
    updated: int
    category_ids: list[UUID]


class Category(CategoryBase):
    id: UUID

    # Read path: explicitly narrow ``field_definitions`` to the lenient
    # :class:`CategoryFieldDefinition` so legacy rows with empty ``options`` still
    # serialize. The write path (CategoryCreate / CategoryUpdate) keeps
    # the strict FieldDefinitionCreate. mypy flags this as a covariance
    # issue (a Liskov-substitution-style concern); in practice Pydantic
    # treats both as a list of objects and the asymmetry is intentional
    # — see ``TestFieldDefinitionLenientRead`` in
    # tests/unit/test_field_definition_schema.py.
    field_definitions: list[CategoryFieldDefinition] | None = []  # type: ignore[assignment]
    model_config = ConfigDict(from_attributes=True)
