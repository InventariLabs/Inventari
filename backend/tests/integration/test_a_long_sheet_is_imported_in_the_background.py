"""A sheet too long for one request is imported by a job the screen follows.

Every row goes through the door the form uses, at 60–70 ms a row, so ten
thousand rows held one request for ten minutes — longer than a browser or a
proxy waits. Past ``INLINE_ROW_LIMIT`` rows the endpoint answers at once with
a job, the rows are imported by a task that owns its session, and the job
says how far it has got and how it ended. A short sheet is still answered
with its result.
"""

import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.core.exceptions import NotFoundException
from app.models.item import Item
from app.models.item_import_job import ItemImportJob
from app.models.storage_location import StorageLocation
from app.services.items import _import_job as import_jobs

pytestmark = pytest.mark.integration

MAPPING = {'name': 'Name', 'quantity': 'Quantity', 'location': 'Location'}


def _csv(count: int, location: str) -> bytes:
    return (
        pd.DataFrame(
            [
                {'Name': f'Long sheet {n}', 'Quantity': n, 'Location': location}
                for n in range(1, count + 1)
            ]
        )
        .to_csv(index=False)
        .encode()
    )


class TestTheEndpointAnswersWithAJobPastTheLimit:
    def test_a_long_sheet_is_answered_with_a_job_and_a_short_one_with_its_result(
        self,
        client: TestClient,
        auth_headers: dict,
        test_storage_location: StorageLocation,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        spawned: list[dict] = []
        monkeypatch.setattr(import_jobs, 'INLINE_ROW_LIMIT', 3)
        monkeypatch.setattr(
            import_jobs, 'spawn', lambda job_id, factory, **kw: spawned.append(kw)
        )

        def _post(count: int):
            return client.post(
                '/api/v1/items/import',
                files={
                    'file': (
                        'stock.csv',
                        _csv(count, test_storage_location.name),
                        'text/csv',
                    )
                },
                data={
                    'mapping_json': json.dumps(MAPPING),
                    'create_missing_locations': 'false',
                    'create_missing_categories': 'false',
                },
                headers=auth_headers,
            )

        short = _post(3)
        assert short.status_code == 200, short.text
        assert short.json()['imported'] == 3
        assert spawned == []

        long = _post(4)
        assert long.status_code == 202, long.text
        job = long.json()
        assert (job['status'], job['total'], job['processed']) == ('running', 4, 0)
        assert len(spawned) == 1, 'the rows are imported by the task, not the request'

        read = client.get(
            f'/api/v1/items/import/jobs/{job["id"]}', headers=auth_headers
        )
        assert read.status_code == 200, read.text
        assert read.json()['status'] == 'running'


def _factory(db: AsyncSession):
    """A session factory that hands the test's own session to the task."""

    @asynccontextmanager
    async def _open():
        yield db

    return _open


class TestTheTaskImportsAndReportsHowItEnded:
    async def test_the_job_ends_done_with_the_synchronous_answer(
        self,
        real_async_db_session: AsyncSession,
        async_test_user,
        async_test_storage_location,
    ) -> None:
        db = real_async_db_session
        user = UserContextDTO(
            id=async_test_user.id, organization_id=async_test_user.organization_id
        )
        job = await import_jobs.start_job_async(db, user, 'stock.csv', 120)
        await db.commit()  # the endpoint commits before the task starts
        assert job.status == 'running'

        await import_jobs.run_job_async(
            job.id,
            _factory(db),
            file_content=_csv(120, async_test_storage_location.name),
            filename='stock.csv',
            mapping=MAPPING,
            user=user,
            create_missing_locations=False,
            create_missing_categories=False,
            on_label_match='add',
        )

        await db.refresh(job)
        assert job.status == 'done'
        assert job.processed == 120
        assert job.result is not None
        assert (job.result['total'], job.result['imported']) == (120, 120)
        imported = await db.scalars(
            select(Item).where(
                Item.organization_id == user.organization_id,
                Item.name.like('Long sheet %'),
            )
        )
        assert len(imported.all()) == 120

    async def test_a_sheet_the_task_cannot_read_ends_failed_with_the_reason(
        self,
        real_async_db_session: AsyncSession,
        async_test_user,
    ) -> None:
        db = real_async_db_session
        user = UserContextDTO(
            id=async_test_user.id, organization_id=async_test_user.organization_id
        )
        job = await import_jobs.start_job_async(db, user, 'broken.xlsx', 1)
        await db.commit()  # the endpoint commits before the task starts

        await import_jobs.run_job_async(
            job.id,
            _factory(db),
            file_content=b'not a workbook',
            filename='broken.xlsx',
            mapping=MAPPING,
            user=user,
            create_missing_locations=False,
            create_missing_categories=False,
            on_label_match='add',
        )

        await db.refresh(job)
        assert job.status == 'failed'
        assert 'could not be read as a spreadsheet' in (job.error or '')

    async def test_an_unexpected_failure_keeps_no_driver_text_for_the_screen(
        self,
        real_async_db_session: AsyncSession,
        async_test_user,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        db = real_async_db_session
        user = UserContextDTO(
            id=async_test_user.id, organization_id=async_test_user.organization_id
        )
        job = await import_jobs.start_job_async(db, user, 'odd.csv', 1)
        await db.commit()

        async def _break(**_: object) -> None:
            raise RuntimeError('INSERT INTO items (...) VALUES (:secret)')

        monkeypatch.setattr(import_jobs, 'import_items', _break)
        await import_jobs.run_job_async(
            job.id,
            _factory(db),
            file_content=b'',
            filename='odd.csv',
            mapping=MAPPING,
            user=user,
            create_missing_locations=False,
            create_missing_categories=False,
            on_label_match='add',
        )

        await db.refresh(job)
        assert job.status == 'failed'
        # the job holds a catalogued reason, translated when it is read
        assert job.error == 'import_job_failed'


class TestAJobIsReadByWhoStartedIt:
    async def test_another_user_of_the_organization_cannot_read_it(
        self,
        real_async_db_session: AsyncSession,
        async_test_user,
        async_test_user2,
    ) -> None:
        db = real_async_db_session
        owner = UserContextDTO(
            id=async_test_user.id, organization_id=async_test_user.organization_id
        )
        job = await import_jobs.start_job_async(db, owner, 'stock.csv', 5)

        assert (await import_jobs.read_job_async(db, owner, job.id)).id == job.id
        stranger = UserContextDTO(
            id=async_test_user2.id, organization_id=async_test_user.organization_id
        )
        with pytest.raises(NotFoundException):
            await import_jobs.read_job_async(db, stranger, job.id)

    async def test_a_job_nobody_is_working_on_reads_failed(
        self,
        real_async_db_session: AsyncSession,
        async_test_user,
    ) -> None:
        db = real_async_db_session
        owner = UserContextDTO(
            id=async_test_user.id, organization_id=async_test_user.organization_id
        )
        job = await import_jobs.start_job_async(db, owner, 'stock.csv', 5)
        await db.execute(
            update(ItemImportJob)
            .where(ItemImportJob.id == job.id)
            .values(
                updated_at=datetime.now(UTC) - import_jobs.STALE_AFTER * 2,
            )
        )
        await db.commit()
        await db.refresh(job)

        read = await import_jobs.read_job_async(db, owner, job.id)

        assert read.status == 'failed'
        assert read.error == 'import_job_interrupted'
        assert import_jobs.reader_reason(read.error, 'pl') == (
            'Import został przerwany, zanim się zakończył.'
        )
        assert import_jobs.reader_reason(read.error, 'en') == (
            'The import was interrupted before it finished.'
        )
        # a sentence the job already holds is not a key: it passes untouched
        assert import_jobs.reader_reason('Could not resolve', 'pl') == (
            'Could not resolve'
        )

    async def test_a_job_that_moved_lately_is_still_running(
        self,
        real_async_db_session: AsyncSession,
        async_test_user,
    ) -> None:
        db = real_async_db_session
        owner = UserContextDTO(
            id=async_test_user.id, organization_id=async_test_user.organization_id
        )
        job = await import_jobs.start_job_async(db, owner, 'stock.csv', 5)
        await db.execute(
            update(ItemImportJob)
            .where(ItemImportJob.id == job.id)
            .values(updated_at=datetime.now(UTC) - timedelta(seconds=30))
        )
        await db.commit()
        await db.refresh(job)

        assert (await import_jobs.read_job_async(db, owner, job.id)).status == 'running'
