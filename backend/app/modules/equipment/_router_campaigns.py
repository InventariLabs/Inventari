from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import SystemPermission, UserContextDTO
from app.core.deps import (
    get_async_db,
    get_current_user_context,
    require_org,
    require_permission,
)
from app.core.exceptions import NotFoundException, ServiceRejectionError
from app.core.module_sdk import PaginatedResponse
from app.i18n.service import SUPPORTED_LANGUAGES, get_current_lang

from .schemas import (
    CampaignCreate,
    CampaignDetail,
    CampaignResponseSchema,
    CampaignSchema,
    CampaignScopeType,
    CampaignStats,
    ReminderRunResult,
    ScopePreview,
)

router = APIRouter()


@router.get('/campaigns/scope-preview', response_model=ScopePreview)
async def scope_preview(
    scope_type: CampaignScopeType = Query(default='ALL'),
    scope_filter_id: UUID | None = Query(default=None),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ITEMS_WRITE),
    org_id: UUID = Depends(require_org),
) -> Any:
    """Count what a scope covers before anything is created."""
    from ._attestation_campaigns import scope_preview_async

    return await scope_preview_async(db, org_id, scope_type, scope_filter_id)


@router.post('/campaigns', response_model=CampaignSchema, status_code=201)
async def create_campaign(
    data: CampaignCreate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ITEMS_WRITE),
    org_id: UUID = Depends(require_org),
) -> Any:
    from .attestation_service import create_campaign as svc_create

    # A past-day refusal is a keyed ServiceRejectionError: the global
    # handler translates it, so the reader gets the sentence in their own
    # language instead of a schema validator's raw English.
    return await svc_create(db, data, org_id, current_user.id)


@router.get('/campaigns', response_model=PaginatedResponse[CampaignSchema])
async def list_campaigns(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> Any:
    from .attestation_service import list_campaigns as svc_list

    campaigns = await svc_list(db, org_id)
    return PaginatedResponse.from_full_list(campaigns, offset=offset, limit=limit)


@router.get('/campaigns/{campaign_id}', response_model=CampaignDetail)
async def get_campaign(
    campaign_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> Any:
    from .attestation_service import get_campaign_detail

    result = await get_campaign_detail(db, campaign_id, org_id)
    if not result:
        raise NotFoundException('campaign', get_current_lang())
    campaign, stats_dict = result
    return CampaignDetail(
        **{c.key: getattr(campaign, c.key) for c in campaign.__table__.columns},
        stats=CampaignStats(**stats_dict),
        responses=[
            CampaignResponseSchema.model_validate(r) for r in campaign.responses
        ],
    )


@router.post('/campaigns/{campaign_id}/launch')
async def launch_campaign(
    campaign_id: UUID,
    lang: str | None = Query(
        default=None,
        description=(
            'BCP-47 root language for the attestation email ('
            + ', '.join(SUPPORTED_LANGUAGES)
            + '). Falls back to the request context language.'
        ),
    ),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ITEMS_WRITE),
    org_id: UUID = Depends(require_org),
) -> Any:
    from app.config import settings

    from .attestation_service import launch_campaign as svc_launch

    resolved_lang = lang if lang in SUPPORTED_LANGUAGES else get_current_lang()
    return await svc_launch(
        db,
        campaign_id,
        org_id,
        str(settings.FRONTEND_URL),
        lang=resolved_lang,
        user_id=current_user.id,
    )


@router.post('/campaigns/{campaign_id}/remind', response_model=ReminderRunResult)
async def send_reminders(
    campaign_id: UUID,
    lang: str | None = Query(
        default=None,
        description=(
            'BCP-47 root language for the reminder email ('
            + ', '.join(SUPPORTED_LANGUAGES)
            + '). Falls back to the request context language.'
        ),
    ),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ITEMS_WRITE),
    org_id: UUID = Depends(require_org),
) -> Any:
    from app.config import settings

    from .attestation_service import send_reminders as svc_remind

    resolved_lang = lang if lang in SUPPORTED_LANGUAGES else get_current_lang()
    return await svc_remind(
        db,
        campaign_id,
        org_id,
        str(settings.FRONTEND_URL),
        lang=resolved_lang,
        user_id=current_user.id,
    )


@router.get('/campaigns/{campaign_id}/responses/{response_id}/link')
async def response_link(
    campaign_id: UUID,
    response_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ITEMS_WRITE),
    org_id: UUID = Depends(require_org),
) -> dict[str, str]:
    """One person's attestation link, to hand over where no e-mail goes.

    Behind the write permission: the link answers on the holder's behalf.
    """
    from app.config import settings

    from ._attestation_campaigns import response_link_async

    url = await response_link_async(
        db, campaign_id, response_id, org_id, str(settings.FRONTEND_URL)
    )
    if url is None:
        raise NotFoundException('attestation', get_current_lang())
    return {'url': url}


@router.post('/campaigns/{campaign_id}/complete', response_model=CampaignSchema)
async def complete_campaign(
    campaign_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ITEMS_WRITE),
    org_id: UUID = Depends(require_org),
) -> Any:
    from .attestation_service import complete_campaign as svc_complete

    return await svc_complete(db, campaign_id, org_id, user_id=current_user.id)


@router.post('/campaigns/{campaign_id}/cancel', response_model=CampaignSchema)
async def cancel_campaign(
    campaign_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ITEMS_WRITE),
    org_id: UUID = Depends(require_org),
) -> Any:
    """Call off a launched campaign, voiding the links already sent."""
    from .attestation_service import cancel_campaign as svc_cancel

    try:
        return await svc_cancel(db, campaign_id, org_id, user_id=current_user.id)
    except ServiceRejectionError as exc:
        raise NotFoundException('campaign', get_current_lang()) from exc


@router.delete('/campaigns/{campaign_id}', status_code=204)
async def delete_campaign(
    campaign_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ITEMS_WRITE),
    org_id: UUID = Depends(require_org),
) -> None:
    """Remove a campaign that was never launched."""
    from .attestation_service import delete_campaign as svc_delete

    try:
        await svc_delete(db, campaign_id, org_id, user_id=current_user.id)
    except ServiceRejectionError as exc:
        raise NotFoundException('campaign', get_current_lang()) from exc
