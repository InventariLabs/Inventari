from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.core.contracts import UomInfoDTO
from app.core.module_sdk import PaginatedResponse

from ._schemas_import import (  # noqa: F401
    DocumentImportAnalyzeResponse,
    DocumentImportErrorResponse,
    DocumentImportLineResponse,
    DocumentImportLinesResponse,
    ImportPreviewRow,
    ImportPreviewValue,
    OpeningStockImportResponse,
    PartnerContext,
    ProductSearchResult,
    QuickCreateStub,
)
from ._schemas_profile import (  # noqa: F401
    DocumentProfileSchema,
    DocumentProfileUpdate,
    PickOrderStrategySchema,
)
from ._schemas_register import (  # noqa: F401
    DocumentTypeConfigCreate,
    DocumentTypeConfigOut,
    DocumentTypeConfigUpdate,
    InventoryPeriodCreate,
    InventoryPeriodSchema,
    RegisterCurrencyTotal,
    RegisterDocumentRow,
    RegisterGroup,
    RegisterResponse,
    RegisterSummary,
)

# Re-export extracted schemas for backward compatibility.
from ._schemas_work_items import WorkItemsSection
from .models import (
    FREE_TEXT_REASON_CODE,
    CorrectionReasonCode,
    DocumentDiscrepancyCode,
    DocumentLineStatus,
    DocumentStatus,
    DocumentType,
    ExtraCostAllocation,
    ExtraCostKind,
    ReturnReasonCode,
    ScrapReasonCode,
)
from .shipment_schemas import DocumentShipmentSchema, ShipmentCreate


class PartnerSnapshot(BaseModel):
    name: str | None = None
    code: str | None = None
    tax_id: str | None = None
    address: str | dict[str, str | None] | None = None
    email: str | None = None
    phone: str | None = None


class ApprovalDecisionSnapshot(BaseModel):
    """One stage's verdict, as the timeline draws it.

    ``decided_at`` is the fact the approval rung shows, and
    ``decided_by``/``decided_by_name`` name the approver of that stage.
    The document's own ``confirmed_at``/``confirmed_by`` are the
    confirmation's — the approval is a moment of its own and does not
    overwrite it.
    """

    status: str
    decided_at: datetime | None = None
    decided_by: UUID | None = None
    decided_by_name: str | None = None


class ApprovalSnapshot(BaseModel):
    request_id: UUID | None = None
    status: str | None = None
    current_stage: int | None = None
    total_stages: int | None = None
    # When the request was raised, and what each stage decided and when —
    # the trace the status ladder is drawn from. A ladder built from the
    # current status alone forgets the approval the moment it is decided.
    created_at: datetime | None = None
    decisions: list[ApprovalDecisionSnapshot] = []


#: Other modules' own fields on a document or a line: one key per module,
#: named as the module is (the manifest's name pattern), holding that module's
#: object. A flat value at the top level is refused — it would belong to no
#: one, and the next module to write would overwrite it.
ModuleMetaData = dict[
    Annotated[str, StringConstraints(pattern=r'^[a-z][a-z0-9_]*$', max_length=64)],
    dict[str, Any],
]


