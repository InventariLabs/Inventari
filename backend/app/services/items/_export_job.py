"""Exports that outgrew one request.

The sheet of every record of a hundred thousand products takes minutes to
write, longer than a phone or a proxy waits on one request. A sheet above
:data:`INLINE_ROW_LIMIT` records is therefore answered with a job instead:
the workbook is written in the background, stored, and the screen reads the
job (:func:`read_job_async`) until it is done, then fetches the file
(:func:`read_file_async`). A smaller sheet is answered inside the request.

The workbook is written by a process of its own
(:func:`app.services.items.export_service.write_workbook_file`), so the
worker that started the job goes on answering its other requests at their
usual speed: on a thread of the worker the sheet still took the interpreter
from the event loop, and those requests answered several times slower. The
task in the worker follows the process, reports how far it has got and
stores the file. It owns the job's session: the request's closes when the
request ends. The job row is committed before the answer goes out, so the
first read finds it.
"""

from __future__ import annotations

import asyncio
import multiprocessing
import tempfile
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import db_facade, worker_recycle
from app.core.contracts import UserContextDTO
from app.core.exceptions import NotFoundException
from app.core.file_storage.errors import StoredFileNotFoundError
from app.core.file_storage.service import FileStorageService
from app.core.logging import get_logger
from app.core.xlsx_export import XLSX_MEDIA_TYPE
from app.i18n._types import Language
from app.i18n.service import get_current_lang, get_error_message
from app.models.item_export_job import ItemExportJob

logger = get_logger(__name__)

#: Records a sheet may hold and still be written inside its request: a few
#: seconds at the rate the sheet of every record is written, about what a
#: job's process takes to start.
INLINE_ROW_LIMIT = 5_000

#: How long a running job may go without reporting before it is reported as
#: lost. The task reports every :data:`REPORT_EVERY_SECONDS` while it lives.
STALE_AFTER = timedelta(minutes=5)

#: Seconds between two reports of how far the sheet has got.
REPORT_EVERY_SECONDS = 2.0

#: How long a job and its workbook are kept after the job started; the daily
#: table retention deletes them after that.
KEEP_FOR = timedelta(days=1)

#: Tasks the event loop only holds weakly; kept here until they finish.
_running: set[asyncio.Task[None]] = set()

#: The catalogued reasons a job keeps in ``error``; :func:`reader_reason`
#: turns them into the reader's language.
_JOB_FAILED = 'export_job_failed'
_JOB_INTERRUPTED = 'export_job_interrupted'

#: A fresh interpreter for every process: a fork would copy the worker's
#: event loop, its open connections and its threads.
_PROCESSES = multiprocessing.get_context('spawn')

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]

#: The body of the writing process, called with the database URL, the path
#: to write the workbook to and a shared integer to add one to for every
#: record it writes. It must pickle: a module-level
#: function, or a ``functools.partial`` of one over picklable arguments.
WorkbookWriter = Callable[[str, str, Any], None]


async def start_job_async(
    db: AsyncSession, user: UserContextDTO, total: int
) -> ItemExportJob:
    """Record the job. The caller commits it before the task is spawned."""
    assert user.organization_id is not None
    job = ItemExportJob(
        organization_id=user.organization_id, user_id=user.id, total=total
    )
    db.add(job)
    await db.flush()
    return job


def spawn(
    job_id: UUID, session_factory: SessionFactory, write: WorkbookWriter
) -> asyncio.Task[None]:
    """Write the workbook in the background; the job row carries the outcome."""
    task = asyncio.create_task(run_job_async(job_id, session_factory, write))
    _running.add(task)
    worker_recycle.hold_until_done(task)
    task.add_done_callback(_running.discard)
    return task


async def _record_async(db: AsyncSession, job_id: UUID, **values: Any) -> None:
    """Write how far the job has got, or how it ended, and commit it."""
    await db.execute(
        update(ItemExportJob)
        .where(ItemExportJob.id == job_id)
        .values(**values, updated_at=datetime.now(UTC))
    )
    await db.commit()


def file_path_of(job: ItemExportJob) -> str:
    """Where a job's workbook is stored: under its organization, by its id."""
    return f'{job.organization_id}/exports/{job.id}.xlsx'


