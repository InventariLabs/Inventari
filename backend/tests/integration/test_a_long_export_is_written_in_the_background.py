"""A sheet too long for one request is written by a job the screen follows.

The sheet of every record of a hundred thousand products takes minutes to
write. Past ``INLINE_ROW_LIMIT`` records the endpoint answers at once with a
job; a process of its own writes the workbook, the job says how far it has
got, and the finished file is fetched from the job. A short sheet is still
answered with the workbook, written while the worker goes on answering its
other requests. A job and its file are deleted a day after the job started.
"""

import asyncio
import sys
import threading
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from functools import partial
from io import BytesIO

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.contracts import UserContextDTO
from app.core.exceptions import NotFoundException
from app.core.file_storage.service import FileStorageService
from app.core.xlsx_export import XLSX_MEDIA_TYPE
from app.models.item import Item
from app.models.item_export_job import ItemExportJob
from app.models.user import User
from app.services import table_retention
from app.services.items import _export_job as export_jobs
from app.services.items import export_service

pytestmark = pytest.mark.integration

EXPORT = '/api/v1/items/export/xlsx'


def _factory(db: AsyncSession):
    """A session factory that hands the test's own session to the task."""

    @asynccontextmanager
    async def _open():
        yield db

    return _open


def _user(account) -> UserContextDTO:
    return UserContextDTO(id=account.id, organization_id=account.organization_id)


