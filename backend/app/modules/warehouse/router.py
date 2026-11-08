from datetime import date, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import (
    APIRouter,
    Body,
    Depends,
    Header,
    Path,
    Query,
    status,
)
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts.dtos import UserContextDTO
from app.core.deps import (
    get_async_db,
    get_current_user_context,
    require_org,
    require_permission,
    require_read_write,
)
from app.core.exceptions import (
    AppException,
    ConflictException,
    NotFoundException,
    catalogue_refusal,
    catalogue_status_refusal,
    map_service_errors,
)
from app.core.logging import get_logger
from app.core.modules import require_module
from app.core.public_api import core_api
from app.core.utils import build_pdf_response, sanitize_filename
from app.i18n.service import get_current_lang, get_error_message

from . import services
from ._corrections_router import router as corrections_router
from ._document_workflow_transitions import WmsSessionActiveError
from ._documents_query_router import query_router
from ._import_router import router as import_router
from ._over_receipt import asking_the_holder
from ._profile_router import router as profile_router
from ._receipt_planning import attach_receipt_plans
from ._router_capacity import router as capacity_router
from ._router_home_shelf import router as home_shelf_router
from ._router_occupancy import router as occupancy_router
from ._router_putaway import router as putaway_router
from ._work_items_router import router as work_items_router
from .document_filters import (
    UnknownDocumentFilterError,
    resolve_document_filters_async,
)
from .document_query_service import document_list_row
from .document_todo_service import work_stage_updates_async
from .document_type_config_router import router as type_config_router
from .documents_periods_router import router as periods_router
from .documents_product_search_router import router as product_search_router
from .documents_templates_router import router as templates_router
from .extra_costs_router import router as extra_costs_router
from .models import DocumentStatus
from .packing_router import router as packing_router
from .pre_post_checks import DocumentHeldError, works_as_confirmed_async
from .schemas import (
    ApprovalDecisionSnapshot,
    ApprovalSnapshot,
    DocumentComplete,
    DocumentCreate,
    DocumentLineTargetUpdate,
    DocumentRowListResponse,
    DocumentSchema,
    DocumentTracking,
    DocumentUpdate,
)
from .shipment_router import router as shipment_router
from .tax_rate_router import router as tax_rate_router
from .wms_picking_router import router as wms_picking_router
from .wms_receiving_router import router as wms_receiving_router

logger = get_logger(__name__)

_PRINTABLE_STATUSES = frozenset({'CONFIRMED', 'COMPLETED'})

#: Every documents endpoint sits behind the module's own permissions.
#: Mounting the guard here rather than per endpoint means a new sub-router is
#: covered the day it is added — moving stock is never an unguarded side effect
#: of being an organization member. The HTTP method carries the read/write
#: distinction honestly across this module: its POSTs all write.
router = APIRouter(
    dependencies=[
        Depends(require_module('warehouse')),
        require_read_write('warehouse:read', 'warehouse:write'),
    ]
)
router.include_router(periods_router)
router.include_router(product_search_router)
router.include_router(query_router)
router.include_router(work_items_router)
router.include_router(templates_router, prefix='/templates')
router.include_router(type_config_router)
router.include_router(extra_costs_router, prefix='/documents')
router.include_router(packing_router, prefix='/documents')
router.include_router(shipment_router)
router.include_router(tax_rate_router)
router.include_router(wms_picking_router)
router.include_router(wms_receiving_router)
router.include_router(profile_router)
router.include_router(corrections_router)
router.include_router(import_router)
router.include_router(putaway_router)
router.include_router(capacity_router)
router.include_router(home_shelf_router)
router.include_router(occupancy_router)


