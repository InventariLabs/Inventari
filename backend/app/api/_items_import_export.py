import json
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Query,
    UploadFile,
)
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api._items_params import parse_template_ids
from app.api.dependencies import get_user_storage_ids
from app.core import db_facade
from app.core.contracts import SystemPermission, UserContextDTO
from app.core.deps import (
    get_async_db,
    get_current_user_context,
    require_permission,
)
from app.core.exceptions import (
    ForbiddenException,
    catalogue_refusal,
    refusal_exception,
)
from app.core.file_import import analyze_import_file as analyze_sheet
from app.core.import_sheet import read_rows
from app.core.upload_validation import read_import_file
from app.i18n.service import get_current_lang, get_plural_error_message
from app.schemas._common import SheetAnalysisResponse
from app.schemas.item import ItemImportJobResponse, ItemImportResponse
from app.services.items import _import_job as import_jobs
from app.services.items import import_items as import_items_service
from app.services.items._import import LabelMatch
from app.services.items.export_service import export_items_to_xlsx

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
):
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
):
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

    # Founding a category or a whole location path is the work the front
    # doors (POST /categories, POST /locations) gate by permission — the
    # bulk door asks for items:write only, and both flags default to on,
    # so without this check the import granted a permission the caller
    # does not hold. Refused, not silently downgraded: the sheet asked
    # for creation, and quietly importing without it would be a
    # half-true answer. The sheet asks only through a column the mapping
    # names — with no category or location column nothing can be founded,
    # whatever the toggles say, and the refusal would be about a switch,
    # not about the sheet. Every missing key is named, so an account short
    # on both reads one refusal that says the whole price.
    named = mapping if isinstance(mapping, dict) else {}
    missing: list[str] = []
    if (
        create_missing_categories
        and named.get('category')
        and not current_user.has_permission(SystemPermission.CATEGORIES_WRITE)
    ):
        missing.append('categories:write')
    if (
        create_missing_locations
        and named.get('location')
        and not current_user.has_permission(SystemPermission.STORAGES_WRITE)
    ):
        missing.append('locations:write')
    if missing:
        raise ForbiddenException(
            message=get_plural_error_message(
                'import_create_forbidden',
                len(missing),
                get_current_lang(),
                permissions=', '.join(missing),
            )
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


@router.get('/import/jobs/{job_id}', response_model=ItemImportJobResponse)
async def read_import_job(
    job_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    _: object = require_permission(SystemPermission.ITEMS_WRITE),
    db: AsyncSession = Depends(get_async_db, scope='function'),
):
    """How far an import that went to the background has got, and how it ended."""
    job = await import_jobs.read_job_async(db, current_user, job_id)
    answer = ItemImportJobResponse.model_validate(job, from_attributes=True)
    answer.error = import_jobs.reader_reason(answer.error)
    return answer


@router.get('/export/xlsx', response_model=None)
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
    user_storage_ids: list[UUID] = Depends(get_user_storage_ids),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ITEMS_READ),
):
    """Export the rows the list shows for the same filters, as a workbook.

    Takes the filters of ``GET /items`` minus pagination and sorting and runs
    them through the same query builder, so the sheet downloaded from under
    "Showing 1–50 of 102" holds those 102 rows. Feature-module columns (e.g.
    equipment's "Assigned To") come from the export-enricher registry — Core
    never imports a module directly.
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
    return await db.run_sync(
        lambda s: export_items_to_xlsx(
            s, current_user, filters, enrichment, user_storage_ids
        )
    )
