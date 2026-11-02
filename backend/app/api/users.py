from uuid import UUID

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_superuser
from app.core.contracts import SystemPermission, UserContextDTO
from app.core.deps import (
    get_async_db,
    get_current_user_context,
    require_org,
    require_permission,
)
from app.core.exceptions import NotFoundException
from app.core.public_api import core_api
from app.schemas.pagination import PaginatedResponse
from app.schemas.user import User as UserSchema

router = APIRouter()


@router.get('', response_model=PaginatedResponse[UserSchema])
async def list_users(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _current_user=Depends(get_superuser),
    db: AsyncSession = Depends(get_async_db, scope='function'),
):
    """List all users (superuser only)."""
    users = await core_api.users.list_all_async(db)
    return PaginatedResponse.from_full_list(users, offset=offset, limit=limit)


@router.get('/org-members', response_model=PaginatedResponse[UserSchema])
async def list_org_members(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ORG_READ),
):
    """List members of the current user's organization."""
    org_id = require_org(current_user)
    members = await core_api.users.list_org_members_async(db, org_id)
    return PaginatedResponse.from_full_list(members, offset=offset, limit=limit)


@router.post('/{user_id}/activate', response_model=UserSchema)
async def activate_user(
    user_id: UUID,
    current_user=Depends(get_superuser),
    db: AsyncSession = Depends(get_async_db, scope='function'),
):
    """Activate or deactivate a user (superuser only)."""
    # Superuser tooling is cross-org by design — the None is the explicit
    # opt-out the signature introduced, not an omitted argument.
    result = await core_api.users.activate_or_deactivate_async(
        db, None, user_id, actor_user_id=current_user.id
    )
    if not result:
        raise NotFoundException('user')
    return result


@router.post('/{user_id}/block', response_model=UserSchema)
async def block_user(
    user_id: UUID,
    reason: str | None = Body(None, embed=True),
    current_user=Depends(get_superuser),
    db: AsyncSession = Depends(get_async_db, scope='function'),
):
    """Block a user (superuser only)."""
    result = await core_api.users.block_async(
        db, None, user_id, reason, actor_user_id=current_user.id
    )
    if not result:
        raise NotFoundException('user')
    return result


@router.post('/{user_id}/unblock', response_model=UserSchema)
async def unblock_user(
    user_id: UUID,
    current_user=Depends(get_superuser),
    db: AsyncSession = Depends(get_async_db, scope='function'),
):
    """Unblock a user (superuser only)."""
    result = await core_api.users.unblock_async(
        db, None, user_id, actor_user_id=current_user.id
    )
    if not result:
        raise NotFoundException('user')
    return result