class DocumentLineCreate(BaseModel):
    item_id: UUID | None = None
    product_template_id: UUID | None = None
    name: str | None = Field(default=None, max_length=255)
    brand: str | None = Field(default=None, max_length=255)
    barcode: str | None = Field(default=None, max_length=50)
    sku: str | None = Field(default=None, max_length=50)
    expected_quantity: Decimal = Field(gt=0)
    uom_id: UUID | None = None
    batch_number: str | None = Field(default=None, max_length=100)
    serial_number: str | None = Field(default=None, max_length=100)
    expiry_date: date | None = None
    notes: str | None = None
    unit_price: Decimal | None = Field(default=None, max_digits=12, decimal_places=2)
    tax_rate: Decimal | None = Field(default=None, max_digits=5, decimal_places=2)
    source_po_line_id: UUID | None = None
    # The shelf the worker named on this line. Kept on the create schema so
    # a DRAFT edit that replaces all lines does not silently drop it.
    target_location_id: UUID | None = None
    # The same holds for other modules' fields on the line.
    meta_data: ModuleMetaData | None = None
    #: The expected quantity is a count somebody typed to get a row — the
    #: receive sheet's — not a figure from an order or a delivery note, so
    #: receiving more than it says is not a surplus. Kept on the line.
    expected_is_count: bool | None = None
    # What a receipt posted in one press says about the goods that arrived:
    # how much of ``expected_quantity`` (the count that arrived) is held back
    # and why. Only ``POST /documents/post`` answers them, with the same
    # three rules a completion applies; a draft does not keep them.
    held_quantity: Decimal | None = Field(default=None, ge=0)
    discrepancy_code: DocumentDiscrepancyCode | None = None
    discrepancy_reason: str | None = Field(default=None, max_length=500)

    @field_validator('name', 'brand', 'batch_number', 'serial_number')
    @classmethod
    def reject_null_bytes(cls, v: str | None) -> str | None:
        if v is not None and '\x00' in v:
            raise ValueError('must not contain null bytes')
        return v

    @model_validator(mode='after')
    def validate_item_or_template(self) -> Self:
        if not self.item_id and not self.product_template_id and not self.name:
            raise ValueError('Provide item_id, product_template_id, or at least a name')
        return self


class DocumentCreate(BaseModel):
    type: str = Field(max_length=20)
    partner_id: UUID | None = None
    source_location_id: UUID | None = None
    target_location_id: UUID | None = None
    scheduled_date: date | None = None
    lines: list[DocumentLineCreate] = Field(min_length=1)
    notes: str | None = Field(default=None, max_length=2000)
    external_reference: str | None = Field(default=None, max_length=100)
    meta_data: ModuleMetaData | None = None
    #: Why the goods are written off — a scrap only; the service refuses any
    #: other type rather than quietly storing a reason nothing reads.
    reason_code: ScrapReasonCode | None = None

    @field_validator('notes')
    @classmethod
    def reject_null_bytes_notes(cls, v: str | None) -> str | None:
        if v is not None and '\x00' in v:
            raise ValueError('notes must not contain null bytes')
        return v

    @field_validator('type')
    @classmethod
    def validate_type(cls, v: str) -> str:
        from . import document_types as dt

        normalized = dt.normalize(v)
        if normalized not in dt.ALL_TYPES:
            raise ValueError(
                f'Invalid type. Allowed: {", ".join(sorted(dt.ALL_TYPES))}'
            )
        return normalized

    @model_validator(mode='after')
    def validate_business_rules(self) -> Self:
        from . import document_types as dt

        # NOTE: the partner requirement for IN/OUT lives in the service layer
        # (_document_workflow_crud.create_document) because it depends on the
        # organization module configuration (partners on/off) — a schema
        # validator cannot know that.
        #
        # The source/target requirements live there too, for the same reason:
        # an organization can name a default location per document type, and
        # a validator that runs before those defaults are applied would reject
        # the very requests the setting exists to simplify.
        # ``validate_locations_async`` enforces them once the defaults are in.
        #
        # CORRECTION must be created via POST /warehouse/corrections, not DocumentCreate
        if dt.is_correction(self.type):
            raise ValueError(
                'Use POST /warehouse/corrections to create correction documents'
            )
        return self


class DocumentLineTargetUpdate(BaseModel):
    """One receipt line's own destination. ``None`` clears the line's say —
    the line goes back to following the rule and the document."""

    target_location_id: UUID | None = None


class DocumentUpdate(BaseModel):
    partner_id: UUID | None = None
    source_location_id: UUID | None = None
    target_location_id: UUID | None = None
    scheduled_date: date | None = None
    notes: str | None = Field(default=None, max_length=2000)
    external_reference: str | None = Field(default=None, max_length=100)
    #: Replaces every module's fields on the header, as ``lines`` replaces the
    #: lines; one module's own write goes through ``PUT …/meta-data/{module}``.
    meta_data: ModuleMetaData | None = None
    lines: list[DocumentLineCreate] | None = None
    #: A scrap draft's reason; refused on any other type.
    reason_code: ScrapReasonCode | None = None