@router.post(
    '/documents', response_model=DocumentSchema, status_code=status.HTTP_201_CREATED
)
@map_service_errors
async def create_document(
    data: DocumentCreate,
    idempotency_key: str | None = Header(None, min_length=8, max_length=64),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> Any:
    """Create a DRAFT document.

    ``Idempotency-Key`` names the save: the same key sent again (a retry
    after the answer was lost) is answered with the draft the first save
    wrote instead of a second draft.
    """
    return await services.create_document(
        db, org_id, data, current_user.id, post_key=idempotency_key
    )


@router.post(
    '/documents/post',
    response_model=DocumentSchema,
    status_code=status.HTTP_201_CREATED,
)
@map_service_errors
async def post_new_document(
    data: DocumentCreate,
    idempotency_key: str | None = Header(None, min_length=8, max_length=64),
    confirm_surplus: bool = Query(False),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> Any:
    """Create a document from scratch and post it, in one transaction.

    The one-screen actions (receipt, dispatch, move) send a whole document
    here instead of writing a draft and walking it through two more calls.
    Creation, confirmation and completion run the same service functions as
    the step-by-step doors, in one transaction, so a refusal writes nothing.

    ``Idempotency-Key`` names the press: the same key sent again (a double
    click, a retry after the answer was lost) is answered with the document
    the first press made instead of posting a second one.

    A surplus past the over-receipt tolerance is a question for a holder of
    the permission: answered 409 ``SURPLUS_NEEDS_CONFIRMATION``, naming the
    surplus and its line, until the same press comes back with
    ``confirm_surplus``.
    """
    may_exceed = current_user.has_permission('warehouse:receive_over_tolerance')
    try:
        with asking_the_holder(may_exceed):
            return await services.post_new_document(
                db,
                org_id,
                data,
                current_user.id,
                post_key=idempotency_key,
                may_exceed_over_receipt=may_exceed and confirm_surplus,
            )
    except WmsSessionActiveError as exc:
        raise ConflictException('WMS_SESSION_ACTIVE', str(exc)) from exc


@router.post(
    '/documents/{doc_id}/duplicate',
    response_model=DocumentSchema,
    status_code=status.HTTP_201_CREATED,
)
@map_service_errors
async def duplicate_document(
    doc_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> Any:
    """Create a new DRAFT document as a copy of ``doc_id``.

    Copies type, partner, locations, notes, external_reference, a scrap's
    reason, and all lines (expected_quantity, template, name/brand/barcode,
    uom, batch, serial, expiry, unit_price, tax_rate). The duplicate always
    starts in DRAFT with an identifier of its own — even if the source is
    COMPLETED or CANCELLED — and takes a number when it is confirmed. Done
    quantities are NOT copied.
    """
    return await services.duplicate_document(db, org_id, doc_id, current_user.id)


@router.get('/documents', response_model=DocumentRowListResponse)
async def list_documents(
    search: str | None = Query(None, min_length=1),
    type: str | None = Query(
        None,
        description=(
            'IN|OUT|INT|INTERNAL_IN|INTERNAL_OUT|CORRECTION|ADJUSTMENT|SCRAP. '
            'Legacy codes PZ/WZ/MM/PW/RW are accepted and normalized. '
            'Several types may be given comma-separated (IN,OUT).'
        ),
    ),
    doc_status: str | None = Query(
        None,
        alias='status',
        description=(
            'DRAFT|CONFIRMED|PENDING_APPROVAL|COMPLETED|CANCELLED, '
            'or several joined by commas'
        ),
    ),
    discrepancy_code: str | None = Query(
        None, description='SHORTAGE|DAMAGE|QUALITY_HOLD|COUNT_VARIANCE|OTHER'
    ),
    partner_id: UUID | None = Query(None),
    ids: list[UUID] | None = Query(
        None,
        description=(
            'Only these documents, organization-scoped. A trail of stock '
            'movements naming its sources asks for the page of rows it '
            'shows — one ask instead of a detail fetch per row. Capped at '
            '100 ids.'
        ),
    ),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    completed_from: datetime | None = Query(
        None,
        description=(
            "Only documents posted at or after this moment — the reader's "
            'own start of day, so the start screen follows their calendar '
            'rather than the server timezone.'
        ),
    ),
    completed_to: datetime | None = Query(
        None,
        description='Only documents posted at or before this moment.',
    ),
    location_id: UUID | None = Query(
        None,
        description=(
            'Only documents whose source or target is this place or stands '
            'under it — one warehouse of several.'
        ),
    ),
    module_filter: list[str] | None = Query(
        None,
        description=(
            'A filter a module adds to the list, named <module>:<name> as '
            'the module registered it (warehouse_api.register_document_filter). '
            'Several narrow together; one no enabled module answers is a 400.'
        ),
    ),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    sort_by: str = Query(
        'document_date',
        pattern='^(number|document_date|created_at|completed_at|type|status)$',
    ),
    sort_order: str = Query('desc', pattern='^(asc|desc)$'),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> DocumentRowListResponse:
    """The documents list: one summed row per document, its lines left out.

    The document's own screen (``GET /documents/{id}``) carries the lines.
    """
    # A warehouse is a place with shelves under it, and a document names the
    # place it went to or came from: "this warehouse" is the subtree, its own
    # name included, on either side of the document.
    location_ids = (
        [
            location_id,
            *await core_api.locations.descendant_ids_async(db, org_id, location_id),
        ]
        if location_id is not None
        else None
    )
    try:
        module_filters = await resolve_document_filters_async(
            db, org_id, module_filter or []
        )
    except UnknownDocumentFilterError as exc:
        raise catalogue_refusal(
            'document_filter_unknown', name=str(exc), field='module_filter'
        ) from exc
    documents, total = await services.list_documents(
        db,
        org_id,
        search=search,
        module_filters=module_filters,
        doc_type=type,
        status=doc_status,
        discrepancy_code=discrepancy_code,
        partner_id=partner_id,
        target_ids=ids[:100] if ids else ids,
        date_from=datetime(date_from.year, date_from.month, date_from.day)
        if date_from
        else None,
        date_to=datetime(date_to.year, date_to.month, date_to.day, 23, 59, 59)
        if date_to
        else None,
        completed_from=completed_from,
        completed_to=completed_to,
        location_ids=location_ids,
        limit=limit,
        offset=offset,
        sort_by=sort_by,
        sort_order=sort_order,
        lines='rows',
    )
    # The stage is derived, never stored — the same answer the To do queue
    # reads, so a document whose session somebody left open says so on the
    # list too. The register is where that walk is started again, and a row
    # that hides an open session reads as work nobody has begun.
    stage_updates = await work_stage_updates_async(db, org_id, documents)
    return DocumentRowListResponse.from_slice(
        items=[
            document_list_row(d).model_copy(update=stage_updates.get(d.id, {}))
            for d in documents
        ],
        offset=offset,
        limit=limit,
        total=total,
    )


@router.get('/documents/pdf', response_class=Response)
async def download_documents_pdf(
    ids: list[UUID] = Query(min_length=1, max_length=100),
    lang: str | None = Query(default=None, pattern='^[a-z]{2}(-[A-Z]{2})?$'),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> Response:
    """The chosen documents as one PDF, in the order of ``ids``.

    One request instead of one download per document. All or nothing: a
    document that is not confirmed or completed (or not the organization's)
    refuses the whole file, naming every one at fault, so a stack of paper is
    never silently shorter than the selection.
    """
    err_lang = get_current_lang()
    # A request that names no language prints in the reader's own, not in
    # English: the sheet goes to the person who asked for it.
    lang = lang or err_lang
    docs = []
    for doc_id in dict.fromkeys(ids):
        doc = await services.get_document(db, org_id, doc_id)
        if not doc:
            raise NotFoundException('document', err_lang)
        docs.append(doc)
    not_printable = [d.number for d in docs if d.status not in _PRINTABLE_STATUSES]
    if not_printable:
        raise catalogue_refusal(
            'documents_pdf_require_confirmed', numbers=', '.join(not_printable)
        )
    profile = await services.get_or_create_profile(db, org_id)
    try:
        from ._print_template_pick import pick_print_template_html
        from .document_pdf_service import generate_merged_pdf_async

        organization = await core_api.organizations.get_async(db, org_id)
        parts = [
            (d, await pick_print_template_html(db, org_id, profile, d.type))
            for d in docs
        ]
        pdf_bytes = await generate_merged_pdf_async(
            parts, profile, lang=lang, organization=organization
        )
    except Exception as exc:  # PDF generation tolerates formatting failures
        logger.exception('Merged PDF generation failed for %d documents', len(docs))
        raise AppException(
            500,
            'PDF_GENERATION_FAILED',
            get_error_message('pdf_generation_failed', err_lang),
        ) from exc
    return build_pdf_response(pdf_bytes, 'documents.pdf')


@router.get('/documents/lookup/{number:path}', response_model=DocumentSchema)
async def lookup_by_number(
    number: str,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> Any:
    lang = get_current_lang()
    doc = await services.get_document_by_number(db, org_id, number)
    if not doc:
        raise NotFoundException('document', lang)
    await attach_receipt_plans(db, doc)
    return doc


@router.get('/documents/{doc_id}', response_model=DocumentSchema)
async def get_document(
    doc_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> DocumentSchema:
    lang = get_current_lang()
    doc = await services.get_document(db, org_id, doc_id)
    if not doc:
        raise NotFoundException('document', lang)
    await attach_receipt_plans(db, doc)
    result = DocumentSchema.model_validate(doc)
    result.approval = await _approval_snapshot(db, org_id, doc_id)
    if doc.status == DocumentStatus.PENDING_APPROVAL.value:
        result = result.model_copy(
            update={'hold_stood_down': await works_as_confirmed_async(db, org_id, doc)}
        )
    # Old approvals overwrote the confirmer with the approver. Recover the
    # original act from the journal, not from the requester (a manual request
    # may have been raised by somebody else). This only enriches the response.
    approved = [
        decision
        for decision in (result.approval.decisions if result.approval else [])
        if decision.status == 'APPROVED' and decision.decided_at is not None
    ]
    last_decision = (
        max(approved, key=lambda decision: decision.decided_at or datetime.min)
        if approved
        else None
    )
    if (
        result.approval is not None
        and result.approval.status == 'APPROVED'
        and last_decision is not None
        and result.confirmed_at is not None
        and last_decision.decided_at is not None
        and result.confirmed_at >= last_decision.decided_at
    ):
        result = result.model_copy(
            update={'confirmed_by': None, 'confirmed_by_name': None}
        )
        after = None
        while True:
            entries, _ = await core_api.audit_log.list_for_org_async(
                db,
                org_id,
                target_type='document',
                target_id=doc_id,
                limit=100,
                after=after,
            )
            confirmation = next(
                (
                    entry
                    for entry in entries
                    if entry.action == 'UPDATE'
                    and entry.snapshot is not None
                    and 'requires_approval' in entry.snapshot
                    and entry.snapshot.get('new_status')
                    in ('CONFIRMED', 'PENDING_APPROVAL')
                ),
                None,
            )
            if confirmation is not None:
                user = (
                    await core_api.users.get_async(db, org_id, confirmation.user_id)
                    if confirmation.user_id is not None
                    else None
                )
                result = result.model_copy(
                    update={
                        'confirmed_at': confirmation.created_at,
                        'confirmed_by': confirmation.user_id,
                        'confirmed_by_name': (
                            user.full_name or user.email if user else None
                        ),
                    }
                )
                break
            if len(entries) < 100:
                break
            after = (entries[-1].created_at, entries[-1].id)
    return result


async def _approval_snapshot(
    db: AsyncSession, org_id: UUID, doc_id: UUID
) -> ApprovalSnapshot | None:
    """The newest request about the document as its card draws it.

    The enriched read is the one that carries each decision's approver name;
    without it the card could say the request was approved but not by whom,
    and the approver would have no place of their own beside the confirmer.

    Asked only while the approvals module is on for the organization, and
    imported only then: the warehouse loads and shows its documents without
    it, and a switched-off module has no trace to show.
    """
    if not await core_api.organizations.is_module_enabled_async(
        db, org_id, 'approvals'
    ):
        return None
    from app.modules.approvals.approvals_api import approvals_api

    requests = await approvals_api.list_requests(
        db, org_id, target_type='document', target_id=doc_id
    )
    if not requests:
        return None
    request_id = requests[0].id
    trace = await approvals_api.get_request_enriched(db, org_id, request_id)
    if trace is None:
        return None
    return ApprovalSnapshot(
        request_id=request_id,
        status=trace['status'],
        current_stage=trace['current_stage'],
        total_stages=trace['total_stages'],
        created_at=trace['created_at'],
        decisions=[
            ApprovalDecisionSnapshot(
                status=decision['status'],
                decided_at=decision['decided_at'],
                decided_by=decision['approver_id'],
                decided_by_name=decision['approver_name'],
            )
            for decision in trace['decisions']
        ],
    )


@router.put('/documents/{doc_id}', response_model=DocumentSchema)
@map_service_errors
async def update_document(
    doc_id: UUID,
    data: DocumentUpdate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> Any:
    return await services.update_document(db, org_id, doc_id, data, current_user.id)


@router.patch('/documents/{doc_id}/lines/{line_id}', response_model=DocumentSchema)
@map_service_errors
async def set_line_target(
    doc_id: UUID,
    line_id: UUID,
    data: DocumentLineTargetUpdate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> Any:
    """Name (or clear) the shelf one receipt line will land on.

    The response is the whole document, the line's plan already recomputed:
    the picker's change and the preview it refreshes are one round trip.
    """
    doc = await services.set_line_target_async(
        db, org_id, doc_id, line_id, data.target_location_id, current_user.id
    )
    await attach_receipt_plans(db, doc)
    return doc


#: A module's name, as its manifest spells it: the key its fields live under.
_ModuleKey = Annotated[str, Path(pattern=r'^[a-z][a-z0-9_]*$', max_length=64)]


@router.put('/documents/{doc_id}/meta-data/{module}', response_model=DocumentSchema)
@map_service_errors
async def set_document_meta_data(
    doc_id: UUID,
    module: _ModuleKey,
    values: Annotated[dict[str, Any], Body()],
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> Any:
    """Replace one module's own fields on the document; ``{}`` removes them.

    Other modules' fields stay as they are. Open until the document is
    completed or cancelled, so a field a pre-post check asks for can still be
    filled in on a confirmed document.
    """
    doc = await services.set_module_meta_data_async(
        db, org_id, doc_id, module, values, current_user.id
    )
    await attach_receipt_plans(db, doc)
    return doc


@router.put(
    '/documents/{doc_id}/lines/{line_id}/meta-data/{module}',
    response_model=DocumentSchema,
)
@map_service_errors
async def set_line_meta_data(
    doc_id: UUID,
    line_id: UUID,
    module: _ModuleKey,
    values: Annotated[dict[str, Any], Body()],
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> Any:
    """Replace one module's own fields on one line; ``{}`` removes them."""
    doc = await services.set_module_meta_data_async(
        db, org_id, doc_id, module, values, current_user.id, line_id=line_id
    )
    await attach_receipt_plans(db, doc)
    return doc


@router.patch('/documents/{doc_id}/confirm', response_model=DocumentSchema)
@map_service_errors
async def confirm_document(
    doc_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> Any:
    return await services.confirm_document(
        db,
        org_id,
        doc_id,
        current_user.id,
        may_exceed_over_receipt=current_user.has_permission(
            'warehouse:receive_over_tolerance'
        ),
    )


@router.post('/documents/{doc_id}/post', response_model=DocumentSchema)
@map_service_errors
async def post_document(
    doc_id: UUID,
    data: DocumentTracking | None = None,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> Any:
    """Confirm and complete a draft in one transaction.

    The whole movement the draft describes is posted as planned. Where the
    profile requires an approval the call parks the document in
    PENDING_APPROVAL instead, and the approval that releases it completes it.
    The body carries no quantities — only the lot and expiry a receipt's
    execution screen asked for.
    """
    try:
        return await services.post_document_now(
            db,
            org_id,
            doc_id,
            current_user.id,
            may_exceed_over_receipt=current_user.has_permission(
                'warehouse:receive_over_tolerance'
            ),
            tracking=data,
        )
    except WmsSessionActiveError as exc:
        raise ConflictException('WMS_SESSION_ACTIVE', str(exc)) from exc


@router.patch('/documents/{doc_id}/complete', response_model=DocumentSchema)
@map_service_errors
async def complete_document(
    doc_id: UUID,
    data: DocumentComplete | None = None,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> Any:
    try:
        return await services.complete_document(
            db,
            org_id,
            doc_id,
            current_user.id,
            data,
            may_exceed_over_receipt=current_user.has_permission(
                'warehouse:receive_over_tolerance'
            ),
        )
    except DocumentHeldError as exc:
        raise ConflictException('APPROVAL_REQUIRED', str(exc)) from exc
    except WmsSessionActiveError as exc:
        raise ConflictException('WMS_SESSION_ACTIVE', str(exc)) from exc


@router.patch('/documents/{doc_id}/cancel', response_model=DocumentSchema)
@map_service_errors
async def cancel_document(
    doc_id: UUID,
    _: None = require_permission('warehouse:manage'),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> Any:
    try:
        return await services.cancel_document(db, org_id, doc_id, current_user.id)
    except WmsSessionActiveError as exc:
        raise ConflictException('WMS_SESSION_ACTIVE', str(exc)) from exc


@router.get('/documents/{doc_id}/pdf', response_class=Response)
async def download_document_pdf(
    doc_id: UUID,
    lang: str | None = Query(default=None, pattern='^[a-z]{2}(-[A-Z]{2})?$'),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> Response:
    err_lang = get_current_lang()
    lang = lang or err_lang
    doc = await services.get_document(db, org_id, doc_id)
    if not doc:
        raise NotFoundException('document', err_lang)
    if doc.status not in _PRINTABLE_STATUSES:
        raise catalogue_refusal('document_pdf_requires_confirmed', status=doc.status)
    profile = await services.get_or_create_profile(db, org_id)
    try:
        from .document_pdf_service import generate_pdf_async

        # the issuer identity (name, tax ID, address, logo) comes from
        # the organization, not from the document profile — one copy for every
        # print family that needs it.
        organization = await core_api.organizations.get_async(db, org_id)
        # The printout answers to the document's type: the organization's
        # default template FOR THIS TYPE wins, the profile's one-layout
        # choice is the fallback for types without their own template, and
        # None renders the filesystem family as before.
        from ._print_template_pick import pick_print_template_html

        user_template_html = await pick_print_template_html(
            db, org_id, profile, doc.type
        )
        pdf_bytes = await generate_pdf_async(
            doc,
            profile,
            lang=lang,
            organization=organization,
            user_template_html=user_template_html,
        )
    except Exception as exc:  # PDF generation tolerates formatting failures
        logger.exception('PDF generation failed for document %s', doc_id)
        raise catalogue_status_refusal(
            'pdf_generation_failed', 500, lang=err_lang
        ) from exc
    return build_pdf_response(
        pdf_bytes, sanitize_filename(doc.number, prefix='document')
    )


@router.delete('/documents/{doc_id}', status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    doc_id: UUID,
    _: None = require_permission('warehouse:manage'),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> None:
    await services.delete_document(db, org_id, doc_id, current_user.id)
