"""The print queue's endpoints.

Pool and storage labels render elsewhere: Core serves them through
``/api/v1/labels/pool/export/png`` and ``/api/v1/locations/{id}/label`` with the
renderers this module registers. A product's barcode label is this module's
own and renders here, ``/product-labels/png``. The rest is the queue — the app sends
labels to a printer, and the print agent next to that printer, under
``/agent/``, claims them, fetches the image and reports. Those endpoints guard
``printing:agent``, which is also the whole reach of a key issued with the
``printing`` scope. On a demo instance the visitor's own label sheet — the
sandbox's shelves and a few products, one A4 — renders here,
``/demo-label-sheet``.
"""

import io
from collections.abc import Iterable
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.contracts import SystemPermission, UserContextDTO
from app.core.deps import (
    get_async_db,
    get_current_user_context,
    require_any_permission,
    require_org,
    require_permission,
)
from app.core.exceptions import AppException, ForbiddenException, catalogue_refusal
from app.core.module_sdk import PaginatedResponse
from app.core.modules import require_module
from app.i18n.service import get_current_lang, get_error_message
from app.modules.printing import schemas
from app.modules.printing.models import PrintAgent, PrintJob
from app.modules.printing.services import print_queue_service as queue
from app.modules.printing.services.label_geometry import LABEL_DPI

router = APIRouter(dependencies=[Depends(require_module('printing'))])

AGENT_PATH = '/agent'

#: A kind of label answers to the reads of the screens that send it, each
#: screen's own: the core read of its records and the read of a module whose
#: screen prints that kind. A shelf is sent from a location card
#: (``locations:read``) and from the warehouse's scan sheet and location codes
#: (``warehouse:read``); a pool label from the Labels screen (``items:read``)
#: and from the equipment register's asset list and its batch of new assets
#: (``equipment:read``); a product's barcode label from the product screens
#: alone. Printing changes no stock, so a viewer prints too. A label a module
#: draws itself is queued through ``printing_api`` under that module's read.
_SHELF_READS = (SystemPermission.STORAGES_READ.value, 'warehouse:read')
_POOL_READS = (SystemPermission.ITEMS_READ.value, 'equipment:read')
_PRODUCT_READS = (SystemPermission.ITEMS_READ.value,)

_READS_PRODUCTS = require_permission(SystemPermission.ITEMS_READ)
_READS_SHELVES = require_any_permission(*_SHELF_READS)

#: The printers and the queue serve every one of those screens, and a package
#: card of a dispatch, so any of their reads opens them. A job keeps the reads
#: of its kind: a new one asks for one of them (``_target_reads``), and the
#: list and a retry show and resend a job only to a holder of one.
_READS_A_TARGET = require_any_permission(*dict.fromkeys(_POOL_READS + _SHELF_READS))


def _target_reads(payload: schemas.PrintJobCreate) -> tuple[str, ...]:
    """The reads that may send this job's labels, by the kind it names."""
    if payload.location_ids:
        return _SHELF_READS
    if payload.item_ids:
        return _PRODUCT_READS
    return _POOL_READS


def _require_read(user: UserContextDTO, permissions: Iterable[str]) -> None:
    if not any(user.has_permission(permission) for permission in permissions):
        raise ForbiddenException(
            get_error_message('insufficient_permissions', get_current_lang())
        )


async def _require_agent_authority(
    user: UserContextDTO = Depends(get_current_user_context),
) -> None:
    """A session administers the queue; a key acts only as the agent."""
    if user.role != 'api_key' and not user.has_permission('org:settings:write'):
        raise ForbiddenException(
            get_error_message('insufficient_permissions', get_current_lang())
        )


def _agent_out(agent: PrintAgent) -> schemas.PrintAgentResponse:
    return schemas.PrintAgentResponse.model_validate(agent).model_copy(
        update={'online': queue.is_online(agent)}
    )


def _job_out(job: PrintJob) -> schemas.PrintJobResponse:
    entries = list(job.labels or [])
    return schemas.PrintJobResponse.model_validate(
        {
            'id': job.id,
            'agent_id': job.agent_id,
            'status': job.status,
            'count': len(entries),
            'short_codes': [entry['short_code'] for entry in entries[:5]],
            'width_mm': job.width_mm,
            'height_mm': job.height_mm,
            'attempts': job.attempts,
            'error': job.error,
            'scale': job.scale,
            'created_at': job.created_at,
            'finished_at': job.finished_at,
        }
    )


# ── the app ─────────────────────────────────────────────────────────