class DocumentLineExecution(BaseModel):
    line_id: UUID
    # Corrections carry a signed delta, so the bound belongs with the line it
    # applies to, not here: a bare ``ge=0`` left a client completing a -3
    # correction no way to say it except ``3``, which the executor then added
    # to stock. ``_apply_execution_quantities`` rejects a negative on
    # every other document type and a sign that contradicts the line.
    done_quantity: Decimal
    #: How much of ``done_quantity`` is received but held back. Only a
    #: receipt may hold goods, only with a code that says why, and never
    #: more than it received; ``_apply_execution_quantities`` owns those
    #: three refusals. Omitted means zero, so every caller that never held
    #: anything keeps its payload unchanged.
    held_quantity: Decimal | None = None
    discrepancy_code: DocumentDiscrepancyCode | None = None
    discrepancy_reason: str | None = Field(default=None, max_length=500)
    #: The lot and expiry read off the pack for a product taken by earliest
    #: expiry. The lot may stay empty; the date may not — without it the
    #: received record sorts behind every dated one. They land on the
    #: document line exactly as a receiving scan's do, and only when the
    #: line carries no date of its own yet.
    batch_number: str | None = Field(default=None, max_length=100)
    expiry_date: date | None = None


class DocumentComplete(BaseModel):
    # Empty when only the confirmation or the shipment below travels (a
    # correction has no per-line quantities): the lines are then read as with
    # no body — what a session wrote stands.
    lines: list[DocumentLineExecution] = Field(default_factory=list)
    # The operator's answer to a record whose unit differs from the card its
    # door adopts: confirm the difference and the record is restated into the
    # card's unit on the way in. It speaks for every line, the way the dialog
    # that produced it does.
    unit_confirmed_over_template: bool = False
    # A line the completion leaves unanswered is refused rather than booked
    # as delivered in full, whether the body names no lines or only some;
    # this is the caller saying that is exactly what it means.
    complete_as_planned: bool = Field(
        default=False,
        description=(
            'Complete without per-line answers: every line the body leaves '
            'unanswered is booked as delivered in full. Without this flag, a '
            'completion that leaves any line of a document other than a '
            'correction with no quantity and no discrepancy reason is refused, '
            'and the answer names those lines. A correction never needs it.'
        ),
    )

    # A dispatch's hand-over to a carrier, recorded in the same transaction
    # as its stock. Refused on any other document type.
    shipment: ShipmentCreate | None = None


class DocumentLineTracking(BaseModel):
    """The lot and expiry read off a pack for one receipt line.

    A one-step posting books every line as planned, so it has no per-line
    quantities to answer with — only the tracking the execution screen's
    lot-and-expiry question collected. The values land on the line exactly
    as a receiving scan's do.
    """

    line_id: UUID
    batch_number: str | None = Field(default=None, max_length=100)
    expiry_date: date | None = None


class DocumentTracking(BaseModel):
    #: The lines whose pack carried a lot or an expiry. A line left out keeps
    #: whatever the document already says.
    lines: list[DocumentLineTracking] = Field(default_factory=list)


