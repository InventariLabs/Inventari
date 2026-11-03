from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.category import CategoryFieldDefinition
from app.schemas.storage_type import StorageType

# The LocationUsage values (app.models.storage_location.LocationUsage).
# Read-side only: no write payload takes a usage any more — a location a
# person creates is always ``internal``, and the virtual ones are seeded by
# the system. The alias survives for the one field that still names the type,
# ``StorageLocationUpdate.usage``, which exists to be refused.
StorageUsageLiteral = Literal[
    'internal',
    'customer',
    'inventory',
    'production',
]


class StorageLocationBase(BaseModel):
    name: str
    parent_id: UUID | None = None
    description: str | None = None
    location_details: str | None = None
    settings: dict[str, Any] | None = None
    # The ordering number walks follow (``StorageLocation.sequence``).
    sequence: int | None = Field(None, ge=0, le=999_999)


class StorageLocationCreate(StorageLocationBase):
    location_type_id: UUID | None = None
    short_code_prefix: str | None = 'LOC'
    short_code: str | None = None
    context_tag: str | None = None
    behavior_mode: str | None = None
    context_schema: list[str] | None = None
    # tightens from list[Any] to the typed CategoryFieldDefinition. The
    # closed Literal + select/multi-select options validator runs at the
    # API boundary, so malformed definitions are rejected at write time
    # rather than at render time (the legacy silent-gate).
    field_definitions: list[CategoryFieldDefinition] | None = None


class StorageLocationUpdate(BaseModel):
    name: str | None = None
    parent_id: UUID | None = None
    description: str | None = None
    location_details: str | None = None
    settings: dict[str, Any] | None = None
    context_schema: list[str] | None = None
    # typed (see StorageLocationCreate).
    field_definitions: list[CategoryFieldDefinition] | None = None
    short_code: str | None = None
    location_type_id: UUID | None = None
    sequence: int | None = Field(None, ge=0, le=999_999)
    # Accepted so the refusal can be a sentence rather than a schema error:
    # the service rejects any value that differs from the stored one. Left
    # out of the schema entirely, a client asking to scrap a shelf would be
    # answered "done" and nothing would have happened.
    usage: StorageUsageLiteral | None = None
    # What a change of ``parent_id`` means, as on a reorg move
    # (``StorageReorgOperation.relocation``); ignored when the parent stays.
    relocation: Literal['physical', 'correction'] | None = None


class StorageLocation(StorageLocationBase):
    id: UUID
    organization_id: UUID
    location_type_id: UUID | None = None
    short_code: str | None = None
    created_at: datetime
    location_type: StorageType | None = None
    context_schema: list[str] = []
    behavior_mode: str = 'STOCK'
    # typed list[CategoryFieldDefinition] (read-side response).
    field_definitions: list[CategoryFieldDefinition] = []
    context_tag: str | None = None
    usage: str = 'internal'  # LocationUsage value

    model_config = ConfigDict(from_attributes=True)


class ArchivedStorageLocation(StorageLocation):
    """One row of ``GET /locations/archived`` — the identity a restore needs.

    A location's identity is its path, not its name: two locations may share
    a name ("Shelf 1" under two different parents), and the archive is where
    picking wrong is costliest — the row is gone from every other screen
    until restored. ``full_path`` carries the shape
    ``StorageLocationSummary`` gives it ("Server Room › Shelf 1").

    ``archived_at`` is the moment the location left the lists, read from the
    organization journal (``SOFT_DELETE`` / ``storage``): archiving writes no
    date column of its own (the flag lives in ``settings``), so the journal
    is where that date lives. A row archived outside the API has no entry
    and answers ``None`` rather than a wrong date.
    """

    full_path: str | None = None
    archived_at: datetime | None = None


class InheritedTrackedField(BaseModel):
    """A tracked field a location takes from a location above it."""

    key: str
    from_id: UUID
    from_name: str


class InheritedFieldDefinition(CategoryFieldDefinition):
    """A custom field a location takes from a location above it."""

    from_id: UUID
    from_name: str