class TestTheEndpointAnswersWithAJobPastTheLimit:
    def test_a_long_sheet_is_answered_with_a_job_and_a_short_one_with_the_workbook(
        self,
        client: TestClient,
        auth_headers: dict,
        test_items_batch: list[Item],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        spawned: list[object] = []
        monkeypatch.setattr(export_jobs, 'INLINE_ROW_LIMIT', 4)
        monkeypatch.setattr(
            export_jobs, 'spawn', lambda job_id, factory, write: spawned.append(write)
        )

        short = client.get(EXPORT, params={'search': 'Product 1'}, headers=auth_headers)
        assert short.status_code == 200, short.text
        assert short.headers['content-type'] == XLSX_MEDIA_TYPE
        assert list(pd.read_excel(BytesIO(short.content))['Name']) == ['Product 1']
        assert spawned == []

        long = client.get(EXPORT, headers=auth_headers)
        assert long.status_code == 202, long.text
        job = long.json()
        assert (job['status'], job['total'], job['processed']) == ('running', 5, 0)
        assert len(spawned) == 1, 'the workbook is written by the job, not the request'

        read = client.get(
            f'/api/v1/items/export/jobs/{job["id"]}', headers=auth_headers
        )
        assert read.status_code == 200, read.text
        assert read.json()['status'] == 'running'
        unfinished = client.get(
            f'/api/v1/items/export/jobs/{job["id"]}/file', headers=auth_headers
        )
        assert unfinished.status_code == 404, 'a running job has no file yet'


class TestTheFileIsTheAskersAlone:
    def test_the_finished_file_is_served_to_the_asker_and_to_nobody_else(
        self,
        client: TestClient,
        db_session: Session,
        auth_headers: dict,
        auth_headers_user2: dict,
        test_user: User,
    ) -> None:
        job = ItemExportJob(
            organization_id=test_user.organization_id,
            user_id=test_user.id,
            status='done',
            total=1,
            processed=1,
        )
        db_session.add(job)
        db_session.flush()
        job.file_path = export_jobs.file_path_of(job)
        db_session.commit()
        asyncio.run(
            FileStorageService().save(
                job.file_path, BytesIO(b'the workbook'), XLSX_MEDIA_TYPE
            )
        )
        address = f'/api/v1/items/export/jobs/{job.id}'

        mine = client.get(f'{address}/file', headers=auth_headers)
        assert mine.status_code == 200, mine.text
        assert mine.content == b'the workbook'
        assert 'inventari_export_' in mine.headers['content-disposition']

        # Same organization, another person: the sheet may cover only the
        # locations its asker can see.
        for path in (address, f'{address}/file'):
            theirs = client.get(path, headers=auth_headers_user2)
            assert theirs.status_code == 404, theirs.text


class TestTheJobWritesTheWorkbookInAProcessOfItsOwn:
    @pytest.fixture(autouse=True)
    def _look_often(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The task looks at the process every 50 ms instead of every 2 s."""
        monkeypatch.setattr(export_jobs, 'REPORT_EVERY_SECONDS', 0.05)

    async def test_the_job_ends_done_and_its_file_holds_the_sheet(
        self,
        real_async_db_session: AsyncSession,
        async_test_user,
        async_test_item,
    ) -> None:
        db = real_async_db_session
        user = _user(async_test_user)
        job = await export_jobs.start_job_async(db, user, 1)
        await db.commit()  # the endpoint commits before the task starts

        await export_jobs.run_job_async(
            job.id,
            _factory(db),
            partial(export_service.write_workbook_file, user, {}, {}, None),
        )

        await db.refresh(job)
        assert (job.status, job.processed, job.error) == ('done', 1, None)
        assert job.file_path == export_jobs.file_path_of(job)
        workbook, _ = await export_jobs.read_file_async(db, user, job.id)
        sheet = pd.read_excel(workbook, sheet_name='Inventory')
        assert list(sheet['Name']) == [async_test_item.name]

    async def test_a_process_that_ends_without_a_workbook_ends_the_job_failed(
        self,
        real_async_db_session: AsyncSession,
        async_test_user,
    ) -> None:
        db = real_async_db_session
        user = _user(async_test_user)
        job = await export_jobs.start_job_async(db, user, 1)
        await db.commit()

        # A builtin, so the process starts without loading the application:
        # called with the URL, the path and the counter, it raises at once.
        await export_jobs.run_job_async(job.id, _factory(db), partial(sys.exit, 3))

        await db.refresh(job)
        assert (job.status, job.file_path) == ('failed', None)
        assert (
            export_jobs.reader_reason(job.error, 'en')
            == 'The export stopped because of an unexpected error.'
        )

    async def test_a_job_nobody_works_on_any_more_reads_as_interrupted(
        self,
        real_async_db_session: AsyncSession,
        async_test_user,
    ) -> None:
        db = real_async_db_session
        user = _user(async_test_user)
        job = await export_jobs.start_job_async(db, user, 10)
        await db.execute(
            update(ItemExportJob)
            .where(ItemExportJob.id == job.id)
            .values(updated_at=datetime.now(UTC) - timedelta(minutes=10))
        )
        await db.refresh(job)

        read = await export_jobs.read_job_async(db, user, job.id)

        assert read.status == 'failed'
        assert (
            export_jobs.reader_reason(read.error, 'en')
            == 'The export was interrupted before it finished.'
        )
        with pytest.raises(NotFoundException):
            await export_jobs.read_file_async(db, user, job.id)


class TestTheWorkerAnswersWhileTheSheetIsWritten:
    async def test_another_request_is_answered_while_a_sheet_is_written(
        self,
        real_async_client: AsyncClient,
        auth_headers: dict,
        test_items_batch: list[Item],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The sheet waits for another request of the same worker to be answered.

        Written on the event loop, the sheet would hold the loop while it
        waits, the other request would never be answered, and the wait would
        run out.
        """
        writing, answered = threading.Event(), threading.Event()
        reading = export_service._iter_items

        def _held(*args, **kwargs):
            writing.set()
            assert answered.wait(timeout=10), 'no request was answered meanwhile'
            yield from reading(*args, **kwargs)

        monkeypatch.setattr(export_service, '_iter_items', _held)

        async def _another_request():
            while not writing.is_set():
                await asyncio.sleep(0.01)
            listed = await real_async_client.get(
                '/api/v1/items', params={'limit': 1}, headers=auth_headers
            )
            answered.set()
            return listed

        exported, listed = await asyncio.gather(
            real_async_client.get(EXPORT, headers=auth_headers), _another_request()
        )

        assert listed.status_code == 200, listed.text
        assert exported.status_code == 200, exported.text
        assert len(pd.read_excel(BytesIO(exported.content))) == len(test_items_batch)


class TestAJobIsKeptForADay:
    async def test_the_retention_deletes_a_day_old_job_with_its_file(
        self,
        real_async_db_session: AsyncSession,
        async_test_user,
    ) -> None:
        db = real_async_db_session
        user = _user(async_test_user)
        storage = FileStorageService()
        old = await export_jobs.start_job_async(db, user, 1)
        young = await export_jobs.start_job_async(db, user, 1)
        for job in (old, young):
            job.status, job.file_path = 'done', export_jobs.file_path_of(job)
            await storage.save(job.file_path, BytesIO(b'sheet'), XLSX_MEDIA_TYPE)
        old.created_at = datetime.now(UTC) - timedelta(days=1, minutes=1)
        await db.commit()

        deleted = await table_retention.purge_old_export_jobs(db)

        assert deleted == 1
        left = await db.scalars(
            select(ItemExportJob.id).where(
                ItemExportJob.organization_id == user.organization_id
            )
        )
        assert list(left) == [young.id]
        assert not await storage.exists(export_jobs.file_path_of(old))
        assert await storage.exists(export_jobs.file_path_of(young))