class DocumentLineSchema(BaseModel):
    id: UUID
    document_id: UUID
    item_id: UUID | None
    product_template_id: UUID | None
    name: str | None
    brand: str | None
    barcode: str | None
    sku: str | None = None
    quantity: Decimal
    expected_quantity: Decimal
    done_quantity: Decimal
    #: The part of ``done_quantity`` that is booked but held back — see
    #: ``DocumentLine.held_quantity``.
    held_quantity: Decimal
    uom_id: UUID | None
    uom: UomInfoDTO | None
    batch_number: str | None
    serial_number: str | None
    expiry_date: date | None
    notes: str | None
    line_status: DocumentLineStatus
    discrepancy_code: DocumentDiscrepancyCode | None
    discrepancy_reason: str | None
    line_number: int
    source_po_line_id: UUID | None = None
    # Where this line's goods actually landed. A putaway rule can send a
    # delivery somewhere other than the document's target location, and the
    # document used to say nothing about it.
    executed_location_id: UUID | None = None
    executed_location_name: str | None = None
    # Where the goods WILL land, computed at read time by the same planner
    # the executor uses — set only while the line still waits for execution.
    # ``planned_source`` says who decided (serial / rule / document / record);
    # for a rule, which one matched and by what key.
    planned_location_id: UUID | None = None
    planned_location_name: str | None = None
    planned_source: str | None = None
    planned_rule_id: UUID | None = None
    planned_rule_match_key: str | None = None
    planned_rule_match_name: str | None = None
    # The line's own destination, when the worker named one; the planner
    # reads it before the rule.
    target_location_id: UUID | None = None
    # The shelf the line takes from when the document's source is a zone,
    # pinned at confirmation (``DocumentLine.source_location_id``).
    source_location_id: UUID | None = None
    source_location_name: str | None = None
    # Set when a matching rule had to step aside — its target is archived
    # or virtual — so the plan can say why the rule did not win.
    planned_rule_warning: str | None = None
    # Set when the rule's shelves are all too full: the plan names the
    # first shelf anyway, with the numbers that say by how much it is over.
    planned_over_capacity: bool | None = None
    planned_capacity_used: Decimal | None = None
    planned_capacity_max: Decimal | None = None
    # The shelf's whole fill in percent — the sum of every limited product's
    # share — set only when other products share the shelf, so a full shelf
    # is explained even where this product's own pair looks roomy.
    planned_shelf_fill: int | None = None
    unit_price: Decimal | None
    tax_rate: Decimal | None
    line_value: Decimal | None
    line_tax: Decimal | None
    line_gross: Decimal | None
    currency: str | None
    #: Other modules' fields on the line, under each module's name.
    meta_data: dict[str, dict[str, Any]] | None = None

    model_config = ConfigDict(from_attributes=True)


class DocumentSchema(BaseModel):
    id: UUID
    organization_id: UUID
    type: DocumentType
    number: str
    status: DocumentStatus
    partner_id: UUID | None
    partner_snapshot: PartnerSnapshot | None
    corrects_document_id: UUID | None
    # The type of the document this one corrects, read from the stored
    # ``corrects_document_id`` relation. A correction's lines are signed
    # deltas on the original, and only the original's type says which way a
    # delta moves stock — a negative correction of a dispatch-like original
    # (a scrap, say) puts goods back on the shelf. Transient — populated by
    # the query service on read, not stored on the model.
    corrects_document_type: str | None = None
    reason_code: str | None = None
    backorder_id: UUID | None = None
    # The number of the document this backorder continues, read from the
    # stored ``backorder_id`` relation. Transient — populated by the To do
    # queue so a draft names its origin without a second request.
    backorder_of_number: str | None = None
    # Reverse pointer: set when this document spawned a backorder on complete
    # . Transient — populated by the query/transition services,
    # not stored on the model.
    generated_backorder_id: UUID | None = None
    generated_backorder_number: str | None = None
    # Pointer to the document a return reverses, read from the stored
    # ``returns`` relation so readers name the original in their own
    # language. Transient — populated by the query service and by the
    # return service on creation, not stored on the model.
    return_of_id: UUID | None = None
    return_of_number: str | None = None
    # The completed correction that undid this document in one press, read
    # from the stored ``reverses`` relation. Transient — populated by the
    # query service on read, never stored on the model.
    reversed_by_id: UUID | None = None
    reversed_by_number: str | None = None
    source_location_id: UUID | None
    target_location_id: UUID | None
    source_location_name: str | None = None
    target_location_name: str | None = None
    scheduled_date: date | None
    notes: str | None
    external_reference: str | None
    #: Other modules' fields on the document, under each module's name.
    meta_data: dict[str, dict[str, Any]] | None = None
    is_opening: bool = False
    lines: list[DocumentLineSchema]
    created_by: UUID
    confirmed_by: UUID | None
    confirmed_by_name: str | None = None
    completed_by: UUID | None = None
    completed_by_name: str | None = None
    cancelled_by: UUID | None = None
    cancelled_by_name: str | None = None
    created_by_name: str | None = None
    created_at: datetime
    updated_at: datetime
    confirmed_at: datetime | None
    completed_at: datetime | None
    cancelled_at: datetime | None = None
    total_net: Decimal | None
    total_tax: Decimal | None
    total_gross: Decimal | None
    currency: str | None
    approval: ApprovalSnapshot | None = None
    # The dispatch's hand-over, with its tracking link. Transient — populated
    # by the query service and by completion, from ``document_shipments``.
    shipment: DocumentShipmentSchema | None = None
    # The work stage the To do queue derives from sessions, picked quantities
    # and packages — never a stored document status. Transient: populated by
    # ``document_todo_service`` for the queue's rows only, ``None`` elsewhere.
    work_stage: (
        Literal['to_start', 'in_progress', 'picked', 'packed', 'ready'] | None
    ) = None
    #: The one action that moves the work on from that stage.
    next_action: (
        Literal['receive', 'pick', 'resume', 'pack', 'complete', 'request_approval']
        | None
    ) = None
    #: Who holds the open session, while the stage is ``in_progress``.
    stage_holder_name: str | None = None

    model_config = ConfigDict(from_attributes=True)


