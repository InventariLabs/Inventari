"""The print queue end to end: the app queues, the agent claims, prints, reports.

The promise under test is the one the old webhook mode broke: the labels
somebody chose are the labels that print, and they count as printed only when
the printer says so — a jam leaves them unprinted and the job can go again.
"""

import io
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi import status
from httpx import AsyncClient
from PIL import Image
from sqlalchemy import inspect, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.testing import ModuleTestHelper
from app.models.label_pool import LabelPool
from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.printing.models import PrintJob
from app.modules.printing.schemas import PROTOCOL_VERSION
from app.services.token_service import create_access_token

_PNG_MAGIC = b'\x89PNG\r\n\x1a\n'
_BASE = '/api/v1/printing'
_TAPE = {'printer_type': 'brother-p710bt'}


def _row_id(row: object) -> UUID:
    """A row's primary key without loading it: safe on a row another check expired."""
    state = inspect(row)
    assert state is not None
    identity = state.identity
    assert identity is not None
    return UUID(str(identity[0]))


def _auth(user: User) -> dict[str, str]:
    user_id = _row_id(user)
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user_id)})}'
    }


async def _org(db: AsyncSession, name: str) -> Organization:
    org = Organization(
        name=name, enabled_modules=['core', 'items', 'locations', 'printing']
    )
    db.add(org)
    await db.commit()
    await db.refresh(org)
    return org


async def _user(db: AsyncSession, org: Organization) -> User:
    user = await ModuleTestHelper.create_user_async(
        db, org, email=f'queue_{uuid4().hex[:8]}@test.com'
    )
    await db.commit()
    return user


async def _labels(
    db: AsyncSession, org: Organization, user: User, count: int, prefix: str
) -> list[LabelPool]:
    rows = [
        LabelPool(
            short_code=f'{prefix}-{i:04d}', organization_id=org.id, created_by=user.id
        )
        for i in range(count)
    ]
    db.add_all(rows)
    await db.commit()
    for row in rows:
        await db.refresh(row)
    return rows


async def _register(client: AsyncClient, user: User, name: str = 'office') -> str:
    response = await client.post(
        f'{_BASE}/agent/register',
        json={
            'name': name,
            **_TAPE,
            'agent_version': '1.0.0',
            'protocol_version': PROTOCOL_VERSION,
        },
        headers=_auth(user),
    )
    assert response.status_code == status.HTTP_200_OK, response.text
    return str(response.json()['id'])


async def _printed_codes(db: AsyncSession, labels: list[LabelPool]) -> set[str]:
    # Not ``lbl.id``: a second call finds the rows expired by the first, and
    # reading an attribute would load it lazily.
    ids = [_row_id(lbl) for lbl in labels]
    db.expire_all()
    rows = (await db.execute(select(LabelPool).where(LabelPool.id.in_(ids)))).scalars()
    return {row.short_code for row in rows if row.printed_at is not None}


@pytest.fixture
async def org(real_async_db_session: AsyncSession) -> Organization:
    return await _org(real_async_db_session, 'Queue Org')


@pytest.fixture
async def user(real_async_db_session: AsyncSession, org: Organization) -> User:
    return await _user(real_async_db_session, org)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_viewer_cannot_act_as_a_print_agent(
    real_async_client: AsyncClient,
    real_async_db_session: AsyncSession,
    org: Organization,
) -> None:
    viewer = await ModuleTestHelper.create_user_async(
        real_async_db_session, org, email='queue_viewer@test.com', role='viewer'
    )
    await real_async_db_session.commit()
    agent_id, job_id = uuid4(), uuid4()
    headers = _auth(viewer)
    responses = [
        await real_async_client.post(
            f'{_BASE}/agent/register',
            json={'name': 'viewer', **_TAPE, 'protocol_version': PROTOCOL_VERSION},
            headers=headers,
        ),
        await real_async_client.post(
            f'{_BASE}/agent/{agent_id}/claim', headers=headers
        ),
        await real_async_client.get(
            f'{_BASE}/agent/jobs/{job_id}/image', headers=headers
        ),
        await real_async_client.post(
            f'{_BASE}/agent/jobs/{job_id}/report',
            json={'agent_id': str(agent_id), 'attempt': 1, 'printed': True},
            headers=headers,
        ),
    ]
    assert [response.status_code for response in responses] == [
        status.HTTP_403_FORBIDDEN
    ] * 4


