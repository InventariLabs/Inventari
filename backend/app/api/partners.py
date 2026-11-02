import json
import uuid

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import SystemPermission, UserContextDTO
from app.core.deps import (
    get_async_db,
    get_current_user_context,
    require_org,
    require_read_write,
)
from app.core.exceptions import (
    ConflictException,
    NotFoundException,
    catalogue_refusal,
    refusal_code,
    refusal_exception,
    refusal_text,
)
from app.core.file_import import analyze_import_file as analyze_sheet
from app.core.upload_validation import read_import_file
from app.schemas._common import SheetAnalysisResponse
from app.schemas.item import Item as ItemSchema
from app.schemas.pagination import PaginatedResponse
from app.schemas.partner import (
    PartnerCreate,
    PartnerImportResponse,
    PartnerListItem,
    PartnerSchema,
    PartnerUpdate,
)
from app.services import partner_service
from app.services.partner_import import import_partners

# Mounted on the router, not per handler: every GET here is a read and every
# other method a write, so the HTTP verb tells the truth about the effect, and
# a route added later lands inside the guard instead of outside it. Before
# this, a `viewer` could rename or delete the supplier whose name and tax id
# are copied onto every document naming them.
router = APIRouter(
    dependencies=[
        require_read_write(
            SystemPermission.PARTNERS_READ, SystemPermission.PARTNERS_WRITE
        )
    ]
)


@router.post('', response_model=PartnerSchema, status_code=201)
async def create_partner(
    data: PartnerCreate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
):
    org_id = require_org(current_user)
    try:
        result = await partner_service.create_async(db, org_id, data, current_user.id)
        return result
    except ValueError as exc:
        raise ConflictException(
            code=refusal_code(exc, 'PARTNER_CONFLICT'), message=refusal_text(exc)
        ) from exc


@router.post('/import/analyze', response_model=SheetAnalysisResponse)
async def analyze_partner_import_file(
    file: UploadFile = File(...),
    current_user: UserContextDTO = Depends(get_current_user_context),
):
    """Headers, the first rows and the row count, for the mapping step.

    The preview travels with the headers because the mapping step shows it:
    a mapping chosen against column names alone cannot be checked by the
    person choosing it.
    """
    require_org(current_user)
    content = await read_import_file(file)
    try:
        return await analyze_sheet(content, file.filename or '')
    except ValueError:
        raise
    except OSError as e:
        raise catalogue_refusal('failed_to_read_file', error=str(e)) from e


@router.post('/import', response_model=PartnerImportResponse)
async def import_partners_from_file(
    file: UploadFile = File(...),
    mapping_json: str = Form(...),
    default_type: str = Form('SUPPLIER'),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
):
    """Imports partners based on mapping; the report names every refused row."""
    require_org(current_user)
    try:
        mapping = json.loads(mapping_json)
    except json.JSONDecodeError as e:
        raise catalogue_refusal('invalid_mapping_json') from e
    content = await read_import_file(file)
    try:
        return await import_partners(
            db=db,
            file_content=content,
            filename=file.filename or '',
            mapping=mapping,
            user=current_user,
            default_type=default_type,
        )
    except ValueError as exc:
        raise refusal_exception(exc) from exc


@router.get('', response_model=PaginatedResponse[PartnerListItem])
async def list_partners(
    search: str | None = Query(
        None, description='Search by name, tax_id, contact_person, email'
    ),
    type: str | None = Query(
        None,
        description='Filter by type (SUPPLIER, CUSTOMER, BOTH, SERVICE_PROVIDER, MANUFACTURER)',
    ),
    types: list[str] | None = Query(
        None,
        description='Filter by a set of types (repeatable), e.g. '
        '?types=SUPPLIER&types=MANUFACTURER — takes precedence over `type`',
    ),
    is_active: bool | None = Query(
        True, description='Filter by active status (None = all)'
    ),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    sort_by: str = Query('name', pattern='^(name|created_at|type)$'),
    sort_order: str = Query('asc', pattern='^(asc|desc)$'),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
):
    org_id = require_org(current_user)
    partner_types = [t.upper() for t in types] if types else None
    partners, total = await partner_service.list_partners_async(
        db,
        org_id,
        search=search,
        partner_type=type,
        partner_types=partner_types,
        is_active=is_active,
        limit=limit,
        offset=offset,
        sort_by=sort_by,  # type: ignore[arg-type]
        sort_order=sort_order,  # type: ignore[arg-type]
    )
    return PaginatedResponse[PartnerListItem].from_slice(
        partners,
        offset=offset,
        limit=limit,
        total=total,
    )


@router.get('/{partner_id}', response_model=PartnerSchema)
async def get_partner(
    partner_id: uuid.UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
):
    org_id = require_org(current_user)
    partner = await partner_service.get_async(db, org_id, partner_id)
    if partner is None:
        raise NotFoundException('partner')
    return partner


@router.put('/{partner_id}', response_model=PartnerSchema)
async def update_partner(
    partner_id: uuid.UUID,
    data: PartnerUpdate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
):
    org_id = require_org(current_user)
    try:
        partner = await partner_service.update_async(
            db, org_id, partner_id, data, user_id=current_user.id
        )
    except ValueError as exc:
        raise ConflictException(
            code=refusal_code(exc, 'PARTNER_CONFLICT'), message=refusal_text(exc)
        ) from exc
    if partner is None:
        raise NotFoundException('partner')
    return partner


@router.delete('/{partner_id}', status_code=204)
async def delete_partner(
    partner_id: uuid.UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
):
    org_id = require_org(current_user)
    try:
        deleted = await partner_service.delete_async(
            db, org_id, partner_id, user_id=current_user.id
        )
    except ValueError as exc:
        raise ConflictException(
            code=refusal_code(exc, 'PARTNER_CONFLICT'), message=refusal_text(exc)
        ) from exc
    if not deleted:
        raise NotFoundException('partner')
    return None


@router.patch('/{partner_id}/deactivate', response_model=PartnerSchema)
async def deactivate_partner(
    partner_id: uuid.UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
):
    org_id = require_org(current_user)
    partner = await partner_service.deactivate_async(
        db, org_id, partner_id, user_id=current_user.id
    )
    if partner is None:
        raise NotFoundException('partner')
    return partner


@router.patch('/{partner_id}/activate', response_model=PartnerSchema)
async def activate_partner(
    partner_id: uuid.UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
):
    org_id = require_org(current_user)
    partner = await partner_service.activate_async(
        db, org_id, partner_id, user_id=current_user.id
    )
    if partner is None:
        raise NotFoundException('partner')
    return partner


@router.get('/{partner_id}/items', response_model=PaginatedResponse[ItemSchema])
async def get_partner_items(
    partner_id: uuid.UUID,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
):
    org_id = require_org(current_user)
    if await partner_service.get_async(db, org_id, partner_id) is None:
        raise NotFoundException('partner')
    items, total = await partner_service.get_items_async(
        db, org_id, partner_id, limit=limit, offset=offset
    )
    return PaginatedResponse[ItemSchema].from_slice(
        [ItemSchema.model_validate(item) for item in items],
        offset=offset,
        limit=limit,
        total=total,
    )
