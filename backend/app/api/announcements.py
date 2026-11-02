from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.dependencies import get_superuser
from app.core.contracts import AnnouncementCreateDTO, AnnouncementDTO, UserContextDTO
from app.core.deps import get_async_db, get_current_user_context
from app.core.public_api import core_api
from app.schemas.pagination import PaginatedResponse

router = APIRouter()


@router.get('', response_model=PaginatedResponse[AnnouncementDTO])
async def get_all_announcements(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db=Depends(get_async_db, scope='function'),
    _superuser=Depends(get_superuser),
):
    """Superuser-only: Fetch all announcements (active, expired, and future)."""
    announcements = await core_api.announcements.list_all_async(db)
    return PaginatedResponse.from_full_list(announcements, offset=offset, limit=limit)


@router.get('/active', response_model=PaginatedResponse[AnnouncementDTO])
async def get_active_announcements(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db=Depends(get_async_db, scope='function'),
    current_user: UserContextDTO = Depends(get_current_user_context),
):
    """Fetch all currently active global announcements."""
    announcements = await core_api.announcements.list_active_async(db)
    return PaginatedResponse.from_full_list(announcements, offset=offset, limit=limit)


@router.post('', response_model=AnnouncementDTO, status_code=status.HTTP_201_CREATED)
async def create_announcement(
    announcement_in: AnnouncementCreateDTO,
    db=Depends(get_async_db, scope='function'),
    current_user: UserContextDTO = Depends(get_current_user_context),
    _superuser=Depends(get_superuser),
):
    """Superuser-only: Create a new installation-wide announcement.

    Announcements carry no ``organization_id`` — one row is read by every
    organisation on the installation. An organisation admin writing one would
    be writing into their neighbours' shell, so the write belongs to whoever
    owns the installation, not to whoever owns a tenant.
    """
    return await core_api.announcements.create_async(db, announcement_in, current_user)


@router.delete('/{announcement_id}', status_code=status.HTTP_204_NO_CONTENT)
async def delete_announcement(
    announcement_id: UUID,
    db=Depends(get_async_db, scope='function'),
    _superuser=Depends(get_superuser),
):
    """Superuser-only: Delete an announcement."""
    deleted = await core_api.announcements.delete_async(db, announcement_id)
    if not deleted:
        from app.core.exceptions import NotFoundException

        raise NotFoundException('announcement')
    return None