@pytest.mark.integration
@pytest.mark.asyncio
class TestTheJobLifeCycle:
    async def test_the_chosen_labels_print_and_only_they_count_as_printed(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        org: Organization,
        user: User,
    ) -> None:
        pool = await _labels(real_async_db_session, org, user, 4, 'PICK')
        chosen = [pool[1], pool[3]]
        agent_id = await _register(real_async_client, user)

        queued = await real_async_client.post(
            f'{_BASE}/jobs',
            json={'label_ids': [str(lbl.id) for lbl in chosen]},
            headers=_auth(user),
        )
        assert queued.status_code == status.HTTP_201_CREATED, queued.text
        job = queued.json()
        assert job['status'] == 'queued'
        assert job['agent_id'] == agent_id
        assert job['short_codes'] == ['PICK-0001', 'PICK-0003']

        claim = await real_async_client.post(
            f'{_BASE}/agent/{agent_id}/claim', headers=_auth(user)
        )
        assert claim.status_code == status.HTTP_200_OK
        assert claim.json()['id'] == job['id']
        assert claim.json()['count'] == 2

        image = await real_async_client.get(
            f'{_BASE}/agent/jobs/{job["id"]}/image', headers=_auth(user)
        )
        assert image.status_code == status.HTTP_200_OK
        assert image.content.startswith(_PNG_MAGIC)
        # Fetching the image spends nothing: only the report does.
        assert await _printed_codes(real_async_db_session, pool) == set()

        report = await real_async_client.post(
            f'{_BASE}/agent/jobs/{job["id"]}/report',
            json={'agent_id': agent_id, 'attempt': 1, 'printed': True},
            headers=_auth(user),
        )
        assert report.status_code == status.HTTP_200_OK
        assert report.json()['status'] == 'printed'
        assert await _printed_codes(real_async_db_session, pool) == {
            'PICK-0001',
            'PICK-0003',
        }

    async def test_a_claimed_job_is_not_handed_out_twice(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        org: Organization,
        user: User,
    ) -> None:
        pool = await _labels(real_async_db_session, org, user, 1, 'ONCE')
        office = await _register(real_async_client, user, 'office')
        garage = await _register(real_async_client, user, 'garage')
        await real_async_client.post(
            f'{_BASE}/jobs',
            json={'agent_id': office, 'label_ids': [str(pool[0].id)]},
            headers=_auth(user),
        )

        first = await real_async_client.post(
            f'{_BASE}/agent/{office}/claim', headers=_auth(user)
        )
        again = await real_async_client.post(
            f'{_BASE}/agent/{office}/claim', headers=_auth(user)
        )
        other = await real_async_client.post(
            f'{_BASE}/agent/{garage}/claim', headers=_auth(user)
        )

        assert first.status_code == status.HTTP_200_OK
        assert again.status_code == status.HTTP_204_NO_CONTENT
        assert other.status_code == status.HTTP_204_NO_CONTENT

    async def test_a_failed_print_leaves_the_labels_unprinted_and_can_go_again(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        org: Organization,
        user: User,
    ) -> None:
        pool = await _labels(real_async_db_session, org, user, 2, 'JAM')
        agent_id = await _register(real_async_client, user)
        job = (
            await real_async_client.post(
                f'{_BASE}/jobs',
                json={'short_codes': ['JAM-0000', 'JAM-0001']},
                headers=_auth(user),
            )
        ).json()
        await real_async_client.post(
            f'{_BASE}/agent/{agent_id}/claim', headers=_auth(user)
        )

        failed = await real_async_client.post(
            f'{_BASE}/agent/jobs/{job["id"]}/report',
            json={
                'agent_id': agent_id,
                'attempt': 1,
                'printed': False,
                'error': 'tape jammed',
            },
            headers=_auth(user),
        )
        assert failed.json()['status'] == 'failed'
        assert failed.json()['error'] == 'tape jammed'
        assert await _printed_codes(real_async_db_session, pool) == set()

        retried = await real_async_client.post(
            f'{_BASE}/jobs/{job["id"]}/retry', headers=_auth(user)
        )
        assert retried.json()['status'] == 'queued'
        claim = await real_async_client.post(
            f'{_BASE}/agent/{agent_id}/claim', headers=_auth(user)
        )
        assert claim.json()['id'] == job['id']
        listed = await real_async_client.get(f'{_BASE}/jobs', headers=_auth(user))
        assert listed.json()['items'][0]['attempts'] == 2

    async def test_the_jobs_are_paged_newest_first_with_their_total(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        org: Organization,
        user: User,
    ) -> None:
        pool = await _labels(real_async_db_session, org, user, 3, 'PAGE')
        await _register(real_async_client, user)
        queued = []
        for label in pool:
            response = await real_async_client.post(
                f'{_BASE}/jobs',
                json={'label_ids': [str(label.id)]},
                headers=_auth(user),
            )
            assert response.status_code == status.HTTP_201_CREATED, response.text
            queued.append(response.json()['id'])

        first = await real_async_client.get(
            f'{_BASE}/jobs', headers=_auth(user), params={'limit': 2}
        )
        rest = await real_async_client.get(
            f'{_BASE}/jobs', headers=_auth(user), params={'limit': 2, 'offset': 2}
        )

        assert first.json()['total'] == rest.json()['total'] == 3
        assert first.json()['has_more'] is True
        assert rest.json()['has_more'] is False
        paged = [job['id'] for job in first.json()['items'] + rest.json()['items']]
        assert sorted(paged) == sorted(queued)

    async def test_only_a_failed_job_can_be_sent_again(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        org: Organization,
        user: User,
    ) -> None:
        pool = await _labels(real_async_db_session, org, user, 1, 'WAIT')
        await _register(real_async_client, user)
        job = (
            await real_async_client.post(
                f'{_BASE}/jobs',
                json={'label_ids': [str(pool[0].id)]},
                headers=_auth(user),
            )
        ).json()

        response = await real_async_client.post(
            f'{_BASE}/jobs/{job["id"]}/retry', headers=_auth(user)
        )

        assert response.status_code == status.HTTP_409_CONFLICT
        assert response.json()['detail']['code'] == 'PRINT_JOB_NOT_RETRYABLE'

    async def test_an_expired_lease_puts_the_job_back_in_line(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        org: Organization,
        user: User,
    ) -> None:
        pool = await _labels(real_async_db_session, org, user, 1, 'LOST')
        agent_id = await _register(real_async_client, user)
        job = (
            await real_async_client.post(
                f'{_BASE}/jobs',
                json={'label_ids': [str(pool[0].id)]},
                headers=_auth(user),
            )
        ).json()
        await real_async_client.post(
            f'{_BASE}/agent/{agent_id}/claim', headers=_auth(user)
        )
        await real_async_db_session.execute(
            update(PrintJob)
            .where(PrintJob.id == job['id'])
            .values(lease_until=datetime.now(UTC) - timedelta(seconds=1))
        )
        await real_async_db_session.commit()

        reclaim = await real_async_client.post(
            f'{_BASE}/agent/{agent_id}/claim', headers=_auth(user)
        )

        assert reclaim.status_code == status.HTTP_200_OK
        assert reclaim.json()['id'] == job['id']
        assert reclaim.json()['attempt'] == 2

    async def test_a_claim_handed_out_again_cannot_be_answered_by_the_old_one(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        org: Organization,
        user: User,
    ) -> None:
        # The agent stalls past its lease, restarts under the same name and
        # claims the job again; the stalled process then wakes and reports.
        pool = await _labels(real_async_db_session, org, user, 1, 'LATE')
        agent_id = await _register(real_async_client, user)
        job = (
            await real_async_client.post(
                f'{_BASE}/jobs',
                json={'label_ids': [str(pool[0].id)]},
                headers=_auth(user),
            )
        ).json()
        first = await real_async_client.post(
            f'{_BASE}/agent/{agent_id}/claim', headers=_auth(user)
        )
        await real_async_db_session.execute(
            update(PrintJob)
            .where(PrintJob.id == job['id'])
            .values(lease_until=datetime.now(UTC) - timedelta(seconds=1))
        )
        await real_async_db_session.commit()
        assert await _register(real_async_client, user) == agent_id
        second = await real_async_client.post(
            f'{_BASE}/agent/{agent_id}/claim', headers=_auth(user)
        )

        stale = await real_async_client.post(
            f'{_BASE}/agent/jobs/{job["id"]}/report',
            json={
                'agent_id': agent_id,
                'attempt': first.json()['attempt'],
                'printed': False,
                'error': 'woke up late',
            },
            headers=_auth(user),
        )
        current = await real_async_client.post(
            f'{_BASE}/agent/jobs/{job["id"]}/report',
            json={
                'agent_id': agent_id,
                'attempt': second.json()['attempt'],
                'printed': True,
            },
            headers=_auth(user),
        )

        assert stale.status_code == status.HTTP_409_CONFLICT
        assert stale.json()['detail']['code'] == 'PRINT_JOB_NOT_CLAIMED'
        assert current.status_code == status.HTTP_200_OK, current.text
        assert current.json()['status'] == 'printed'
        assert await _printed_codes(real_async_db_session, pool) == {'LATE-0000'}

    async def test_only_the_claimant_reports(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        org: Organization,
        user: User,
    ) -> None:
        pool = await _labels(real_async_db_session, org, user, 1, 'MINE')
        office = await _register(real_async_client, user, 'office')
        garage = await _register(real_async_client, user, 'garage')
        job = (
            await real_async_client.post(
                f'{_BASE}/jobs',
                json={'agent_id': office, 'label_ids': [str(pool[0].id)]},
                headers=_auth(user),
            )
        ).json()
        await real_async_client.post(
            f'{_BASE}/agent/{office}/claim', headers=_auth(user)
        )

        response = await real_async_client.post(
            f'{_BASE}/agent/jobs/{job["id"]}/report',
            json={'agent_id': garage, 'attempt': 1, 'printed': True},
            headers=_auth(user),
        )

        assert response.status_code == status.HTTP_409_CONFLICT
        assert await _printed_codes(real_async_db_session, pool) == set()


