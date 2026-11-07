from datetime import date, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts.dtos import UserContextDTO
from app.core.deps import get_async_db, get_current_user_context, require_org
from app.core.module_sdk import PaginatedResponse
from app.core.public_api import core_api

from ._order_side import order_side_async
from ._schemas_work_items import WorkItemState, WorkItemView
from .document_profile_service import get_profile, resolve_document_tax_rate
from .document_query_service import document_row, get_last_purchase_price_async
from .document_register_service import (
    DEFAULT_ROWS_LIMIT,
    get_register_csv,
    get_register_rows_async,
    get_register_summary_async,
)
from .document_todo_service import (
    awaiting_approval_documents_async,
    backorder_drafts_async,
    quarantine_holds_async,
    todo_documents_async,
)
from .schemas import (
    DocumentListResponse,
    DocumentsTodoDecisions,
    DocumentsTodoResponse,
    DocumentsTodoSection,
    PriceHintResponse,
    QuarantineTodoSection,
    RegisterDocumentRow,
    RegisterResponse,
)
from .tax_rate_assignment_service import product_tax_rates_async
from .work_item_service import UNASSIGNED, assemble_work_items_async

# Read-only query endpoints split out of ``router.py`` to keep that file
# under the 400-LOC lint limit. The ``require_module('warehouse')``
# dependency is inherited from the parent ``router`` that includes this
# sub-router (see ``router.include_router(query_router)``).
query_router = APIRouter()

#: The most tasks one request lists.
_MAX_WORK_LIMIT = 1000
#: How deep a filtered view looks into each source: all of it. A filter or a
#: count made over a source's first rows would drop a column, a person or an
#: overdue card that happens to lie past them, with no sign that it did.
_EVERY_ROW = 2**31 - 1


