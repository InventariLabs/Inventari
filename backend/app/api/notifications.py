from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.core.contracts import NotificationDTO, UserContextDTO
from app.core.deps import get_async_db, get_current_user_context
from app.core.exceptions import NotFoundException
from app.core.public_api import core_api
from app.schemas._common import MessageResponse
from app.schemas.notification import NotificationUpdate
from app.schemas.pagination import PaginatedResponse
from app.services.notification_service import NotificationService

router = APIRouter()


@router.get('', response_model=PaginatedResponse[NotificationDTO])
async def get_notifications(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db=Depends(get_async_db, scope='function'),
    unread_only: bool = False,
):
    """One page of the current user's notifications, newest first."""
    notifications, total = await NotificationService.page_for_user_async(
        db, current_user.id, unread_only=unread_only, offset=offset, limit=limit
    )
    return PaginatedResponse.from_slice(notifications, offset, limit, total)


@router.patch('/{notification_id}', response_model=NotificationDTO)
async def update_notification(
    notification_id: UUID,
    notification_in: NotificationUpdate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db=Depends(get_async_db, scope='function'),
):
    """Mark a notification as read/unread."""
    result = await core_api.notifications.update_read_status_async(
        db, notification_id, current_user.id, notification_in.is_read
    )
    if result is None:
        raise NotFoundException('notification')
    return result


@router.post('/read-all', response_model=MessageResponse)
async def mark_all_read(
    current_user: UserContextDTO = Depends(get_current_user_context),
    db=Depends(get_async_db, scope='function'),
):
    """Mark all notifications as read for the current user."""
    await core_api.notifications.mark_all_read_async(db, current_user.id)
    return MessageResponse(message='All notifications marked as read')


@router.delete('/{notification_id}', status_code=status.HTTP_204_NO_CONTENT)
async def delete_notification(
    notification_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db=Depends(get_async_db, scope='function'),
):
    """Delete a specific notification."""
    deleted = await core_api.notifications.delete_async(
        db, notification_id, current_user.id
    )
    if not deleted:
        raise NotFoundException('notification')
    return None