@router.get(
    '/agents',
    response_model=PaginatedResponse[schemas.PrintAgentResponse],
    dependencies=[_READS_A_TARGET],
)
async def list_agents(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    org_id: UUID = Depends(require_org),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> PaginatedResponse[schemas.PrintAgentResponse]:
    """The organization's printers, each online or not."""
    agents = [_agent_out(agent) for agent in await queue.list_agents_async(db, org_id)]
    return PaginatedResponse.from_full_list(agents, offset=offset, limit=limit)


@router.post(
    '/jobs',
    response_model=schemas.PrintJobResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_READS_A_TARGET],
)
async def queue_job(
    payload: schemas.PrintJobCreate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    org_id: UUID = Depends(require_org),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> schemas.PrintJobResponse:
    """Send the chosen labels to a printer."""
    read_permissions = _target_reads(payload)
    _require_read(current_user, read_permissions)
    job = await queue.queue_job_async(
        db,
        org_id,
        current_user.id,
        read_permissions=read_permissions,
        agent_id=payload.agent_id,
        label_ids=payload.label_ids,
        short_codes=payload.short_codes,
        storage_ids=payload.location_ids,
        item_ids=payload.item_ids,
        caption=payload.caption,
        qr_only=payload.qr_only,
        show_code=payload.show_code,
        details=payload.details,
        copies=payload.copies,
        width_mm=payload.width_mm,
        height_mm=payload.height_mm,
        bars=payload.bars,
        qr=payload.qr,
    )
    return _job_out(job)


@router.post(
    '/product-labels/png',
    response_model=None,
    responses={200: {'content': {'image/png': {}}}},
    dependencies=[_READS_PRODUCTS],
)
async def product_labels_png(
    payload: schemas.ProductLabelExport,
    org_id: UUID = Depends(require_org),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> StreamingResponse:
    """The products' barcode labels as one PNG, side by side.

    A product with no code to print is left out; ``X-Labels-Without-Code``
    says how many were, so the screen can say so.
    """
    from app.modules.printing.services.product_label_service import (
        generate_product_label_batch_png,
    )

    # X-Labels-With-Details counts the labels that carry a lot or an expiry
    # date whether or not they print it: the screen offers the option only
    # when some do.
    labels, without_code, with_details = await queue.product_labels_async(
        db, org_id, payload.item_ids, details=payload.details
    )
    if not labels:
        raise catalogue_refusal('product_label_no_code')
    labels = [label for label in labels for _ in range(payload.copies)]
    png = generate_product_label_batch_png(labels, payload.width_mm, payload.height_mm)
    return StreamingResponse(
        io.BytesIO(png),
        media_type='image/png',
        headers={
            'X-Labels-Without-Code': str(without_code),
            'X-Labels-With-Details': str(with_details),
        },
    )


@router.post(
    '/location-labels/png',
    response_model=None,
    responses={200: {'content': {'image/png': {}}}},
    dependencies=[_READS_SHELVES],
)
async def location_labels_png(
    payload: schemas.LocationLabelExport,
    org_id: UUID = Depends(require_org),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> StreamingResponse:
    """Shelf labels as one PNG: the code large, in Code 128, a QR if asked.

    A location with no code to print is left out; ``X-Labels-Without-Code``
    says how many were.
    """
    from app.modules.printing.services.product_label_service import (
        generate_product_label_batch_png,
    )

    labels, without_code = await queue.location_labels_async(
        db, org_id, payload.location_ids, qr=payload.qr
    )
    if not labels:
        raise catalogue_refusal('print_job_nothing_to_print')
    labels = [label for label in labels for _ in range(payload.copies)]
    png = generate_product_label_batch_png(labels, payload.width_mm, payload.height_mm)
    return StreamingResponse(
        io.BytesIO(png),
        media_type='image/png',
        headers={'X-Labels-Without-Code': str(without_code)},
    )


@router.get(
    '/demo-label-sheet',
    response_model=None,
    responses={
        200: {'content': {'image/png': {}}},
        404: {'description': 'This instance is not a demo'},
    },
    dependencies=[_READS_PRODUCTS],
)
async def demo_label_sheet(
    org_id: UUID = Depends(require_org),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> StreamingResponse:
    """The demo's own label sheet as one A4 PNG: its shelves, a few products.

    Only a demo instance answers; anywhere else the route is not there.
    Every code printed on it is the sandbox's own — the demo's seed gives
    the same shelves the same codes in every sandbox — so one printed sheet
    scans anywhere in the demo, with a phone camera or a 1D scanner.
    """
    if not settings.INVENTARI_DEMO:
        raise AppException(
            status_code=status.HTTP_404_NOT_FOUND,
            code='NOT_FOUND',
            message=get_error_message('not_found', get_current_lang()),
        )

    from app.modules.printing.services.demo_label_sheet_service import (
        demo_label_sheet_async,
    )

    labels, png = await demo_label_sheet_async(db, org_id)
    if not labels:
        raise catalogue_refusal('print_job_nothing_to_print')
    return StreamingResponse(io.BytesIO(png), media_type='image/png')


@router.get(
    '/jobs',
    response_model=PaginatedResponse[schemas.PrintJobResponse],
    dependencies=[_READS_A_TARGET],
)
async def list_jobs(
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: UserContextDTO = Depends(get_current_user_context),
    org_id: UUID = Depends(require_org),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> PaginatedResponse[schemas.PrintJobResponse]:
    """One page of the jobs the caller may read, newest first."""
    jobs, total = await queue.list_jobs_async(
        db,
        org_id,
        may_read=current_user.has_permission,
        offset=offset,
        limit=limit,
    )
    return PaginatedResponse.from_slice(
        [_job_out(job) for job in jobs], offset, limit, total
    )


@router.post(
    '/jobs/{job_id}/retry',
    response_model=schemas.PrintJobResponse,
    dependencies=[_READS_A_TARGET],
)
async def retry_job(
    job_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    org_id: UUID = Depends(require_org),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> schemas.PrintJobResponse:
    """Send a failed job to its printer again, for a reader of what it prints."""
    job = await queue.get_job_async(db, org_id, job_id)
    _require_read(current_user, job.read_permissions)
    job = await queue.retry_job_async(db, org_id, job_id)
    return _job_out(job)


# ── the print agent ─────────────────────────────────────────────────


@router.post(
    f'{AGENT_PATH}/register',
    response_model=schemas.PrintAgentResponse,
    dependencies=[
        require_permission('printing:agent'),
        Depends(_require_agent_authority),
    ],
)
async def register_agent(
    payload: schemas.PrintAgentRegister,
    org_id: UUID = Depends(require_org),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> schemas.PrintAgentResponse:
    """An agent announces its printer; the same name again says it is back."""
    agent = await queue.register_agent_async(
        db,
        org_id,
        name=payload.name,
        printer_type=payload.printer_type,
        agent_version=payload.agent_version,
        protocol_version=payload.protocol_version,
    )
    return _agent_out(agent)


@router.post(
    f'{AGENT_PATH}/{{agent_id}}/claim',
    dependencies=[
        require_permission('printing:agent'),
        Depends(_require_agent_authority),
    ],
    response_model=schemas.PrintJobClaim,
    responses={204: {'description': 'Nothing to print'}},
)
async def claim_job(
    agent_id: UUID,
    org_id: UUID = Depends(require_org),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> schemas.PrintJobClaim | Response:
    """The agent's poll: its next job under a lease, or 204 when none waits."""
    job = await queue.claim_next_async(db, org_id, agent_id)
    if job is None or job.lease_until is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    return schemas.PrintJobClaim(
        id=job.id,
        count=len(job.labels or []),
        width_mm=job.width_mm,
        height_mm=job.height_mm,
        lease_until=job.lease_until,
        attempt=job.attempts,
    )


@router.get(
    f'{AGENT_PATH}/jobs/{{job_id}}/image',
    response_model=None,
    dependencies=[
        require_permission('printing:agent'),
        Depends(_require_agent_authority),
    ],
)
async def job_image(
    job_id: UUID,
    dpi: float = Query(
        LABEL_DPI,
        ge=72.0,
        le=1200.0,
        description="The printer's resolution: the label is drawn at it.",
    ),
    max_height_px: int | None = Query(
        None,
        ge=8,
        le=10000,
        description=(
            'The most dots the printer can print across: a taller label is '
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
    index: int | None = Query(
        None,
        ge=0,
        description=(
            'The one label at this place in the job, copies counted, instead '
            'of the whole strip: for a printer that cuts after each label.'
        ),
    ),
    org_id: UUID = Depends(require_org),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> StreamingResponse:
    """The job's labels as one PNG, at the job's label size. Marks nothing.

    The agent may name its printer's raster, and gets the same layout in
    millimetres drawn at it, so a 180 dpi head prints QR modules on whole
    dots rather than a 300 dpi file resampled to uneven ones.
    """
    png = await queue.job_image_async(
        db,
        org_id,
        job_id,
        settings.FRONTEND_URL,
        dpi=dpi,
        max_height_px=max_height_px,
        edge_to_edge=edge_to_edge,
        index=index,
    )
    return StreamingResponse(io.BytesIO(png), media_type='image/png')


@router.post(
    f'{AGENT_PATH}/jobs/{{job_id}}/report',
    response_model=schemas.PrintJobResponse,
    dependencies=[
        require_permission('printing:agent'),
        Depends(_require_agent_authority),
    ],
)
async def report_job(
    job_id: UUID,
    payload: schemas.PrintJobReport,
    org_id: UUID = Depends(require_org),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> schemas.PrintJobResponse:
    """The agent's outcome; pool labels count as printed only on success."""
    job = await queue.report_job_async(
        db,
        org_id,
        job_id,
        payload.agent_id,
        attempt=payload.attempt,
        printed=payload.printed,
        error=payload.error,
        scale=payload.scale,
    )
    return _job_out(job)
