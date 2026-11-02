from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.core.deps import get_async_db, get_current_user_context
from app.core.exceptions import NotFoundException
from app.core.logging import get_logger
from app.schemas.user import (
    Language as LanguageSchema,
)
from app.schemas.user import (
    User as UserSchema,
)
from app.schemas.user import (
    UserUpdate,
)
from app.services.auth_service import AuthService

logger = get_logger(__name__)

router = APIRouter()


@router.get('/me', response_model=UserSchema)
async def get_me(
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
):
    """Fetches currently logged in user's profile, with their permissions.

    The permission set is what makes frontend gating possible at all: without
    it ``useHasPermission`` had nothing to check and fell back to "admin or
    nothing", so every non-admin saw a UI gated purely by role.

    Admins are sent the full catalog rather than their (usually empty) grants,
    matching the backend bypass in ``UserContextDTO.has_permission`` — a UI
    that hid actions the API would happily perform would be lying.
    """
    try:
        profile = await AuthService.get_profile_async(db, current_user.id)
    except ValueError as exc:
        raise NotFoundException('user') from exc

    result = UserSchema.model_validate(profile)
    result.permissions = _visible_permissions(current_user)
    return result


def _visible_permissions(user: UserContextDTO) -> list[str]:
    """Every permission key the caller effectively holds, sorted."""
    if user.role == 'admin':
        from app.core._registry_class import module_registry

        return sorted(module_registry.get_all_permissions())

    keys = {str(p.value) for p in user.permissions} | set(user.extra_permissions)
    return sorted(keys)


@router.patch('/me', response_model=UserSchema)
async def update_me(
    user_update: UserUpdate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
):
    """Update current user's profile."""
    update_data = user_update.model_dump(exclude_unset=True)
    try:
        return await AuthService.update_user_profile_async(
            db, current_user.id, update_data
        )
    except ValueError as exc:
        raise NotFoundException('user') from exc


class LanguageUpdate(BaseModel):
    """Schema for updating user language preference."""

    language: LanguageSchema


@router.post('/me/language', response_model=UserSchema)
async def update_my_language(
    language_update: LanguageUpdate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
):
    """Update current user's preferred language."""
    try:
        return await AuthService.update_user_profile_async(
            db, current_user.id, {'preferred_language': language_update.language}
        )
    except ValueError as exc:
        raise NotFoundException('user') from exc
