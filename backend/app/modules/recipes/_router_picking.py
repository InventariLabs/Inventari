from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.core.db_utils import paginate_async
from app.core.deps import (
    get_async_db,
    get_current_user,
    get_current_user_context,
    require_org,
    require_permission,
)
from app.core.exceptions import (
    NotFoundException,
    catalogue_status_refusal,
    map_service_errors,
)
from app.core.module_sdk import PaginatedResponse
from app.i18n.service import get_current_lang

from .models import PickingSession
from .schemas import (
    CookingHistoryItem,
    PatchCookingHistoryRequest,
    PickingScanRequest,
    PickingScanResponse,
    PickingStartRequest,
    PickingStartResponse,
    RecordCookingRequest,
    UndoPickRequest,
    UndoPickResponse,
)
from .services import get_recipe


def _build_history_item(session: PickingSession) -> CookingHistoryItem:
    picked = sum(1 for i in session.items if i.status == 'picked')
    skipped = sum(1 for i in session.items if i.status == 'skipped')
    total = sum(1 for i in session.items if i.status != 'skipped')
    duration = None
    if session.completed_at and session.created_at:
        duration = max(
            0, int((session.completed_at - session.created_at).total_seconds() / 60)
        )
    return CookingHistoryItem(
        session_id=session.id,
        cooked_at=session.completed_at,
        servings=session.servings,
        duration_minutes=duration,
        notes=session.notes,
        rating=session.rating,
        items_picked=picked,
        items_skipped=skipped,
        items_total=total,
    )