class StorageLocationSummary(BaseModel):
    id: UUID
    name: str
    parent_id: UUID | None = None
    short_code: str | None = None
    sequence: int | None = None
    settings: dict[str, Any] | None = None
    location_type: StorageType | None = None
    context_schema: list[str] = []
    behavior_mode: str = 'STOCK'
    # typed list[CategoryFieldDefinition].
    field_definitions: list[CategoryFieldDefinition] = []
    # The product fields the locations above this one set: a field set on a
    # rack applies to every shelf in it, and to a shelf added later. Nearest
    # level first, each key once — the nearest level that sets it wins. They
    # come from the ancestors only, whatever this location sets itself, so a
    # screen editing the own lists still knows what stays from above.
    inherited_context_schema: list[InheritedTrackedField] = []
    inherited_field_definitions: list[InheritedFieldDefinition] = []
    context_tag: str | None = None
    usage: str = 'internal'  # LocationUsage value
    items_count: int
    subtree_items_count: int = 0  # items here + in all descendants
    # Only populated when the other counts were narrowed — to one module by
    # module_scope, or to the general records by exclude_module_contexts:
    # records of EVERY module standing directly in this location — the number
    # the deletion guard answers to, since the server refuses while any of
    # them stands here (children are reparented on delete, not asked first).
    # Zero on a listing nothing narrowed, where items_count already is the
    # whole truth.
    total_items_count: int = 0
    # The all-modules twin of subtree_items_count: records of EVERY module
    # standing HERE OR IN ANY DESCENDANT — the number a delete confirmation
    # has to name, since children are reparented and everything in the
    # subtree changes its place in the tree. Unlike total_items_count above
    # it does not wait for a module_scope listing: it rides EVERY listing,
    # folded from the full organization tree, because the dialog that names
    # it lives on the unscoped one (spaces) as much as on the scoped one
    # (equipment) — a descendant the listing's filter drops is still a
    # record the delete moves. The single-storage summary endpoint is not a
    # listing; it answers a smaller shape and leaves this at the default.
    total_subtree_items_count: int = 0
    # The OTHER number the same confirmation names: the DIRECT children, the
    # only locations that move up one level when this one is deleted.
    # Grandchildren stay under the parent that moved, so a subtree walk would
    # promise a move that never happens. On EVERY listing, scoped or not —
    # it is not a narrowed twin of anything, and the dialog that names it
    # lives on the unscoped one (spaces) as much as on the scoped one
    # (equipment). Counted across every module from the full organization
    # tree: a child the listing's filter drops is still a child the delete
    # reparents.
    direct_children_count: int = 0
    # How many of those direct children this listing itself shows. The two
    # differ by the children the listing hides — archived ones, or ones its
    # module filter drops — which the delete lifts all the same; the
    # confirmation names the difference instead of a number the reader can
    # match against nothing on screen.
    listed_children_count: int = 0
    expiring_soon_count: int  # items expiring within 7 days
    full_path: str | None = (
        None  # precomputed full hierarchy path, e.g. "Warehouse › Zone A › Shelf 1"
    )
    is_leaf: bool = (
        True  # True if no other storage has this as parent (i.e. can hold items)
    )

    model_config = ConfigDict(from_attributes=True)


class StorageLocationBreadcrumb(BaseModel):
    id: UUID
    name: str

    model_config = ConfigDict(from_attributes=True)


class StorageLocationNode(BaseModel):
    """Tree node — used by GET /locations/tree endpoint."""

    id: UUID
    name: str
    parent_id: UUID | None = None
    usage: str
    location_type_id: UUID | None = None
    short_code: str | None = None
    sequence: int | None = None
    context_tag: str | None = None
    items_count: int = 0
    subtree_items_count: int = 0  # items here + in all descendants
    # How many locations stand directly below. A level asked for alone
    # (``depth``) leaves ``children`` empty, and this is what tells the screen
    # whether there is anything to open.
    children_count: int = 0
    children: list[StorageLocationNode] = []

    model_config = ConfigDict(from_attributes=True)


StorageLocationNode.model_rebuild()


class StorageCodeReprint(BaseModel):
    """A location whose sticker still carries the code it had before numbering."""

    id: UUID
    name: str
    path: str
    short_code: str | None = None
    #: The code on the sticker now on the shelf. It keeps scanning: it stays
    #: as a pool label aimed at this location.
    old_code: str


class StorageCodes(BaseModel):
    """How a warehouse makes its location codes, and what waits to be relabelled."""

    warehouse_id: UUID
    #: The template in force: the warehouse's own, else its profile's.
    template: str
    #: True when the template follows the tree (``A-02-01``), False for a
    #: random prefix (``LOC-7KQ2``).
    is_tree: bool
    #: Whether the warehouse names a template of its own.
    stored: bool
    #: The profile's template, the one a warehouse naming none follows.
    default_template: str
    reprint: list[StorageCodeReprint] = []


class StorageCodeTemplateUpdate(BaseModel):
    """A warehouse's code template; empty or null to follow the profile again."""

    template: str | None = Field(default=None, max_length=100)