@pytest.mark.integration
@pytest.mark.asyncio
class TestChoosingThePrinter:
    async def test_without_a_printer_there_is_nowhere_to_send(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        org: Organization,
        user: User,
    ) -> None:
        pool = await _labels(real_async_db_session, org, user, 1, 'NONE')

        response = await real_async_client.post(
            f'{_BASE}/jobs',
            json={'label_ids': [str(pool[0].id)]},
            headers=_auth(user),
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()['detail']['code'] == 'PRINT_NO_AGENT'

    async def test_with_several_printers_one_has_to_be_chosen(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        org: Organization,
        user: User,
    ) -> None:
        pool = await _labels(real_async_db_session, org, user, 1, 'TWO')
        await _register(real_async_client, user, 'office')
        await _register(real_async_client, user, 'garage')

        response = await real_async_client.post(
            f'{_BASE}/jobs',
            json={'label_ids': [str(pool[0].id)]},
            headers=_auth(user),
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()['detail']['code'] == 'PRINT_CHOOSE_AGENT'

    async def test_a_registered_agent_is_listed_online(
        self, real_async_client: AsyncClient, user: User
    ) -> None:
        await _register(real_async_client, user, 'office')
        await _register(real_async_client, user, 'office')  # a restart

        agents = (
            await real_async_client.get(f'{_BASE}/agents', headers=_auth(user))
        ).json()['items']

        assert [(a['name'], a['online'], a['printer_type']) for a in agents] == [
            ('office', True, 'brother-p710bt')
        ]

    async def test_a_storage_label_keeps_its_caption_rule(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        org: Organization,
        user: User,
    ) -> None:
        shelf = StorageLocation(
            name='Pantry shelf',
            short_code=f'LOC-{uuid4().hex[:6]}',
            organization_id=org.id,
            created_by=user.id,
            settings={'label_show_description': False},
        )
        real_async_db_session.add(shelf)
        await real_async_db_session.commit()
        agent_id = await _register(real_async_client, user)

        job = (
            await real_async_client.post(
                f'{_BASE}/jobs',
                json={'location_ids': [str(shelf.id)]},
                headers=_auth(user),
            )
        ).json()
        stored = await real_async_db_session.get(PrintJob, job['id'])
        await real_async_client.post(
            f'{_BASE}/agent/{agent_id}/claim', headers=_auth(user)
        )
        image = await real_async_client.get(
            f'{_BASE}/agent/jobs/{job["id"]}/image', headers=_auth(user)
        )

        assert stored is not None
        assert stored.labels[0]['caption'] is None
        assert stored.labels[0]['qr_only'] is True
        assert image.content.startswith(_PNG_MAGIC)

    async def test_the_download_options_travel_with_the_job(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        org: Organization,
        user: User,
    ) -> None:
        pool = await _labels(real_async_db_session, org, user, 2, 'OPT')
        await _register(real_async_client, user)
        ids = [str(lbl.id) for lbl in pool]

        captioned = (
            await real_async_client.post(
                f'{_BASE}/jobs',
                json={'label_ids': ids, 'caption': 'Spices', 'copies': 2},
                headers=_auth(user),
            )
        ).json()
        bare = (
            await real_async_client.post(
                f'{_BASE}/jobs',
                json={'label_ids': ids, 'caption': 'ignored', 'qr_only': True},
                headers=_auth(user),
            )
        ).json()

        first = await real_async_db_session.get(PrintJob, captioned['id'])
        second = await real_async_db_session.get(PrintJob, bare['id'])
        assert first is not None and second is not None
        assert captioned['count'] == 4
        assert [e['short_code'] for e in first.labels] == [
            'OPT-0000',
            'OPT-0000',
            'OPT-0001',
            'OPT-0001',
        ]
        assert {e['caption'] for e in first.labels} == {'Spices'}
        assert [(e['caption'], e['qr_only']) for e in second.labels] == [
            (None, True),
            (None, True),
        ]

    async def test_one_kind_of_target_per_job(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        org: Organization,
        user: User,
    ) -> None:
        pool = await _labels(real_async_db_session, org, user, 1, 'MIX')
        await _register(real_async_client, user)

        response = await real_async_client.post(
            f'{_BASE}/jobs',
            json={'label_ids': [str(pool[0].id)], 'short_codes': ['MIX-0000']},
            headers=_auth(user),
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.integration
@pytest.mark.asyncio
class TestTheHandshakeCarriesTheVersions:
    """What the agent says about itself at registration, and what comes back.

    An agent sits on a machine nobody here controls, so the one chance to tell
    an old one from a new one is the handshake: it names the protocol it
    speaks, the server records it, and a protocol the server does not speak is
    refused in words the agent prints.
    """

    async def test_a_registration_carries_and_records_the_versions(
        self, real_async_client: AsyncClient, user: User
    ) -> None:
        response = await real_async_client.post(
            f'{_BASE}/agent/register',
            json={
                'name': 'office',
                **_TAPE,
                'agent_version': '1.2.3',
                'protocol_version': PROTOCOL_VERSION,
            },
            headers=_auth(user),
        )

        assert response.status_code == status.HTTP_200_OK, response.text
        assert (
            response.json()['agent_version'],
            response.json()['protocol_version'],
        ) == ('1.2.3', PROTOCOL_VERSION)
        agents = (
            await real_async_client.get(f'{_BASE}/agents', headers=_auth(user))
        ).json()['items']
        assert [
            (a['name'], a['agent_version'], a['protocol_version']) for a in agents
        ] == [('office', '1.2.3', PROTOCOL_VERSION)]

    async def test_the_response_names_the_protocol_the_server_speaks(
        self, real_async_client: AsyncClient, user: User
    ) -> None:
        response = await real_async_client.post(
            f'{_BASE}/agent/register',
            json={
                'name': 'office',
                **_TAPE,
                'agent_version': '1.2.3',
                'protocol_version': PROTOCOL_VERSION,
            },
            headers=_auth(user),
        )

        assert response.json()['server_protocol_version'] == PROTOCOL_VERSION

    async def test_a_protocol_the_server_does_not_speak_is_refused(
        self, real_async_client: AsyncClient, user: User
    ) -> None:
        response = await real_async_client.post(
            f'{_BASE}/agent/register',
            json={
                'name': 'office',
                **_TAPE,
                'agent_version': '1.2.3',
                'protocol_version': PROTOCOL_VERSION + 1,
            },
            headers=_auth(user),
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()['detail']['code'] == 'PRINT_AGENT_PROTOCOL_UNSUPPORTED'
        # The refusal says what this server speaks, in the agent's own log.
        assert str(PROTOCOL_VERSION) in response.json()['detail']['message']
        assert (
            await real_async_client.get(f'{_BASE}/agents', headers=_auth(user))
        ).json()['items'] == []

    async def test_an_agent_that_names_no_protocol_is_refused(
        self, real_async_client: AsyncClient, user: User
    ) -> None:
        response = await real_async_client.post(
            f'{_BASE}/agent/register',
            json={'name': 'office', **_TAPE, 'agent_version': '1.0.0'},
            headers=_auth(user),
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()['detail']['code'] == 'PRINT_AGENT_PROTOCOL_MISSING'
        assert (
            await real_async_client.get(f'{_BASE}/agents', headers=_auth(user))
        ).json()['items'] == []

    async def test_the_registration_is_logged_with_its_versions(
        self,
        real_async_client: AsyncClient,
        user: User,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        with caplog.at_level('INFO'):
            await real_async_client.post(
                f'{_BASE}/agent/register',
                json={
                    'name': 'office',
                    **_TAPE,
                    'agent_version': '1.2.3',
                    'protocol_version': PROTOCOL_VERSION,
                },
                headers=_auth(user),
            )

        logged = [
            r.getMessage() for r in caplog.records if 'protocol' in r.getMessage()
        ]
        assert any('1.2.3' in message for message in logged)
        assert any(str(PROTOCOL_VERSION) in message for message in logged)


@pytest.mark.integration
@pytest.mark.asyncio
class TestTheJobCarriesItsLabelSize:
    """One label file for every printer, at the size the person chose.

    A printer used to carry a media profile and a label size, and a job
    printed at those: the preview showed one label and the printer made
    another. The size now travels with the job and the printer adds nothing;
    fitting the file to the printer is its agent's job.
    """

    async def test_the_printed_image_is_the_preview_at_the_jobs_size(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        org: Organization,
        user: User,
    ) -> None:
        pool = await _labels(real_async_db_session, org, user, 2, 'SAME')
        agent_id = await _register(real_async_client, user)
        ids = [str(lbl.id) for lbl in pool]
        job = (
            await real_async_client.post(
                f'{_BASE}/jobs',
                json={
                    'label_ids': ids,
                    'qr_only': True,
                    'show_code': True,
                    'width_mm': 40.0,
                    'height_mm': 30.0,
                },
                headers=_auth(user),
            )
        ).json()
        claim = await real_async_client.post(
            f'{_BASE}/agent/{agent_id}/claim', headers=_auth(user)
        )

        printed = await real_async_client.get(
            f'{_BASE}/agent/jobs/{job["id"]}/image', headers=_auth(user)
        )
        preview = await real_async_client.get(
            '/api/v1/labels/pool/export/png',
            params={
                'label_ids': ids,
                'count': 2,
                'width': 40.0,
                'height': 30.0,
                'qr_only': True,
                'show_code': True,
                'mark_printed': False,
            },
            headers=_auth(user),
        )

        assert (job['width_mm'], job['height_mm']) == (40.0, 30.0)
        assert (claim.json()['width_mm'], claim.json()['height_mm']) == (40.0, 30.0)
        assert preview.status_code == status.HTTP_200_OK, preview.text
        assert printed.status_code == status.HTTP_200_OK, printed.text
        assert printed.content == preview.content

    async def test_a_size_finer_than_a_tenth_prints_as_previewed(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        org: Organization,
        user: User,
    ) -> None:
        """A width typed as 50.06 is queued as 50.06, not 50.1.

        Stored to a tenth, the job drew a label 592 px wide from a preview
        591 px wide: the same 300 dpi, a different file.
        """
        pool = await _labels(real_async_db_session, org, user, 1, 'FINE')
        agent_id = await _register(real_async_client, user)
        ids = [str(pool[0].id)]
        job = (
            await real_async_client.post(
                f'{_BASE}/jobs',
                json={'label_ids': ids, 'width_mm': 50.06, 'height_mm': 24.0},
                headers=_auth(user),
            )
        ).json()
        claim = await real_async_client.post(
            f'{_BASE}/agent/{agent_id}/claim', headers=_auth(user)
        )

        printed = await real_async_client.get(
            f'{_BASE}/agent/jobs/{job["id"]}/image', headers=_auth(user)
        )
        preview = await real_async_client.get(
            '/api/v1/labels/pool/export/png',
            params={
                'label_ids': ids,
                'width': 50.06,
                'height': 24.0,
                'mark_printed': False,
            },
            headers=_auth(user),
        )

        assert job['width_mm'] == 50.06
        assert claim.json()['width_mm'] == 50.06
        assert Image.open(io.BytesIO(printed.content)).size == (591, 283)
        assert printed.content == preview.content

    async def test_a_job_sent_without_a_size_has_the_default_label_size(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        org: Organization,
        user: User,
    ) -> None:
        """A 50 x 24 label, 591 x 283 px at 300 dpi, not cropped to its square."""
        pool = await _labels(real_async_db_session, org, user, 1, 'DEFAULT')
        agent_id = await _register(real_async_client, user)
        job = (
            await real_async_client.post(
                f'{_BASE}/jobs',
                json={'label_ids': [str(pool[0].id)], 'qr_only': True},
                headers=_auth(user),
            )
        ).json()
        await real_async_client.post(
            f'{_BASE}/agent/{agent_id}/claim', headers=_auth(user)
        )

        image = await real_async_client.get(
            f'{_BASE}/agent/jobs/{job["id"]}/image', headers=_auth(user)
        )

        assert (job['width_mm'], job['height_mm']) == (50.0, 24.0)
        assert Image.open(io.BytesIO(image.content)).size == (591, 283)

    async def test_the_agent_gets_the_same_label_at_its_printers_raster(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        org: Organization,
        user: User,
    ) -> None:
        """A 180 dpi head printing 128 dots across, sent a 50 x 24 label.

        It gets the label drawn at 180 dpi and scaled to the 128 dots it can
        print — the same layout as the download, not that file resampled.
        """
        pool = await _labels(real_async_db_session, org, user, 1, 'RASTER')
        agent_id = await _register(real_async_client, user)
        job = (
            await real_async_client.post(
                f'{_BASE}/jobs',
                json={'label_ids': [str(pool[0].id)], 'qr_only': True},
                headers=_auth(user),
            )
        ).json()
        await real_async_client.post(
            f'{_BASE}/agent/{agent_id}/claim', headers=_auth(user)
        )

        image = await real_async_client.get(
            f'{_BASE}/agent/jobs/{job["id"]}/image',
            params={'dpi': 180, 'max_height_px': 128},
            headers=_auth(user),
        )
        export = await real_async_client.get(
            '/api/v1/labels/pool/export/png',
            params={
                'label_ids': [str(pool[0].id)],
                'qr_only': True,
                'dpi': 180,
                'max_height_px': 128,
                'mark_printed': False,
            },
            headers=_auth(user),
        )

        assert image.status_code == status.HTTP_200_OK, image.text
        png = Image.open(io.BytesIO(image.content))
        assert png.size == (267, 128)
        # It prints at the shrunk size: 18 mm on the tape, not 24 mm again.
        assert png.info['dpi'] == pytest.approx((180, 180), abs=0.5)
        assert export.content == image.content

    async def test_one_label_of_a_job_is_served_by_its_place_in_it(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        org: Organization,
        user: User,
    ) -> None:
        """A printer that cuts after each label asks for them one at a time.

        Each is the label the strip holds at that place, drawn as the
        download draws that label alone; the strip is still the answer when
        no place is named, and a place past the end is refused.
        """
        pool = await _labels(real_async_db_session, org, user, 3, 'APART')
        agent_id = await _register(real_async_client, user)
        job = (
            await real_async_client.post(
                f'{_BASE}/jobs',
                json={
                    'label_ids': [str(label.id) for label in pool],
                    'qr_only': True,
                },
                headers=_auth(user),
            )
        ).json()
        await real_async_client.post(
            f'{_BASE}/agent/{agent_id}/claim', headers=_auth(user)
        )
        url = f'{_BASE}/agent/jobs/{job["id"]}/image'

        strip = await real_async_client.get(url, headers=_auth(user))
        singles = [
            await real_async_client.get(
                url, params={'index': place}, headers=_auth(user)
            )
            for place in range(3)
        ]
        alone = [
            await real_async_client.get(
                '/api/v1/labels/pool/export/png',
                params={
                    'label_ids': [str(label.id)],
                    'qr_only': True,
                    'mark_printed': False,
                },
                headers=_auth(user),
            )
            for label in pool
        ]
        past_the_end = await real_async_client.get(
            url, params={'index': 3}, headers=_auth(user)
        )

        assert [single.status_code for single in singles] == [status.HTTP_200_OK] * 3
        assert [single.content for single in singles] == [one.content for one in alone]
        assert len({single.content for single in singles}) == 3
        # The strip is still every label side by side.
        assert (
            Image.open(io.BytesIO(strip.content)).size[0]
            > Image.open(io.BytesIO(singles[0].content)).size[0]
        )
        assert past_the_end.status_code == status.HTTP_404_NOT_FOUND

    async def test_a_tape_printer_gets_a_bare_square_as_tall_as_its_band(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        org: Organization,
        user: User,
    ) -> None:
        """A P-touch says its tape leaves white edges of its own.

        The bare square then takes all 128 dots across, at a whole number of
        dots a module, and the job image and the export agree on it.
        """
        import qrcode

        from app.config import settings
        from app.core.scan_links import scan_url

        pool = await _labels(real_async_db_session, org, user, 1, 'EDGE')
        agent_id = await _register(real_async_client, user)
        job = (
            await real_async_client.post(
                f'{_BASE}/jobs',
                json={'label_ids': [str(pool[0].id)], 'qr_only': True},
                headers=_auth(user),
            )
        ).json()
        await real_async_client.post(
            f'{_BASE}/agent/{agent_id}/claim', headers=_auth(user)
        )
        raster = {'dpi': 180, 'max_height_px': 128, 'edge_to_edge': True}

        image = await real_async_client.get(
            f'{_BASE}/agent/jobs/{job["id"]}/image', params=raster, headers=_auth(user)
        )
        export = await real_async_client.get(
            '/api/v1/labels/pool/export/png',
            params={
                'label_ids': [str(pool[0].id)],
                'qr_only': True,
                'mark_printed': False,
                **raster,
            },
            headers=_auth(user),
        )

        assert image.status_code == status.HTTP_200_OK, image.text
        qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M)
        qr.add_data(scan_url(pool[0].short_code, settings.FRONTEND_URL))
        qr.make(fit=True)
        side = qr.modules_count * (128 // qr.modules_count)
        dark = Image.eval(
            Image.open(io.BytesIO(image.content)).convert('L'),
            lambda v: 255 if v < 128 else 0,
        ).getbbox()
        assert dark is not None
        assert (dark[2] - dark[0], dark[3] - dark[1]) == (side, side)
        assert export.content == image.content

    async def test_a_shrunk_label_is_reported_and_kept_on_the_job(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        org: Organization,
        user: User,
    ) -> None:
        pool = await _labels(real_async_db_session, org, user, 1, 'SHRUNK')
        agent_id = await _register(real_async_client, user)
        job = (
            await real_async_client.post(
                f'{_BASE}/jobs',
                json={'label_ids': [str(pool[0].id)]},
                headers=_auth(user),
            )
        ).json()
        await real_async_client.post(
            f'{_BASE}/agent/{agent_id}/claim', headers=_auth(user)
        )

        report = await real_async_client.post(
            f'{_BASE}/agent/jobs/{job["id"]}/report',
            json={'agent_id': agent_id, 'attempt': 1, 'printed': True, 'scale': 0.753},
            headers=_auth(user),
        )
        listed = (
            await real_async_client.get(f'{_BASE}/jobs', headers=_auth(user))
        ).json()['items']

        assert report.status_code == status.HTTP_200_OK, report.text
        assert report.json()['scale'] == 0.753
        assert [entry['scale'] for entry in listed] == [0.753]

    @pytest.mark.parametrize(
        'scale',
        [
            pytest.param(None, id='left-out'),
            pytest.param(1.0, id='one'),
            # A 24 mm label on a 180 dpi head 170 dots tall: 170.08 dots
            # asked, 170 printed.
            pytest.param(170 / (24 / 25.4 * 180), id='a-hair-under-one'),
        ],
    )
    async def test_a_label_printed_at_its_size_is_printed_with_no_scale(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        org: Organization,
        user: User,
        scale: float | None,
    ) -> None:
        """The report comes after the labels are on paper.

        Refusing it left the job claimed until its lease ran out, and the
        agent printed it again.
        """
        pool = await _labels(real_async_db_session, org, user, 1, 'WHOLE')
        agent_id = await _register(real_async_client, user)
        job = (
            await real_async_client.post(
                f'{_BASE}/jobs',
                json={'label_ids': [str(pool[0].id)]},
                headers=_auth(user),
            )
        ).json()
        await real_async_client.post(
            f'{_BASE}/agent/{agent_id}/claim', headers=_auth(user)
        )

        body: dict[str, object] = {'agent_id': agent_id, 'attempt': 1, 'printed': True}
        if scale is not None:
            body['scale'] = scale
        report = await real_async_client.post(
            f'{_BASE}/agent/jobs/{job["id"]}/report', json=body, headers=_auth(user)
        )
        listed = (
            await real_async_client.get(f'{_BASE}/jobs', headers=_auth(user))
        ).json()['items']

        assert report.status_code == status.HTTP_200_OK, report.text
        assert [(entry['status'], entry['scale']) for entry in listed] == [
            ('printed', None)
        ]
        assert await _printed_codes(real_async_db_session, pool) == {'WHOLE-0000'}

    async def test_an_agent_announcing_media_and_size_still_registers(
        self, real_async_client: AsyncClient, user: User
    ) -> None:
        """What an agent sends beyond the contract is ignored, not refused.

        The media and the size left the printer for the job; an agent still
        sending them registers all the same. What the handshake must say is
        which protocol it speaks — that is the one thing checked (and a
        registration naming none is refused).
        """
        response = await real_async_client.post(
            f'{_BASE}/agent/register',
            json={
                'name': 'old-agent',
                'printer_type': 'brother-p710bt',
                'media': 'brother_tape',
                'width_mm': 50.0,
                'height_mm': 24.0,
                'agent_version': '0.9.0',
                'protocol_version': PROTOCOL_VERSION,
            },
            headers=_auth(user),
        )

        assert response.status_code == status.HTTP_200_OK, response.text
        assert 'media' not in response.json()
        assert 'width_mm' not in response.json()

    async def test_a_printer_has_no_media_or_size_to_set(
        self, real_async_client: AsyncClient, user: User
    ) -> None:
        agent_id = await _register(real_async_client, user)

        response = await real_async_client.patch(
            f'{_BASE}/agents/{agent_id}',
            json={'media': 'sheet', 'width_mm': 40.0, 'height_mm': 30.0},
            headers=_auth(user),
        )

        assert response.status_code in (
            status.HTTP_404_NOT_FOUND,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )


@pytest.mark.integration
@pytest.mark.asyncio
class TestTheQueueStaysInItsOrganization:
    async def test_another_organization_sees_and_touches_nothing(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        org: Organization,
        user: User,
    ) -> None:
        pool = await _labels(real_async_db_session, org, user, 1, 'HOME')
        agent_id = await _register(real_async_client, user)
        job = (
            await real_async_client.post(
                f'{_BASE}/jobs',
                json={'label_ids': [str(pool[0].id)]},
                headers=_auth(user),
            )
        ).json()
        other_org = await _org(real_async_db_session, 'Queue Elsewhere')
        stranger = await _user(real_async_db_session, other_org)

        jobs = await real_async_client.get(f'{_BASE}/jobs', headers=_auth(stranger))
        agents = await real_async_client.get(f'{_BASE}/agents', headers=_auth(stranger))
        claim = await real_async_client.post(
            f'{_BASE}/agent/{agent_id}/claim', headers=_auth(stranger)
        )
        image = await real_async_client.get(
            f'{_BASE}/agent/jobs/{job["id"]}/image', headers=_auth(stranger)
        )
        queue_theirs = await real_async_client.post(
            f'{_BASE}/jobs',
            json={'agent_id': agent_id, 'label_ids': [str(pool[0].id)]},
            headers=_auth(stranger),
        )

        assert jobs.json()['items'] == []
        assert agents.json()['items'] == []
        assert claim.status_code == status.HTTP_404_NOT_FOUND
        assert image.status_code == status.HTTP_404_NOT_FOUND
        assert queue_theirs.status_code == status.HTTP_404_NOT_FOUND
