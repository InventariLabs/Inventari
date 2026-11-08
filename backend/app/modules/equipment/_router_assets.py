from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.core.deps import get_async_db, get_current_user_context, require_org

from ._asset_timeline import get_asset_timeline_async
from ._assets_service import list_equipment_assets_async
from ._schemas_equipment import (
    AssetTimelineResponse,
    EquipmentAssetItem,
    EquipmentAssetListResponse,
)

router = APIRouter()


@router.get('/assets', response_model=EquipmentAssetListResponse)
async def list_equipment_assets(
    search: str | None = Query(None, description='ILIKE over name/brand/barcode'),
    category_id: UUID | None = Query(None, description='Filter by category'),
    location_id: UUID | None = Query(None, description='Filter by location'),
    status: str | None = Query(
        None,
        description='Filter by meta_data.equipment.equipment_status '
        '(AVAILABLE / DEPLOYED / MAINTENANCE / RETIRED)',
    ),
    checked_out: bool = Query(
        False,
        description='Only assets with an open EquipmentAssignment (source of '
        'truth for "checked out")',
    ),
    hide_retired: bool = Query(
        False,
        description='Leave out retired assets nobody holds - the fleet the '
        'dashboard counts',
    ),
    sort: Literal['name', 'created_at', 'purchase_price', 'warranty_until', 'location']
    | None = Query(None, description='Sort key for the asset list'),
    sort_dir: Literal['asc', 'desc'] = Query('desc', description='Sort direction'),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> Any:
    """Paginated equipment asset list with status / checked-out filters."""
    items, total, assigned = await list_equipment_assets_async(
        db,
        org_id,
        search=search,
        category_id=category_id,
        storage_id=location_id,
        status=status,
        checked_out=checked_out,
        hide_retired=hide_retired,
        sort=sort,
        sort_dir=sort_dir,
        limit=limit,
        offset=offset,
    )
    payload: list[EquipmentAssetItem] = []
    for item in items:
        dto = EquipmentAssetItem.model_validate(item)
        holder = assigned.get(item.id)
        if holder is not None:
            dto.holder_name = holder.name
            dto.holder_kind = holder.kind
            if holder.place_id is not None:
                # Checked out to a place: it stands there until it comes
                # back, so that is the location this row reports. The asset's
                # own location stays its home, where the return puts it.
                dto.location_id = holder.place_id
                dto.location_name = holder.name
        payload.append(dto)
    return EquipmentAssetListResponse.from_slice(
        items=payload,
        offset=offset,
        limit=limit,
        total=total,
    )


@router.get(
    '/assets/{item_id}/timeline',
    response_model=AssetTimelineResponse,
)
async def get_asset_timeline(
    item_id: UUID,
    limit: int = Query(200, ge=1, le=500, description='Max entries per source'),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> AssetTimelineResponse:
    """The asset's timeline, assembled server-side.

    One read for the tab: the register's history is the spine (status
    changes live only there), and the handover and maintenance records come
    along for the details only they carry."""
    return await get_asset_timeline_async(db, org_id, item_id, limit=limit)
