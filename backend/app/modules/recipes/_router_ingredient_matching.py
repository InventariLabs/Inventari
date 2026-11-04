"""Global ingredient routes: the mass-matching screen.

One view of every ingredient no recipe in the organization has linked yet,
LLM proposals to approve, and one write applying the approved subset. The
paths are two static segments under ``/ingredients``, so they cannot be
shadowed by the dynamic ``/{recipe_id}`` routes; they are still registered
with the other static route groups (see ``router.py``).
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.core.deps import get_async_db, get_current_user_context, require_org
from app.core.exceptions import map_service_errors
from app.core.limiter import limiter

from ._schemas_linking import (
    BulkLinkIngredientsRequest,
    BulkLinkIngredientsResponse,
    IngredientMatchProposalsResponse,
    UnlinkedIngredientsResponse,
)
from .ingredient_linking_service import (
    apply_links,
    count_ingredients,
    list_unlinked_ingredients,
    suggest_matches,
)


def register_ingredient_matching_routes(router: APIRouter) -> None:
    @router.get('/ingredients/unlinked', response_model=UnlinkedIngredientsResponse)
    async def list_unlinked_ingredients_endpoint(
        # The screen works the backlog down in one sitting, so a page is wide.
        limit: int = Query(200, ge=1, le=1000),
        offset: int = Query(0, ge=0),
        current_user: UserContextDTO = Depends(get_current_user_context),
        db: AsyncSession = Depends(get_async_db, scope='function'),
        org_id: UUID = Depends(require_org),
    ) -> Any:
        items = await list_unlinked_ingredients(db, org_id)
        page = UnlinkedIngredientsResponse.from_full_list(
            items, offset=offset, limit=limit
        )
        return page.model_copy(
            update={'ingredient_total': await count_ingredients(db, org_id)}
        )

    @router.post(
        '/ingredients/match-proposals',
        response_model=IngredientMatchProposalsResponse,
    )
    @limiter.limit('10/minute')
    @map_service_errors
    async def suggest_matches_endpoint(
        request: Request,
        current_user: UserContextDTO = Depends(get_current_user_context),
        db: AsyncSession = Depends(get_async_db, scope='function'),
        org_id: UUID = Depends(require_org),
    ) -> Any:
        usage_ctx: dict[str, Any] = {
            'db': db,
            'user_id': current_user.id,
            'organization_id': org_id,
        }
        proposals, considered = await suggest_matches(db, org_id, usage_ctx=usage_ctx)
        return IngredientMatchProposalsResponse(
            proposals=proposals, considered=considered
        )

    @router.post(
        '/ingredients/link-templates',
        response_model=BulkLinkIngredientsResponse,
    )
    async def bulk_link_ingredients_endpoint(
        data: BulkLinkIngredientsRequest,
        current_user: UserContextDTO = Depends(get_current_user_context),
        db: AsyncSession = Depends(get_async_db, scope='function'),
        org_id: UUID = Depends(require_org),
    ) -> Any:
        linked, recipe_ids = await apply_links(db, org_id, data)
        return BulkLinkIngredientsResponse(linked=linked, recipe_ids=recipe_ids)
