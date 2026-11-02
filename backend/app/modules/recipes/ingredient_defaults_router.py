from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Query,
    Response,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.core.deps import get_async_db, get_current_user_context, require_org
from app.core.exceptions import (
    AppException,
    catalogue_refusal,
    map_service_errors,
    refusal_code,
    refusal_text,
)
from app.core.module_sdk import PaginatedResponse
from app.core.upload_validation import MAX_IMPORT_ROWS, read_capped_upload

from ._allergens import infer_allergens
from ._defaults_seeding import deduplicate_defaults, seed_system_defaults
from .defaults_service import (
    delete_org_default,
    export_defaults,
    import_defaults,
    list_defaults,
    lookup_default,
    upsert_org_default,
)
from .schemas import (
    ImportDefaultsResult,
    IngredientDefaultCreate,
    IngredientDefaultLookupResponse,
    IngredientDefaultSchema,
)

router = APIRouter(prefix='/ingredient-defaults')


@router.get('', response_model=PaginatedResponse[IngredientDefaultSchema])
async def list_ingredient_defaults(
    lang: str = Query('en', description='Language code: en | pl'),
    q: str | None = Query(None, description='Name search query'),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> PaginatedResponse[IngredientDefaultSchema]:
    """List ingredient nutrition defaults (system + org overrides)."""
    org_id = require_org(current_user)
    items, total = await list_defaults(
        db, org_id, lang=lang, q=q, limit=limit, offset=offset
    )
    return PaginatedResponse[IngredientDefaultSchema].from_slice(
        [IngredientDefaultSchema.model_validate(item) for item in items],
        offset=offset,
        limit=limit,
        total=total,
    )


@router.get('/lookup', response_model=IngredientDefaultLookupResponse)
async def lookup_ingredient_default(
    name: str = Query(..., description='Ingredient name to look up'),
    lang: str = Query('en', description='Language code: en | pl'),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> IngredientDefaultLookupResponse:
    """Look up nutrition defaults for a single ingredient name."""
    org_id = require_org(current_user)
    row = await lookup_default(db, name, lang=lang, org_id=org_id)
    allergens = infer_allergens(name)
    if not row:
        return IngredientDefaultLookupResponse(
            found=False, name=name, lang=lang, allergens=allergens
        )
    return IngredientDefaultLookupResponse(
        found=True,
        name=row.name,
        lang=row.lang,
        calories_kcal=row.calories_kcal,
        protein_g=row.protein_g,
        fat_g=row.fat_g,
        carbs_g=row.carbs_g,
        fiber_g=row.fiber_g,
        sugar_g=row.sugar_g,
        salt_g=row.salt_g,
        source=row.source,
        allergens=allergens,
    )


@router.get('/export')
async def export_ingredient_defaults(
    lang: str = Query('en', description='Language code: en | pl'),
    fmt: str = Query('json', description='json | csv'),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Response:
    """Export all visible defaults as JSON or CSV."""
    org_id = require_org(current_user)
    content = await export_defaults(db, org_id, lang=lang, fmt=fmt)
    if fmt == 'csv':
        return Response(
            content=content,
            media_type='text/csv',
            headers={
                'Content-Disposition': f'attachment; filename="ingredient_defaults_{lang}.csv"'
            },
        )
    return Response(
        content=content,
        media_type='application/json',
    )


@router.post(
    '',
    response_model=IngredientDefaultSchema,
    status_code=status.HTTP_201_CREATED,
)
async def create_ingredient_default(
    data: IngredientDefaultCreate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> IngredientDefaultSchema:
    """Create or update an org-level nutrition override."""
    org_id = require_org(current_user)
    row = await upsert_org_default(db, org_id, data.model_dump())
    return IngredientDefaultSchema.model_validate(row)


@router.delete('/{default_id}', status_code=status.HTTP_204_NO_CONTENT)
@map_service_errors
async def delete_ingredient_default(
    default_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> None:
    """Delete an org override. Cannot delete system defaults."""
    org_id = require_org(current_user)
    await delete_org_default(db, org_id, default_id)


@router.post(
    '/import', response_model=ImportDefaultsResult, status_code=status.HTTP_200_OK
)
async def import_ingredient_defaults(
    file: UploadFile = File(...),
    lang: str = Query('en', description='Language code: en | pl'),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> ImportDefaultsResult:
    """Import nutrition defaults from a JSON or CSV file upload."""
    import csv as csv_module
    import json as json_module

    org_id = require_org(current_user)
    try:
        raw = await read_capped_upload(file)
    except ValueError as exc:
        raise AppException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            code=refusal_code(exc, 'FILE_TOO_LARGE'),
            message=refusal_text(exc),
        ) from exc
    content = raw.decode('utf-8', errors='replace')
    filename = (file.filename or '').lower()

    try:
        if filename.endswith('.csv'):
            reader = csv_module.DictReader(content.splitlines())
            items = list(reader)
        else:
            items = json_module.loads(content)
    except Exception as exc:  # an uploaded file's every parse failure is a refusal
        raise catalogue_refusal(
            'ingredient_defaults_unreadable_file', detail=str(exc)
        ) from exc

    if len(items) > MAX_IMPORT_ROWS:
        raise catalogue_refusal(
            'import_too_many_rows', count=len(items), limit=MAX_IMPORT_ROWS
        )

    result = await import_defaults(db, org_id, lang, items)
    return ImportDefaultsResult(**result)


@router.post('/seed', status_code=status.HTTP_200_OK)
async def seed_ingredient_defaults(
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> dict[str, int]:
    """Trigger idempotent seeding and deduplication of system defaults (admin utility)."""
    require_org(current_user)
    deduped = await deduplicate_defaults(db)
    inserted = await seed_system_defaults(db)
    return {'inserted': inserted, 'deduped': deduped}
