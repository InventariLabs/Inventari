from fastapi import APIRouter, Depends

from app.api.dependencies import get_superuser
from app.core.deps import get_async_db
from app.services.admin_service import admin_service

router = APIRouter()


@router.get(
    '/stats/summary',
    response_model=dict,
    dependencies=[Depends(get_superuser)],
)
async def get_system_summary(db=Depends(get_async_db, scope='function')):
    """Returns high-level system metrics."""
    return await admin_service.get_system_summary(db)


@router.get(
    '/stats/ai-usage',
    response_model=dict,
    dependencies=[Depends(get_superuser)],
)
async def get_ai_usage_stats(db=Depends(get_async_db, scope='function'), days: int = 7):
    """Returns detailed AI usage statistics per organization."""
    return await admin_service.get_ai_usage_stats(db, days)


@router.get(
    '/stats/activity',
    response_model=dict,
    dependencies=[Depends(get_superuser)],
)
async def get_activity_stats(db=Depends(get_async_db, scope='function'), days: int = 7):
    """Returns activity timeline."""
    return await admin_service.get_activity_stats(db, days)
