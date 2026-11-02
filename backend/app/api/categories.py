from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.core.contracts import (
    CategoryCreateDTO,
    CategoryDTO,
    CategoryUpdateDTO,
    SystemPermission,
    UserContextDTO,
)
from app.core.deps import (
    get_async_db,
    get_current_user_context,
    require_org,
    require_permission,
)
from app.core.exceptions import (
    NotFoundException,
    refusal_exception,
)
from app.core.public_api import core_api
from app.schemas.category import CategoryGroupRename, CategoryGroupRenameResult
from app.schemas.pagination import PaginatedResponse

router = APIRouter()


def _dedupe_categories(categories: list[CategoryDTO]) -> list[CategoryDTO]:
    """If both system and organization category with same code exist, keep organization one."""
    result: dict[str, CategoryDTO] = {}
    for cat in categories:
        key = cat.code if cat.code else f'id_{cat.id}'
        if key not in result or cat.organization_id is not None:
            result[key] = cat
    return list(result.values())


@router.get('', response_model=PaginatedResponse[CategoryDTO])
async def get_categories(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    include_inactive: bool = Query(
        False, description='Include categories marked as inactive'
    ),
    exclude_module_contexts: bool = Query(
        False,
        description='Exclude categories whose context_tag is claimed by an enabled vertical module',
    ),
    with_counts: bool = Query(
        False, description='Include how many live items each category holds'
    ),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db=Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.CATEGORIES_READ),
):
    """List of categories with optional module-context filters."""
    claimed_tags: set[str] = set()
    if exclude_module_contexts:
        from app.core.module_scope import get_claimed_context_tags

        claimed_tags = get_claimed_context_tags()

    categories = await core_api.categories.list_with_filters_async(
        db,
        require_org(current_user),
        include_inactive=include_inactive,
        claimed_tags=claimed_tags or None,
        with_counts=with_counts,
    )
    deduped = _dedupe_categories(categories)
    ordered = sorted(deduped, key=lambda x: (x.sort_order or 0, x.name))
    return PaginatedResponse.from_full_list(ordered, offset=offset, limit=limit)


@router.post('', response_model=CategoryDTO, status_code=status.HTTP_201_CREATED)
async def create_category(
    category_in: CategoryCreateDTO,
    _: object = require_permission(SystemPermission.CATEGORIES_WRITE),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db=Depends(get_async_db, scope='function'),
):
    """Add custom category."""
    try:
        return await core_api.categories.create_async(db, category_in, current_user)
    except ValueError as exc:
        raise refusal_exception(exc) from exc


@router.patch('/groups', response_model=CategoryGroupRenameResult)
async def rename_category_group_endpoint(
    payload: CategoryGroupRename,
    _: object = require_permission(SystemPermission.CATEGORIES_WRITE),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db=Depends(get_async_db, scope='function'),
):
    """Rename a category group in one go, or take it off its categories.

    Declared before ``/{category_id}`` so "groups" is read as this route and
    not as a category id.
    """
    org_id = require_org(current_user)
    new_name = (payload.new_name or '').strip() or None
    changed = await core_api.categories.rename_group_async(
        db,
        org_id,
        current_name=payload.current_name,
        new_name=new_name,
        category_ids=payload.category_ids,
        user=current_user,
    )
    if not changed:
        raise NotFoundException('category')
    return CategoryGroupRenameResult(updated=len(changed), category_ids=changed)


@router.get('/{category_id}', response_model=CategoryDTO)
async def get_category(
    category_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db=Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.CATEGORIES_READ),
):
    """Category details."""
    org_id = require_org(current_user)
    category = await core_api.categories.get_by_id_async(db, org_id, category_id)
    if not category:
        raise NotFoundException('category')
    return category


@router.put('/{category_id}', response_model=CategoryDTO)
async def update_category(
    category_id: UUID,
    category_in: CategoryUpdateDTO,
    _: object = require_permission(SystemPermission.CATEGORIES_WRITE),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db=Depends(get_async_db, scope='function'),
):
    """Update category."""
    org_id = require_org(current_user)
    # A refusal of the payload (a system field's label renamed, a dropdown
    # without options) is the global handler's to answer with a 400 in the
    # request language. Every ValueError used to be answered "category not
    # found" here, which told the reader the row they were editing was gone.
    # A missing row is the ``None`` below.
    result = await core_api.categories.update_async(
        db, org_id, category_id, category_in, current_user
    )
    if result is None:
        raise NotFoundException('category')
    return result


@router.delete('/{category_id}', status_code=status.HTTP_204_NO_CONTENT)
async def delete_category(
    category_id: UUID,
    _: object = require_permission(SystemPermission.CATEGORIES_WRITE),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db=Depends(get_async_db, scope='function'),
):
    """Delete category."""
    org_id = require_org(current_user)
    try:
        deleted = await core_api.categories.delete_async(
            db, org_id, category_id, current_user
        )
    except ValueError as exc:
        raise refusal_exception(exc) from exc
    if not deleted:
        raise NotFoundException('category')
    return None
