import json
from collections.abc import Awaitable, Callable
from functools import partial
from typing import Any
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    Query,
    UploadFile,
)
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api._items_params import parse_template_ids
from app.api.dependencies import get_user_storage_ids
from app.config import settings
from app.core import db_facade
from app.core.contracts import SystemPermission, UserContextDTO
from app.core.deps import (
    get_async_db,
    get_current_user_context,
    require_org,
    require_permission,
)
from app.core.exceptions import (
    ForbiddenException,
    catalogue_refusal,
    refusal_exception,
)
from app.core.file_import import analyze_import_file as analyze_sheet
from app.core.file_import import refuse_founding_without_permission
from app.core.grocy_file import GrocyFile, read_grocy_file
from app.core.import_sheet import read_rows
from app.core.upload_validation import read_capped_upload, read_import_file
from app.core.xlsx_export import xlsx_file_response
from app.i18n.service import get_current_lang, get_plural_error_message
from app.schemas._common import SheetAnalysisResponse
from app.schemas.item import (
    GrocyFileAnalysis,
    ItemExportJobResponse,
    ItemImportJobResponse,
    ItemImportResponse,
)
from app.services.items import _export_job as export_jobs
from app.services.items import _import_job as import_jobs
from app.services.items import export_service
from app.services.items import import_items as import_items_service
from app.services.items._grocy_import import (
    analyze_grocy_file_async,
    grocy_import_steps,
    import_grocy_file_async,
    plan_grocy_import_async,
)
from app.services.items._import import LabelMatch

router = APIRouter()


@router.post('/import/analyze', response_model=SheetAnalysisResponse)
async def analyze_import_file(
    file: UploadFile = File(...),
    current_user: UserContextDTO = Depends(get_current_user_context),
    # On the route, not in the service: the bulk door must ask for the same
    # permission as the single-product door (POST /items). The guard is this
    # route's parameter, not the router's — the ``APIRouter()`` above carries
    # no ``dependencies=``, so a route added to this file inherits nothing
    # and must name the permission itself. The export route below stays open
    # on purpose: reading the catalogue out is not changing it.
    _: object = require_permission(SystemPermission.ITEMS_WRITE),
) -> Any:
    """Headers, the first rows and the row count of an XLSX/CSV upload.

    The preview travels with the headers because the mapping step shows it:
    a mapping chosen against column names alone cannot be checked by the
    person choosing it.
    """
    content = await read_import_file(file)
    try:
        return await analyze_sheet(content, file.filename or '')
    except ValueError:
        raise
    except OSError as e:
        raise catalogue_refusal('failed_to_read_file', error=str(e)) from e


