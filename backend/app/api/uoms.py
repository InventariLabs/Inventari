"""Units of measure — read-only reference data, cached per organization.

Every item form loads both of these lists, and they are among the most static
data in the product: UoMs are written by seeding only (organization creation
and profile switch), never by a runtime endpoint. That is what makes them safe
to cache where categories and storage types are not — those are created from
several services and from the item importer, so a cache would need
invalidation in each of those places to avoid serving a form a stale list.

There is deliberately no invalidation hook: the seeders write *system* UoMs
(``organization_id`` NULL), which arrive with a deploy or a profile switch,
not while a user is looking at a form. The TTL is the whole consistency
window, and an invalidator with no caller would be exactly the dead surface
 was spent removing.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.core.cache import cache_get_or_set
from app.core.contracts import UomCategoryDTO, UomDTO, UserContextDTO
from app.core.deps import get_async_db, get_current_user_context, require_org
from app.core.public_api import core_api
from app.schemas.pagination import PaginatedResponse

router = APIRouter()

_TTL = 300


def _uoms_key(org_id: UUID) -> str:
    return f'org:{org_id}:uoms'


def _uom_categories_key(org_id: UUID) -> str:
    return f'org:{org_id}:uom-categories'


@router.get('', response_model=PaginatedResponse[UomDTO])
async def get_uoms(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db=Depends(get_async_db, scope='function'),
    current_user: UserContextDTO = Depends(get_current_user_context),
):
    """List all units of measure visible to the current organization (system + org-specific)."""
    org_id = require_org(current_user)

    async def _compute():
        return await core_api.uoms.list_for_org_async(db, org_id)

    uoms = await cache_get_or_set(_uoms_key(org_id), ttl=_TTL, factory=_compute)
    return PaginatedResponse.from_full_list(uoms, offset=offset, limit=limit)


@router.get('/categories', response_model=PaginatedResponse[UomCategoryDTO])
async def get_uom_categories(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db=Depends(get_async_db, scope='function'),
    current_user: UserContextDTO = Depends(get_current_user_context),
):
    """List all UoM categories visible to the current organization (system + org-specific)."""
    org_id = require_org(current_user)

    async def _compute():
        return await core_api.uoms.list_categories_for_org_async(db, org_id)

    categories = await cache_get_or_set(
        _uom_categories_key(org_id), ttl=_TTL, factory=_compute
    )
    return PaginatedResponse.from_full_list(categories, offset=offset, limit=limit)