class DocumentListResponse(PaginatedResponse[DocumentSchema]):
    """Paginated document list — the canonical envelope.

    Both endpoints already accepted ``limit``/``offset`` query params, so
    ``limit``, ``offset`` and ``has_more`` report real values rather than
    invented ones.
    """


class DocumentListUnitSchema(BaseModel):
    """The unit a list line's quantity is printed in: its symbol and step."""

    symbol: str
    rounding: Decimal

    model_config = ConfigDict(from_attributes=True)


class DocumentListLineSchema(BaseModel):
    """One of a list row's first lines: enough to say what moved."""

    name: str | None
    quantity: Decimal
    done_quantity: Decimal
    uom: DocumentListUnitSchema | None

    model_config = ConfigDict(from_attributes=True)


class DocumentUnitProgressSchema(BaseModel):
    """What a document's lines in one unit planned and did, summed.

    Kept per unit: 20 pcs and 12.5 kg are not 32.5 of anything.
    """

    unit: str | None
    planned: Decimal
    done: Decimal


class DocumentModuleLineSchema(BaseModel):
    """A line that carries a module's fields, as a module's list column reads it."""

    id: UUID
    batch_number: str | None
    meta_data: dict[str, dict[str, Any]] | None = None

    model_config = ConfigDict(from_attributes=True)


class DocumentListRowSchema(BaseModel):
    """A document as the documents list shows it, without its lines.

    The list prints a sentence, a count and a progress bar per document; the
    lines themselves are the document's own screen. Carried whole, they made
    a page of fifty documents a megabyte. What the row needs from them is
    summed here: ``line_count``, ``unit_progress`` and the first two lines
    (``first_lines``), which name the product of a one-line document.
    ``module_lines`` are the lines a module's column can read — those that
    carry fields of a module — and no others.
    """

    id: UUID
    type: str
    number: str
    status: str
    partner_id: UUID | None
    partner_snapshot: PartnerSnapshot | None
    source_location_id: UUID | None
    target_location_id: UUID | None
    source_location_name: str | None = None
    target_location_name: str | None = None
    #: The document this draft continues, when a short completion raised it.
    backorder_id: UUID | None = None
    scheduled_date: date | None
    notes: str | None
    external_reference: str | None
    meta_data: dict[str, dict[str, Any]] | None = None
    is_opening: bool = False
    created_by_name: str | None = None
    confirmed_by_name: str | None = None
    completed_by_name: str | None = None
    created_at: datetime
    completed_at: datetime | None
    total_net: Decimal | None
    total_gross: Decimal | None
    currency: str | None
    work_stage: (
        Literal['to_start', 'in_progress', 'picked', 'packed', 'ready'] | None
    ) = None
    next_action: (
        Literal['receive', 'pick', 'resume', 'pack', 'complete', 'request_approval']
        | None
    ) = None
    stage_holder_name: str | None = None
    #: The dispatch's hand-over and its tracking link, where one was recorded.
    shipment: DocumentShipmentSchema | None = None
    line_count: int
    unit_progress: list[DocumentUnitProgressSchema]
    first_lines: list[DocumentListLineSchema]
    module_lines: list[DocumentModuleLineSchema]


