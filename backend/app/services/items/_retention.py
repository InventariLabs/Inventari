"""Archive retention — periodic purge of long-archived items.

Organizations opt in via ``settings['archive_retention_days']`` (integer,
``null``/missing = disabled). The retention run purges archived items older
than the cutoff through the exact same path as manual purge — the
blockers, the org flag and the immutable audit entry all apply, with
``reason='RETENTION'`` and a null user (system). Blocked items are reported
and left alone; they are re-evaluated on the next run, never retried in a
loop within one run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.interceptors import InterceptorError
from app.core.logging import get_logger
from app.models.item import Item
from app.models.organization import Organization
from app.services.items._lifecycle import (
    _org_allows_permanent_delete,
    purge_item,
)

logger = get_logger(__name__)


@dataclass
class RetentionReport:
    """Outcome of one retention run — logged, never acted upon automatically."""

    purged: int = 0
    blocked: list[dict[str, Any]] = field(default_factory=list)
    skipped_orgs: list[dict[str, Any]] = field(default_factory=list)


async def run_archive_retention(
    db: AsyncSession, *, now: datetime | None = None
) -> RetentionReport:
    """Purge archived items past each org's retention window.

       Each purge runs in a savepoint, so one that fails takes back only its
       own writes and never the earlier ones; the caller commits the run.
       Blocked items (interceptor veto, validation
    error) are recorded in the report; the org flag from disables
       retention for the whole org, mirroring the manual path.
    """
    now = now or datetime.now(UTC)
    report = RetentionReport()

    orgs = (await db.scalars(select(Organization))).all()
    # What the run needs from each org is copied out before the first purge: a
    # savepoint that rolls back expires what it touched, so reading
    # `org.settings` after one could lazy-load on the async session and raise
    # MissingGreenlet.
    org_plan = [(org.id, dict(org.settings or {})) for org in orgs]
    for org_id, settings_dict in org_plan:
        days = settings_dict.get('archive_retention_days')
        if not isinstance(days, int) or days <= 0:
            continue

        if not await _org_allows_permanent_delete(db, org_id):
            report.skipped_orgs.append(
                {
                    'organization_id': str(org_id),
                    'reason': 'permanent_delete_disabled',
                }
            )
            continue

        cutoff = now - timedelta(days=days)
        items = (
            await db.scalars(
                select(Item).where(
                    Item.organization_id == org_id,
                    Item.is_deleted.is_(True),
                    Item.deleted_at.isnot(None),
                    Item.deleted_at <= cutoff,
                )
            )
        ).all()
        # Ids first for the same reason: after a rollback only a value that
        # never lived on the ORM is safe to read, and `get` refreshes an
        # expired instance — on the happy path the identity map answers with
        # the row the select above already loaded.
        item_ids = [item.id for item in items]

        for item_id in item_ids:
            try:
                item = await db.get(Item, item_id)
                if item is None:
                    continue
                # System purge: no user context — the audit entry carries
                # reason=RETENTION and a null user_id.
                async with db.begin_nested():
                    await purge_item(db, item, None, reason='RETENTION')
                report.purged += 1
            except InterceptorError as exc:
                blocks = (exc.details or {}).get('blocks') or []
                report.blocked.append(
                    {
                        'item_id': str(item_id),
                        'types': [b.get('type') for b in blocks if isinstance(b, dict)],
                        'message': exc.message,
                    }
                )
            except PermissionError as exc:
                # Org flag flipped mid-run — stop processing this org.
                report.skipped_orgs.append(
                    {
                        'organization_id': str(org_id),
                        'reason': str(exc),
                    }
                )
                break
            except ValueError as exc:
                report.blocked.append(
                    {
                        'item_id': str(item_id),
                        'type': 'validation',
                        'message': str(exc),
                    }
                )
            except Exception:  # one bad row must not sink the run
                logger.exception(
                    '[archive-retention] purge failed for item %s', item_id
                )
                report.blocked.append(
                    {
                        'item_id': str(item_id),
                        'type': 'error',
                        'message': 'Unexpected error — see logs',
                    }
                )

    return report


async def run_archive_retention_once() -> None:
    """Scheduled-task entry point: open a session and run one retention pass."""
    from app.core import db_facade

    if db_facade.AsyncSessionLocal is None:
        return
    async with db_facade.AsyncSessionLocal() as db:
        try:
            report = await run_archive_retention(db)
            await db.commit()
            logger.info(
                '[archive-retention] purged=%d blocked=%d skipped_orgs=%d',
                report.purged,
                len(report.blocked),
                len(report.skipped_orgs),
            )
            if report.blocked:
                logger.warning('[archive-retention] blocked items: %s', report.blocked)
        except Exception:  # worker loop must never crash
            logger.exception('[archive-retention] run failed')
            await db.rollback()
