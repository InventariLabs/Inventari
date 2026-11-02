from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import SystemPermission, UserContextDTO
from app.core.deps import (
    get_async_db,
    get_current_user_context,
    require_org,
    require_permission,
)
from app.core.exceptions import NotFoundException, map_service_errors
from app.core.module_sdk import PaginatedResponse
from app.i18n.service import get_current_lang

from .schemas import (
    EquipmentModelCreate,
    EquipmentModelSchema,
    EquipmentModelUpdate,
)

router = APIRouter()


@router.get('/models', response_model=PaginatedResponse[EquipmentModelSchema])
async def list_models(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> Any:
    from .model_service import list_equipment_models

    models = await list_equipment_models(db, org_id)
    return PaginatedResponse.from_full_list(models, offset=offset, limit=limit)


@router.post('/models', response_model=EquipmentModelSchema, status_code=201)
async def create_model(
    data: EquipmentModelCreate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ITEMS_WRITE),
    org_id: UUID = Depends(require_org),
) -> Any:
    from .model_service import create_equipment_model

    result = await create_equipment_model(
        db,
        org_id,
        data.name,
        brand=data.brand,
        description=data.description,
        image_url=data.image_url,
        category_id=data.category_id,
        equipment_meta=data.equipment_meta,
        user_id=current_user.id,
    )
    return result


@router.put('/models/{model_id}', response_model=EquipmentModelSchema)
@map_service_errors
async def update_model(
    model_id: UUID,
    data: EquipmentModelUpdate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ITEMS_WRITE),
    org_id: UUID = Depends(require_org),
) -> Any:
    from .model_service import update_equipment_model

    return await update_equipment_model(
        db,
        org_id,
        model_id,
        name=data.name,
        brand=data.brand,
        description=data.description,
        image_url=data.image_url,
        category_id=data.category_id,
        equipment_meta=data.equipment_meta,
        user_id=current_user.id,
    )


@router.delete('/models/{model_id}', status_code=204)
async def delete_model(
    model_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ITEMS_DELETE),
    org_id: UUID = Depends(require_org),
) -> None:
    from .model_service import delete_equipment_model

    deleted = await delete_equipment_model(db, org_id, model_id, current_user.id)
    if not deleted:
        raise NotFoundException('model', get_current_lang())


@router.post('/models/{model_id}/clone', response_model=EquipmentModelSchema)
async def clone_model(
    model_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ITEMS_WRITE),
    org_id: UUID = Depends(require_org),
) -> Any:
    from app.core.public_api import core_api

    from .model_service import clone_equipment_model

    existing = await core_api.product_templates.get_async(db, org_id, model_id)
    if not existing:
        raise NotFoundException('model', get_current_lang())
    new_name = f'{existing.name} (copy)'
    return await clone_equipment_model(
        db, org_id, model_id, new_name, user_id=current_user.id
    )
