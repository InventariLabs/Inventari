"""The app's side of the print queue asks for the read of the screen that prints.

These routes asked for nothing but membership: a role or a key holding no
read of products or locations listed the organization's printers and jobs,
rendered any product's or shelf's label and sent jobs to a printer. Each
kind of label now answers to the reads of the screens that send it: a
product's to ``items:read``; a pool label to ``items:read`` (Labels) or
``equipment:read`` (the equipment register); a shelf to ``locations:read``
(a location card) or ``warehouse:read`` (the warehouse's scan sheet and
location codes). The print agent's own routes keep ``printing:agent``.
"""

import uuid
from datetime import UTC, datetime
from typing import cast

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.category import Category
from app.models.label_pool import LabelPool
from app.models.organization import Organization
from app.models.role import Role, UserRole
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.printing.models import PrintJob
from app.modules.printing.schemas import PROTOCOL_VERSION

_BASE = '/api/v1/printing'

pytestmark = pytest.mark.integration


@pytest.fixture
def h(db_session: Session) -> ModuleTestHelper:
    return ModuleTestHelper(db_session)


@pytest.fixture
def org(h: ModuleTestHelper) -> Organization:
    return h.create_org('Print Org', ['core', 'items', 'locations', 'printing'])


@pytest.fixture
def admin(h: ModuleTestHelper, org: Organization) -> User:
    return h.create_user(org, email=f'print_admin_{uuid.uuid4().hex[:6]}@test.com')


@pytest.fixture
def shelf(h: ModuleTestHelper, org: Organization, admin: User) -> StorageLocation:
    kind = h.create_storage_type('Shelf', 'SHELF', organization_id=org.id)
    shelf = h.create_storage_location(org, kind, admin, name='Shelf A')
    shelf.short_code = 'SHELF-A'
    h.db.commit()
    return shelf


