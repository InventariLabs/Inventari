"""Reserve shelves fill a pick face before anything is bought.

A reorder rule fires on the pick face, but the product still stands on the
reserve rack of the same warehouse. The alert proposes an internal move from
that rack — unreserved, active batches, oldest first — and only what the rack
cannot cover reaches a draft purchase order. Acting on the proposal posts one
ordinary transfer (INT), and the shortage is gone with it.

The four cases the task names are here: reserve covers all, covers part,
covers nothing, and what a proposal may not touch (quarantine, reservations,
another warehouse, a pick face marked as reserve).
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any, cast

import pytest
from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.testing import ModuleTestHelper
from app.models.item import Item
from app.models.storage_location import StorageLocation
from app.modules.purchase_orders.models import ReorderRule
from app.modules.warehouse.models.profile import DocumentProfile
from tests.integration._shelf import (
    post_on_shelf,
    put_on_shelf,
    reserve_for_an_order,
    run_in_async_session,
    shelf_keeper,
)

ALERTS_URL = '/api/v1/purchase-orders/replenishment/alerts'
PROPOSAL_URL = '/api/v1/purchase-orders/replenishment/proposals'
TODO_URL = '/api/v1/warehouse/todo'
DRAFT_POS_URL = '/api/v1/purchase-orders/replenishment/draft-pos'


def _shelf(
    db: Session,
    org: Any,
    user: Any,
    parent: StorageLocation | None,
    name: str,
    *,
    reserve: bool = False,
) -> StorageLocation:
    location = StorageLocation(
        organization_id=org.id,
        name=name,
        parent_id=parent.id if parent is not None else None,
        created_by=user.id,
        settings={'is_reserve': True} if reserve else None,
    )
    db.add(location)
    db.commit()
    db.refresh(location)
    return location


def _rule(
    db: Session,
    org: Any,
    template: Any,
    location: StorageLocation,
    *,
    min_qty: str = '10',
    max_qty: str = '20',
    partner_id: Any = None,
) -> ReorderRule:
    rule = ReorderRule(
        organization_id=org.id,
        product_template_id=template.id,
        storage_location_id=location.id,
        min_quantity=Decimal(min_qty),
        max_quantity=Decimal(max_qty),
        safety_stock=Decimal('0'),
        preferred_partner_id=partner_id,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


def _two_pick_faces_on_one_reserve_pool(
    client: TestClient,
    headers: dict[str, str],
    db: Session,
    org: Any,
    user: Any,
    parent: StorageLocation,
    template: Any,
    partner: Any,
    first_pick: StorageLocation,
    reserve: StorageLocation,
) -> tuple[ReorderRule, ReorderRule]:
    """Two pick faces below their minimum, one reserve shelf between them."""
    second_pick = _shelf(db, org, user, parent, 'Pick B-02')
    first_rule = _rule(db, org, template, first_pick, partner_id=partner.id)
    second_rule = _rule(db, org, template, second_pick, partner_id=partner.id)
    post_on_shelf(client, headers, template, first_pick.id, '3')
    post_on_shelf(client, headers, template, second_pick.id, '3')
    post_on_shelf(client, headers, template, reserve.id, '20')
    return first_rule, second_rule


def _alerts(
    client: TestClient, headers: dict[str, str], rule: ReorderRule
) -> dict[str, Any]:
    response = client.get(ALERTS_URL, headers=headers)
    assert response.status_code == status.HTTP_200_OK, response.text
    found = [
        row
        for row in response.json()['items']
        if row['reorder_rule_id'] == str(rule.id)
    ]
    assert len(found) == 1, response.text
    return cast(dict[str, Any], found[0])


def _rule_alerts(
    client: TestClient, headers: dict[str, str], rule: ReorderRule
) -> list[dict[str, Any]]:
    """Every alert the rule has — empty where the shortage no longer stands."""
    response = client.get(ALERTS_URL, headers=headers)
    assert response.status_code == status.HTTP_200_OK, response.text
    return [
        cast(dict[str, Any], row)
        for row in response.json()['items']
        if row['reorder_rule_id'] == str(rule.id)
    ]


def _tasks(client: TestClient, headers: dict[str, str]) -> list[dict[str, Any]]:
    response = client.get(
        TODO_URL,
        params={'date_to': date.today().isoformat()},
        headers=headers,
    )
    assert response.status_code == status.HTTP_200_OK, response.text
    return cast(list[dict[str, Any]], response.json()['work_items']['items'])


@pytest.fixture
def approving_org(h: ModuleTestHelper) -> Any:
    """An organisation where an internal transfer needs a signature first."""
    org: Any = h.create_org(
        'Reserve Approval Org',
        [
            'core',
            'items',
            'locations',
            'categories',
            'warehouse',
            'purchase_orders',
            'approvals',
        ],
    )
    h.set_module_settings(org, 'approvals', {'allow_admin_self_approve': True})
    return org


class TestReserveReplenishment:
    @pytest.fixture
    def pick_face(
        self, db_session: Session, po_org: Any, po_user: Any, po_location: Any
    ) -> StorageLocation:
        return _shelf(db_session, po_org, po_user, po_location, 'Pick B-01')

    @pytest.fixture
    def reserve_rack(
        self, db_session: Session, po_org: Any, po_user: Any, po_location: Any
    ) -> StorageLocation:
        return _shelf(
            db_session, po_org, po_user, po_location, 'Reserve R-12', reserve=True
        )

    def test_reserve_covers_all_leaves_nothing_to_buy(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        db_session: Session,
        po_org: Any,
        po_partner: Any,
        po_template: Any,
        pick_face: StorageLocation,
        reserve_rack: StorageLocation,
    ) -> None:
        rule = _rule(
            db_session,
            po_org,
            po_template,
            pick_face,
            partner_id=po_partner.id,
        )
        post_on_shelf(client, po_auth_headers, po_template, pick_face.id, '3')
        post_on_shelf(client, po_auth_headers, po_template, reserve_rack.id, '40')

        alert = _alerts(client, po_auth_headers, rule)
        assert alert['suggested_reorder_quantity'] == 17.0
        assert alert['reserve_available_quantity'] == 40.0
        assert alert['proposed_move_quantity'] == 17.0
        assert alert['remaining_to_buy'] == 0.0

        draft = client.post(
            DRAFT_POS_URL,
            json={'reorder_rule_ids': [str(rule.id)]},
            headers=po_auth_headers,
        )
        assert draft.status_code == status.HTTP_201_CREATED, draft.text
        assert draft.json()['created'] == []
        assert draft.json()['skipped'][0]['reason'] == 'covered_by_reserve'

    def test_reserve_covers_part_and_the_order_is_the_remainder(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        db_session: Session,
        po_org: Any,
        po_partner: Any,
        po_template: Any,
        pick_face: StorageLocation,
        reserve_rack: StorageLocation,
    ) -> None:
        rule = _rule(
            db_session,
            po_org,
            po_template,
            pick_face,
            partner_id=po_partner.id,
        )
        post_on_shelf(client, po_auth_headers, po_template, pick_face.id, '3')
        post_on_shelf(client, po_auth_headers, po_template, reserve_rack.id, '5')

        alert = _alerts(client, po_auth_headers, rule)
        assert alert['reserve_available_quantity'] == 5.0
        assert alert['proposed_move_quantity'] == 5.0
        assert alert['remaining_to_buy'] == 12.0

        draft = client.post(
            DRAFT_POS_URL,
            json={'reorder_rule_ids': [str(rule.id)]},
            headers=po_auth_headers,
        )
        assert draft.status_code == status.HTTP_201_CREATED, draft.text
        created = draft.json()['created']
        assert len(created) == 1
        assert created[0]['lines'][0]['quantity_ordered'] == '12.000'

    def test_two_reserve_shelves_leave_nothing_to_buy(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        db_session: Session,
        po_org: Any,
        po_user: Any,
        po_partner: Any,
        po_template: Any,
        po_location: Any,
        pick_face: StorageLocation,
        reserve_rack: StorageLocation,
    ) -> None:
        """Reserve is the warehouse's, not one shelf's: 10 + 10 covers 17."""
        second_reserve = _shelf(
            db_session, po_org, po_user, po_location, 'Reserve R-13', reserve=True
        )
        rule = _rule(
            db_session,
            po_org,
            po_template,
            pick_face,
            partner_id=po_partner.id,
        )
        post_on_shelf(client, po_auth_headers, po_template, pick_face.id, '3')
        post_on_shelf(client, po_auth_headers, po_template, reserve_rack.id, '10')
        post_on_shelf(client, po_auth_headers, po_template, second_reserve.id, '10')

        alert = _alerts(client, po_auth_headers, rule)
        assert alert['reserve_available_quantity'] == 20.0
        # One move still draws from the shelf holding the most...
        assert alert['proposed_move_quantity'] == 10.0
        # ...but reserve as a whole covers the shortage, so nothing is bought.
        assert alert['remaining_to_buy'] == 0.0

        draft = client.post(
            DRAFT_POS_URL,
            json={'reorder_rule_ids': [str(rule.id)]},
            headers=po_auth_headers,
        )
        assert draft.status_code == status.HTTP_201_CREATED, draft.text
        assert draft.json()['created'] == []
        assert draft.json()['skipped'][0]['reason'] == 'covered_by_reserve'

    def test_two_pick_faces_share_one_reserve_pool(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        db_session: Session,
        po_org: Any,
        po_user: Any,
        po_partner: Any,
        po_template: Any,
        po_location: Any,
        pick_face: StorageLocation,
        reserve_rack: StorageLocation,
    ) -> None:
        """Reserve is one pool: twenty on the rack cannot cover two seventeens."""
        first_rule, second_rule = _two_pick_faces_on_one_reserve_pool(
            client,
            po_auth_headers,
            db_session,
            po_org,
            po_user,
            po_location,
            po_template,
            po_partner,
            pick_face,
            reserve_rack,
        )

        first = _alerts(client, po_auth_headers, first_rule)
        second = _alerts(client, po_auth_headers, second_rule)
        # Both rows see the same rack, because it is the warehouse's stock...
        assert first['reserve_available_quantity'] == 20.0
        assert second['reserve_available_quantity'] == 20.0
        # ...but its units are promised once, so fourteen are still missing.
        assert first['remaining_to_buy'] + second['remaining_to_buy'] == 14.0
        assert sorted(
            [first['proposed_move_quantity'], second['proposed_move_quantity']]
        ) == [3.0, 17.0]
        # The tasks tell the same story: neither promises more than its share.
        assert sorted(
            float(task['count'])
            for task in _tasks(client, po_auth_headers)
            if task['source_kind'] == 'replenishment'
        ) == [3.0, 17.0]

        draft = client.post(
            DRAFT_POS_URL,
            json={
                'reorder_rule_ids': [str(first_rule.id), str(second_rule.id)],
            },
            headers=po_auth_headers,
        )
        assert draft.status_code == status.HTTP_201_CREATED, draft.text
        created = draft.json()['created']
        assert len(created) == 1
        assert [line['quantity_ordered'] for line in created[0]['lines']] == ['14.000']
        assert [row['reason'] for row in draft.json()['skipped']] == [
            'covered_by_reserve'
        ]

    def test_a_batch_of_one_rule_still_counts_the_other_alert(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        db_session: Session,
        po_org: Any,
        po_user: Any,
        po_partner: Any,
        po_template: Any,
        po_location: Any,
        pick_face: StorageLocation,
        reserve_rack: StorageLocation,
    ) -> None:
        """One draft batch cannot count a shelf another alert already claimed."""
        first_rule, second_rule = _two_pick_faces_on_one_reserve_pool(
            client,
            po_auth_headers,
            db_session,
            po_org,
            po_user,
            po_location,
            po_template,
            po_partner,
            pick_face,
            reserve_rack,
        )
        first = _alerts(client, po_auth_headers, first_rule)
        remainder_rule = first_rule if first['remaining_to_buy'] > 0 else second_rule

        draft = client.post(
            DRAFT_POS_URL,
            json={'reorder_rule_ids': [str(remainder_rule.id)]},
            headers=po_auth_headers,
        )
        assert draft.status_code == status.HTTP_201_CREATED, draft.text
        created = draft.json()['created']
        assert len(created) == 1
        assert created[0]['lines'][0]['quantity_ordered'] == '14.000'

    def test_no_reserve_still_buys_the_whole_shortage(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        db_session: Session,
        po_org: Any,
        po_partner: Any,
        po_template: Any,
        pick_face: StorageLocation,
    ) -> None:
        rule = _rule(
            db_session,
            po_org,
            po_template,
            pick_face,
            partner_id=po_partner.id,
        )
        post_on_shelf(client, po_auth_headers, po_template, pick_face.id, '3')

        alert = _alerts(client, po_auth_headers, rule)
        assert alert['reserve_available_quantity'] == 0.0
        assert alert['proposed_move_quantity'] == 0.0
        assert alert['remaining_to_buy'] == 17.0

        draft = client.post(
            DRAFT_POS_URL,
            json={'reorder_rule_ids': [str(rule.id)]},
            headers=po_auth_headers,
        )
        assert draft.status_code == status.HTTP_201_CREATED, draft.text
        assert draft.json()['created'][0]['lines'][0]['quantity_ordered'] == '17.000'

    def test_the_proposal_is_a_task_and_posting_it_fills_the_shelf(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        db_session: Session,
        po_org: Any,
        po_template: Any,
        pick_face: StorageLocation,
        reserve_rack: StorageLocation,
    ) -> None:
        rule = _rule(db_session, po_org, po_template, pick_face)
        post_on_shelf(client, po_auth_headers, po_template, pick_face.id, '3')
        post_on_shelf(client, po_auth_headers, po_template, reserve_rack.id, '40')

        tasks = [
            task
            for task in _tasks(client, po_auth_headers)
            if task['source_kind'] == 'replenishment'
        ]
        assert len(tasks) == 1
        assert tasks[0]['kind'] == 'replenish'
        assert tasks[0]['source_id'] == str(rule.id)
        assert tasks[0]['subject'] == po_template.name
        assert float(tasks[0]['count']) == 17.0
        assert tasks[0]['place'] == pick_face.name
        assert tasks[0]['next_action'] == 'replenish'

        proposal = client.get(f'{PROPOSAL_URL}/{rule.id}', headers=po_auth_headers)
        assert proposal.status_code == status.HTTP_200_OK, proposal.text
        plan = proposal.json()
        assert plan['target_location_id'] == str(pick_face.id)
        assert Decimal(plan['quantity']) == Decimal('17.000')
        assert plan['lines'][0]['source_location_id'] == str(reserve_rack.id)

        moved = client.post(f'{PROPOSAL_URL}/{rule.id}/move', headers=po_auth_headers)
        assert moved.status_code == status.HTTP_201_CREATED, moved.text
        document = moved.json()
        assert document['type'] == 'INT'
        assert document['status'] == 'COMPLETED'
        posted = client.get(
            f'/api/v1/warehouse/documents/{document["id"]}', headers=po_auth_headers
        ).json()
        assert posted['source_location_id'] == str(reserve_rack.id)
        assert posted['target_location_id'] == str(pick_face.id)

        # The shelf was filled, so the alert and its task are gone.
        assert client.get(ALERTS_URL, headers=po_auth_headers).json()['items'] == []
        assert [
            task
            for task in _tasks(client, po_auth_headers)
            if task['source_kind'] == 'replenishment'
        ] == []

        db_session.expire_all()
        on_pick_face = db_session.scalars(
            select(Item).where(Item.storage_location_id == pick_face.id)
        ).all()
        assert sum((item.quantity for item in on_pick_face), Decimal('0')) == Decimal(
            '20.000'
        )

    def test_only_usable_stock_of_the_same_warehouse_is_proposed(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        po_org: Any,
        po_user: Any,
        po_template: Any,
        po_location: Any,
        pick_face: StorageLocation,
        reserve_rack: StorageLocation,
    ) -> None:
        """FEFO, active batches only, reservations held, one warehouse only."""
        rule = _rule(db_session, po_org, po_template, pick_face)
        post_on_shelf(client, po_auth_headers, po_template, pick_face.id, '3')
        other_warehouse = _shelf(db_session, po_org, po_user, None, 'Warehouse Two')
        other_reserve = _shelf(
            db_session, po_org, po_user, other_warehouse, 'Reserve far', reserve=True
        )
        post_on_shelf(client, po_auth_headers, po_template, other_reserve.id, '100')
        # A pick face is never a reserve source, whatever sits on it.
        other_pick = _shelf(db_session, po_org, po_user, other_warehouse, 'Pick B-02')
        post_on_shelf(client, po_auth_headers, po_template, other_pick.id, '100')
        db_session.commit()

        async def _stock(session: AsyncSession) -> None:
            keeper = await shelf_keeper(session, po_org.id)
            lot_early = await _lot(
                session, po_org.id, po_template.id, 'LOT-EARLY', days=5
            )
            lot_late = await _lot(
                session, po_org.id, po_template.id, 'LOT-LATE', days=50
            )
            lot_bad = await _lot(session, po_org.id, po_template.id, 'LOT-BAD', days=1)
            await put_on_shelf(
                session,
                keeper,
                po_template,
                reserve_rack.id,
                Decimal('10'),
                lot_id=lot_early,
                expiry_date=date.today() + timedelta(days=5),
            )
            await put_on_shelf(
                session,
                keeper,
                po_template,
                reserve_rack.id,
                Decimal('10'),
                lot_id=lot_late,
                expiry_date=date.today() + timedelta(days=50),
            )
            await put_on_shelf(
                session,
                keeper,
                po_template,
                reserve_rack.id,
                Decimal('100'),
                lot_id=lot_bad,
                expiry_date=date.today() + timedelta(days=1),
            )
            # A batch past its date is no cover: the planner will not draw it.
            lot_expired = await _lot(
                session, po_org.id, po_template.id, 'LOT-EXPIRED', days=-10
            )
            await put_on_shelf(
                session,
                keeper,
                po_template,
                reserve_rack.id,
                Decimal('50'),
                lot_id=lot_expired,
                expiry_date=date.today() + timedelta(days=-10),
            )
            from app.core.public_api import core_api

            await core_api.stock.set_lot_status_async(
                session, po_org.id, lot_bad, 'quarantined', 'recall'
            )
            await reserve_for_an_order(
                session, po_template, reserve_rack.id, Decimal('5')
            )

        run_in_async_session(async_engine_fixture, _stock)
        db_session.expire_all()

        alert = _alerts(client, po_auth_headers, rule)
        # 10 early + 10 late, less 5 held for an order; quarantine, the past
        # its date batch and the other warehouse are invisible.
        assert alert['reserve_available_quantity'] == 15.0
        assert alert['proposed_move_quantity'] == 15.0
        assert alert['remaining_to_buy'] == 2.0

        proposal = client.get(f'{PROPOSAL_URL}/{rule.id}', headers=po_auth_headers)
        assert proposal.status_code == status.HTTP_200_OK, proposal.text
        lines = proposal.json()['lines']
        # The early batch is drawn first; the hold leaves five of it behind.
        assert [line['lot_name'] for line in lines] == ['LOT-EARLY', 'LOT-LATE']
        assert [Decimal(line['quantity']) for line in lines] == [
            Decimal('5.000'),
            Decimal('10.000'),
        ]

    def test_the_oldest_date_is_drawn_across_batches_and_unnamed_stock(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        po_org: Any,
        po_template: Any,
        pick_face: StorageLocation,
        reserve_rack: StorageLocation,
    ) -> None:
        """FEFO ranks records, not (batch, owner) groups: a lot waits its turn.

        An unbatched record with an early date, an active batch dated later
        and a second unbatched record dated last: the draw takes the first
        and the batch, never the group's later record ahead of the batch.
        """
        rule = _rule(
            db_session, po_org, po_template, pick_face, min_qty='5', max_qty='10'
        )

        async def _stock(session: AsyncSession) -> None:
            keeper = await shelf_keeper(session, po_org.id)
            middle = await _lot(
                session, po_org.id, po_template.id, 'BATCH-MIDDLE', days=40
            )
            await put_on_shelf(
                session,
                keeper,
                po_template,
                reserve_rack.id,
                Decimal('5'),
                expiry_date=date.today() + timedelta(days=8),
            )
            await put_on_shelf(
                session,
                keeper,
                po_template,
                reserve_rack.id,
                Decimal('5'),
                lot_id=middle,
                expiry_date=date.today() + timedelta(days=40),
            )
            await put_on_shelf(
                session,
                keeper,
                po_template,
                reserve_rack.id,
                Decimal('5'),
                expiry_date=date.today() + timedelta(days=100),
            )

        run_in_async_session(async_engine_fixture, _stock)

        proposal = client.get(f'{PROPOSAL_URL}/{rule.id}', headers=po_auth_headers)
        assert proposal.status_code == status.HTTP_200_OK, proposal.text
        lines = proposal.json()['lines']
        assert [line['lot_name'] for line in lines] == [None, 'BATCH-MIDDLE']
        assert [Decimal(line['quantity']) for line in lines] == [
            Decimal('5.000'),
            Decimal('5.000'),
        ]

    def test_a_proposal_nobody_acts_on_expires_with_the_next_read(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        db_session: Session,
        po_org: Any,
        po_template: Any,
        pick_face: StorageLocation,
        reserve_rack: StorageLocation,
    ) -> None:
        """The task is derived, not stored: empty the rack, the task is gone."""
        rule = _rule(db_session, po_org, po_template, pick_face)
        post_on_shelf(client, po_auth_headers, po_template, pick_face.id, '3')
        record = post_on_shelf(
            client, po_auth_headers, po_template, reserve_rack.id, '40'
        )
        assert [
            task
            for task in _tasks(client, po_auth_headers)
            if task['source_kind'] == 'replenishment'
        ]

        emptied = client.patch(
            f'/api/v1/items/{record["id"]}/quantity',
            json={'quantity': '0'},
            headers=po_auth_headers,
        )
        assert emptied.status_code == status.HTTP_200_OK, emptied.text

        alert = _alerts(client, po_auth_headers, rule)
        assert alert['reserve_available_quantity'] == 0.0
        assert alert['proposed_move_quantity'] == 0.0
        assert alert['remaining_to_buy'] == 17.0
        assert [
            task
            for task in _tasks(client, po_auth_headers)
            if task['source_kind'] == 'replenishment'
        ] == []

    def test_a_shelf_back_above_its_minimum_has_nothing_to_move(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        db_session: Session,
        po_org: Any,
        po_template: Any,
        pick_face: StorageLocation,
        reserve_rack: StorageLocation,
    ) -> None:
        """A sheet left open when the shortage ends carries nothing to post.

        The proposal is read live, not from the task: filling the pick face
        to its minimum after the sheet was opened empties the plan, and the
        posting door refuses it rather than moving stock nobody asked for.
        """
        rule = _rule(db_session, po_org, po_template, pick_face)
        record = post_on_shelf(client, po_auth_headers, po_template, pick_face.id, '3')
        post_on_shelf(client, po_auth_headers, po_template, reserve_rack.id, '40')

        opened = client.get(f'{PROPOSAL_URL}/{rule.id}', headers=po_auth_headers)
        assert opened.status_code == status.HTTP_200_OK, opened.text
        assert Decimal(opened.json()['quantity']) == Decimal('17.000')

        # A receipt tops the pick face up to 12; its minimum is 10.
        filled = client.patch(
            f'/api/v1/items/{record["id"]}/quantity',
            json={'quantity': '12'},
            headers=po_auth_headers,
        )
        assert filled.status_code == status.HTTP_200_OK, filled.text
        assert client.get(ALERTS_URL, headers=po_auth_headers).json()['items'] == []

        expired = client.get(f'{PROPOSAL_URL}/{rule.id}', headers=po_auth_headers)
        assert expired.status_code == status.HTTP_200_OK, expired.text
        assert expired.json()['lines'] == []
        assert Decimal(expired.json()['quantity']) == Decimal('0')

        moved = client.post(f'{PROPOSAL_URL}/{rule.id}/move', headers=po_auth_headers)
        assert moved.status_code == status.HTTP_400_BAD_REQUEST, moved.text
        assert moved.json()['detail']['message'] == (
            'There is nothing to carry from reserve: the shelf no longer has '
            'the stock, or the pick face no longer needs it.'
        )

    def test_a_reserve_shelf_is_never_refilled(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        db_session: Session,
        po_org: Any,
        po_user: Any,
        po_template: Any,
        po_location: Any,
        reserve_rack: StorageLocation,
    ) -> None:
        second_reserve = _shelf(
            db_session, po_org, po_user, po_location, 'Reserve R-13', reserve=True
        )
        rule = _rule(db_session, po_org, po_template, reserve_rack)
        post_on_shelf(client, po_auth_headers, po_template, reserve_rack.id, '1')
        post_on_shelf(client, po_auth_headers, po_template, second_reserve.id, '40')

        alert = _alerts(client, po_auth_headers, rule)
        assert alert['reserve_available_quantity'] == 0.0
        assert alert['proposed_move_quantity'] == 0.0
        assert alert['remaining_to_buy'] == 19.0

    def test_the_shelf_scan_is_required_when_the_profile_asks_for_it(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        db_session: Session,
        po_org: Any,
        po_template: Any,
        pick_face: StorageLocation,
        reserve_rack: StorageLocation,
    ) -> None:
        rule = _rule(db_session, po_org, po_template, pick_face)
        reserve_rack.short_code = 'R-12'
        db_session.add(
            DocumentProfile(
                organization_id=po_org.id,
                name='Simple',
                confirm_shelf_by_scan=True,
            )
        )
        db_session.commit()
        post_on_shelf(client, po_auth_headers, po_template, pick_face.id, '3')
        post_on_shelf(client, po_auth_headers, po_template, reserve_rack.id, '40')

        without_scan = client.post(
            f'{PROPOSAL_URL}/{rule.id}/move', headers=po_auth_headers
        )
        assert without_scan.status_code == status.HTTP_400_BAD_REQUEST, (
            without_scan.text
        )
        assert without_scan.json()['detail']['message'] == (
            'Scan the reserve location you are taking the goods from.'
        )

        wrong_shelf = client.post(
            f'{PROPOSAL_URL}/{rule.id}/move',
            params={'scanned_code': 'SOMEWHERE-ELSE'},
            headers=po_auth_headers,
        )
        assert wrong_shelf.status_code == status.HTTP_400_BAD_REQUEST, wrong_shelf.text
        assert wrong_shelf.json()['detail']['message'] == (
            'That code names another shelf: scan the reserve location the goods are taken from.'
        )

        moved = client.post(
            f'{PROPOSAL_URL}/{rule.id}/move',
            params={'scanned_code': 'R-12'},
            headers=po_auth_headers,
        )
        assert moved.status_code == status.HTTP_201_CREATED, moved.text
        assert moved.json()['status'] == 'COMPLETED'

    def test_a_transfer_waiting_for_approval_is_not_offered_twice(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        approving_org: Any,
    ) -> None:
        """A move held for approval has already claimed the shortage it answers.

        The one-step door stops at PENDING_APPROVAL, so the pick face's stock
        has not moved and its alert still reads uncovered while the goods are
        on their way. Acting on the task again must not carry them a second
        time: two approvals would fill the shelf to 37 against a maximum of
        20 and leave the reserve short of what the second move promised.
        """
        user = h.create_user(approving_org, email='reserve-approval@example.com')
        headers = h.get_auth_headers(user)
        storage_type = h.create_storage_type(
            'Warehouse', 'WAREHOUSE', organization_id=approving_org.id
        )
        location = h.create_storage_location(
            approving_org, storage_type, user, name='Main Warehouse'
        )
        template = h.create_template(
            approving_org, name='Approval Product', sku='PO-APP-001'
        )
        partner = h.create_partner(approving_org, user, name='Approval Supplier')
        pick_face = _shelf(db_session, approving_org, user, location, 'Pick B-01')
        reserve_rack = _shelf(
            db_session, approving_org, user, location, 'Reserve R-12', reserve=True
        )
        rule = _rule(
            db_session, approving_org, template, pick_face, partner_id=partner.id
        )

        workflow = client.post(
            '/api/v1/approvals/workflows',
            headers=headers,
            json={
                'target_type': 'document',
                'requester_scope': {'everyone': True},
                'is_active': True,
                'expected_scope': {'holds': 'all'},
                'name': 'Reserve Move Approval',
                'stages': [
                    {
                        'order': 1,
                        'role': 'manager',
                        'label': 'Manager Approval',
                        'approver_user_ids': [],
                    }
                ],
            },
        )
        assert workflow.status_code == status.HTTP_201_CREATED, workflow.text
        profile = client.get('/api/v1/warehouse/profile', headers=headers).json()
        saved = client.put(
            '/api/v1/warehouse/profile',
            headers=headers,
            json={
                **{
                    key: value
                    for key, value in profile.items()
                    if key not in ('id', 'organization_id', 'created_at', 'updated_at')
                },
                'approval_required_for_types': ['INT'],
            },
        )
        assert saved.status_code == status.HTTP_200_OK, saved.text

        post_on_shelf(client, headers, template, pick_face.id, '3')

        async def _stock(session: AsyncSession) -> None:
            keeper = await shelf_keeper(session, approving_org.id)
            first = await _lot(session, approving_org.id, template.id, 'FIRST', days=5)
            second = await _lot(
                session, approving_org.id, template.id, 'SECOND', days=50
            )
            await put_on_shelf(
                session,
                keeper,
                template,
                reserve_rack.id,
                Decimal('17'),
                lot_id=first,
                expiry_date=date.today() + timedelta(days=5),
            )
            await put_on_shelf(
                session,
                keeper,
                template,
                reserve_rack.id,
                Decimal('23'),
                lot_id=second,
                expiry_date=date.today() + timedelta(days=50),
            )

        run_in_async_session(async_engine_fixture, _stock)
        db_session.expire_all()

        def _on_shelf(location_id: Any) -> Decimal:
            db_session.expire_all()
            rows = db_session.scalars(
                select(Item).where(Item.storage_location_id == location_id)
            ).all()
            return sum((row.quantity for row in rows), Decimal('0'))

        first_move = client.post(f'{PROPOSAL_URL}/{rule.id}/move', headers=headers)
        assert first_move.status_code == status.HTTP_201_CREATED, first_move.text
        assert first_move.json()['status'] == 'PENDING_APPROVAL'
        # The hold reserved the goods at the source but moved nothing yet.
        assert _on_shelf(pick_face.id) == Decimal('3.000')
        assert _on_shelf(reserve_rack.id) == Decimal('40.000')

        # The shelf is no longer short of what stands on its way.
        assert _rule_alerts(client, headers, rule) == []
        assert [
            task
            for task in _tasks(client, headers)
            if task['source_kind'] == 'replenishment'
            and task['source_id'] == str(rule.id)
        ] == []
        proposal = client.get(f'{PROPOSAL_URL}/{rule.id}', headers=headers)
        assert proposal.status_code == status.HTTP_200_OK, proposal.text
        assert Decimal(proposal.json()['quantity']) == Decimal('0')
        assert proposal.json()['lines'] == []

        second_move = client.post(f'{PROPOSAL_URL}/{rule.id}/move', headers=headers)
        assert second_move.status_code == status.HTTP_400_BAD_REQUEST, second_move.text
        assert second_move.json()['detail']['message'] == (
            'There is nothing to carry from reserve: the shelf no longer has '
            'the stock, or the pick face no longer needs it.'
        )
        draft = client.post(
            DRAFT_POS_URL,
            json={'reorder_rule_ids': [str(rule.id)]},
            headers=headers,
        )
        assert draft.status_code == status.HTTP_201_CREATED, draft.text
        assert draft.json()['created'] == []
        assert draft.json()['skipped'][0]['reason'] == 'not_alerting'

        # One approval, one move: the shelf reaches its maximum, not 37.
        approved = client.post(
            f'/api/v1/approvals/documents/{first_move.json()["id"]}/approve',
            headers=headers,
        )
        assert approved.status_code == status.HTTP_200_OK, approved.text
        assert _on_shelf(pick_face.id) == Decimal('20.000')
        assert _on_shelf(reserve_rack.id) == Decimal('23.000')

    def test_a_scanned_transfer_still_counts_as_promised(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        db_session: Session,
        po_org: Any,
        po_partner: Any,
        po_template: Any,
        pick_face: StorageLocation,
        reserve_rack: StorageLocation,
    ) -> None:
        """A scan writes the line's quantity before completion moves the stock.

        ``done_quantity`` is what the picking has counted, not what has
        posted: the shelf still reads short while the goods stand scanned in
        their boxes. Reading the promise as expected minus done dropped it
        at exactly that moment, so the task came back and a second transfer
        could overfill the pick face once both posted.
        """
        from uuid import UUID

        from app.modules.warehouse.models import Document

        po_template.barcode = 'RESERVE-SCAN-01'
        db_session.commit()
        rule = _rule(
            db_session, po_org, po_template, pick_face, partner_id=po_partner.id
        )
        post_on_shelf(client, po_auth_headers, po_template, pick_face.id, '3')
        record = post_on_shelf(
            client, po_auth_headers, po_template, reserve_rack.id, '40'
        )

        transfer = client.post(
            '/api/v1/warehouse/documents',
            headers=po_auth_headers,
            json={
                'type': 'INT',
                'source_location_id': str(reserve_rack.id),
                'target_location_id': str(pick_face.id),
                'lines': [{'item_id': record['id'], 'expected_quantity': 17}],
            },
        )
        assert transfer.status_code == status.HTTP_201_CREATED, transfer.text
        document_id = transfer.json()['id']
        confirmed = client.patch(
            f'/api/v1/warehouse/documents/{document_id}/confirm',
            headers=po_auth_headers,
        )
        assert confirmed.status_code == status.HTTP_200_OK, confirmed.text

        def _on_shelf(location_id: Any) -> Decimal:
            db_session.expire_all()
            rows = db_session.scalars(
                select(Item).where(Item.storage_location_id == location_id)
            ).all()
            return sum((row.quantity for row in rows), Decimal('0'))

        # Confirmed and on its way: the shelves still read 3 and 40, and the
        # shortage is already spoken for.
        assert _on_shelf(pick_face.id) == Decimal('3.000')
        assert _rule_alerts(client, po_auth_headers, rule) == []

        session = client.post(
            f'/api/v1/warehouse/documents/{document_id}/picking/start',
            headers=po_auth_headers,
        )
        assert session.status_code == status.HTTP_201_CREATED, session.text
        scan = client.post(
            f'/api/v1/warehouse/documents/{document_id}/picking/'
            f'{session.json()["id"]}/scan',
            headers=po_auth_headers,
            json={'barcode': po_template.barcode, 'quantity': 17},
        )
        assert scan.status_code == status.HTTP_200_OK, scan.text
        assert scan.json()['session_complete'] is True

        db_session.expire_all()
        document = db_session.scalar(
            select(Document).where(Document.id == UUID(document_id))
        )
        assert document is not None
        assert document.status == 'CONFIRMED'
        assert document.lines[0].done_quantity == Decimal('17.000')
        # Scanned, not yet posted: the goods are still on their way.
        assert _on_shelf(pick_face.id) == Decimal('3.000')
        assert _rule_alerts(client, po_auth_headers, rule) == []

        proposal = client.get(f'{PROPOSAL_URL}/{rule.id}', headers=po_auth_headers)
        assert proposal.status_code == status.HTTP_200_OK, proposal.text
        assert Decimal(proposal.json()['quantity']) == Decimal('0')
        assert proposal.json()['lines'] == []
        second_move = client.post(
            f'{PROPOSAL_URL}/{rule.id}/move', headers=po_auth_headers
        )
        assert second_move.status_code == status.HTTP_400_BAD_REQUEST, second_move.text
        assert second_move.json()['detail']['message'] == (
            'There is nothing to carry from reserve: the shelf no longer has '
            'the stock, or the pick face no longer needs it.'
        )

        completed = client.patch(
            f'/api/v1/warehouse/documents/{document_id}/complete',
            headers=po_auth_headers,
            json={'complete_as_planned': True},
        )
        assert completed.status_code == status.HTTP_200_OK, completed.text
        assert _on_shelf(pick_face.id) == Decimal('20.000')
        assert _on_shelf(reserve_rack.id) == Decimal('23.000')


async def _lot(
    session: AsyncSession,
    org_id: Any,
    template_id: Any,
    name: str,
    *,
    days: int,
) -> Any:
    from app.core.public_api import core_api

    return await core_api.stock.get_or_create_lot_async(
        session,
        org_id,
        template_id,
        name,
        expiry_date=date.today() + timedelta(days=days),
    )
