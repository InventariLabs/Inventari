"""Imports that outgrew one request.

Every row of a sheet goes through the door the form uses, so an import costs
tens of milliseconds a row and a sheet of ten thousand takes minutes — far
longer than a browser or a proxy waits on one request. A sheet above
:data:`INLINE_ROW_LIMIT` rows is therefore answered with a job instead: the
rows are imported by a task that outlives the request, and the screen reads
the job (:func:`read_job_async`) until it is done. A smaller sheet is
imported inside the request and answered with its result, as before.

The task owns its session: the request's closes when the request ends. The
job row is committed before the answer goes out, so the first read finds it.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import worker_recycle
from app.core.contracts import UserContextDTO
from app.core.exceptions import NotFoundException, ServiceRejectionError
from app.core.logging import get_logger
from app.i18n._types import Language
from app.i18n.service import get_current_lang, get_error_message
from app.models.item_import_job import ItemImportJob

from ._import import LabelMatch, import_items

logger = get_logger(__name__)

#: Rows an import may have and still be answered inside its request. At the
#: measured 60–70 ms a row this is about fifteen seconds.
INLINE_ROW_LIMIT = 200

#: How long a running job may go without committing a batch before it is
#: reported as lost. A batch is fifty rows, a few seconds.
STALE_AFTER = timedelta(minutes=5)

#: Tasks the event loop only holds weakly; kept here until they finish.
_running: set[asyncio.Task[None]] = set()

#: The catalogued reasons a job keeps in ``error`` when it holds no sentence of
#: its own; :func:`reader_reason` turns them into the reader's language.
_JOB_FAILED = 'import_job_failed'
_JOB_INTERRUPTED = 'import_job_interrupted'

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


async def start_job_async(
    db: AsyncSession, user: UserContextDTO, filename: str, total: int
) -> ItemImportJob:
    """Record the job. The caller commits it before the task is spawned."""
    assert user.organization_id is not None
    job = ItemImportJob(
        organization_id=user.organization_id,
        user_id=user.id,
        filename=filename[:255],
        total=total,
    )
    db.add(job)
    await db.flush()
    return job


def spawn(
    job_id: UUID,
    session_factory: SessionFactory,
    **import_arguments: Any,
) -> asyncio.Task[None]:
    """Run the import in the background; the job row carries the outcome."""
    task = asyncio.create_task(
        run_job_async(job_id, session_factory, **import_arguments)
    )
    _running.add(task)
    worker_recycle.hold_until_done(task)
    task.add_done_callback(_running.discard)
    return task


async def _record_progress_async(db: AsyncSession, job_id: UUID, **values: Any) -> None:
    """Write what the job has done so far and commit it, for the screen to read.

    The commit also carries the rows the import wrote since the last report:
    the import itself never commits, and the job owns its session.
    """
    await db.execute(
        update(ItemImportJob)
        .where(ItemImportJob.id == job_id)
        .values(**values, updated_at=datetime.now(UTC))
    )
    await db.commit()


async def run_job_async(
    job_id: UUID,
    session_factory: SessionFactory,
    *,
    file_content: bytes,
    filename: str,
    mapping: dict,
    user: UserContextDTO,
    create_missing_locations: bool,
    create_missing_categories: bool,
    on_label_match: LabelMatch,
) -> None:
    """Import the sheet and write what happened onto the job.

    The task owns its session and its transactions: no request is around it
    to commit for it.
    """
    async with session_factory() as db:
        try:
            result = await import_items(
                db=db,
                file_content=file_content,
                filename=filename,
                mapping=mapping,
                user=user,
                create_missing_locations=create_missing_locations,
                create_missing_categories=create_missing_categories,
                on_label_match=on_label_match,
                on_batch=lambda processed: _record_progress_async(
                    db, job_id, processed=processed
                ),
            )
            outcome: dict[str, Any] = {
                'status': 'done',
                'processed': result['total'],
                'result': result,
            }
        except Exception as exc:  # the job is how the failure reaches the screen
            logger.exception('[import] job %s failed', job_id)
            await db.rollback()
            # Only a refusal is written for the reader; any other exception
            # carries driver or parser text, which the log has and the screen
            # must not (the traceback is logged above).
            reason = (
                str(exc)[:2000]
                if isinstance(exc, ServiceRejectionError)
                else _JOB_FAILED
            )
            outcome = {'status': 'failed', 'error': reason}
        await _record_progress_async(db, job_id, **outcome)


async def read_job_async(
    db: AsyncSession, user: UserContextDTO, job_id: UUID
) -> ItemImportJob:
    """The job the caller started, with a lost one reported as failed.

    A job nobody is working on any more — its worker was restarted under it —
    would read ``running`` for ever; one that has not moved for
    :data:`STALE_AFTER` is marked failed here, the first time somebody asks (the request commits it).
    """
    job = await db.get(ItemImportJob, job_id)
    if (
        job is None
        or job.organization_id != user.organization_id
        or job.user_id != user.id
    ):
        raise NotFoundException('import_job', get_current_lang())
    if job.status == 'running' and datetime.now(UTC) - job.updated_at > STALE_AFTER:
        job.status = 'failed'
        job.error = _JOB_INTERRUPTED
        await db.flush()
    return job


def reader_reason(error: str | None, lang: Language | None = None) -> str | None:
    """The job's failure as a sentence in *lang* (the request's by default).

    The job holds either a refusal's sentence, written in the language of the
    request that started it, or the key of a catalogued reason, which only
    the read knows the language for.
    """
    if error in (_JOB_FAILED, _JOB_INTERRUPTED):
        return get_error_message(error, lang or get_current_lang())
    return error