class DocumentRowListResponse(PaginatedResponse[DocumentListRowSchema]):
    """A page of the documents list, one summed row per document."""


class DocumentsTodoSection(BaseModel):
    """One side of the floor's queue: its rows and the server's own count.

    The count describes every matching document, not the rows that fit in the
    page — the two must agree when the queue is longer than one screen.

    Not a pagination envelope on purpose (``docs/subsystems/PAGINATION.md``,
    *Sections of a dashboard*): a section is one capped slice of a screen
    that holds several of them, answered by one request. It has no page to
    ask for, so ``limit``/``offset``/``has_more`` would promise a walk that
    does not exist; the screen reads more than the cap from the document list.
    """

    items: list[DocumentSchema]
    total: int


class QuarantineHoldSchema(BaseModel):
    """Goods waiting for somebody to release them or write them off.

    A named batch names itself. Goods held without one are named by the
    receipt that placed them on the quarantine shelf and by the product the
    decision is about, so the reader recognizes the row and reaches the
    receipt or the shelf that holds it. The quantity is what is still held,
    not what the receipt once set aside.
    """

    lot_id: UUID | None = None
    document_id: UUID | None = None
    document_number: str | None = None
    product_template_id: UUID | None = None
    #: The stock record the held goods stand in, so the release form opens
    #: with the goods already named.
    item_id: UUID | None = None
    name: str
    product_name: str | None = None
    quantity: Decimal
    uom_symbol: str | None = None
    reason: str | None = None
    location_id: UUID | None = None
    location_name: str | None = None


class QuarantineTodoSection(BaseModel):
    """The quarantine holds in To do, with the server's own count.

    A capped dashboard section, not a pageable list; see ``DocumentsTodoSection``.
    """

    items: list[QuarantineHoldSchema]
    total: int


class DocumentsTodoDecisions(BaseModel):
    """What waits on a person's answer rather than on the floor's work.

    Three kinds, each opening the screen where its decision is taken: a
    backorder draft is confirmed or cancelled on its document, a document
    waiting for approval is approved or rejected there, and goods in
    quarantine are released or written off — a batch on its own screen, a
    receipt's held quantity with the transfer or scrap off the quarantine
    shelf. Reading this block decides nothing.
    """

    backorders: DocumentsTodoSection
    approvals: DocumentsTodoSection
    quarantine: QuarantineTodoSection


class DocumentsTodoResponse(BaseModel):
    """To do's tasks, the two document lists they are partly built from, and
    the decisions waiting on a person."""

    inbound: DocumentsTodoSection
    outbound: DocumentsTodoSection
    decisions: DocumentsTodoDecisions
    work_items: WorkItemsSection


class PriceHintResponse(BaseModel):
    """suggested unit price for a product on a document.

    ``source`` is ``pricelist`` (partner offer), ``last_purchase``
    (most recent priced receipt) or ``None`` when no price is known.
    """

    unit_price: Decimal | None = None
    tax_rate: Decimal | None = None
    currency: str | None = None
    source: Literal['pricelist', 'last_purchase'] | None = None


# ─── Correction schemas ────────────────────────────────────────────────────────


class CorrectionLineCreate(BaseModel):
    """Delta for a single line in a correction document."""

    original_line_number: int = Field(
        ge=1, description='line_number of the original doc line'
    )
    quantity_delta: Decimal = Field(
        description='Signed delta: positive = add more stock, negative = reverse/remove'
    )
    notes: str | None = Field(
        default=None, max_length=500, description='Reason for this line correction'
    )

    model_config = ConfigDict(from_attributes=True)


