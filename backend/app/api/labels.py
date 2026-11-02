import io
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.contracts import (
    LabelPoolCreateDTO,
    LabelScanDTO,
    SystemPermission,
    UserContextDTO,
)
from app.core.deps import (
    get_async_db,
    get_current_user_context,
    require_org,
    require_permission,
)
from app.core.events import SystemEvent
from app.core.exceptions import (
    AppException,
    ConflictException,
    NotFoundException,
    catalogue_refusal,
    map_service_errors,
    refusal_code,
    refusal_text,
)
from app.core.limiter import limiter
from app.core.public_api import core_api
from app.core.scan_registry import scan_registry
from app.i18n.service import get_current_lang, get_error_message
from app.schemas._common import LabelUnassignResponse
from app.schemas.item import Item as ItemSchema
from app.schemas.label_pool import (
    LabelAssignRequest,
    LabelFromCodesRequest,
    LabelPoolListResponse,
    LabelPoolResponse,
    LabelScanResponse,
)
from app.services.items import assign_label_or_barcode

router = APIRouter()

# A label is a sticker on a physical thing, so the pool is inventory data and
# rides on ITEMS_WRITE instead of a key of its own: the role allowed to add and
# edit products is exactly the role that prints, frees and reassigns their
# labels. A read-only account generating a second pool puts codes on paper that
# duplicate ones already stuck to shelves.
_ITEMS_WRITE = require_permission(SystemPermission.ITEMS_WRITE)


@router.post(
    '/pool/generate',
    # list-envelope-exception: a bulk result, the labels this request just created
    response_model=list[LabelPoolResponse],
    status_code=status.HTTP_201_CREATED,
)
async def generate_label_pool(
    request: LabelPoolCreateDTO,
    _: object = _ITEMS_WRITE,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
):
    """Generates a pool of N unique labels for the user's organization."""
    require_org(current_user)

    labels = await core_api.labels.generate_pool_async(db, request, current_user)
    await core_api.events.emit_transactional_async(
        db,
        SystemEvent.LABEL_BATCH_GENERATED,
        {
            'organization_id': str(current_user.organization_id),
            'count': len(labels),
            'label_type': request.label_type,
            'prefix': request.prefix,
            'label_ids': [str(lbl.id) for lbl in labels],
            'created_by': str(current_user.id),
        },
    )
    return labels


