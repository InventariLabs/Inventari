"""A warehouse may receive in two steps: into a receiving area, then away.

One step is the default: a receipt puts its goods on the shelf the putaway
rules choose. A warehouse that unloads at the dock and shelves later chooses
two steps; its receipts then land in its receiving area — a location made
inside the warehouse when the mode is first used — and every product waiting
there is a putaway task in To do, naming the shelf the rules suggest. Doing
the task posts the move.

The task is the receipt line, not the stock record: two lines of one
product share a record in the receiving area, yet each is its own carry to
the shelf that has room for it.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.public_api import core_api
from app.core.testing import ModuleTestHelper
from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.user import User
from app.modules.warehouse.models import DocumentStatus


@pytest.fixture
def warehouse(
    h: ModuleTestHelper,
    doc_org: Organization,
    doc_storage_type: StorageType,
    doc_user: User,
) -> StorageLocation:
    return h.create_storage_location(
        doc_org, doc_storage_type, doc_user, name='Main Warehouse'
    )


@pytest.fixture
def shelf(
    db_session: Session,
    h: ModuleTestHelper,
    doc_org: Organization,
    doc_storage_type: StorageType,
    doc_user: User,
    warehouse: StorageLocation,
) -> StorageLocation:
    location = h.create_storage_location(
        doc_org, doc_storage_type, doc_user, name='Shelf A - Top'
    )
    location.parent_id = warehouse.id
    db_session.commit()
    return location


@pytest.fixture
def rice(h: ModuleTestHelper, doc_org: Organization) -> ProductTemplate:
    return h.create_template(doc_org, name='Jasmine Rice')


def _choose(
    client: TestClient,
    headers: dict[str, str],
    warehouse_id: UUID,
    *,
    two_step: bool,
) -> dict[str, Any]:
    resp = client.put(
        f'/api/v1/warehouse/putaway/receiving-modes/{warehouse_id}',
        headers=headers,
        json={'two_step': two_step},
    )
    assert resp.status_code == status.HTTP_200_OK, resp.text
    return cast(dict[str, Any], resp.json())


def _rule(
    client: TestClient,
    headers: dict[str, str],
    template: ProductTemplate,
    target: StorageLocation,
) -> None:
    resp = client.post(
        '/api/v1/warehouse/putaway-rules',
        headers=headers,
        json={
            'product_template_id': str(template.id),
            'target_location_id': str(target.id),
        },
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text


def _receive(
    client: TestClient,
    headers: dict[str, str],
    *,
    partner: Partner,
    target: StorageLocation,
    template: ProductTemplate,
    quantity: int,
) -> dict[str, Any]:
    resp = client.post(
        '/api/v1/warehouse/documents/post',
        headers=headers,
        json={
            'type': 'IN',
            'partner_id': str(partner.id),
            'target_location_id': str(target.id),
            'lines': [
                {'product_template_id': str(template.id), 'expected_quantity': quantity}
            ],
        },
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    body = cast(dict[str, Any], resp.json())
    assert body['status'] == DocumentStatus.COMPLETED.value
    return body


def _putaway_tasks(client: TestClient, headers: dict[str, str]) -> list[dict[str, Any]]:
    resp = client.get(
        '/api/v1/warehouse/todo',
        headers=headers,
        params={'date_to': date.today().isoformat()},
    )
    assert resp.status_code == status.HTTP_200_OK, resp.text
    return [
        item for item in resp.json()['work_items']['items'] if item['kind'] == 'putaway'
    ]


def _second_shelf(
    db: Session,
    h: ModuleTestHelper,
    org: Organization,
    storage_type: StorageType,
    user: User,
    warehouse: StorageLocation,
) -> StorageLocation:
    location = h.create_storage_location(org, storage_type, user, name='Shelf B')
    location.parent_id = warehouse.id
    db.commit()
    return location


def _limit(
    client: TestClient,
    headers: dict[str, str],
    location: StorageLocation,
    template: ProductTemplate,
    max_quantity: int,
) -> None:
    resp = client.post(
        '/api/v1/warehouse/putaway/capacity',
        headers=headers,
        json={
            'location_id': str(location.id),
            'product_template_id': str(template.id),
            'max_quantity': str(max_quantity),
        },
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text


def _put_away(
    client: TestClient, headers: dict[str, str], task: dict[str, Any]
) -> dict[str, Any]:
    resp = client.post(
        f'/api/v1/warehouse/work-items/putaway/{task["source_id"]}',
        headers=headers,
        json={'location_id': task['place_id']},
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    return cast(dict[str, Any], resp.json())


def _stock_at(db: Session, template: ProductTemplate, location_id: UUID) -> Decimal:
    db.expire_all()
    rows = db.scalars(
        select(Item).where(
            Item.template_id == template.id,
            Item.storage_location_id == location_id,
            Item.is_deleted.is_(False),
        )
    ).all()
    return sum((row.quantity or Decimal('0') for row in rows), Decimal('0'))


@pytest.mark.integration
class TestTwoStepReceiving:
    def test_a_warehouse_receives_in_one_step_until_it_chooses_two(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        warehouse: StorageLocation,
        shelf: StorageLocation,
        rice: ProductTemplate,
    ) -> None:
        listed = client.get(
            '/api/v1/warehouse/putaway/receiving-modes', headers=doc_auth_headers
        )
        assert listed.status_code == status.HTTP_200_OK, listed.text
        assert listed.json()['items'] == []

        _rule(client, doc_auth_headers, rice, shelf)
        _receive(
            client,
            doc_auth_headers,
            partner=doc_partner,
            target=warehouse,
            template=rice,
            quantity=40,
        )

        assert _stock_at(db_session, rice, shelf.id) == Decimal('40')
        assert _putaway_tasks(client, doc_auth_headers) == []

    def test_choosing_two_steps_makes_the_receiving_area_inside_the_warehouse(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        warehouse: StorageLocation,
    ) -> None:
        chosen = _choose(client, doc_auth_headers, warehouse.id, two_step=True)

        assert chosen['warehouse_id'] == str(warehouse.id)
        assert chosen['two_step'] is True
        area = db_session.get(StorageLocation, UUID(chosen['receiving_location_id']))
        assert area is not None
        assert area.parent_id == warehouse.id
        assert area.name == 'Receiving'
        assert area.usage == 'internal'
        assert chosen['receiving_location_name'] == 'Receiving'

        listed = client.get(
            '/api/v1/warehouse/putaway/receiving-modes', headers=doc_auth_headers
        ).json()['items']
        assert [row['warehouse_id'] for row in listed] == [str(warehouse.id)]

        # Back to one step and on again: the same area, not a second one.
        _choose(client, doc_auth_headers, warehouse.id, two_step=False)
        again = _choose(client, doc_auth_headers, warehouse.id, two_step=True)
        assert again['receiving_location_id'] == chosen['receiving_location_id']

    def test_only_a_warehouse_chooses_how_it_receives(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        shelf: StorageLocation,
    ) -> None:
        resp = client.put(
            f'/api/v1/warehouse/putaway/receiving-modes/{shelf.id}',
            headers=doc_auth_headers,
            json={'two_step': True},
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.text

    def test_a_two_step_receipt_lands_in_receiving_and_each_product_waits_as_a_task(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_partner: Partner,
        h: ModuleTestHelper,
        warehouse: StorageLocation,
        shelf: StorageLocation,
        rice: ProductTemplate,
    ) -> None:
        beans = h.create_template(doc_org, name='Black Beans')
        _rule(client, doc_auth_headers, rice, shelf)
        area_id = UUID(
            _choose(client, doc_auth_headers, warehouse.id, two_step=True)[
                'receiving_location_id'
            ]
        )

        resp = client.post(
            '/api/v1/warehouse/documents/post',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(warehouse.id),
                'lines': [
                    {'product_template_id': str(rice.id), 'expected_quantity': 40},
                    {'product_template_id': str(beans.id), 'expected_quantity': 12},
                ],
            },
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        lines = resp.json()['lines']
        assert {line['executed_location_id'] for line in lines} == {str(area_id)}

        assert _stock_at(db_session, rice, area_id) == Decimal('40')
        assert _stock_at(db_session, rice, shelf.id) == Decimal('0')

        tasks = {
            task['subject']: task for task in _putaway_tasks(client, doc_auth_headers)
        }
        assert set(tasks) == {'Jasmine Rice', 'Black Beans'}
        rice_task = tasks['Jasmine Rice']
        assert rice_task['next_action'] == 'put_away'
        assert rice_task['state'] == 'todo'
        assert Decimal(rice_task['count']) == Decimal('40')
        # The shelf the putaway rule names is the suggestion.
        assert rice_task['place'] == 'Shelf A - Top'
        assert rice_task['place_id'] == str(shelf.id)
        # Nothing asked for the label under this profile.
        assert rice_task['shelf_scan_required'] is False
        # No rule names a shelf for the beans: the worker chooses one.
        assert tasks['Black Beans']['place_id'] is None

    def test_putting_a_task_away_posts_the_move_and_ends_the_task(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        warehouse: StorageLocation,
        shelf: StorageLocation,
        rice: ProductTemplate,
    ) -> None:
        _rule(client, doc_auth_headers, rice, shelf)
        area_id = UUID(
            _choose(client, doc_auth_headers, warehouse.id, two_step=True)[
                'receiving_location_id'
            ]
        )
        _receive(
            client,
            doc_auth_headers,
            partner=doc_partner,
            target=warehouse,
            template=rice,
            quantity=40,
        )
        (task,) = _putaway_tasks(client, doc_auth_headers)

        moved = client.post(
            f'/api/v1/warehouse/work-items/putaway/{task["source_id"]}',
            headers=doc_auth_headers,
            json={'location_id': task['place_id']},
        )
        assert moved.status_code == status.HTTP_201_CREATED, moved.text
        body = moved.json()
        assert body['type'] == 'INT'
        assert body['status'] == DocumentStatus.COMPLETED.value
        assert body['source_location_id'] == str(area_id)
        assert body['target_location_id'] == str(shelf.id)

        assert _stock_at(db_session, rice, shelf.id) == Decimal('40')
        assert _stock_at(db_session, rice, area_id) == Decimal('0')
        assert _putaway_tasks(client, doc_auth_headers) == []

    def test_the_shelf_label_confirms_the_place_before_the_move_is_posted(
        self,
        client: TestClient,
        db_session: Session,
        h: ModuleTestHelper,
        doc_org: Organization,
        doc_storage_type: StorageType,
        doc_user: User,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        warehouse: StorageLocation,
        shelf: StorageLocation,
        rice: ProductTemplate,
    ) -> None:
        """The setting is the shelf's answer, not the screen's: nothing posts
        until the code the worker read resolves to the shelf they chose."""
        shelf.short_code = 'SHF-A1'
        other = _second_shelf(
            db_session, h, doc_org, doc_storage_type, doc_user, warehouse
        )
        other.short_code = 'SHF-B2'
        db_session.commit()
        turned_on = client.put(
            '/api/v1/warehouse/profile',
            headers=doc_auth_headers,
            json={'confirm_shelf_by_scan': True},
        )
        assert turned_on.status_code == status.HTTP_200_OK, turned_on.text
        _rule(client, doc_auth_headers, rice, shelf)
        area_id = UUID(
            _choose(client, doc_auth_headers, warehouse.id, two_step=True)[
                'receiving_location_id'
            ]
        )
        _receive(
            client,
            doc_auth_headers,
            partner=doc_partner,
            target=warehouse,
            template=rice,
            quantity=40,
        )
        (task,) = _putaway_tasks(client, doc_auth_headers)
        assert task['shelf_scan_required'] is True
        assert task['place_code'] == 'SHF-A1'
        post = f'/api/v1/warehouse/work-items/putaway/{task["source_id"]}'

        unchecked = client.post(
            post,
            headers=doc_auth_headers,
            json={'location_id': task['place_id']},
        )
        assert unchecked.status_code == status.HTTP_400_BAD_REQUEST, unchecked.text
        wrong = client.post(
            post,
            headers=doc_auth_headers,
            json={'location_id': task['place_id'], 'scanned_code': 'SHF-B2'},
        )
        assert wrong.status_code == status.HTTP_400_BAD_REQUEST, wrong.text
        assert _stock_at(db_session, rice, shelf.id) == Decimal('0')
        assert _stock_at(db_session, rice, area_id) == Decimal('40')

        moved = client.post(
            post,
            headers=doc_auth_headers,
            json={'location_id': task['place_id'], 'scanned_code': 'SHF-A1'},
        )
        assert moved.status_code == status.HTTP_201_CREATED, moved.text
        assert _stock_at(db_session, rice, shelf.id) == Decimal('40')
        assert _stock_at(db_session, rice, area_id) == Decimal('0')

    def test_a_record_outside_a_receiving_area_is_no_putaway_task(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_stock_item: Item,
        shelf: StorageLocation,
    ) -> None:
        resp = client.post(
            f'/api/v1/warehouse/work-items/putaway/{doc_stock_item.id}',
            headers=doc_auth_headers,
            json={'location_id': str(shelf.id)},
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND, resp.text

    def test_a_receiving_area_that_was_removed_is_made_again_on_the_next_receipt(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        warehouse: StorageLocation,
        rice: ProductTemplate,
    ) -> None:
        area_id = UUID(
            _choose(client, doc_auth_headers, warehouse.id, two_step=True)[
                'receiving_location_id'
            ]
        )
        area = db_session.get(StorageLocation, area_id)
        db_session.delete(area)
        db_session.commit()

        body = _receive(
            client,
            doc_auth_headers,
            partner=doc_partner,
            target=warehouse,
            template=rice,
            quantity=5,
        )

        landed = UUID(body['lines'][0]['executed_location_id'])
        assert landed != area_id
        new_area = db_session.get(StorageLocation, landed)
        assert new_area is not None
        assert new_area.parent_id == warehouse.id
        assert new_area.name == 'Receiving'

    def test_a_draft_receipt_plans_the_receiving_area(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        warehouse: StorageLocation,
        shelf: StorageLocation,
        rice: ProductTemplate,
    ) -> None:
        _rule(client, doc_auth_headers, rice, shelf)
        area_id = _choose(client, doc_auth_headers, warehouse.id, two_step=True)[
            'receiving_location_id'
        ]
        created = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(warehouse.id),
                'lines': [
                    {'product_template_id': str(rice.id), 'expected_quantity': 3}
                ],
            },
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        doc = client.get(
            f'/api/v1/warehouse/documents/{created.json()["id"]}',
            headers=doc_auth_headers,
        ).json()
        (line,) = doc['lines']
        assert line['planned_location_id'] == area_id
        assert line['planned_source'] == 'receiving'

    def test_two_lines_of_one_product_are_two_tasks_each_to_a_shelf_with_room(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_storage_type: StorageType,
        doc_user: User,
        doc_partner: Partner,
        h: ModuleTestHelper,
        warehouse: StorageLocation,
        shelf: StorageLocation,
        rice: ProductTemplate,
    ) -> None:
        shelf_b = _second_shelf(
            db_session, h, doc_org, doc_storage_type, doc_user, warehouse
        )
        _limit(client, doc_auth_headers, shelf, rice, 50)
        _limit(client, doc_auth_headers, shelf_b, rice, 50)
        resp = client.post(
            '/api/v1/warehouse/putaway-rules',
            headers=doc_auth_headers,
            json={
                'product_template_id': str(rice.id),
                'location_ids': [str(shelf.id), str(shelf_b.id)],
            },
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        area_id = UUID(
            _choose(client, doc_auth_headers, warehouse.id, two_step=True)[
                'receiving_location_id'
            ]
        )

        resp = client.post(
            '/api/v1/warehouse/documents/post',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(warehouse.id),
                'lines': [
                    {'product_template_id': str(rice.id), 'expected_quantity': 40},
                    {'product_template_id': str(rice.id), 'expected_quantity': 40},
                ],
            },
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        assert _stock_at(db_session, rice, area_id) == Decimal('80')

        # One record holds both lines; the shelves have room for one each.
        first_line, second_line = (line['id'] for line in resp.json()['lines'])
        tasks = {t['source_id']: t for t in _putaway_tasks(client, doc_auth_headers)}
        assert {
            line_id: (Decimal(t['count']), t['place_id'])
            for line_id, t in tasks.items()
        } == {
            first_line: (Decimal('40'), str(shelf.id)),
            second_line: (Decimal('40'), str(shelf_b.id)),
        }

        # The second line goes first: the first line's task stays as it was.
        _put_away(client, doc_auth_headers, tasks[second_line])
        assert _stock_at(db_session, rice, shelf_b.id) == Decimal('40')
        assert _stock_at(db_session, rice, area_id) == Decimal('40')
        (left,) = _putaway_tasks(client, doc_auth_headers)
        assert left['source_id'] == first_line
        assert Decimal(left['count']) == Decimal('40')
        assert left['place_id'] == str(shelf.id)

        _put_away(client, doc_auth_headers, left)
        assert _stock_at(db_session, rice, shelf.id) == Decimal('40')
        assert _stock_at(db_session, rice, area_id) == Decimal('0')
        assert _putaway_tasks(client, doc_auth_headers) == []

    def test_each_delivery_waits_as_its_own_task_and_a_done_one_is_no_task(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        warehouse: StorageLocation,
        shelf: StorageLocation,
        rice: ProductTemplate,
    ) -> None:
        _rule(client, doc_auth_headers, rice, shelf)
        area_id = UUID(
            _choose(client, doc_auth_headers, warehouse.id, two_step=True)[
                'receiving_location_id'
            ]
        )
        first = _receive(
            client,
            doc_auth_headers,
            partner=doc_partner,
            target=warehouse,
            template=rice,
            quantity=12,
        )
        second = _receive(
            client,
            doc_auth_headers,
            partner=doc_partner,
            target=warehouse,
            template=rice,
            quantity=8,
        )

        tasks = {t['number']: t for t in _putaway_tasks(client, doc_auth_headers)}
        assert {n: Decimal(t['count']) for n, t in tasks.items()} == {
            first['number']: Decimal('12'),
            second['number']: Decimal('8'),
        }

        done = tasks[first['number']]
        _put_away(client, doc_auth_headers, done)
        assert _stock_at(db_session, rice, shelf.id) == Decimal('12')
        assert _stock_at(db_session, rice, area_id) == Decimal('8')
        assert [t['number'] for t in _putaway_tasks(client, doc_auth_headers)] == [
            second['number']
        ]

        again = client.post(
            f'/api/v1/warehouse/work-items/putaway/{done["source_id"]}',
            headers=doc_auth_headers,
            json={'location_id': str(shelf.id)},
        )
        assert again.status_code == status.HTTP_404_NOT_FOUND, again.text

    def test_goods_moved_off_the_dock_by_hand_end_the_oldest_delivery_first(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        warehouse: StorageLocation,
        shelf: StorageLocation,
        rice: ProductTemplate,
    ) -> None:
        area_id = _choose(client, doc_auth_headers, warehouse.id, two_step=True)[
            'receiving_location_id'
        ]
        first = _receive(
            client,
            doc_auth_headers,
            partner=doc_partner,
            target=warehouse,
            template=rice,
            quantity=12,
        )
        second = _receive(
            client,
            doc_auth_headers,
            partner=doc_partner,
            target=warehouse,
            template=rice,
            quantity=8,
        )
        record_id = first['lines'][0]['item_id']
        assert second['lines'][0]['item_id'] == record_id

        moved = client.post(
            '/api/v1/warehouse/documents/post',
            headers=doc_auth_headers,
            json={
                'type': 'INT',
                'source_location_id': area_id,
                'target_location_id': str(shelf.id),
                'lines': [{'item_id': record_id, 'expected_quantity': 15}],
            },
        )
        assert moved.status_code == status.HTTP_201_CREATED, moved.text

        (left,) = _putaway_tasks(client, doc_auth_headers)
        assert left['number'] == second['number']
        assert Decimal(left['count']) == Decimal('5')

    def test_the_receipts_long_since_cleared_are_not_read_again(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        warehouse: StorageLocation,
        shelf: StorageLocation,
        rice: ProductTemplate,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        area_id = _choose(client, doc_auth_headers, warehouse.id, two_step=True)[
            'receiving_location_id'
        ]
        receipts = [
            _receive(
                client,
                doc_auth_headers,
                partner=doc_partner,
                target=warehouse,
                template=rice,
                quantity=4,
            )
            for _ in range(6)
        ]
        moved = client.post(
            '/api/v1/warehouse/documents/post',
            headers=doc_auth_headers,
            json={
                'type': 'INT',
                'source_location_id': area_id,
                'target_location_id': str(shelf.id),
                'lines': [
                    {
                        'item_id': receipts[0]['lines'][0]['item_id'],
                        'expected_quantity': 20,
                    }
                ],
            },
        )
        assert moved.status_code == status.HTTP_201_CREATED, moved.text

        reads: list[object] = []
        convert = core_api.uoms.to_stock_uom_async

        async def counting(*args: Any, **kwargs: Any) -> Decimal:
            reads.append(args)
            return cast(Decimal, await convert(*args, **kwargs))

        monkeypatch.setattr(core_api.uoms, 'to_stock_uom_async', counting)

        (left,) = _putaway_tasks(client, doc_auth_headers)

        assert left['number'] == receipts[-1]['number']
        # Only the newest delivery can still have goods waiting: the older
        # ones were answered for the moment the area's stock was.
        assert len(reads) == 1

    def test_a_task_with_no_rule_offers_the_shelf_the_product_already_lies_on(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_storage_type: StorageType,
        doc_user: User,
        doc_partner: Partner,
        h: ModuleTestHelper,
        warehouse: StorageLocation,
        shelf: StorageLocation,
        rice: ProductTemplate,
    ) -> None:
        shelf_b = _second_shelf(
            db_session, h, doc_org, doc_storage_type, doc_user, warehouse
        )
        shelf.short_code = 'A-01-01'
        shelf_b.short_code = 'A-02-01'
        db_session.commit()
        beans = h.create_template(doc_org, name='Black Beans')
        _choose(client, doc_auth_headers, warehouse.id, two_step=True)

        # The beans wait in the area; the worker carries them to Shelf B.
        _receive(
            client,
            doc_auth_headers,
            partner=doc_partner,
            target=warehouse,
            template=beans,
            quantity=12,
        )
        (beans_task,) = _putaway_tasks(client, doc_auth_headers)
        assert beans_task['place_id'] is None
        moved = client.post(
            f'/api/v1/warehouse/work-items/putaway/{beans_task["source_id"]}',
            headers=doc_auth_headers,
            json={'location_id': str(shelf_b.id)},
        )
        assert moved.status_code == status.HTTP_201_CREATED, moved.text

        # A later move to Shelf A makes that the last shelf used in the zone;
        # the beans still lie on Shelf B, and that is the answer.
        _receive(
            client,
            doc_auth_headers,
            partner=doc_partner,
            target=warehouse,
            template=rice,
            quantity=5,
        )
        (rice_task,) = _putaway_tasks(client, doc_auth_headers)
        moved = client.post(
            f'/api/v1/warehouse/work-items/putaway/{rice_task["source_id"]}',
            headers=doc_auth_headers,
            json={'location_id': str(shelf.id)},
        )
        assert moved.status_code == status.HTTP_201_CREATED, moved.text

        _receive(
            client,
            doc_auth_headers,
            partner=doc_partner,
            target=warehouse,
            template=beans,
            quantity=4,
        )
        (task,) = _putaway_tasks(client, doc_auth_headers)
        assert task['place_id'] == str(shelf_b.id)
        assert task['place'] == 'Shelf B'
        assert task['place_code'] == 'A-02-01'
        assert task['place_source'] == 'stock'

    def test_a_task_with_no_rule_offers_the_last_shelf_used_in_the_warehouse(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_storage_type: StorageType,
        doc_user: User,
        doc_partner: Partner,
        h: ModuleTestHelper,
        warehouse: StorageLocation,
        shelf: StorageLocation,
        rice: ProductTemplate,
    ) -> None:
        shelf.short_code = 'A-01-01'
        db_session.commit()
        beans = h.create_template(doc_org, name='Black Beans')
        _choose(client, doc_auth_headers, warehouse.id, two_step=True)

        # Nothing tells this task where the rice goes, so the worker chooses.
        _receive(
            client,
            doc_auth_headers,
            partner=doc_partner,
            target=warehouse,
            template=rice,
            quantity=5,
        )
        (rice_task,) = _putaway_tasks(client, doc_auth_headers)
        assert rice_task['place_id'] is None
        assert rice_task['place_source'] is None
        moved = client.post(
            f'/api/v1/warehouse/work-items/putaway/{rice_task["source_id"]}',
            headers=doc_auth_headers,
            json={'location_id': str(shelf.id)},
        )
        assert moved.status_code == status.HTTP_201_CREATED, moved.text

        # The beans have never stood in this warehouse: the shelf the last
        # move used is the only sensible answer left.
        _receive(
            client,
            doc_auth_headers,
            partner=doc_partner,
            target=warehouse,
            template=beans,
            quantity=3,
        )
        (task,) = _putaway_tasks(client, doc_auth_headers)
        assert task['place_id'] == str(shelf.id)
        assert task['place'] == 'Shelf A - Top'
        assert task['place_code'] == 'A-01-01'
        assert task['place_source'] == 'zone'