@pytest.fixture
def product_id(
    client: TestClient, h: ModuleTestHelper, admin: User, shelf: StorageLocation
) -> str:
    resp = client.post(
        '/api/v1/items',
        headers=h.get_auth_headers(admin),
        json={
            'name': 'Plum butter',
            'location_id': str(shelf.id),
            'quantity': 1,
            'sku': 'PLUM-1',
        },
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    return cast(str, resp.json()['id'])


@pytest.fixture
def pool_label(h: ModuleTestHelper, org: Organization, admin: User) -> LabelPool:
    label = LabelPool(
        short_code=f'EQ-{uuid.uuid4().hex[:6]}',
        organization_id=org.id,
        created_by=admin.id,
    )
    h.db.add(label)
    h.db.commit()
    return label


def _assigned_label(
    h: ModuleTestHelper, org: Organization, admin: User, item_id: str
) -> LabelPool:
    label = LabelPool(
        short_code=f'EQ-{uuid.uuid4().hex[:6]}',
        organization_id=org.id,
        created_by=admin.id,
        item_id=uuid.UUID(item_id),
        is_assigned=True,
        assigned_at=datetime.now(UTC),
    )
    h.db.add(label)
    h.db.commit()
    return label


@pytest.fixture
def asset_label(
    client: TestClient,
    h: ModuleTestHelper,
    org: Organization,
    admin: User,
    shelf: StorageLocation,
) -> LabelPool:
    """The label stuck on one of the equipment register's assets."""
    category = Category(name='Laptops', organization_id=org.id, context_tag='equipment')
    h.db.add(category)
    h.db.commit()
    created = client.post(
        '/api/v1/items',
        headers=h.get_auth_headers(admin),
        json={
            'name': 'Register laptop',
            'location_id': str(shelf.id),
            'category_id': str(category.id),
            'quantity': 1,
        },
    )
    assert created.status_code == status.HTTP_201_CREATED, created.text
    return _assigned_label(h, org, admin, created.json()['id'])


@pytest.fixture
def product_label(
    h: ModuleTestHelper, org: Organization, admin: User, product_id: str
) -> LabelPool:
    """The label of an ordinary product, which no module claims."""
    return _assigned_label(h, org, admin, product_id)


@pytest.fixture
def agent_id(client: TestClient, h: ModuleTestHelper, admin: User) -> str:
    resp = client.post(
        f'{_BASE}/agent/register',
        json={
            'name': 'office',
            'printer_type': 'brother-p710bt',
            'agent_version': '1.0.0',
            'protocol_version': PROTOCOL_VERSION,
        },
        headers=h.get_auth_headers(admin),
    )
    assert resp.status_code == status.HTTP_200_OK, resp.text
    return cast(str, resp.json()['id'])


def _with_role(
    h: ModuleTestHelper, db: Session, org: Organization, permissions: list[str]
) -> dict[str, str]:
    user = h.create_user(
        org, email=f'print_{uuid.uuid4().hex[:8]}@test.com', role='user'
    )
    role = Role(
        name=f'role_{uuid.uuid4().hex[:6]}',
        permissions=permissions,
        is_system=False,
        organization_id=org.id,
    )
    db.add(role)
    db.flush()
    db.add(UserRole(user_id=user.id, role_id=role.id))
    db.commit()
    return h.get_auth_headers(user)


def _answers(
    client: TestClient,
    headers: dict[str, str],
    *,
    agent_id: str,
    product_id: str,
    shelf: StorageLocation,
) -> dict[str, int]:
    size = {'width_mm': 50, 'height_mm': 25}
    calls = {
        'GET /agents': lambda: client.get(f'{_BASE}/agents', headers=headers),
        'GET /jobs': lambda: client.get(f'{_BASE}/jobs', headers=headers),
        'POST /jobs': lambda: client.post(
            f'{_BASE}/jobs',
            json={'agent_id': agent_id, 'item_ids': [product_id]},
            headers=headers,
        ),
        'POST /jobs/{id}/retry': lambda: client.post(
            f'{_BASE}/jobs/{uuid.uuid4()}/retry', headers=headers
        ),
        'POST /product-labels/png': lambda: client.post(
            f'{_BASE}/product-labels/png',
            json={'item_ids': [product_id], **size},
            headers=headers,
        ),
        'POST /location-labels/png': lambda: client.post(
            f'{_BASE}/location-labels/png',
            json={'location_ids': [str(shelf.id)], **size},
            headers=headers,
        ),
        'GET /demo-label-sheet': lambda: client.get(
            f'{_BASE}/demo-label-sheet', headers=headers
        ),
    }
    return {name: call().status_code for name, call in calls.items()}


class TestThePrintQueueAsksForARead:
    def test_a_role_without_the_reads_is_refused_every_route(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        db_session: Session,
        org: Organization,
        agent_id: str,
        product_id: str,
        shelf: StorageLocation,
    ) -> None:
        headers = _with_role(h, db_session, org, ['stock_takes:read'])

        answers = _answers(
            client, headers, agent_id=agent_id, product_id=product_id, shelf=shelf
        )

        assert answers == dict.fromkeys(answers, status.HTTP_403_FORBIDDEN)

    def test_a_role_with_the_reads_reaches_every_route(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        db_session: Session,
        org: Organization,
        agent_id: str,
        product_id: str,
        shelf: StorageLocation,
    ) -> None:
        headers = _with_role(h, db_session, org, ['items:read', 'locations:read'])

        answers = _answers(
            client, headers, agent_id=agent_id, product_id=product_id, shelf=shelf
        )

        # Past the guard every route gives its own answer: a job id nobody
        # queued is not found, and only a demo instance has a demo sheet.
        assert answers == {
            'GET /agents': status.HTTP_200_OK,
            'GET /jobs': status.HTTP_200_OK,
            'POST /jobs': status.HTTP_201_CREATED,
            'POST /jobs/{id}/retry': status.HTTP_404_NOT_FOUND,
            'POST /product-labels/png': status.HTTP_200_OK,
            'POST /location-labels/png': status.HTTP_200_OK,
            'GET /demo-label-sheet': status.HTTP_404_NOT_FOUND,
        }

    def test_a_shelf_label_answers_to_the_location_read(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        db_session: Session,
        org: Organization,
        agent_id: str,
        product_id: str,
        shelf: StorageLocation,
    ) -> None:
        headers = _with_role(h, db_session, org, ['items:read'])

        answers = _answers(
            client, headers, agent_id=agent_id, product_id=product_id, shelf=shelf
        )

        assert answers['POST /location-labels/png'] == status.HTTP_403_FORBIDDEN
        assert answers['POST /product-labels/png'] == status.HTTP_200_OK


class TestAJobAnswersToTheReadOfItsTarget:
    """The printers and the queue serve product and shelf labels alike.

    A location card sends its shelf to the printer through the same
    ``/agents`` and ``/jobs`` as the Labels screen, so the queue admits
    either read, and a job asks for the read of what it prints.
    """

    def _queue(
        self,
        client: TestClient,
        headers: dict[str, str],
        agent_id: str,
        target: dict[str, list[str]],
    ) -> int:
        response = client.post(
            f'{_BASE}/jobs', json={'agent_id': agent_id, **target}, headers=headers
        )
        return int(response.status_code)

    def test_a_location_reader_prints_a_shelf_and_not_a_product(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        db_session: Session,
        org: Organization,
        agent_id: str,
        product_id: str,
        shelf: StorageLocation,
    ) -> None:
        headers = _with_role(h, db_session, org, ['locations:read'])

        assert client.get(f'{_BASE}/agents', headers=headers).status_code == 200
        assert client.get(f'{_BASE}/jobs', headers=headers).status_code == 200
        shelf_job = self._queue(
            client, headers, agent_id, {'location_ids': [str(shelf.id)]}
        )
        product_job = self._queue(client, headers, agent_id, {'item_ids': [product_id]})

        assert shelf_job == status.HTTP_201_CREATED
        assert product_job == status.HTTP_403_FORBIDDEN

    def test_a_product_reader_prints_a_product_and_not_a_shelf(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        db_session: Session,
        org: Organization,
        agent_id: str,
        product_id: str,
        shelf: StorageLocation,
    ) -> None:
        headers = _with_role(h, db_session, org, ['items:read'])

        shelf_job = self._queue(
            client, headers, agent_id, {'location_ids': [str(shelf.id)]}
        )
        product_job = self._queue(client, headers, agent_id, {'item_ids': [product_id]})

        assert shelf_job == status.HTTP_403_FORBIDDEN
        assert product_job == status.HTTP_201_CREATED


class TestEveryScreenThatSendsALabelReachesTheQueue:
    """A screen of a module prints with that module's read, not the core's.

    The equipment register sends its assets' pool labels and the warehouse's
    scan sheet and location codes send shelves; a role holding the module's
    read and no core read lost the printer on those screens when the queue
    asked for ``items:read`` or ``locations:read`` alone. The module's read
    opens its own kind of label only.
    """

    def _answers(
        self,
        client: TestClient,
        headers: dict[str, str],
        *,
        agent_id: str,
        targets: dict[str, dict[str, list[str]]],
    ) -> dict[str, int]:
        answers = {
            'GET /agents': client.get(f'{_BASE}/agents', headers=headers).status_code
        }
        for name, target in targets.items():
            response = client.post(
                f'{_BASE}/jobs', json={'agent_id': agent_id, **target}, headers=headers
            )
            answers[name] = response.status_code
        return answers

    @pytest.fixture
    def targets(
        self,
        product_id: str,
        shelf: StorageLocation,
        pool_label: LabelPool,
        asset_label: LabelPool,
    ) -> dict[str, dict[str, list[str]]]:
        return {
            'pool label by code': {'short_codes': [pool_label.short_code]},
            'pool label by id': {'label_ids': [str(pool_label.id)]},
            'asset label by code': {'short_codes': [asset_label.short_code]},
            'asset label by id': {'label_ids': [str(asset_label.id)]},
            'product': {'item_ids': [product_id]},
            'shelf': {'location_ids': [str(shelf.id)]},
        }

    def test_the_equipment_register_prints_its_pool_labels(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        db_session: Session,
        org: Organization,
        agent_id: str,
        targets: dict[str, dict[str, list[str]]],
    ) -> None:
        headers = _with_role(h, db_session, org, ['equipment:read', 'equipment:write'])

        answers = self._answers(client, headers, agent_id=agent_id, targets=targets)

        # The register prints the labels of its own assets; a label nobody
        # has assigned is the organization's pool, not the register's.
        assert answers == {
            'GET /agents': status.HTTP_200_OK,
            'pool label by code': status.HTTP_400_BAD_REQUEST,
            'pool label by id': status.HTTP_400_BAD_REQUEST,
            'asset label by code': status.HTTP_201_CREATED,
            'asset label by id': status.HTTP_201_CREATED,
            'product': status.HTTP_403_FORBIDDEN,
            'shelf': status.HTTP_403_FORBIDDEN,
        }

    def test_the_warehouse_prints_its_shelves(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        db_session: Session,
        org: Organization,
        agent_id: str,
        targets: dict[str, dict[str, list[str]]],
        shelf: StorageLocation,
    ) -> None:
        headers = _with_role(h, db_session, org, ['warehouse:read'])

        answers = self._answers(client, headers, agent_id=agent_id, targets=targets)
        preview = client.post(
            f'{_BASE}/location-labels/png',
            json={'location_ids': [str(shelf.id)], 'width_mm': 50, 'height_mm': 25},
            headers=headers,
        )

        assert preview.status_code == status.HTTP_200_OK, preview.text
        assert answers == {
            'GET /agents': status.HTTP_200_OK,
            'pool label by code': status.HTTP_403_FORBIDDEN,
            'pool label by id': status.HTTP_403_FORBIDDEN,
            'asset label by code': status.HTTP_403_FORBIDDEN,
            'asset label by id': status.HTTP_403_FORBIDDEN,
            'product': status.HTTP_403_FORBIDDEN,
            'shelf': status.HTTP_201_CREATED,
        }

    def test_the_labels_screen_prints_pool_labels_and_products(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        db_session: Session,
        org: Organization,
        agent_id: str,
        targets: dict[str, dict[str, list[str]]],
    ) -> None:
        headers = _with_role(h, db_session, org, ['items:read'])

        answers = self._answers(client, headers, agent_id=agent_id, targets=targets)

        assert answers == {
            'GET /agents': status.HTTP_200_OK,
            'pool label by code': status.HTTP_201_CREATED,
            'pool label by id': status.HTTP_201_CREATED,
            'asset label by code': status.HTTP_201_CREATED,
            'asset label by id': status.HTTP_201_CREATED,
            'product': status.HTTP_201_CREATED,
            'shelf': status.HTTP_403_FORBIDDEN,
        }


class TestAnEquipmentReaderQueuesOnlyTheRegistersLabels:
    """The register's read prints the labels of the register's records.

    The queue admitted ``equipment:read`` for pool labels and resolved them
    with no module bound, so a role holding only the register's read queued
    a job carrying any product's name, or a label nobody had assigned. The
    label sheet download had already learned the bound; the queue draws the
    same labels now.
    """

    def _queue(
        self,
        client: TestClient,
        headers: dict[str, str],
        agent_id: str,
        target: dict[str, list[str]],
    ) -> tuple[int, dict[str, object]]:
        response = client.post(
            f'{_BASE}/jobs', json={'agent_id': agent_id, **target}, headers=headers
        )
        return response.status_code, response.json()

    def test_a_products_label_and_a_free_label_are_refused(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        db_session: Session,
        org: Organization,
        agent_id: str,
        asset_label: LabelPool,
        product_label: LabelPool,
        pool_label: LabelPool,
    ) -> None:
        headers = _with_role(h, db_session, org, ['equipment:read'])

        answers = {
            name: self._queue(client, headers, agent_id, target)[0]
            for name, target in {
                'product label by code': {'short_codes': [product_label.short_code]},
                'product label by id': {'label_ids': [str(product_label.id)]},
                'free label by code': {'short_codes': [pool_label.short_code]},
                'free label by id': {'label_ids': [str(pool_label.id)]},
                'asset label by code': {'short_codes': [asset_label.short_code]},
            }.items()
        }

        assert answers == {
            'product label by code': status.HTTP_400_BAD_REQUEST,
            'product label by id': status.HTTP_400_BAD_REQUEST,
            'free label by code': status.HTTP_400_BAD_REQUEST,
            'free label by id': status.HTTP_400_BAD_REQUEST,
            'asset label by code': status.HTTP_201_CREATED,
        }

    def test_a_mixed_ask_queues_the_registers_label_alone(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        db_session: Session,
        org: Organization,
        agent_id: str,
        asset_label: LabelPool,
        product_label: LabelPool,
        pool_label: LabelPool,
    ) -> None:
        headers = _with_role(h, db_session, org, ['equipment:read'])
        codes = [
            product_label.short_code,
            asset_label.short_code,
            pool_label.short_code,
        ]

        by_code = self._queue(client, headers, agent_id, {'short_codes': codes})
        by_id = self._queue(
            client,
            headers,
            agent_id,
            {'label_ids': [str(product_label.id), str(asset_label.id)]},
        )

        for answer, body in (by_code, by_id):
            assert answer == status.HTTP_201_CREATED, body
            assert body['count'] == 1
            assert body['short_codes'] == [asset_label.short_code]

    def test_a_product_reader_still_queues_any_pool_label(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        db_session: Session,
        org: Organization,
        agent_id: str,
        product_label: LabelPool,
        pool_label: LabelPool,
    ) -> None:
        headers = _with_role(h, db_session, org, ['items:read', 'equipment:read'])
        codes = [product_label.short_code, pool_label.short_code]

        answer, body = self._queue(client, headers, agent_id, {'short_codes': codes})

        assert answer == status.HTTP_201_CREATED, body
        assert body['count'] == 2


class TestAQueuedJobAnswersToTheReadOfItsTarget:
    """The queue lists and resends a job only to a reader of what it prints.

    A job keeps what its labels say — a product's name and code, a shelf's —
    and a retry sends it to the printer again. The list and the retry admit
    every read of a screen that prints, so a role refused a new product job
    read the product codes off the list and printed that job again, and the
    same held for a shelf. A job is listed to the reads that may send its
    kind of label, whoever sent it.
    """

    @pytest.fixture
    def failed(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        db_session: Session,
        admin: User,
        agent_id: str,
        product_id: str,
        shelf: StorageLocation,
        pool_label: LabelPool,
    ) -> dict[str, str]:
        """A failed job of each kind, queued by an admin."""
        targets = {
            'product': {'item_ids': [product_id]},
            'shelf': {'location_ids': [str(shelf.id)]},
            'pool': {'label_ids': [str(pool_label.id)]},
        }
        jobs = {}
        for name, target in targets.items():
            response = client.post(
                f'{_BASE}/jobs',
                json={'agent_id': agent_id, **target},
                headers=h.get_auth_headers(admin),
            )
            assert response.status_code == status.HTTP_201_CREATED, response.text
            jobs[name] = response.json()['id']
        db_session.execute(
            update(PrintJob)
            .where(PrintJob.id.in_([uuid.UUID(job) for job in jobs.values()]))
            .values(status='failed')
        )
        db_session.commit()
        return jobs

    @pytest.mark.parametrize(
        ('permission', 'readable'),
        [
            ('locations:read', {'shelf'}),
            ('warehouse:read', {'shelf'}),
            ('items:read', {'product', 'pool'}),
            ('equipment:read', {'pool'}),
        ],
    )
    def test_a_reader_lists_and_resends_only_what_it_may_read(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        db_session: Session,
        org: Organization,
        failed: dict[str, str],
        permission: str,
        readable: set[str],
    ) -> None:
        headers = _with_role(h, db_session, org, [permission])

        page = client.get(f'{_BASE}/jobs', headers=headers).json()
        retried = {
            name: client.post(f'{_BASE}/jobs/{job}/retry', headers=headers).status_code
            for name, job in failed.items()
        }

        listed_ids = {row['id'] for row in page['items']}
        listed = {name for name, job in failed.items() if job in listed_ids}
        assert listed == readable
        assert page['total'] == len(readable)
        assert retried == {
            name: status.HTTP_200_OK if name in readable else status.HTTP_403_FORBIDDEN
            for name in failed
        }
