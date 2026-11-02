"""Scheduler workers — auto-expire tokens + send scheduled reminders."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.i18n.service import SUPPORTED_LANGUAGES
from app.modules.equipment.models import AuditCampaign, AuditResponse

from ._attestation_campaigns import send_reminders

logger = get_logger(__name__)


async def run_scheduled_reminder_check_async(db: AsyncSession) -> None:
    """Async: called periodically by the task scheduler.

    1. Expires tokens past deadline.
    2. Sends reminders for campaigns where deadline is within reminder_days_before.
    """
    now = datetime.now(UTC)

    expired_result = await db.execute(
        update(AuditResponse)
        .where(
            AuditResponse.status == 'PENDING',
            AuditResponse.token_expires_at < now,
        )
        .values(status='EXPIRED')
    )
    expired_count = expired_result.rowcount or 0  # type: ignore[attr-defined]
    if expired_count:
        logger.info('[attestation] Expired %d responses', expired_count)

    active_campaigns = (
        await db.scalars(select(AuditCampaign).where(AuditCampaign.status == 'ACTIVE'))
    ).all()
    for campaign in active_campaigns:
        days_to_deadline = (campaign.deadline - now).days
        if days_to_deadline > campaign.reminder_days_before:
            continue
        if campaign.last_reminder_sent_at and (
            now - campaign.last_reminder_sent_at
        ) < timedelta(hours=20):
            continue

        from app.config import settings
        from app.core.public_api import core_api

        frontend_url = getattr(settings, 'FRONTEND_URL', 'http://localhost:5173')
        # Resolve the language for the reminder email from the campaign
        # creator's ``preferred_language``. Falls back to English if the user
        # cannot be fetched or their language is unsupported.
        lang = 'en'
        try:
            creator = await core_api.users.get_full_async(
                db, campaign.organization_id, campaign.created_by
            )
            if creator is not None:
                preferred = getattr(creator, 'preferred_language', None)
                if preferred in SUPPORTED_LANGUAGES:
                    lang = preferred
        except Exception:  # noqa: BLE001 — never crash the worker
            logger.warning(
                '[attestation] Could not resolve creator lang for campaign %s; '
                'defaulting to %s',
                campaign.id,
                lang,
            )
        try:
            result = await send_reminders(
                db,
                campaign.id,
                campaign.organization_id,
                frontend_url,
                lang=lang,
            )
            logger.info(
                '[attestation] Auto-reminder: sent %d emails for campaign %s',
                result['reminders_sent'],
                campaign.id,
            )
        except Exception:  # worker loop must never crash
            logger.exception(
                '[attestation] Failed auto-reminder for campaign %s', campaign.id
            )

    await db.commit()


async def run_attestation_reminder_self_contained() -> None:
    """Self-contained async worker — creates its own AsyncSession."""
    from app.core import db_facade

    if db_facade.AsyncSessionLocal is None:
        logger.warning(
            '[equipment] AsyncSessionLocal not initialized; skipping attestation reminder'
        )
        return
    async with db_facade.AsyncSessionLocal() as db:
        await run_scheduled_reminder_check_async(db)