@router.post(
    '/pool/from-codes',
    # list-envelope-exception: a bulk result, the labels this request just created
    response_model=list[LabelPoolResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_labels_from_codes(
    request: LabelFromCodesRequest,
    _: object = _ITEMS_WRITE,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
):
    """Create labels from explicit short_codes (e.g. equipment serials).

    Per-org uniqueness: a short_code already used in the org, or duplicated
    within the request, is rejected with 409.
    """
    require_org(current_user)
    from app.core.contracts import LabelCodeItemDTO

    code_dtos = [LabelCodeItemDTO(**c.model_dump()) for c in request.codes]
    try:
        labels = await core_api.labels.create_from_codes_async(
            db,
            code_dtos,
            current_user,
            label_type=request.label_type,
            context_tag=request.context_tag,
        )
    except ValueError as exc:
        raise ConflictException(
            refusal_code(exc, 'LABEL_CODE_CONFLICT'), message=refusal_text(exc)
        ) from exc
    await core_api.events.emit_transactional_async(
        db,
        SystemEvent.LABEL_BATCH_GENERATED,
        {
            'organization_id': str(current_user.organization_id),
            'count': len(labels),
            'label_type': request.label_type,
            'label_ids': [str(lbl.id) for lbl in labels],
            'created_by': str(current_user.id),
        },
    )
    return labels


@router.get('/pool', response_model=LabelPoolListResponse)
async def get_label_pool(
    unassigned_only: bool = Query(False, description='Only unassigned labels'),
    label_type: str | None = Query(None, description='Filter by label type'),
    status: str | None = Query(
        None, description='Pool status: FREE, PRINTED, ASSIGNED, ARCHIVED'
    ),
    limit: int | None = Query(None, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ITEMS_READ),
):
    """List of labels for the user's organization - Optimized."""
    items, total = await core_api.labels.list_for_org_with_relations_async(
        db,
        current_user.organization_id,  # type: ignore[arg-type]
        unassigned_only=unassigned_only,
        label_type=label_type,
        status=status,
        offset=offset,
        limit=limit,
    )
    # When limit is None (no pagination requested), normalise to total so the
    # envelope stays compatible with PaginatedResponse[int]. That normalisation
    # also makes `from_slice` reproduce the old explicit `limit is not None and
    # ...` guard: with limit==total the computation is `offset + total < total`,
    # which is False for every `offset >= 0` — and offset is `Query(0, ge=0)`.
    effective_limit = limit if limit is not None else total
    # `from_slice` types `items` explicitly, which surfaces a mismatch the
    # loose Pydantic `__init__` was hiding: the service hands back
    # `LabelPoolDTO`, the envelope declares `LabelPoolResponse`. Pydantic
    # coerced them during construction anyway — do it explicitly, the way
    # every other list endpoint here already does.
    return LabelPoolListResponse.from_slice(
        items=[LabelPoolResponse.model_validate(label) for label in items],
        offset=offset,
        limit=effective_limit,
        total=total,
    )


@router.get('/pool/stats', response_model=dict)
async def get_label_stats(
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ITEMS_READ),
):
    """Returns statistics for the label pool."""
    return await core_api.labels.get_pool_stats_async(db, current_user.organization_id)  # type: ignore[arg-type]


@router.delete('/pool/{label_id}', status_code=status.HTTP_204_NO_CONTENT)
async def delete_label(
    label_id: UUID,
    _: object = _ITEMS_WRITE,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
):
    """Deletes a specific label."""
    org_id = require_org(current_user)
    label = await core_api.labels.get_by_id_async(db, label_id, org_id)
    if not label:
        raise NotFoundException('label')

    item = None
    if label.is_assigned and label.item_id:
        item = await core_api.items.get_async(
            db,
            org_id,
            label.item_id,
        )
        if item and not item.is_deleted:
            raise catalogue_refusal('label_in_use_by_product')

    deleted = await core_api.labels.delete_async(
        db, label_id, org_id, user_id=current_user.id
    )
    if not deleted:
        raise NotFoundException('label')
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# 120 a minute per user: two codes a second sustained is faster than a wedge
# scanner is worked, and still stops a camera that keeps re-reading one symbol.
# The scope is named because slowapi keys a bucket by URL otherwise, and every
# code is a URL of its own: the allowance would never run out on distinct codes.
@router.get('/scan/{short_code:path}', response_model=LabelScanResponse)
@limiter.shared_limit('120/minute', scope='label-scan')
async def scan_label(
    request: Request,
    short_code: str,
    code: str | None = None,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ITEMS_READ),
):
    """Endpoint called after scanning a QR code (Place or Product) or Barcode."""

    input_code = short_code
    if code:
        if '?' not in input_code:
            input_code = f'{short_code}?code={code}'

    result = await scan_registry.scan(input_code, current_user, db)

    if result:
        # A provider may answer with the contract DTO rather than this API's
        # published subclass (a module reaches the contract, not the schema):
        # the payload is the same shape, so it is rebuilt as the response
        # model before FastAPI validates it.
        if isinstance(result, LabelScanDTO):
            return LabelScanResponse.model_validate(result.model_dump())
        return result

    # Nothing resolved the code. The product provider tries every code as a
    # barcode or SKU, so even a label-shaped miss is "nothing matched" rather
    # than "a label that does not exist" — and the screens offer the search.
    raise AppException(
        status_code=404,
        code='SCAN_UNRECOGNIZED',
        message=get_error_message('scan_unrecognized', get_current_lang()),
    )


@router.post(
    '/pool/{short_code}/unassign',
    response_model=LabelUnassignResponse,
    status_code=status.HTTP_200_OK,
)
async def unassign_label(
    short_code: str,
    _: object = _ITEMS_WRITE,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
):
    """Manually frees a label from an archived/deleted item."""
    org_id = require_org(current_user)
    label = await core_api.labels.unassign_async(
        db, short_code, org_id, user_id=current_user.id
    )
    if label is None:
        raise NotFoundException('label')

    return LabelUnassignResponse(message='Label is now free for reuse')


@router.post('/pool/{short_code}/assign-item', response_model=LabelPoolResponse)
async def assign_label_to_existing_item(
    short_code: str,
    item_id: UUID,
    _: object = _ITEMS_WRITE,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
):
    """Assigns a free label to an already-existing item (ITAM flow)."""

    org_id = require_org(current_user)
    label = await core_api.labels.get_by_short_code_async(db, short_code, org_id)
    if not label:
        raise NotFoundException('label')
    if label.is_assigned:
        raise catalogue_refusal('label_already_assigned')

    item = await core_api.items.get_async(
        db,
        org_id,
        item_id,
    )
    if not item:
        raise NotFoundException('item')

    assigned = await core_api.labels.assign_to_existing_item_async(
        db, short_code, item_id, org_id, user_id=current_user.id
    )
    if assigned is None:
        raise NotFoundException('label')
    return assigned


@router.post('/scan/{short_code}/assign', response_model=ItemSchema)
@map_service_errors
async def assign_label_to_item(
    short_code: str,
    data: LabelAssignRequest,
    _: object = _ITEMS_WRITE,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
):
    """Assigns a label to a newly created product OR creates a product with a barcode.

    The canonical mapping answers its refusals, the item limit included, in
    the shapes the form door (``POST /items``) answers them with.
    """
    return await assign_label_or_barcode(db, short_code, data, current_user)