@query_router.get('/todo', response_model=DocumentsTodoResponse)
async def get_documents_todo(
    date_to: date = Query(
        ...,
        description=(
            'The last day a document may be planned for and still be in the '
            "queue — the reader's own today, so the queue follows their "
            'calendar rather than the server timezone.'
        ),
    ),
    limit: int = Query(50, ge=1, le=200),
    inbound_offset: int = Query(
        0,
        ge=0,
        description='Rows of the inbound list already read, so its own next page starts here.',
    ),
    outbound_offset: int = Query(
        0,
        ge=0,
        description='Rows of the outbound list already read, so its own next page starts here.',
    ),
    work_limit: int | None = Query(
        None,
        ge=1,
        le=_MAX_WORK_LIMIT,
        description=(
            'Tasks to list when that is more than `limit`; the sections of '
            'the queue keep `limit`.'
        ),
    ),
    view: WorkItemView = Query(
        'all',
        description=(
            "Narrow the tasks to the reader's own (`mine`) or the overdue "
            'ones before they are cut to the page.'
        ),
    ),
    state: WorkItemState | None = Query(
        None,
        description='Narrow the tasks to one board column before they are cut to the page.',
    ),
    assignee: str | None = Query(
        None,
        pattern=f'^({UNASSIGNED}|[0-9a-fA-F-]{{36}})$',
        description=(
            "Narrow the tasks to one person's (a user id) or to those for "
            f'nobody (`{UNASSIGNED}`) before they are cut to the page.'
        ),
    ),
    location_id: UUID | None = Query(
        None,
        description=(
            'Keep the documents and put-away tasks of one warehouse (and the '
            'shelves under it). Tasks that name no place, such as orders, '
            'counts and custom tasks, are listed either way.'
        ),
    ),
    include_done: bool = Query(
        False,
        description='Also list what was done in the last day, after the open tasks.',
    ),
    done_since: datetime | None = Query(
        None,
        description=(
            'Also list what was done since this instant, after the open tasks '
            '(so a reader can ask for their own calendar day); never further '
            'back than the last day.'
        ),
    ),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> DocumentsTodoResponse:
    """The floor's queue: inbound and outbound work, and what needs a decision.

    Each side is one list with the work stage and next action derived from the
    document's own sessions, picked quantities and packages, and the server's
    total for that side. Each side pages on its own offset. The document
    status stays what it is; the stage is how far the work has actually gone.

    ``decisions`` names the backorder drafts, the documents this person can
    approve and the goods held in quarantine, each opening where the decision
    is taken. Reading the queue confirms nothing.

    ``work_items`` is the same work as one list of tasks, joined by what the
    documents do not hold: deliveries ordered but not yet received, planned
    production and counts that have fallen due, and the tasks added by hand.
    Each carries its assignee and the one action that moves it on.
    """
    page = work_limit or limit
    location_ids = (
        [
            location_id,
            *await core_api.locations.descendant_ids_async(db, org_id, location_id),
        ]
        if location_id is not None
        else None
    )
    # A filter has to look through the sources, not only their first page.
    narrowed = view != 'all' or state is not None or assignee is not None
    reach = _EVERY_ROW if narrowed else page
    approvals_enabled = await core_api.organizations.is_module_enabled_async(
        db, org_id, 'approvals'
    )
    (
        inbound,
        inbound_total,
        outbound,
        outbound_total,
        stage_updates,
    ) = await todo_documents_async(
        db,
        org_id,
        date_to=date_to,
        limit=max(limit, reach),
        inbound_offset=inbound_offset,
        outbound_offset=outbound_offset,
        approvals_enabled=approvals_enabled,
        location_ids=location_ids,
    )
    backorders, backorders_total = await backorder_drafts_async(
        db, org_id, limit=max(limit, reach), location_ids=location_ids
    )
    approvals, approvals_total = await awaiting_approval_documents_async(
        db,
        org_id,
        current_user,
        limit=max(limit, reach),
        location_ids=location_ids,
    )
    quarantine, quarantine_total = await quarantine_holds_async(db, org_id, limit=limit)
    work_items = await assemble_work_items_async(
        db,
        org_id,
        current_user,
        date_to=date_to,
        limit=page,
        reach=reach,
        include_done=include_done,
        done_since=done_since,
        view=view,
        state=state,
        assignee=assignee,
        inbound=inbound,
        outbound=outbound,
        stage_updates=stage_updates,
        backorders=backorders,
        approvals=approvals,
        documents_total=(
            inbound_total + outbound_total + backorders_total + approvals_total
        ),
        location_ids=location_ids,
    )
    return DocumentsTodoResponse(
        inbound=DocumentsTodoSection(
            items=[
                document_row(doc).model_copy(update=stage_updates.get(doc.id, {}))
                for doc in inbound[:limit]
            ],
            total=inbound_total,
        ),
        outbound=DocumentsTodoSection(
            items=[
                document_row(doc).model_copy(update=stage_updates.get(doc.id, {}))
                for doc in outbound[:limit]
            ],
            total=outbound_total,
        ),
        decisions=DocumentsTodoDecisions(
            backorders=DocumentsTodoSection(
                items=[document_row(doc) for doc in backorders[:limit]],
                total=backorders_total,
            ),
            approvals=DocumentsTodoSection(
                items=[document_row(doc) for doc in approvals[:limit]],
                total=approvals_total,
            ),
            quarantine=QuarantineTodoSection(
                items=quarantine,
                total=quarantine_total,
            ),
        ),
        work_items=work_items,
    )


@query_router.get('/awaiting-my-approval', response_model=DocumentListResponse)
async def list_documents_awaiting_my_approval(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> DocumentListResponse:
    """List documents the current user can act on (PENDING/IN_PROGRESS).

    Powers the "To approve" submenu in the warehouse module — approvers
    see only what they can act on without leaving the document context. The
    same read fills To do's *Needs a decision* block, so one rule answers
    both: the approvals module must be on, the reader must hold
    ``approvals:approve`` and the open stage must name them. A disabled
    module reads as an empty queue; a failed lookup is a 500.
    """
    documents, total = await awaiting_approval_documents_async(
        db, org_id, current_user, limit=limit, offset=offset
    )
    items = [document_row(d) for d in documents]
    return DocumentListResponse.from_slice(
        items=items,
        offset=offset,
        limit=limit,
        total=total,
    )


@query_router.get('/price-hint', response_model=PriceHintResponse)
async def get_price_hint(
    template_id: UUID = Query(..., description='Product template id'),
    partner_id: UUID | None = Query(
        None, description='Partner id for supplier pricelist lookup'
    ),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> PriceHintResponse:
    """suggested unit price for a product on a document.

    Chain: partner pricelist (purchase_orders module, when it is there) →
    most recent priced purchase → nothing. Enables the "auto-suggest price"
    step of value tracking without making the warehouse module depend on
    the purchase_orders module being enabled.
    """
    profile = await get_profile(db, org_id)
    # The same rate the document itself will apply: the one the product or
    # its category names, else the profile's explicit entry, else the
    # country's standard rate when the profile states no opinion.
    tax_rate = (await product_tax_rates_async(db, org_id, [template_id])).get(
        template_id
    )
    if tax_rate is None and profile:
        tax_rate = await resolve_document_tax_rate(db, org_id, profile)

    orders = await order_side_async(db, org_id) if partner_id is not None else None
    if partner_id is not None and orders is not None:
        # A switched-off orders module is ``None`` above, and an empty
        # pricelist is an empty list: what the lookup raises is a defect, and
        # falling through to the last purchase would suggest another price.
        offers = await orders.list_pricelist_for_partner_async(
            db,
            org_id,
            partner_id,
            product_template_id=template_id,
        )
        if offers:
            best = min(offers, key=lambda o: o.unit_price)
            return PriceHintResponse(
                unit_price=best.unit_price,
                tax_rate=tax_rate,
                currency=best.currency,
                source='pricelist',
            )

    last = await get_last_purchase_price_async(db, org_id, template_id)
    if last is not None:
        return PriceHintResponse(
            unit_price=last.unit_price,
            tax_rate=tax_rate,
            currency=last.currency,
            source='last_purchase',
        )

    return PriceHintResponse(tax_rate=tax_rate)


@query_router.get('/register/summary', response_model=RegisterResponse)
async def get_document_register_summary(
    date_from: date = Query(..., description='Start date (inclusive)'),
    date_to: date = Query(..., description='End date (inclusive)'),
    type: str | None = Query(default=None, description='Filter by document type'),
    status: str | None = Query(
        default=None, description='Filter by status, default COMPLETED'
    ),
    partner_id: UUID | None = Query(default=None),
    location_id: UUID | None = Query(default=None),
    group_by: str = Query(
        default='type', description='type | partner | location | month'
    ),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> RegisterResponse:
    """Groups and totals for the whole window, no document rows."""
    return await get_register_summary_async(
        db=db,
        org_id=org_id,
        date_from=date_from,
        date_to=date_to,
        doc_type=type,
        status_filter=status,
        partner_id=partner_id,
        location_id=location_id,
        group_by=group_by,
    )


@query_router.get(
    '/register/rows', response_model=PaginatedResponse[RegisterDocumentRow]
)
async def get_document_register_rows(
    date_from: date = Query(..., description='Start date (inclusive)'),
    date_to: date = Query(..., description='End date (inclusive)'),
    type: str | None = Query(default=None, description='Filter by document type'),
    status: str | None = Query(
        default=None, description='Filter by status, default COMPLETED'
    ),
    partner_id: UUID | None = Query(default=None),
    location_id: UUID | None = Query(default=None),
    group_by: str = Query(
        default='type', description='type | partner | location | month'
    ),
    group_key: str = Query(
        default='',
        description="The group to page through; '' is the no-partner/no-location bucket",
    ),
    offset: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_ROWS_LIMIT, ge=1, le=200),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> PaginatedResponse[RegisterDocumentRow]:
    """One group's documents, one page; `total` counts the group."""
    return await get_register_rows_async(
        db=db,
        org_id=org_id,
        date_from=date_from,
        date_to=date_to,
        doc_type=type,
        status_filter=status,
        partner_id=partner_id,
        location_id=location_id,
        group_by=group_by,
        group_key=group_key,
        offset=offset,
        limit=limit,
    )


@query_router.get('/register')
async def export_document_register_csv(
    date_from: date = Query(..., description='Start date (inclusive)'),
    date_to: date = Query(..., description='End date (inclusive)'),
    type: str | None = Query(default=None, description='Filter by document type'),
    status: str | None = Query(
        default=None, description='Filter by status, default COMPLETED'
    ),
    partner_id: UUID | None = Query(default=None),
    location_id: UUID | None = Query(default=None),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> Response:
    """The register as a file — the one way to get everything.

    The paged register cannot serve this, so the export queries its own rows
    and no limit touches it.
    """
    csv_content = await get_register_csv(
        db=db,
        org_id=org_id,
        date_from=date_from,
        date_to=date_to,
        doc_type=type,
        status_filter=status,
        partner_id=partner_id,
        location_id=location_id,
    )
    return Response(
        content=csv_content,
        media_type='text/csv',
        headers={
            'Content-Disposition': f'attachment; filename="register_{date_from}_{date_to}.csv"'
        },
    )