def register_picking_routes(router: APIRouter) -> None:
    @router.post(
        '/{recipe_id}/picking/start',
        response_model=PickingStartResponse,
        status_code=status.HTTP_201_CREATED,
    )
    @map_service_errors
    async def start_picking_endpoint(
        recipe_id: UUID,
        data: PickingStartRequest,
        current_user: UserContextDTO = Depends(get_current_user_context),
        db: AsyncSession = Depends(get_async_db, scope='function'),
        org_id: UUID = Depends(require_org),
    ) -> Any:
        from ._meal_plan import require_entry_of_recipe_async
        from .picking_service import start_picking_session

        if data.meal_plan_entry_id is not None:
            await require_entry_of_recipe_async(
                db, data.meal_plan_entry_id, recipe_id, org_id
            )
        return await start_picking_session(
            db,
            recipe_id,
            org_id,
            current_user.id,
            data.servings,
            data.scale,
            data.meal_plan_entry_id,
        )

    @router.post(
        '/{recipe_id}/picking/{session_id}/scan',
        response_model=PickingScanResponse,
    )
    @map_service_errors
    async def scan_picking_endpoint(
        recipe_id: UUID,
        session_id: UUID,
        data: PickingScanRequest,
        current_user: UserContextDTO = Depends(get_current_user_context),
        current_user_model: Any = Depends(get_current_user),
        db: AsyncSession = Depends(get_async_db, scope='function'),
        org_id: UUID = Depends(require_org),
    ) -> Any:
        from .picking_service import scan_item_in_picking

        return await scan_item_in_picking(
            db,
            session_id,
            org_id,
            current_user_model,
            barcode=data.barcode,
            item_id=data.item_id,
            from_checklist=data.from_checklist,
        )

    @router.get(
        '/{recipe_id}/picking/{session_id}',
        response_model=PickingStartResponse,
    )
    @map_service_errors
    async def read_picking_endpoint(
        recipe_id: UUID,
        session_id: UUID,
        current_user: UserContextDTO = Depends(get_current_user_context),
        db: AsyncSession = Depends(get_async_db, scope='function'),
        org_id: UUID = Depends(require_org),
    ) -> Any:
        """Re-read an active session with the shelf resolved again.

        The sheet asks for this after linking an ingredient mid-session, so
        a correction made at the shelf costs a round trip instead of the
        whole session.
        """
        from .picking_service import read_picking_session

        return await read_picking_session(db, session_id, org_id)

    @router.post(
        '/{recipe_id}/picking/{session_id}/complete',
        dependencies=[require_permission('recipes:consume')],
    )
    @map_service_errors
    async def complete_picking_endpoint(
        recipe_id: UUID,
        session_id: UUID,
        current_user: UserContextDTO = Depends(get_current_user_context),
        db: AsyncSession = Depends(get_async_db, scope='function'),
        org_id: UUID = Depends(require_org),
    ) -> Any:
        from .picking_service import complete_picking_session

        return await complete_picking_session(
            db, session_id, org_id, lang=get_current_lang()
        )

    @router.delete(
        '/{recipe_id}/picking/{session_id}',
        status_code=status.HTTP_204_NO_CONTENT,
    )
    @map_service_errors
    async def cancel_picking_endpoint(
        recipe_id: UUID,
        session_id: UUID,
        current_user: UserContextDTO = Depends(get_current_user_context),
        db: AsyncSession = Depends(get_async_db, scope='function'),
        org_id: UUID = Depends(require_org),
    ) -> None:
        from .picking_service import cancel_picking_session

        await cancel_picking_session(db, session_id, org_id)

    @router.post(
        '/{recipe_id}/picking/{session_id}/undo',
        response_model=UndoPickResponse,
    )
    @map_service_errors
    async def undo_pick_endpoint(
        recipe_id: UUID,
        session_id: UUID,
        data: UndoPickRequest,
        current_user: UserContextDTO = Depends(get_current_user_context),
        db: AsyncSession = Depends(get_async_db, scope='function'),
        org_id: UUID = Depends(require_org),
    ) -> Any:
        from .picking_service import undo_pick

        return await undo_pick(db, session_id, org_id, data.ingredient_id)

    @router.get(
        '/{recipe_id}/history',
        response_model=PaginatedResponse[CookingHistoryItem],
    )
    async def get_cooking_history(
        recipe_id: UUID,
        limit: int = Query(20, ge=1, le=200),
        offset: int = Query(0, ge=0),
        current_user: UserContextDTO = Depends(get_current_user_context),
        db: AsyncSession = Depends(get_async_db, scope='function'),
        org_id: UUID = Depends(require_org),
    ) -> PaginatedResponse[CookingHistoryItem]:
        recipe = await get_recipe(db, recipe_id, org_id)
        if not recipe:
            raise NotFoundException('recipe', get_current_lang())

        sessions, total = await paginate_async(
            db,
            select(PickingSession)
            .where(
                PickingSession.recipe_id == recipe_id,
                PickingSession.organization_id == org_id,
                PickingSession.status == 'completed',
            )
            .order_by(PickingSession.completed_at.desc(), PickingSession.id),
            limit=limit,
            offset=offset,
        )
        return PaginatedResponse.from_slice(
            [_build_history_item(s) for s in sessions],
            offset=offset,
            limit=limit,
            total=total,
        )

    @router.post(
        '/{recipe_id}/history',
        response_model=CookingHistoryItem,
        status_code=status.HTTP_201_CREATED,
    )
    @map_service_errors
    async def record_cooking_history_endpoint(
        recipe_id: UUID,
        data: RecordCookingRequest,
        current_user: UserContextDTO = Depends(get_current_user_context),
        db: AsyncSession = Depends(get_async_db, scope='function'),
        org_id: UUID = Depends(require_org),
    ) -> CookingHistoryItem:
        from .picking_service import record_cooking_session

        session = await record_cooking_session(
            db,
            recipe_id,
            org_id,
            current_user.id,
            data.servings,
            session_id=data.session_id,
        )
        return _build_history_item(session)

    @router.patch(
        '/{recipe_id}/history/{session_id}', response_model=CookingHistoryItem
    )
    async def patch_cooking_history(
        recipe_id: UUID,
        session_id: UUID,
        data: PatchCookingHistoryRequest,
        current_user: UserContextDTO = Depends(get_current_user_context),
        db: AsyncSession = Depends(get_async_db, scope='function'),
        org_id: UUID = Depends(require_org),
    ) -> CookingHistoryItem:
        from .picking_service import _UNSET, _Unset, update_cooking_history_session

        await get_recipe(db, recipe_id, org_id)

        notes = data.notes if 'notes' in data.model_fields_set else _UNSET
        rating: int | None | _Unset = _UNSET
        if 'rating' in data.model_fields_set:
            if data.rating is not None and not 1 <= data.rating <= 5:
                raise catalogue_status_refusal('rating_must_be_1_to_5', 422)
            rating = data.rating

        session = await update_cooking_history_session(
            db, session_id, recipe_id, org_id, notes=notes, rating=rating
        )
        if not session:
            raise NotFoundException('history_entry')

        return _build_history_item(session)