@router.get('/pool/export/png', response_model=None)
async def export_labels_png(
    count: int = Query(50, ge=1, le=200),
    label_ids: list[str] | None = Query(None),
    short_codes: list[str] | None = Query(
        None, description='Resolve labels by short_code (e.g. item.label_code)'
    ),
    width: float = Query(50.0, ge=10.0, le=300.0, description='Width in mm'),
    height: float = Query(24.0, ge=5.0, le=300.0, description='Height in mm'),
    base_url: str | None = Query(None, description='Base URL for QR codes'),
    description: str | None = Query(
        None, description='Custom description for single label print'
    ),
    columns: int | None = Query(
        None, ge=1, le=100, description='Number of columns (default: all in one row)'
    ),
    qr_only: bool = Query(
        False,
        description=(
            'Leave the caption off the label — including the one filled in '
            'from the assigned product when none is sent. Independent of '
            'show_code, so the two together print the short code alone.'
        ),
    ),
    show_code: bool = Query(
        False,
        description=(
            'Print the short code under the QR, small. Off by default: a '
            'shelf is read by caption, and the code is for the moment a scan '
            'fails and somebody types it in.'
        ),
    ),
    mark_printed: bool = Query(
        True,
        description=(
            'Whether to mark the exported labels as printed. The preview asks '
            'for the same image and must not spend the pool to show it.'
        ),
    ),
    dpi: float = Query(
        300.0,
        ge=72.0,
        le=1200.0,
        description=(
            "Resolution to draw at; a print agent names its printer's, so a "
            'QR lands on whole dots.'
        ),
    ),
    max_height_px: int | None = Query(
        None,
        ge=8,
        le=10000,
        description=(
            'The most dots the printer prints across: a taller label is '
            'scaled down as a whole to fit.'
        ),
    ),
    edge_to_edge: bool = Query(
        False,
        description=(
            'The printer leaves a white edge of its own above and below the '
            'label, as a tape wider than its head does: a bare QR is drawn as '
            'tall as the label.'
        ),
    ),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ITEMS_READ),
):
    """Exports labels as one PNG: each label at its size, in mm, at 300 dpi."""
    org_id = require_org(current_user)

    if label_ids:
        labels_dto = await core_api.labels.list_in_ids_async(
            db, [UUID(i) for i in label_ids], org_id
        )
        labels_map = {str(lbl.id): lbl for lbl in labels_dto}
        labels = []
        for lid in label_ids:
            if lid in labels_map:
                labels.append(labels_map[lid])
    elif short_codes:
        labels_dto = await core_api.labels.list_by_short_codes_async(
            db, short_codes, org_id
        )
        codes_map = {lbl.short_code: lbl for lbl in labels_dto}
        labels = [codes_map[sc] for sc in short_codes if sc in codes_map]
    else:
        labels_dto = await core_api.labels.list_unprinted_unassigned_async(
            db,
            org_id,
            limit=count,
        )
        labels = list(labels_dto)

    if not labels:
        # Its own code, not VALIDATION_ERROR: the print agent polls this
        # endpoint and an empty pool is its normal state, which it must tell
        # apart from a refusal without reading a translated message.
        raise AppException(
            status_code=400,
            code='NO_LABELS_AVAILABLE',
            message=get_error_message('no_labels_available', get_current_lang()),
        )

    if description:
        for label in labels:
            label.description = description
    else:
        # No caption typed for this print run: an assigned product supplies
        # one, so its name and expiry do not have to be typed in again to
        # appear on the label they are already about.
        from app.services.label_service import label_caption

        for label in labels:
            label.description = label_caption(label)

    target_base_url = base_url if base_url else settings.FRONTEND_URL

    from app.core.label_rendering import render_label_batch_png, render_label_png

    if len(labels) == 1:
        png_data = render_label_png(
            labels[0],
            width_mm=width,
            height_mm=height,
            base_url=target_base_url,
            qr_only=qr_only,
            show_code=show_code,
            dpi=dpi,
            max_height_px=max_height_px,
            edge_to_edge=edge_to_edge,
        )
    else:
        final_cols = columns if columns is not None else 100
        png_data = render_label_batch_png(
            labels,
            width_mm=width,
            height_mm=height,
            base_url=target_base_url,
            columns=final_cols,
            qr_only=qr_only,
            show_code=show_code,
            dpi=dpi,
            max_height_px=max_height_px,
            edge_to_edge=edge_to_edge,
        )
    if not mark_printed:
        # A preview of the file is the file. Rendering it a second time to
        # show it must not consume the labels or announce an export that
        # nobody has taken yet.
        return StreamingResponse(io.BytesIO(png_data), media_type='image/png')

    await core_api.labels.mark_as_printed_by_ids_async(
        db, [lbl.id for lbl in labels], org_id
    )
    await core_api.events.emit_transactional_async(
        db,
        SystemEvent.LABEL_BATCH_EXPORTED,
        {
            'organization_id': str(current_user.organization_id),
            'count': len(labels),
            'label_ids': [str(lbl.id) for lbl in labels],
            'width_mm': width,
            'height_mm': height,
        },
    )

    return StreamingResponse(
        io.BytesIO(png_data),
        media_type='image/png',
        headers={
            'Content-Disposition': f'attachment; filename=labels_{len(labels)}pcs.png'
        },
    )
