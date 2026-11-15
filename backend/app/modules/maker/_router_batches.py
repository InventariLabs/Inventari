"""A run's batches: shelf life, ingredient batches, the output's hold, record, files."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Query,
    UploadFile,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import (
    AuditAction,
    AuditTargetType,
    StockLotDTO,
    SystemPermission,
    UserContextDTO,
)
from app.core.deps import (
    get_async_db,
    get_current_user_context,
    require_org,
    require_permission,
)
from app.core.exceptions import AppException, map_service_errors
from app.core.module_sdk import (
    FileSignatureMismatchError,
    FileTooLargeError,
    FileTypeNotAllowedError,
    PaginatedResponse,
)
from app.core.public_api import core_api

from . import (
    batch_record,
    ingredient_batches,
    output_batch,
    production_attachments,
)
from ._schemas_batches import (
    BatchRecordRead,
    IngredientBatchPlanResponse,
    OutputBatchHold,
    OutputBatchRead,
    ProductionAttachmentRead,
    ShelfLifeRead,
    ShelfLifeUpdate,
)
from .availability_service import resolve_check_location

router = APIRouter(prefix='/production', tags=['maker'])


@router.get('/shelf-lives/{template_id}', response_model=ShelfLifeRead)
async def get_shelf_life(
    template_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> ShelfLifeRead:
    """How many days the product keeps once made (None: nobody said)."""
    return ShelfLifeRead(
        product_template_id=template_id,
        shelf_life_days=await output_batch.get_shelf_life_async(
            db, org_id, template_id
        ),
    )


@router.put(
    '/shelf-lives/{template_id}',
    response_model=ShelfLifeRead,
    dependencies=[require_permission('maker:manage')],
)
@map_service_errors
async def set_shelf_life(
    template_id: UUID,
    data: ShelfLifeUpdate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> ShelfLifeRead:
    """Set the product's shelf life in days, or clear it with ``null``.

    A fact about the product, so it lands in the organization journal with
    both sides, as a typed price does.
    """
    before = await output_batch.get_shelf_life_async(db, org_id, template_id)
    days = await output_batch.set_shelf_life_async(
        db, org_id, template_id, data.shelf_life_days
    )
    template = await core_api.product_templates.get_async(db, org_id, template_id)
    await core_api.audit_log.log_action_async(
        db,
        organization_id=org_id,
        user_id=current_user.id,
        action=AuditAction.UPDATE,
        target_type=AuditTargetType.PRODUCT_TEMPLATE,
        target_id=template_id,
        snapshot={
            'name': template.name if template else None,
            'shelf_life_days_before': before,
            'shelf_life_days_after': days,
        },
    )
    return ShelfLifeRead(product_template_id=template_id, shelf_life_days=days)


@router.get('/ingredient-batches', response_model=IngredientBatchPlanResponse)
@map_service_errors
async def plan_ingredient_batches(
    output_template_id: UUID = Query(...),
    planned_qty: Decimal = Query(..., gt=0, max_digits=12, decimal_places=3),
    output_location_id: UUID = Query(...),
    recipe_id: UUID | None = Query(None),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> IngredientBatchPlanResponse:
    """Which batches each ingredient of a run would be taken from, read-only.

    The run as its form or its draft names it: the product, the recipe
    (its default when left out), the quantity and where the output goes.
    Answers the draw the run makes when nobody chooses, and every batch the
    person may choose instead — at the scope the run draws under.
    """
    scope = await resolve_check_location(
        db, org_id, context_location_id=output_location_id
    )
    return IngredientBatchPlanResponse(
        ingredients=await ingredient_batches.plan_ingredient_batches(
            db,
            org_id,
            output_template_id,
            planned_qty,
            recipe_id=recipe_id,
            location_id=scope,
        )
    )


def _output_batches_read(lots: list[StockLotDTO]) -> OutputBatchRead:
    """The answer of a hold or a release: the run's own batch, then all of them."""
    own = lots[0]
    return OutputBatchRead(
        lot_id=own.id,
        lot_name=own.name,
        status=own.status,
        batches=output_batch.run_batch_reads(lots),
    )


@router.post(
    '/orders/{order_id}/hold',
    response_model=OutputBatchRead,
    dependencies=[require_permission('maker:manage')],
)
@map_service_errors
async def hold_output_batch(
    order_id: UUID,
    data: OutputBatchHold,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> OutputBatchRead:
    """Put every batch of the run's output on hold until it is released."""
    lots = await output_batch.hold_output_async(
        db, org_id, order_id, current_user, data.reason
    )
    return _output_batches_read(lots)


@router.post(
    '/orders/{order_id}/release',
    response_model=OutputBatchRead,
    dependencies=[require_permission('maker:manage')],
)
@map_service_errors
async def release_output_batch(
    order_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> OutputBatchRead:
    """Release the run's held output batches back into use."""
    lots = await output_batch.release_output_async(db, org_id, order_id, current_user)
    return _output_batches_read(lots)


@router.get('/orders/{order_id}/record', response_model=BatchRecordRead)
@map_service_errors
async def get_batch_record(
    order_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> BatchRecordRead:
    """The printable batch record of a completed run."""
    return await batch_record.build_batch_record(db, org_id, order_id)


@router.get(
    '/orders/{order_id}/attachments',
    response_model=PaginatedResponse[ProductionAttachmentRead],
)
@map_service_errors
async def list_run_attachments(
    order_id: UUID,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> PaginatedResponse[ProductionAttachmentRead]:
    """The photos and files filed under the run, newest first."""
    rows = await production_attachments.list_attachments(db, org_id, order_id)
    return PaginatedResponse.from_full_list(
        [production_attachments.to_read(org_id, row) for row in rows],
        offset=offset,
        limit=limit,
    )


@router.post(
    '/orders/{order_id}/attachments',
    response_model=ProductionAttachmentRead,
    status_code=201,
)
@map_service_errors
async def upload_run_attachment(
    order_id: UUID,
    file: UploadFile = File(...),
    # A run's papers are the run's record: the same door that closes a run.
    _: object = require_permission(SystemPermission.ITEMS_WRITE),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> ProductionAttachmentRead:
    """File a photo or a document under the run, within a product attachment's limits."""
    content = await file.read()
    try:
        row = await production_attachments.upload_attachment(
            db,
            org_id,
            order_id,
            current_user,
            content=content,
            original_name=file.filename or 'upload',
            content_type=file.content_type or 'application/octet-stream',
        )
    except FileTooLargeError as exc:
        raise AppException(
            status_code=413, code='FILE_TOO_LARGE', message=str(exc)
        ) from exc
    except FileSignatureMismatchError as exc:
        raise AppException(
            status_code=400, code='FILE_SIGNATURE_MISMATCH', message=str(exc)
        ) from exc
    except FileTypeNotAllowedError as exc:
        raise AppException(
            status_code=415, code='FILE_TYPE_NOT_ALLOWED', message=str(exc)
        ) from exc
    return production_attachments.to_read(org_id, row)


@router.delete('/orders/{order_id}/attachments/{attachment_id}', status_code=204)
@map_service_errors
async def delete_run_attachment(
    order_id: UUID,
    attachment_id: UUID,
    background_tasks: BackgroundTasks,
    _: object = require_permission(SystemPermission.ITEMS_WRITE),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> None:
    """Take a file off the run; the stored file goes once the removal is committed."""
    file_path = await production_attachments.delete_attachment(
        db, org_id, order_id, attachment_id, current_user
    )
    background_tasks.add_task(
        production_attachments.discard_stored_file, org_id, file_path
    )
