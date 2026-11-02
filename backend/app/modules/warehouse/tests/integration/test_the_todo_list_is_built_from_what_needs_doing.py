"""To do lists what needs doing, not only the documents that are confirmed.

A purchase order that expects goods, a production run planned for today and a
count that has fallen due are work, and none of them is a confirmed document.
The tasks are read from those records on every request, so what happens to
the record is what happens to the task: a session moves it on, a receipt
stands in for its order, a cancelled order is gone. Nothing is ticked by hand
except a task the boss added himself, and the one thing the sources cannot
say — who a task is for — is stored beside them.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from sqlalchemy.orm import Session

from app.core.contracts import WorkItemDTO, WorkItemQueryDTO
from app.core.exceptions import ConflictException
from app.core.testing import ModuleTestHelper
from app.models.audit_log import AuditLog
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.maker.models import ProductionOrder
from app.modules.purchase_orders.models import PurchaseOrder, PurchaseOrderLine
from app.modules.stock_takes.models import (
    CycleCountFrequency,
    CycleCountSchedule,
    StockTake,
    StockTakeStatus,
)
from app.modules.warehouse.models import (
    CUSTOM_SOURCE_KIND,
    Document,
    WmsPickSession,
    WorkItemOverlay,
)
from app.modules.warehouse.warehouse_api import warehouse_api
from app.modules.warehouse.work_item_service import assign_work_item_async

_TODAY = date.today()
_YESTERDAY = _TODAY - timedelta(days=1)
_PARK_TIMEOUT = 15.0


async def _wait_until_claimants_park(engine: AsyncEngine, racers: int) -> None:
    """Return once ``racers`` claims wait on the work-item overlay table.

    Only statements against ``work_item_overlays`` are counted: the suite
    runs other tests in parallel, and an unrelated lock waiter must not pass
    for one of ours.
    """
    probe_engine = engine.execution_options(isolation_level='AUTOCOMMIT')
    async with probe_engine.connect() as probe:
        deadline = asyncio.get_running_loop().time() + _PARK_TIMEOUT
        while True:
            waiting = await probe.scalar(
                text(
                    'SELECT count(*) FROM pg_stat_activity '
                    "WHERE datname = current_database() AND wait_event_type = 'Lock' "
                    "AND query LIKE '%work_item_overlays%'"
                )
            )
            if waiting is not None and waiting >= racers:
                return
            if asyncio.get_running_loop().time() > deadline:
                raise AssertionError(f'{racers} claim(s) never parked on the row')
            await asyncio.sleep(0.02)


@pytest.fixture
def doc_org(h: ModuleTestHelper) -> Organization:
    return h.create_org(
        'Work Items Org',
        [
            'core',
            'items',
            'locations',
            'categories',
            'warehouse',
            'purchase_orders',
            'maker',
            'stock_takes',
            'cert_checks',
        ],
    )


def _work_items(
    client: TestClient, headers: dict[str, str], **params: Any
) -> dict[str, Any]:
    response = client.get(
        '/api/v1/warehouse/todo',
        headers=headers,
        params={'date_to': _TODAY.isoformat(), 'limit': 50, **params},
    )
    assert response.status_code == status.HTTP_200_OK, response.text
    return cast(dict[str, Any], response.json()['work_items'])


def _task(section: dict[str, Any], key: str) -> dict[str, Any] | None:
    for item in section['items']:
        if item['key'] == key:
            return cast(dict[str, Any], item)
    return None


def _order(
    db_session: Session,
    org: Organization,
    user: User,
    partner: Partner,
    template: ProductTemplate,
    *,
    scheduled: date | None,
    status_word: str = 'CONFIRMED',
    received: str = '0',
) -> PurchaseOrder:
    order = PurchaseOrder(
        organization_id=org.id,
        number=f'PO/{uuid4().hex[:6]}',
        status=status_word,
        partner_id=partner.id,
        scheduled_date=scheduled,
        created_by=user.id,
    )
    order.lines = [
        PurchaseOrderLine(
            product_template_id=template.id,
            name=template.name,
            quantity_ordered=Decimal('10'),
            quantity_received=Decimal(received),
        )
    ]
    db_session.add(order)
    db_session.commit()
    return order


def _confirmed_receipt_for(
    client: TestClient,
    headers: dict[str, str],
    order: PurchaseOrder,
    partner: Partner,
    target: StorageLocation,
    template: ProductTemplate,
) -> str:
    response = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'IN',
            'partner_id': str(partner.id),
            'target_location_id': str(target.id),
            'scheduled_date': _TODAY.isoformat(),
            'lines': [
                {
                    'product_template_id': str(template.id),
                    'expected_quantity': '10',
                    'source_po_line_id': str(order.lines[0].id),
                }
            ],
        },
    )
    assert response.status_code == status.HTTP_201_CREATED, response.text
    doc_id = cast(str, response.json()['id'])
    confirmed = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=headers
    )
    assert confirmed.status_code == status.HTTP_200_OK, confirmed.text
    return doc_id


@pytest.mark.integration
class TestTheTodoListIsBuiltFromWhatNeedsDoing:
    def test_an_order_a_production_run_and_a_due_count_are_tasks(
        self,
        client: TestClient,
        db_session: Session,
        doc_org: Organization,
        doc_user: User,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_template: ProductTemplate,
        doc_target_location: StorageLocation,
    ) -> None:
        late = _order(
            db_session, doc_org, doc_user, doc_partner, doc_template,
            scheduled=_YESTERDAY,
        )  # fmt: skip
        later = _order(
            db_session, doc_org, doc_user, doc_partner, doc_template,
            scheduled=_TODAY + timedelta(days=3),
        )  # fmt: skip
        run = ProductionOrder(
            organization_id=doc_org.id,
            number='PR/1',
            output_template_id=doc_template.id,
            planned_qty=Decimal('4'),
            output_storage_location_id=doc_target_location.id,
            status='DRAFT',
            production_date=_TODAY,
        )
        due_count = CycleCountSchedule(
            organization_id=doc_org.id,
            name='Fast movers',
            frequency=CycleCountFrequency.WEEKLY,
            created_by=doc_user.id,
            last_run_at=datetime.now(UTC) - timedelta(days=10),
        )
        not_due_count = CycleCountSchedule(
            organization_id=doc_org.id,
            name='Slow movers',
            frequency=CycleCountFrequency.MONTHLY,
            created_by=doc_user.id,
            last_run_at=datetime.now(UTC) - timedelta(days=2),
        )
        db_session.add_all([run, due_count, not_due_count])
        db_session.commit()

        section = _work_items(client, doc_auth_headers)

        delivery = _task(section, f'purchase_order:{late.id}')
        assert delivery is not None
        assert delivery['kind'] == 'expected_delivery'
        assert delivery['subject'] == doc_partner.name
        assert delivery['next_action'] == 'receive_delivery'
        assert delivery['state'] == 'todo'
        assert delivery['overdue'] is True
        assert delivery['due_date'] == _YESTERDAY.isoformat()
        assert Decimal(delivery['count']) == 1
        # An order expected next week is not today's work.
        assert _task(section, f'purchase_order:{later.id}') is None

        production = _task(section, f'production_order:{run.id}')
        assert production is not None
        assert production['kind'] == 'produce'
        assert production['subject'] == doc_template.name
        assert production['next_action'] == 'produce'
        assert production['overdue'] is False
        assert Decimal(production['count']) == 4

        count = _task(section, f'cycle_count:{due_count.id}')
        assert count is not None
        assert count['kind'] == 'count'
        assert count['subject'] == 'Fast movers'
        assert count['next_action'] == 'count'
        assert _task(section, f'cycle_count:{not_due_count.id}') is None
        assert section['total'] == len(section['items']) == 3

    def test_a_confirmed_document_is_a_task_that_follows_its_session(
        self,
        client: TestClient,
        db_session: Session,
        doc_org: Organization,
        doc_user: User,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_template: ProductTemplate,
        doc_target_location: StorageLocation,
    ) -> None:
        order = _order(
            db_session, doc_org, doc_user, doc_partner, doc_template,
            scheduled=_TODAY,
        )  # fmt: skip
        receipt_id = _confirmed_receipt_for(
            client, doc_auth_headers, order, doc_partner, doc_target_location,
            doc_template,
        )  # fmt: skip

        section = _work_items(client, doc_auth_headers)

        # The receipt stands for the delivery: one task, not two.
        assert _task(section, f'purchase_order:{order.id}') is None
        task = _task(section, f'document:{receipt_id}:receive')
        assert task is not None
        assert task['kind'] == 'receive'
        assert task['state'] == 'todo'
        assert task['next_action'] == 'receive'
        assert task['subject'] == doc_partner.name
        assert task['place'] == doc_target_location.name
        assert task['document_type'] == 'IN'
        assert task['document_status'] == 'CONFIRMED'
        assert Decimal(task['count']) == 1

        # Starting a session moves the task on; nobody changed a status.
        document = db_session.get(Document, UUID(receipt_id))
        assert document is not None
        db_session.add(
            WmsPickSession(
                organization_id=doc_org.id,
                document_id=document.id,
                assigned_to=doc_user.id,
                status='active',
                started_at=datetime.now(),
            )
        )
        db_session.commit()
        started = _task(
            _work_items(client, doc_auth_headers), f'document:{receipt_id}:receive'
        )
        assert started is not None
        assert started['state'] == 'in_progress'
        assert started['next_action'] == 'resume'
        assert started['stage_holder_name'] == doc_user.full_name

    def test_a_cancelled_order_or_a_finished_run_is_no_longer_a_task(
        self,
        client: TestClient,
        db_session: Session,
        doc_org: Organization,
        doc_user: User,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_template: ProductTemplate,
        doc_target_location: StorageLocation,
    ) -> None:
        order = _order(
            db_session, doc_org, doc_user, doc_partner, doc_template,
            scheduled=_TODAY,
        )  # fmt: skip
        run = ProductionOrder(
            organization_id=doc_org.id,
            output_template_id=doc_template.id,
            planned_qty=Decimal('1'),
            output_storage_location_id=doc_target_location.id,
            status='DRAFT',
            production_date=_TODAY,
        )
        db_session.add(run)
        db_session.commit()
        assert len(_work_items(client, doc_auth_headers)['items']) == 2

        order.status = 'CANCELLED'
        run.status = 'COMPLETED'
        db_session.commit()

        assert _work_items(client, doc_auth_headers)['items'] == []

    def test_a_task_can_be_given_to_a_person_and_taken_back(
        self,
        client: TestClient,
        db_session: Session,
        doc_org: Organization,
        doc_user: User,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        order = _order(
            db_session, doc_org, doc_user, doc_partner, doc_template,
            scheduled=_TODAY,
        )  # fmt: skip
        key = f'purchase_order:{order.id}'
        path = f'/api/v1/warehouse/work-items/purchase_order/{order.id}/assignee'
        before = _task(_work_items(client, doc_auth_headers), key)
        assert before is not None
        assert before['assignee_id'] is None

        given = client.put(
            path, headers=doc_auth_headers, json={'assignee_id': str(doc_user.id)}
        )
        assert given.status_code == status.HTTP_204_NO_CONTENT, given.text
        # A second assignment changes the same row rather than adding one.
        again = client.put(
            path, headers=doc_auth_headers, json={'assignee_id': str(doc_user.id)}
        )
        assert again.status_code == status.HTTP_204_NO_CONTENT, again.text
        after = _task(_work_items(client, doc_auth_headers), key)
        assert after is not None
        assert after['assignee_id'] == str(doc_user.id)
        assert after['assignee_name'] == doc_user.full_name

        taken_back = client.put(path, headers=doc_auth_headers, json={})
        assert taken_back.status_code == status.HTTP_204_NO_CONTENT
        released = _task(_work_items(client, doc_auth_headers), key)
        assert released is not None
        assert released['assignee_id'] is None

    def test_a_claim_leaves_a_task_with_the_person_who_took_it_first(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        db_session: Session,
        doc_org: Organization,
        doc_user: User,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        """A claim lands on nobody's task and refuses a task already held.

        This is the phone's tap: the row it was read from may be stale, so the
        server decides. A task somebody else took in the meantime keeps its
        holder and answers 409; the same person claiming twice is harmless.
        """
        order = _order(
            db_session, doc_org, doc_user, doc_partner, doc_template,
            scheduled=_TODAY,
        )  # fmt: skip
        colleague = h.create_user(doc_org, email='colleague@example.com')
        key = f'purchase_order:{order.id}'
        path = f'/api/v1/warehouse/work-items/purchase_order/{order.id}/assignee'

        claimed = client.put(
            path,
            headers=doc_auth_headers,
            json={'assignee_id': str(doc_user.id), 'only_if_unassigned': True},
        )
        assert claimed.status_code == status.HTTP_204_NO_CONTENT, claimed.text
        holder = _task(_work_items(client, doc_auth_headers), key)
        assert holder is not None
        assert holder['assignee_id'] == str(doc_user.id)

        # A second tap by the reader who already holds it changes nothing.
        again = client.put(
            path,
            headers=doc_auth_headers,
            json={'assignee_id': str(doc_user.id), 'only_if_unassigned': True},
        )
        assert again.status_code == status.HTTP_204_NO_CONTENT, again.text

        # Somebody else's claim loses, and the holder is not overwritten.
        lost = client.put(
            path,
            headers=doc_auth_headers,
            json={'assignee_id': str(colleague.id), 'only_if_unassigned': True},
        )
        assert lost.status_code == status.HTTP_409_CONFLICT, lost.text
        assert lost.json()['detail']['code'] == 'WORK_ITEM_TAKEN'
        unchanged = _task(_work_items(client, doc_auth_headers), key)
        assert unchanged is not None
        assert unchanged['assignee_id'] == str(doc_user.id)
        assert unchanged['assignee_name'] == doc_user.full_name

        # Choosing a person on the desktop still reassigns deliberately.
        given = client.put(
            path,
            headers=doc_auth_headers,
            json={'assignee_id': str(colleague.id)},
        )
        assert given.status_code == status.HTTP_204_NO_CONTENT, given.text
        reassigned = _task(_work_items(client, doc_auth_headers), key)
        assert reassigned is not None
        assert reassigned['assignee_id'] == str(colleague.id)

    def test_a_task_cannot_be_given_to_someone_outside_the_organization(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        db_session: Session,
        doc_org: Organization,
        doc_user: User,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        stranger_org = h.create_org('Elsewhere', ['core'])
        stranger = h.create_user(stranger_org, email='stranger@example.com')
        order = _order(
            db_session, doc_org, doc_user, doc_partner, doc_template,
            scheduled=_TODAY,
        )  # fmt: skip

        response = client.put(
            f'/api/v1/warehouse/work-items/purchase_order/{order.id}/assignee',
            headers=doc_auth_headers,
            json={'assignee_id': str(stranger.id)},
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND, response.text

    def test_a_custom_task_is_added_assigned_ticked_off_and_removed(
        self,
        client: TestClient,
        db_session: Session,
        doc_user: User,
        doc_auth_headers: dict[str, str],
    ) -> None:
        created = client.post(
            '/api/v1/warehouse/work-items/custom',
            headers=doc_auth_headers,
            json={
                'title': '  Move the rack  ',
                'assignee_id': str(doc_user.id),
                'due_date': _YESTERDAY.isoformat(),
            },
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        item_id = created.json()['source_id']
        key = f'custom:{item_id}'

        task = _task(_work_items(client, doc_auth_headers), key)
        assert task is not None
        assert task['kind'] == 'custom'
        assert task['subject'] == 'Move the rack'
        assert task['assignee_id'] == str(doc_user.id)
        assert task['overdue'] is True
        assert task['next_action'] is None

        # It can be handed to nobody, like any other task.
        released = client.put(
            f'/api/v1/warehouse/work-items/custom/{item_id}/assignee',
            headers=doc_auth_headers,
            json={'assignee_id': None},
        )
        assert released.status_code == status.HTTP_204_NO_CONTENT, released.text
        unassigned = _task(_work_items(client, doc_auth_headers), key)
        assert unassigned is not None
        assert unassigned['assignee_id'] is None

        ticked = client.put(
            f'/api/v1/warehouse/work-items/custom/{item_id}/done',
            headers=doc_auth_headers,
            json={'done': True},
        )
        assert ticked.status_code == status.HTTP_204_NO_CONTENT, ticked.text
        assert _task(_work_items(client, doc_auth_headers), key) is None
        done = _task(_work_items(client, doc_auth_headers, include_done=True), key)
        assert done is not None
        assert done['state'] == 'done'
        assert done['overdue'] is False

        client.put(
            f'/api/v1/warehouse/work-items/custom/{item_id}/done',
            headers=doc_auth_headers,
            json={'done': False},
        )
        assert _task(_work_items(client, doc_auth_headers), key) is not None

        removed = client.delete(
            f'/api/v1/warehouse/work-items/custom/{item_id}',
            headers=doc_auth_headers,
        )
        assert removed.status_code == status.HTTP_204_NO_CONTENT, removed.text
        assert _task(_work_items(client, doc_auth_headers), key) is None
        # Every act on the task is in the organization log, in order.
        entries = (
            db_session.query(AuditLog)
            .filter(AuditLog.target_type == 'work_item')
            .order_by(AuditLog.created_at)
            .all()
        )
        assert [entry.action for entry in entries] == [
            'CREATE',
            'UPDATE',
            'UPDATE',
            'UPDATE',
            'HARD_DELETE',
        ]
        missing = client.delete(
            f'/api/v1/warehouse/work-items/custom/{item_id}',
            headers=doc_auth_headers,
        )
        assert missing.status_code == status.HTTP_404_NOT_FOUND

    def test_a_custom_task_is_claimed_only_while_nobody_holds_it(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        doc_org: Organization,
        doc_user: User,
        doc_auth_headers: dict[str, str],
    ) -> None:
        colleague = h.create_user(doc_org, email='colleague@example.com')
        created = client.post(
            '/api/v1/warehouse/work-items/custom',
            headers=doc_auth_headers,
            json={'title': 'Move the rack'},
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        item_id = created.json()['source_id']
        path = f'/api/v1/warehouse/work-items/custom/{item_id}/assignee'

        claimed = client.put(
            path,
            headers=doc_auth_headers,
            json={'assignee_id': str(doc_user.id), 'only_if_unassigned': True},
        )
        assert claimed.status_code == status.HTTP_204_NO_CONTENT, claimed.text

        lost = client.put(
            path,
            headers=doc_auth_headers,
            json={'assignee_id': str(colleague.id), 'only_if_unassigned': True},
        )
        assert lost.status_code == status.HTTP_409_CONFLICT, lost.text
        task = _task(_work_items(client, doc_auth_headers), f'custom:{item_id}')
        assert task is not None
        assert task['assignee_id'] == str(doc_user.id)

    def test_two_people_claiming_a_custom_task_at_once_leave_one_winner(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        doc_org: Organization,
        doc_user: User,
        doc_auth_headers: dict[str, str],
        db_session: Session,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        """Both claims park on the row; releasing it leaves one holder.

        The claim used to read the overlay and then write it back, so both
        requests read 'nobody' before either wrote, both answered success, and
        the later one silently overwrote the first. A third connection holds
        the row so the claims write behind one lock — the window the lost
        holder lived in — rather than a window the scheduler happened to pick.
        """
        colleague = h.create_user(doc_org, email='colleague@example.com')
        created = client.post(
            '/api/v1/warehouse/work-items/custom',
            headers=doc_auth_headers,
            json={'title': 'Move the rack'},
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        item_id = UUID(created.json()['source_id'])
        db_session.commit()

        async def _race() -> dict[UUID, str]:
            maker = async_sessionmaker(
                bind=async_engine_fixture, expire_on_commit=False
            )

            async def _claim(assignee: UUID) -> str:
                async with maker() as db:
                    try:
                        await assign_work_item_async(
                            db,
                            doc_org.id,
                            doc_user.id,
                            source_kind=CUSTOM_SOURCE_KIND,
                            source_id=item_id,
                            assignee_id=assignee,
                            only_if_unassigned=True,
                        )
                    except ConflictException as refusal:
                        assert (
                            cast(dict[str, Any], refusal.detail)['code']
                            == 'WORK_ITEM_TAKEN'
                        )
                        return 'taken'
                    await db.commit()
                    return 'claimed'

            async with maker() as blocker:
                await blocker.execute(
                    select(WorkItemOverlay.id)
                    .where(WorkItemOverlay.id == item_id)
                    .with_for_update()
                )
                first = asyncio.create_task(_claim(doc_user.id))
                second = asyncio.create_task(_claim(colleague.id))
                try:
                    await _wait_until_claimants_park(async_engine_fixture, 2)
                finally:
                    await blocker.rollback()
                answers = await asyncio.gather(first, second)
            return {doc_user.id: answers[0], colleague.id: answers[1]}

        outcomes = asyncio.run(_race())

        assert sorted(outcomes.values()) == ['claimed', 'taken']
        winner = next(user_id for user_id, why in outcomes.items() if why == 'claimed')
        db_session.expire_all()
        holder = db_session.scalars(
            select(WorkItemOverlay).where(WorkItemOverlay.id == item_id)
        ).one()
        assert holder.assignee_id == winner

    def test_a_blank_title_is_refused(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        response = client.post(
            '/api/v1/warehouse/work-items/custom',
            headers=doc_auth_headers,
            json={'title': '   '},
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_custom_tasks_of_another_organization_are_not_reachable(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        doc_auth_headers: dict[str, str],
    ) -> None:
        other_org = h.create_org('Other', ['core', 'items', 'locations', 'warehouse'])
        other = h.create_user(other_org, email='other@example.com')
        other_headers = h.get_auth_headers(other)
        created = client.post(
            '/api/v1/warehouse/work-items/custom',
            headers=other_headers,
            json={'title': 'Not yours'},
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        item_id = created.json()['source_id']

        assert _work_items(client, doc_auth_headers)['items'] == []
        assert (
            client.delete(
                f'/api/v1/warehouse/work-items/custom/{item_id}',
                headers=doc_auth_headers,
            ).status_code
            == status.HTTP_404_NOT_FOUND
        )


@pytest.mark.integration
class TestStateFollowsWhatHappensToTheSource:
    def test_a_count_is_under_way_while_its_stock_take_is_open_then_done(
        self,
        client: TestClient,
        db_session: Session,
        doc_org: Organization,
        doc_user: User,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
    ) -> None:
        schedule = CycleCountSchedule(
            organization_id=doc_org.id,
            name='Fast movers',
            frequency=CycleCountFrequency.WEEKLY,
            created_by=doc_user.id,
            last_run_at=datetime.now(UTC) - timedelta(days=10),
        )
        db_session.add(schedule)
        db_session.commit()
        key = f'cycle_count:{schedule.id}'
        assert _task(_work_items(client, doc_auth_headers), key)['state'] == 'todo'  # type: ignore[index]

        # Running the schedule makes a stock take that names it, and moves
        # the schedule's last run to now.
        take = StockTake(
            organization_id=doc_org.id,
            user_id=doc_user.id,
            storage_location_id=doc_target_location.id,
            name='Cycle Count: Fast movers',
            status=StockTakeStatus.IN_PROGRESS,
            schedule_id=schedule.id,
        )
        schedule.last_run_at = datetime.now(UTC)
        db_session.add(take)
        db_session.commit()

        under_way = _task(_work_items(client, doc_auth_headers), key)
        assert under_way is not None
        assert under_way['state'] == 'in_progress'
        assert under_way['action_href'] == f'/inventory/stock-takes/{take.id}/counting'
        # The run moved the schedule's last run to now, so the next period's
        # day is not the day this count fell due: it shows no day at all.
        assert under_way['due_date'] is None
        assert under_way['overdue'] is False

        take.status = StockTakeStatus.COMPLETED
        take.completed_at = datetime.now(UTC)
        db_session.commit()

        assert _task(_work_items(client, doc_auth_headers), key) is None
        finished = _task(_work_items(client, doc_auth_headers, include_done=True), key)
        assert finished is not None
        assert finished['state'] == 'done'
        assert finished['next_action'] is None
        assert finished['due_date'] is None

    def test_a_run_recorded_today_is_done_and_one_cancelled_is_gone(
        self,
        client: TestClient,
        db_session: Session,
        doc_org: Organization,
        doc_auth_headers: dict[str, str],
        doc_template: ProductTemplate,
        doc_target_location: StorageLocation,
    ) -> None:
        made = ProductionOrder(
            organization_id=doc_org.id,
            number='PR/DONE',
            output_template_id=doc_template.id,
            planned_qty=Decimal('4'),
            actual_qty=Decimal('5'),
            output_storage_location_id=doc_target_location.id,
            status='COMPLETED',
            production_date=_TODAY,
            completed_at=datetime.now(UTC),
        )
        dropped = ProductionOrder(
            organization_id=doc_org.id,
            number='PR/DROPPED',
            output_template_id=doc_template.id,
            planned_qty=Decimal('1'),
            output_storage_location_id=doc_target_location.id,
            status='CANCELLED',
            production_date=_TODAY,
        )
        db_session.add_all([made, dropped])
        db_session.commit()

        assert _work_items(client, doc_auth_headers)['items'] == []
        section = _work_items(client, doc_auth_headers, include_done=True)

        task = _task(section, f'production_order:{made.id}')
        assert task is not None
        assert task['state'] == 'done'
        assert Decimal(task['count']) == 5
        assert task['next_action'] is None
        assert _task(section, f'production_order:{dropped.id}') is None

    def test_a_document_posted_today_is_done_after_the_open_tasks(
        self,
        client: TestClient,
        db_session: Session,
        doc_org: Organization,
        doc_user: User,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_template: ProductTemplate,
        doc_target_location: StorageLocation,
    ) -> None:
        order = _order(
            db_session, doc_org, doc_user, doc_partner, doc_template,
            scheduled=_TODAY,
        )  # fmt: skip
        receipt_id = _confirmed_receipt_for(
            client, doc_auth_headers, order, doc_partner, doc_target_location,
            doc_template,
        )  # fmt: skip
        other = ProductionOrder(
            organization_id=doc_org.id,
            number='PR/OPEN',
            output_template_id=doc_template.id,
            planned_qty=Decimal('1'),
            output_storage_location_id=doc_target_location.id,
            status='DRAFT',
            production_date=_TODAY,
        )
        db_session.add(other)
        document = db_session.get(Document, UUID(receipt_id))
        assert document is not None
        document.status = 'COMPLETED'
        document.completed_at = datetime.now(UTC)
        order.status = 'COMPLETED'
        db_session.commit()

        assert (
            _task(
                _work_items(client, doc_auth_headers), f'document:{receipt_id}:receive'
            )
            is None
        )
        section = _work_items(client, doc_auth_headers, include_done=True)

        posted = _task(section, f'document:{receipt_id}:receive')
        assert posted is not None
        assert posted['state'] == 'done'
        assert posted['kind'] == 'receive'
        assert posted['next_action'] is None
        assert [item['state'] for item in section['items']] == ['todo', 'done']


@pytest.mark.integration
class TestTheListCanBeNarrowedAndPagedOnTheServer:
    def _crowd(
        self,
        db_session: Session,
        org: Organization,
        user: User,
        count: int,
    ) -> None:
        db_session.add_all(
            WorkItemOverlay(
                organization_id=org.id,
                source_kind='custom',
                title=f'Chore {number}',
                created_by=user.id,
            )
            for number in range(count)
        )
        db_session.add(
            WorkItemOverlay(
                organization_id=org.id,
                source_kind='custom',
                title='Mine and late',
                due_date=_YESTERDAY,
                assignee_id=user.id,
                created_by=user.id,
            )
        )
        db_session.commit()

    def test_mine_and_overdue_look_past_the_first_page(
        self,
        client: TestClient,
        db_session: Session,
        doc_org: Organization,
        doc_user: User,
        doc_auth_headers: dict[str, str],
    ) -> None:
        self._crowd(db_session, doc_org, doc_user, 120)

        everything = _work_items(client, doc_auth_headers, limit=50)
        mine = _work_items(client, doc_auth_headers, limit=50, view='mine')
        late = _work_items(client, doc_auth_headers, limit=50, view='overdue')

        assert len(everything['items']) == 50
        assert everything['total'] == 121
        for narrowed in (mine, late):
            assert narrowed['total'] == 1
            assert [item['subject'] for item in narrowed['items']] == ['Mine and late']

    def test_undated_tasks_come_after_the_overdue_and_the_dated(
        self,
        client: TestClient,
        db_session: Session,
        doc_org: Organization,
        doc_user: User,
        doc_auth_headers: dict[str, str],
    ) -> None:
        db_session.add_all(
            WorkItemOverlay(
                organization_id=doc_org.id,
                source_kind='custom',
                title=title,
                due_date=due,
                created_by=doc_user.id,
            )
            for title, due in [
                ('A chore without a day', None),
                ('Later this week', _TODAY + timedelta(days=3)),
                ('Late', _YESTERDAY),
                ('Today', _TODAY),
            ]
        )
        db_session.commit()

        titles = [
            item['subject'] for item in _work_items(client, doc_auth_headers)['items']
        ]

        assert titles == [
            'Late',
            'Today',
            'Later this week',
            'A chore without a day',
        ]

    def test_a_longer_page_lists_what_the_short_one_cut_off(
        self,
        client: TestClient,
        db_session: Session,
        doc_org: Organization,
        doc_user: User,
        doc_auth_headers: dict[str, str],
    ) -> None:
        self._crowd(db_session, doc_org, doc_user, 250)

        long_page = _work_items(client, doc_auth_headers, limit=50, work_limit=300)

        assert len(long_page['items']) == 251
        assert long_page['total'] == 251
        too_long = client.get(
            '/api/v1/warehouse/todo',
            headers=doc_auth_headers,
            params={'date_to': _TODAY.isoformat(), 'work_limit': 1001},
        )
        assert too_long.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


@pytest.mark.integration
class TestModulesOnByDefaultContributeTasks:
    def test_an_organization_with_no_module_list_gets_the_default_modules_tasks(
        self,
        client: TestClient,
        db_session: Session,
        doc_org: Organization,
        doc_user: User,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        order = _order(
            db_session, doc_org, doc_user, doc_partner, doc_template,
            scheduled=_YESTERDAY,
        )  # fmt: skip
        doc_org.enabled_modules = []
        db_session.commit()

        section = _work_items(client, doc_auth_headers)

        assert _task(section, f'purchase_order:{order.id}') is not None


_CERT_ID = uuid4()


async def _certificate_checks(
    db: Any, org_id: UUID, query: WorkItemQueryDTO
) -> tuple[list[WorkItemDTO], int]:
    """A customer-specific module's provider: one check, worded by the module."""
    return [
        WorkItemDTO(
            kind='certificate_check',
            source_kind='certificate_check',
            source_id=_CERT_ID,
            due_date=query.date_to,
            sentence='Check the delivery certificate for ZK/7',
            action_label='Open certificate',
            action_href='/certificates/7',
        )
    ], 1