class StorageNumberRequest(BaseModel):
    #: False numbers what has no shelf code yet and keeps the rest; True
    #: numbers every family afresh in walk order.
    renumber: bool = False


class StorageCodeChange(BaseModel):
    id: UUID
    name: str
    old_code: str | None = None
    new_code: str


class StorageNumberResponse(BaseModel):
    changes: list[StorageCodeChange]
    codes: StorageCodes


class StorageReprintedRequest(BaseModel):
    """Locations whose new sticker is on the shelf now."""

    location_ids: list[UUID] = Field(min_length=1, max_length=1000)


class StorageTypeInlineCreate(BaseModel):
    """Storage type passed inline — created atomically within StorageHierarchyCreate."""

    name: str
    type_code: str = ''
    icon: str = 'Package'
    behavior_mode: str = 'STOCK'
    context_schema: list[str] = []
    # typed list[CategoryFieldDefinition].
    field_definitions: list[CategoryFieldDefinition] = []


class StorageHierarchyStep(BaseModel):
    """One node of a location chain: an existing one, or one to create.

    ``id`` names a node that already exists. ``name`` resolves to the child
    of the previous step that carries it, and creates it when there is none.
    """

    id: UUID | None = None
    name: str | None = None


class StorageHierarchyCreate(BaseModel):
    """Atomically create a chain of locations of any length (ADR-018).

    ``steps`` walks downwards from ``parent_id``; every field below it
    describes the **last** step, which is the location the caller is really
    creating. Finishing higher up is a shorter chain, not a null name.
    """

    # The node the chain hangs under. Omitted: the chain hangs under nothing,
    # and its first named step becomes a root — the same shape as every
    # seeded warehouse and as the one StorageRequired makes.
    parent_id: UUID | None = None
    steps: list[StorageHierarchyStep] = Field(min_length=1)

    # Everything below applies to the node the last step lands on.
    description: str | None = None
    short_code: str | None = None

    # Tracking fields chosen by user (replaces storage_type_id in wizard flow)
    context_schema: list[str] = []
    # Typed list[CategoryFieldDefinition].
    field_definitions: list[CategoryFieldDefinition] = []

    # Legacy: still accepted for API compat (e.g. StoragesPage type editor)
    location_type_id: UUID | None = None
    location_type: StorageTypeInlineCreate | None = None

    # Module scoping — e.g. 'equipment', 'food'; NULL = universal
    context_tag: str | None = None


class StorageArchiveRequest(BaseModel):
    """«Move content and close» payload.

    ``move_items_to`` is required when the location (or any of its
    descendants) still holds items; the archive then relocates them in the
    same operation.
    """

    move_items_to: UUID | None = None


class StorageReorgOperation(BaseModel):
    """Single operation in a storage reorganization batch.

    ``parent_id`` accepts an existing location UUID, a ``temporary_id``
    defined by an earlier ``create`` in the same batch, or ``None`` (root).
    """

    op: Literal['delete', 'create', 'move']
    id: UUID | None = None  # delete/move target
    temporary_id: str | None = None  # create key, referenced by later ops
    name: str | None = None  # create
    parent_id: str | None = None  # move/create target (UUID | temp key | None)
    # What a move of a location holding stock means. ``physical``: the
    # location and everything in it was carried there, and the move records
    # a relocation with a movement per product inside. ``correction`` (and
    # None, what every move meant before the choice existed): the tree was
    # wrong, the stock was always there, and only the journal hears of it.
    relocation: Literal['physical', 'correction'] | None = None


class StorageReorgRequest(BaseModel):
    operations: list[StorageReorgOperation] = []
    # Validate the batch and say what each move would carry, writing nothing:
    # what the confirmation shows before the person moving chooses.
    dry_run: bool = False


class StorageMoveScope(BaseModel):
    """What one move of a batch carries with it, read on the batch's final tree."""

    index: int
    id: UUID
    name: str
    #: Locations below the moved one, at any depth.
    locations_inside: int
    #: Distinct products holding stock in the moved location and below it.
    products: int
    #: The parent's full path, "Main Warehouse / Zone A"; None for the top level.
    from_path: str | None = None
    to_path: str | None = None
    #: The top-level location above it is another one after the move.
    warehouse_changes: bool


class StorageReorgRejection(BaseModel):
    """One rejected operation with its position in the batch and the reason."""

    index: int
    op: str
    temporary_id: str | None = None
    reason: str


class StorageReorgResponse(BaseModel):
    applied: bool
    created: dict[str, UUID] = {}
    rejections: list[StorageReorgRejection] = []
    #: Filled by a dry run: one entry per move operation.
    moves: list[StorageMoveScope] = []
