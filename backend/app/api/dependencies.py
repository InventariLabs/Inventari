from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import SystemPermission, UserContextDTO
from app.core.deps import get_async_db
from app.core.exceptions import ForbiddenException
from app.core.public_api import core_api
from app.i18n.service import get_current_lang, get_error_message
from app.services.identity_service import get_current_user, get_current_user_context


def _check_admin(current_user: UserContextDTO) -> None:
    """Allow the built-in admin level or any custom role holding admin:access.

    A role name is not an authority — an organization that carved a
       custom administration role expects its holder to reach the same org-admin
       endpoints the ``admin`` enum level reaches. API-key contexts keep being
       refused: their permission set does not contain admin:access.
    """
    if current_user.role == 'admin':
        return
    if current_user.has_permission(SystemPermission.ADMIN_ACCESS):
        return
    raise ForbiddenException(
        get_error_message('admin_permissions_required', get_current_lang())
    )


async def get_current_admin_user(
    current_user: UserContextDTO = Depends(get_current_user_context),
) -> UserContextDTO:
    """Ensures the current user may act as an organization administrator.

    Delegates the check to ``_check_admin`` — which accepts the built-in
    ``admin`` level and any custom role holding ``admin:access`` —
    but keeps returning the user, so call sites that depend on this for the
    ``UserContextDTO`` keep working.
    """
    _check_admin(current_user)
    return current_user


async def get_superuser(
    current_user=Depends(get_current_user),
) -> object:
    """Ensures the current user is a system-wide superuser."""
    if not current_user.is_superuser:
        raise ForbiddenException(
            get_error_message('superuser_required', get_current_lang())
        )
    return current_user


async def get_user_storage_ids(
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> list[UUID]:
    """Dependency to get storage IDs for the current user."""
    if not current_user.organization_id:
        return []
    return await core_api.locations.list_storage_ids_async(
        db, current_user.organization_id
    )
