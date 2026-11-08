"""Startup-time self-healing for superuser promotion and org ``short_id`` backfill.

This lives in Core, not in a hosting module, so that every self-hosted
instance gets:

- backfill of ``short_id`` on organizations missing one
- promotion of the configured ``SUPERUSER_EMAIL`` user (or first user) to superuser

This is a Core concern (self-hosting), not a SaaS concern.

Non-fatal: any error is logged and the transaction is rolled back so
that startup never crashes the app.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.logging import get_logger
from app.services._org_reads import list_missing_short_id
from app.services._org_writes import generate_short_id
from app.services.user_service import UserService

logger = get_logger(__name__)


async def run_startup_bootstrap_async(db: AsyncSession | None = None) -> None:
    """Run startup self-healing.

    Opens its own ``AsyncSession`` when *db* is ``None`` (caller does not
    supply one — used from ``_lifespan.py``). When *db* is supplied the
    caller owns the commit (used by tests).

    Idempotent: safe to call on every startup.
    """
    if db is not None:
        await _bootstrap_inner(db)
        return

    # Late import: ``AsyncSessionLocal`` is created inside lifespan; importing
    # at module load would bind to the import-time event loop.
    from app.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:  # type: ignore[misc]
        try:
            await _bootstrap_inner(session)
            await session.commit()
        except Exception as exc:  # noqa: BLE001 — startup must not crash
            logger.warning('[Bootstrap] failed (non-fatal): %s', exc)
            await session.rollback()


async def _bootstrap_inner(db: AsyncSession) -> None:
    """Inner bootstrap logic — caller owns the transaction."""
    from sqlalchemy.exc import ProgrammingError

    try:
        organizations = await list_missing_short_id(db)
        if organizations:
            logger.info(
                '[Bootstrap] found %d organizations without short_id — backfilling',
                len(organizations),
            )
            for org in organizations:
                org.short_id = generate_short_id()
            await db.flush()

        if settings.INVENTARI_DEMO:
            # The shared demo account is an organization admin by design; a
            # startup promotion would hand every visitor instance-wide powers.
            pass
        elif settings.SUPERUSER_EMAIL:
            # Bootstrap runs before any organization context exists.
            owner = await UserService.get_user_by_email_async(
                db, settings.SUPERUSER_EMAIL
            )
            if owner and not owner.is_superuser:
                logger.info(
                    '[Bootstrap] promoting configured user %s to superuser',
                    owner.email,
                )
                await UserService.promote_superuser_async(db, owner.id)
        else:
            first_user = await UserService.get_first_by_created_at_async(db, None)
            if first_user and not first_user.is_superuser:
                logger.info(
                    '[Bootstrap] promoting first system user %s to superuser',
                    first_user.email,
                )
                await UserService.promote_superuser_async(db, first_user.id)
    except ProgrammingError as exc:
        # Schema not ready yet (e.g. Alembic mid-migration on first boot).
        logger.warning(
            '[Bootstrap] skipped — database schema might not be ready yet: %s', exc
        )
        raise