class CorrectionCreate(BaseModel):
    """Request body for POST /warehouse/corrections."""

    corrects_document_id: UUID
    lines: list[CorrectionLineCreate] = Field(min_length=1)
    reason_code: CorrectionReasonCode
    notes: str | None = Field(
        default=None,
        max_length=2000,
        description='What the code does not say (required when the code is OTHER)',
    )

    @model_validator(mode='after')
    def other_needs_a_note(self) -> 'CorrectionCreate':
        """A correction rewrites recorded history, so it says why.

        The code carries that for every named reason; OTHER carries nothing,
        so there the note is the reason and cannot be blank.
        """
        if self.reason_code == FREE_TEXT_REASON_CODE and not (self.notes or '').strip():
            raise ValueError('Correction reason is required')
        return self


class ReturnLineCreate(BaseModel):
    """A single line in a return request."""

    original_line_number: int = Field(ge=1)
    return_quantity: Decimal = Field(gt=0)
    reason: str | None = Field(default=None, max_length=500)


class ReturnCreate(BaseModel):
    """Request body for POST /warehouse/documents/{id}/return."""

    lines: list[ReturnLineCreate] = Field(min_length=1)
    reason_code: ReturnReasonCode
    notes: str | None = Field(
        default=None,
        max_length=2000,
        description='What the code does not say (required when the code is OTHER)',
    )

    @model_validator(mode='after')
    def other_needs_a_note(self) -> 'ReturnCreate':
        if self.reason_code == FREE_TEXT_REASON_CODE and not (self.notes or '').strip():
            raise ValueError('Return reason is required')
        return self


class DocumentSummary(BaseModel):
    """Minimal document summary used in correction references."""

    id: UUID
    number: str
    type: str
    status: str
    created_at: datetime
    #: Why the correction was raised — the picker that demanded it owes the
    #: reader the answer on every screen that names the correction.
    reason_code: str | None = None

    model_config = ConfigDict(from_attributes=True)


class DocumentTargetSummaryDTO(BaseModel):
    """Lightweight document summary for cross-module consumers (e.g., approvals).

    Surfaces the fields an approver needs to identify and bound the value of
    the document they're reviewing, without loading the full document or its
    lines. Fetched in a single batched IN-query with a COUNT subquery — see
    ``WarehouseAPI.get_target_summaries_by_ids_async``.

    ``source_location_name`` and
    ``target_location_name`` are surfaced so the approvals card can show
    a meaningful fallback for documents that have no partner (typically
    INT — internal transfers between storage locations).
    """

    id: UUID
    number: str
    type: str
    partner_name: str | None = None
    total_value: Decimal | None = None
    currency: str | None = None
    lines_count: int = 0
    source_location_name: str | None = None
    target_location_name: str | None = None
    #: True when the document was submitted through the one-step action, whose
    #: approval posts the stock instead of leaving the document confirmed for
    #: a later execution. The approvals screen says which of the two this
    #: approval does; without it the reader was promised a second step that
    #: never comes.
    posts_on_approval: bool = False

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Delivery costs (freight, duty, insurance) on a receipt.
# ---------------------------------------------------------------------------
class ExtraCostCreate(BaseModel):
    kind: ExtraCostKind = ExtraCostKind.FREIGHT
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    currency: str | None = Field(default=None, max_length=3)
    allocation_method: ExtraCostAllocation = ExtraCostAllocation.VALUE
    note: str | None = Field(default=None, max_length=255)


class ExtraCostOut(BaseModel):
    id: UUID
    document_id: UUID
    kind: str
    amount: Decimal
    currency: str | None = None
    allocation_method: str
    note: str | None = None


class ExtraCostLinePreview(BaseModel):
    """What one line will cost once the delivery's own costs are on it."""

    line_id: UUID
    product_name: str | None = None
    quantity: Decimal
    unit_price: Decimal | None = None
    surcharge: Decimal = Decimal('0')
    unit_cost_after: Decimal | None = None


class ExtraCostsView(BaseModel):
    costs: list[ExtraCostOut] = []
    total: Decimal = Decimal('0')
    currency: str | None = None
    #: True while the costs can still be added or removed.
    editable: bool = True
    #: Methods that could not be used and fell back to quantity — value
    #: allocation needs values, and weight allocation needs weights.
    fell_back: list[str] = []
    lines: list[ExtraCostLinePreview] = []
