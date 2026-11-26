# architecture: core_service_direct_db
"""How long the tables that would otherwise only grow keep their rows.

One daily run, one window per kind of row (``docs/SCALING.md`` lists every
growing table and why the others keep everything). Only rows that have finished
their work qualify: an event the relay has not published and mail still on its
way stay however old they are.

The windows apply to the whole installation. These rows are the system's own
bookkeeping, not something an organization decides about, unlike its webhook
log or its archive.
"""

from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import ColumnElement, CursorResult, delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.file_storage.errors import StoredFileNotFoundError
from app.core.file_storage.service import FileStorageService
from app.core.logging import get_logger
from app.models.email_job import EmailJob
from app.models.event_outbox import EventOutbox
from app.models.item_export_job import ItemExportJob
from app.models.item_import_job import ItemImportJob
from app.models.notification import Notification
from app.services.email_jobs import _STATUS_FAILED, _STATUS_SENT
from app.services.items._export_job import KEEP_FOR as EXPORT_KEPT_FOR
from app.services.items._import_job import KEEP_FOR as IMPORT_KEPT_FOR

logger = get_logger(__name__)

_BATCH_SIZE = 5000


def _days_before_now(days: int) -> datetime:
    return datetime.now(UTC) - timedelta(days=days)


async def _delete_in_batches(
    db: AsyncSession, model: Any, *conditions: ColumnElement[bool]
) -> int:
    """Delete the matching rows a slice at a time, each slice committed.

    The first run on an established install meets years of rows, and one
    statement over all of them would be one long transaction. ``SKIP LOCKED``
    keeps two nodes from waiting on each other when the scheduler has no Redis
    lock to hold the tick to one of them; what one of them skips, the next run
    takes.
    """
    deleted = 0
    while True:
        batch = (
            select(model.id)
            .where(*conditions)
            .limit(_BATCH_SIZE)
            .with_for_update(skip_locked=True)
        )
        result = await db.execute(
            delete(model)
            .where(model.id.in_(batch))
            .execution_options(synchronize_session=False)
        )
        await db.commit()
        in_this_batch = result.rowcount if isinstance(result, CursorResult) else 0
        deleted += in_this_batch
        if in_this_batch < _BATCH_SIZE:
            return deleted


async def purge_published_outbox(db: AsyncSession) -> int:
    """Delete outbox rows published before the window.

    A published row has reached the stream and nothing reads it again; the
    window only leaves room to look at what was sent recently.
    """
    cutoff = _days_before_now(settings.EVENT_OUTBOX_RETENTION_DAYS)
    return await _delete_in_batches(db, EventOutbox, EventOutbox.published_at < cutoff)


async def purge_finished_email_jobs(db: AsyncSession) -> int:
    """Delete mail that was sent or gave up, once it is past the window.

    Counted from ``created_at``, the one date every row has. The queue retries
    for minutes, so it is as good as the date the mail finished.
    """
    cutoff = _days_before_now(settings.EMAIL_JOB_RETENTION_DAYS)
    return await _delete_in_batches(
        db,
        EmailJob,
        EmailJob.status.in_((_STATUS_SENT, _STATUS_FAILED)),
        EmailJob.created_at < cutoff,
    )


async def purge_old_notifications(db: AsyncSession) -> int:
    """Delete read notifications past their window, unread ones past a longer one."""
    read_cutoff = _days_before_now(settings.NOTIFICATION_READ_RETENTION_DAYS)
    unread_cutoff = _days_before_now(settings.NOTIFICATION_UNREAD_RETENTION_DAYS)
    return await _delete_in_batches(
        db,
        Notification,
        or_(
            Notification.created_at < unread_cutoff,
            Notification.is_read.is_(True) & (Notification.created_at < read_cutoff),
        ),
    )


async def purge_old_export_jobs(db: AsyncSession) -> int:
    """Delete export jobs a day after they started, each with its workbook.

    A workbook is a copy of an organization's catalogue: it is kept long
    enough to be fetched, not for good. The files go first; one already gone
    (another node took it on the same tick) is no reason to keep the row.
    """
    started_before = datetime.now(UTC) - EXPORT_KEPT_FOR
    paths = await db.scalars(
        select(ItemExportJob.file_path).where(ItemExportJob.created_at < started_before)
    )
    storage = FileStorageService()
    for path in paths.all():
        if path is None:  # the job never finished: there is no file
            continue
        with suppress(StoredFileNotFoundError):
            await storage.delete(path)
    return await _delete_in_batches(
        db, ItemExportJob, ItemExportJob.created_at < started_before
    )


async def purge_old_import_jobs(db: AsyncSession) -> int:
    """Delete import jobs a week after they last moved, each with its answer.

    The age is the last report, not the start: a running import reports every
    batch, so a job that has been still for the whole window is finished, or
    belongs to a worker that is gone and still reads "running".
    """
    still_since = datetime.now(UTC) - IMPORT_KEPT_FOR
    return await _delete_in_batches(
        db, ItemImportJob, ItemImportJob.updated_at < still_since
    )


_PURGES: tuple[tuple[str, Callable[[AsyncSession], Awaitable[int]]], ...] = (
    ('event_outbox', purge_published_outbox),
    ('email_jobs', purge_finished_email_jobs),
    ('notifications', purge_old_notifications),
    ('item_export_jobs', purge_old_export_jobs),
    ('item_import_jobs', purge_old_import_jobs),
)


async def run_table_retention_once() -> None:
    """Scheduled-task entry point: trim each table on a session of its own.

    A table that fails is logged and waits for tomorrow's run; the others are
    still trimmed today.
    """
    from app.core import db_facade

    if db_facade.AsyncSessionLocal is None:
        return
    for table, purge in _PURGES:
        async with db_facade.AsyncSessionLocal() as db:
            try:
                deleted = await purge(db)
                if deleted:
                    logger.info('[table-retention] %s: deleted %d', table, deleted)
            except Exception:  # worker loop must never crash
                logger.exception('[table-retention] %s failed', table)
                await db.rollback()