@router.post(
    '/import',
    response_model=ItemImportResponse,
    responses={202: {'model': ItemImportJobResponse}},
)
async def import_items(
    file: UploadFile = File(...),
    mapping_json: str = Form(...),
    create_missing_locations: bool = Form(True),
    create_missing_categories: bool = Form(True),
    on_label_match: LabelMatch = Form('add'),
    current_user: UserContextDTO = Depends(get_current_user_context),
    _: object = require_permission(SystemPermission.ITEMS_WRITE),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    """Imports items based on mapping.

    ``on_label_match`` says what a row does when its Label Code names a
    product the organization already has: add it anyway (the default, and
    what the import always did), skip the row, or overwrite the product.

    A sheet of more than ``INLINE_ROW_LIMIT`` rows takes minutes, longer than
    a browser or a proxy waits, so it is answered at once with ``202`` and a
    job (:class:`ItemImportJobResponse`) that is read at
    ``GET /items/import/jobs/{id}``. A shorter one is imported inside the
    request and answered with its result.
    """
    try:
        mapping = json.loads(mapping_json)
    except json.JSONDecodeError as e:
        raise catalogue_refusal('invalid_mapping_json') from e

    refuse_founding_without_permission(
        current_user,
        mapping,
        create_missing_locations=create_missing_locations,
        create_missing_categories=create_missing_categories,
    )

    content = await read_import_file(file)
    filename = file.filename or ''
    try:
        rows = len(read_rows(content, filename))
        if rows <= import_jobs.INLINE_ROW_LIMIT:
            return await import_items_service(
                db=db,
                file_content=content,
                filename=filename,
                mapping=mapping,
                user=current_user,
                create_missing_locations=create_missing_locations,
                create_missing_categories=create_missing_categories,
                on_label_match=on_label_match,
            )
    except ValueError as exc:
        raise refusal_exception(exc) from exc

    job = await import_jobs.start_job_async(db, current_user, filename, rows)
    # Committed before the task starts: it reads the job from its own session.
    await db.commit()
    import_jobs.spawn(
        job.id,
        db_facade.AsyncSessionLocal,
        file_content=content,
        filename=filename,
        mapping=mapping,
        user=current_user,
        create_missing_locations=create_missing_locations,
        create_missing_categories=create_missing_categories,
        on_label_match=on_label_match,
    )
    return JSONResponse(
        status_code=202,
        content=ItemImportJobResponse.model_validate(
            job, from_attributes=True
        ).model_dump(mode='json'),
    )


async def _read_grocy_upload(file: UploadFile) -> GrocyFile:
    """The uploaded Grocy database, read; a refusal when it is not one.

    No extension is asked for: a copy of ``grocy.db`` keeps its bytes under
    any name, and the file's own header says what it is.
    """
    content = await read_capped_upload(file)
    try:
        return read_grocy_file(content)
    except ValueError as exc:
        raise refusal_exception(exc) from exc


def _category_matches(text: str) -> dict[str, UUID]:
    """``{"<Grocy group>": "<category id>"}``, read; a refusal when it is not."""
    try:
        parsed = json.loads(text or '{}')
        if not isinstance(parsed, dict):
            raise TypeError(type(parsed).__name__)
        return {str(name): UUID(str(value)) for name, value in parsed.items()}
    except (json.JSONDecodeError, TypeError, ValueError) as e:
        raise catalogue_refusal('invalid_mapping_json') from e


@router.post('/import/grocy/analyze', response_model=GrocyFileAnalysis)
async def analyze_grocy_file(
    file: UploadFile = File(...),
    current_user: UserContextDTO = Depends(get_current_user_context),
    _: object = require_permission(SystemPermission.ITEMS_WRITE),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    """What Grocy's database file (``data/grocy.db``) holds, before the move.

    Grocy writes no export, so a move reads its file. Nothing is written
    here: the step before the move shows what comes across, what would be
    founded, what an earlier run already brought, and what stays behind.
    """
    require_org(current_user)
    grocy = await _read_grocy_upload(file)
    return await analyze_grocy_file_async(db, current_user, grocy)


@router.post(
    '/import/grocy',
    response_model=ItemImportResponse,
    responses={202: {'model': ItemImportJobResponse}},
)
async def import_grocy_file(
    file: UploadFile = File(...),
    category_matches_json: str = Form('{}'),
    current_user: UserContextDTO = Depends(get_current_user_context),
    _: object = require_permission(SystemPermission.ITEMS_WRITE),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    """Move in from Grocy: its locations, groups, stores, products and stock.

    The founding the file asks for — a location, a category, a supplier the
    organization does not have — is the work the front doors gate by
    permission, so an account short of one is refused before anything is
    written, with every missing key named. A file of more than
    ``INLINE_ROW_LIMIT`` steps (batches, and products without stock) is
    answered with ``202`` and a job, as a long sheet is.

    ``category_matches_json`` maps a Grocy group's name to a category the
    reader's screen recognised by the name it shows — a seeded category is
    stored in English and shown in the reader's language.
    """
    require_org(current_user)
    category_matches = _category_matches(category_matches_json)
    grocy = await _read_grocy_upload(file)
    plan = await plan_grocy_import_async(db, current_user, grocy, category_matches)
    missing = [
        key
        for founds, permission, key in (
            (plan.new_locations, SystemPermission.STORAGES_WRITE, 'locations:write'),
            (
                plan.new_categories,
                SystemPermission.CATEGORIES_WRITE,
                'categories:write',
            ),
            (plan.new_suppliers, SystemPermission.PARTNERS_WRITE, 'partners:write'),
        )
        if founds and not current_user.has_permission(permission)
    ]
    if missing:
        raise ForbiddenException(
            message=get_plural_error_message(
                'grocy_import_forbidden',
                len(missing),
                get_current_lang(),
                permissions=', '.join(missing),
            )
        )

    steps = grocy_import_steps(grocy)
    if steps <= import_jobs.INLINE_ROW_LIMIT:
        return await import_grocy_file_async(
            db, grocy, current_user, category_matches=category_matches
        )

    job = await import_jobs.start_job_async(
        db, current_user, file.filename or 'grocy.db', steps
    )
    # Committed before the task starts: it reads the job from its own session.
    await db.commit()

    async def work(
        session: AsyncSession, on_batch: Callable[[int], Awaitable[None]]
    ) -> dict[str, Any]:
        return await import_grocy_file_async(
            session,
            grocy,
            current_user,
            on_batch=on_batch,
            category_matches=category_matches,
        )

    import_jobs.spawn(job.id, db_facade.AsyncSessionLocal, work=work)
    return JSONResponse(
        status_code=202,
        content=ItemImportJobResponse.model_validate(
            job, from_attributes=True
        ).model_dump(mode='json'),
    )


@router.get('/import/jobs/{job_id}', response_model=ItemImportJobResponse)
async def read_import_job(
    job_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    _: object = require_permission(SystemPermission.ITEMS_WRITE),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    """How far an import that went to the background has got, and how it ended."""
    job = await import_jobs.read_job_async(db, current_user, job_id)
    answer = ItemImportJobResponse.model_validate(job, from_attributes=True)
    answer.error = import_jobs.reader_reason(answer.error)
    return answer


@router.get(
    '/export/xlsx',
    response_model=None,
    responses={202: {'model': ItemExportJobResponse}},
)
async def export_items_xlsx(
    location_id: UUID | None = Query(None, description='Filter by location'),
    category_id: UUID | None = Query(None, description='Filter by category'),
    context_tag: str | None = Query(
        None, description='Filter by category context_tag (e.g. equipment)'
    ),
    exclude_module_contexts: bool = Query(
        False,
        description='Hide items whose category belongs to a vertical module',
    ),
    location_usage: str | None = Query(
        'internal',
        description=(
            'Filter by location usage (internal, customer, inventory); '
            "'any' exports every location"
        ),
    ),
    search: str | None = Query(
        None, description='Search by name, brand, barcode or label code'
    ),
    expiring_days: int | None = Query(
        None, description='Products expiring within X days'
    ),
    only_expired: bool = Query(False, description='Show only expired items'),
    only_low_stock: bool = Query(False, description='Show only low stock items'),
    needs_attention: bool = Query(
        False,
        description='Expired, expiring soon, or of a product at its threshold',
    ),
    template_ids: str = Query(
        '',
        description='Comma-separated product template UUIDs; empty means no filter.',
    ),
    asks_for_job: bool = Header(
        False, alias='X-Test-Export-Job', include_in_schema=False
    ),
    user_storage_ids: list[UUID] = Depends(get_user_storage_ids),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ITEMS_READ),
) -> Any:
    """Export the rows the list shows for the same filters, as a workbook.

    Takes the filters of ``GET /items`` minus pagination and sorting and runs
    them through the same query builder, so the sheet downloaded from under
    "Showing 1–50 of 102" holds those 102 rows. Feature-module columns (e.g.
    equipment's "Assigned To") come from the export-enricher registry — Core
    never imports a module directly.

    A sheet of more than ``INLINE_ROW_LIMIT`` records takes longer than a
    phone or a proxy waits, so it is answered at once with ``202`` and a job
    (:class:`ItemExportJobResponse`) read at ``GET /items/export/jobs/{id}``;
    its workbook is fetched from ``GET /items/export/jobs/{id}/file`` once
    the job is done; a process of its own writes it, so the worker's other
    requests do not wait for it. A shorter one is answered with the
    workbook, written on a thread.
    """
    parsed_template_ids = parse_template_ids(template_ids)

    claimed_tags: set[str] = set()
    if exclude_module_contexts:
        from app.core.module_scope import get_claimed_context_tags

        claimed_tags = get_claimed_context_tags()

    # Same rule as the list: an explicit storage ask is more specific than
    # the usage default. 'any' is the backup export asking for everything.
    if location_usage == 'any' or (
        location_id is not None and location_usage == 'internal'
    ):
        location_usage = None

    enrichment: dict[UUID, dict[str, object]] = {}
    today = None
    if current_user.organization_id:
        from app.core.export_enrichers import enrich_export_rows
        from app.core.public_api import core_api

        org = await core_api.organizations.get_async(db, current_user.organization_id)
        enrichment = await enrich_export_rows(
            db, current_user.organization_id, org.enabled_modules or [] if org else []
        )
        today = await core_api.organizations.today_async(
            db, current_user.organization_id
        )

    filters = {
        'location_usage': location_usage,
        'storage_id': location_id,
        'category_id': category_id,
        'context_tag': context_tag,
        'claimed_tags': claimed_tags or None,
        'search': search,
        'expiring_days': expiring_days,
        'only_expired': only_expired,
        'only_low_stock': only_low_stock,
        'needs_attention': needs_attention,
        'template_ids': parsed_template_ids or None,
        'today': today,
    }
    rows = await export_service.count_rows_async(
        db, current_user.organization_id, user_storage_ids, filters
    )
    # A browser spec follows a job without storing thousands of records: a
    # ``TESTING`` stack lets a request ask for one, any other ignores the ask.
    inline_limit = (
        0 if asks_for_job and settings.TESTING else export_jobs.INLINE_ROW_LIMIT
    )
    if rows <= inline_limit or current_user.organization_id is None:
        return await export_service.export_items_async(
            current_user, filters, enrichment, user_storage_ids
        )

    job = await export_jobs.start_job_async(db, current_user, rows)
    # Committed before the task starts: it reads the job from its own session.
    await db.commit()
    export_jobs.spawn(
        job.id,
        db_facade.AsyncSessionLocal,
        partial(
            export_service.write_workbook_file,
            current_user,
            filters,
            enrichment,
            user_storage_ids,
        ),
    )
    return JSONResponse(
        status_code=202,
        content=ItemExportJobResponse.model_validate(
            job, from_attributes=True
        ).model_dump(mode='json'),
    )


@router.get('/export/jobs/{job_id}', response_model=ItemExportJobResponse)
async def read_export_job(
    job_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    _: object = require_permission(SystemPermission.ITEMS_READ),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    """How far an export that went to the background has got, and how it ended."""
    job = await export_jobs.read_job_async(db, current_user, job_id)
    answer = ItemExportJobResponse.model_validate(job, from_attributes=True)
    answer.error = export_jobs.reader_reason(answer.error)
    return answer


@router.get('/export/jobs/{job_id}/file', response_model=None)
async def read_export_file(
    job_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    _: object = require_permission(SystemPermission.ITEMS_READ),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    """The workbook of a finished export job, kept for a day after it started."""
    workbook, made_at = await export_jobs.read_file_async(db, current_user, job_id)
    return xlsx_file_response(
        workbook, filename_stem=export_service.FILENAME_STEM, made_at=made_at
    )