async def _broken_provider(
    db: Any, org_id: UUID, query: WorkItemQueryDTO
) -> tuple[list[WorkItemDTO], int]:
    raise RuntimeError('a module with a bug')


async def _no_tasks(
    db: Any, org_id: UUID, query: WorkItemQueryDTO
) -> tuple[list[WorkItemDTO], int]:
    return [], 0


@pytest.fixture
def certificate_provider() -> Any:
    warehouse_api.register_work_item_provider('cert_checks', _certificate_checks)
    yield
    # The registry is process-wide; leave the module with nothing to say.
    warehouse_api.register_work_item_provider('cert_checks', _no_tasks)


@pytest.mark.integration
class TestAnotherModuleContributesTasks:
    def test_a_registered_providers_task_is_listed_with_its_own_words_and_link(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        certificate_provider: None,
    ) -> None:
        section = _work_items(client, doc_auth_headers)

        task = _task(section, f'certificate_check:{_CERT_ID}')
        assert task is not None
        assert task['kind'] == 'certificate_check'
        assert task['sentence'] == 'Check the delivery certificate for ZK/7'
        assert task['action_label'] == 'Open certificate'
        assert task['action_href'] == '/certificates/7'
        assert task['state'] == 'todo'
        assert section['total'] == 1

    def test_its_tasks_disappear_with_the_module(
        self,
        client: TestClient,
        db_session: Session,
        doc_org: Organization,
        doc_auth_headers: dict[str, str],
        certificate_provider: None,
    ) -> None:
        assert len(_work_items(client, doc_auth_headers)['items']) == 1

        doc_org.enabled_modules = [
            name for name in doc_org.enabled_modules if name != 'cert_checks'
        ]
        db_session.commit()

        assert _work_items(client, doc_auth_headers)['items'] == []

    def test_a_task_of_a_module_can_be_assigned_like_any_other(
        self,
        client: TestClient,
        doc_user: User,
        doc_auth_headers: dict[str, str],
        certificate_provider: None,
    ) -> None:
        given = client.put(
            f'/api/v1/warehouse/work-items/certificate_check/{_CERT_ID}/assignee',
            headers=doc_auth_headers,
            json={'assignee_id': str(doc_user.id)},
        )
        assert given.status_code == status.HTTP_204_NO_CONTENT, given.text

        task = _task(
            _work_items(client, doc_auth_headers), f'certificate_check:{_CERT_ID}'
        )
        assert task is not None
        assert task['assignee_id'] == str(doc_user.id)

    def test_a_provider_that_fails_does_not_empty_the_list(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        certificate_provider: None,
    ) -> None:
        warehouse_api.register_work_item_provider('stock_takes', _broken_provider)
        try:
            section = _work_items(client, doc_auth_headers)
        finally:
            from app.modules.stock_takes.stock_takes_api import stock_takes_api

            warehouse_api.register_work_item_provider(
                'stock_takes', stock_takes_api.list_work_items_async
            )

        assert _task(section, f'certificate_check:{_CERT_ID}') is not None