def _database_url() -> str:
    """The database the worker reads, spelled for a process to connect to it."""
    with db_facade.SessionLocal() as db:
        url: str = db.get_bind().url.render_as_string(hide_password=False)
    return url


async def _write_in_a_process_async(
    db: AsyncSession, job_id: UUID, total: int, write: WorkbookWriter
) -> bytes:
    """Run *write* in a process of its own and return the workbook it wrote.

    The task wakes every :data:`REPORT_EVERY_SECONDS` to write how far the
    process has got, which also keeps the job from reading as lost while the
    sheet is long. A process that ends without a workbook raises.
    """
    steps = _PROCESSES.Value('q', 0, lock=False)
    with tempfile.TemporaryDirectory(prefix='export-') as folder:
        path = str(Path(folder) / 'workbook.xlsx')
        # Daemonic: a worker that stops takes its unfinished export with it,
        # and the job then reads as interrupted.
        writer = _PROCESSES.Process(
            target=write, args=(_database_url(), path, steps), daemon=True
        )
        writer.start()
        while writer.is_alive():
            await asyncio.sleep(REPORT_EVERY_SECONDS)
            await _record_async(db, job_id, processed=min(total, steps.value))
        if writer.exitcode != 0:
            raise RuntimeError(f'the export process ended with {writer.exitcode}')
        return await asyncio.to_thread(Path(path).read_bytes)


async def run_job_async(
    job_id: UUID, session_factory: SessionFactory, write: WorkbookWriter
) -> None:
    """Write the workbook, store it and write what happened onto the job.

    The task owns its session and its transactions: no request is around it
    to commit for it.
    """
    async with session_factory() as db:
        try:
            job = await db.get(ItemExportJob, job_id)
            if job is None:
                raise LookupError(f'export job {job_id} is not in the database')
            total, stored_at = job.total, file_path_of(job)
            workbook = await _write_in_a_process_async(db, job_id, total, write)
            await FileStorageService().save(
                stored_at, BytesIO(workbook), XLSX_MEDIA_TYPE
            )
            outcome: dict[str, Any] = {
                'status': 'done',
                'processed': total,
                'file_path': stored_at,
            }
        except Exception:  # the job is how the failure reaches the screen
            logger.exception('[export] job %s failed', job_id)
            await db.rollback()
            # The traceback is in the log; the screen gets a catalogued
            # reason, never driver or library text.
            outcome = {'status': 'failed', 'error': _JOB_FAILED}
        await _record_async(db, job_id, **outcome)


async def read_job_async(
    db: AsyncSession, user: UserContextDTO, job_id: UUID
) -> ItemExportJob:
    """The job the caller started, with a lost one reported as failed.

    A job nobody is working on any more — its worker was restarted under it —
    would read ``running`` for ever; one that has not moved for
    :data:`STALE_AFTER` is marked failed here, the first time somebody asks
    (the request commits it).
    """
    job = await db.get(ItemExportJob, job_id)
    if (
        job is None
        or job.organization_id != user.organization_id
        or job.user_id != user.id
    ):
        raise NotFoundException('export_job', get_current_lang())
    if job.status == 'running' and datetime.now(UTC) - job.updated_at > STALE_AFTER:
        job.status = 'failed'
        job.error = _JOB_INTERRUPTED
        await db.flush()
    return job


async def read_file_async(
    db: AsyncSession, user: UserContextDTO, job_id: UUID
) -> tuple[BytesIO, datetime]:
    """The workbook of a finished job of the caller's, and when it was asked for.

    A job that is not done has no file yet, and one past :data:`KEEP_FOR`
    has none any more: both are not found.
    """
    job = await read_job_async(db, user, job_id)
    if job.status != 'done' or not job.file_path:
        raise NotFoundException('export_job', get_current_lang())
    try:
        workbook = await FileStorageService().get(job.file_path)
    except StoredFileNotFoundError as exc:
        raise NotFoundException('export_job', get_current_lang()) from exc
    return workbook, job.created_at


def reader_reason(error: str | None, lang: Language | None = None) -> str | None:
    """The job's failure as a sentence in *lang* (the request's by default)."""
    if error in (_JOB_FAILED, _JOB_INTERRUPTED):
        return get_error_message(error, lang or get_current_lang())
    return error
