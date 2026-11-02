"""A dispatch from a zone takes each line from the shelves below it, pinned.

The source of a dispatch may be a zone: a location with shelves under it.
Confirmation plans each line across those shelves in the product's removal
order and splits the line where the plan moves from one shelf to the next,
so every share is held on the shelf it will leave from. The split lines carry
the shelf they take from, and completion draws from exactly those shelves.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any, cast

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.stock_lot import StockLot
from app.models.stock_move import StockMove
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.approvals.models import ApprovalWorkflow
from app.modules.warehouse.tests.integration._records import (
    shelf_quant as _shelf_quant,
)
from app.modules.warehouse.tests.integration._records import (
    sow as _sow,
)


def _shelf(
    db_session: Session,
    org: Organization,
    user: User,
    parent: StorageLocation,
    name: str,
) -> StorageLocation:
    shelf = StorageLocation(
        organization_id=org.id,
        name=name,
        parent_id=parent.id,
        storage_type_id=parent.storage_type_id,
        created_by=user.id,
    )
    db_session.add(shelf)
    db_session.flush()
    return shelf


def _lines(
    client: TestClient, headers: dict[str, str], doc_id: str
) -> list[dict[str, Any]]:
    shown = client.get(f'/api/v1/warehouse/documents/{doc_id}', headers=headers)
    assert shown.status_code == status.HTTP_200_OK, shown.text
    return cast(
        list[dict[str, Any]],
        sorted(shown.json()['lines'], key=lambda x: x['line_number']),
    )


def _draft(
    client: TestClient,
    headers: dict[str, str],
    partner: Partner,
    zone: StorageLocation,
    target: StorageLocation,
    item: Item,
    template: ProductTemplate,
    quantity: int,
) -> str:
    created = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'OUT',
            'partner_id': str(partner.id),
            'source_location_id': str(zone.id),
            'target_location_id': str(target.id),
            'lines': [
                {
                    'item_id': str(item.id),
                    'product_template_id': str(template.id),
                    'expected_quantity': quantity,
                }
            ],
        },
    )
    assert created.status_code == status.HTTP_201_CREATED, created.text
    return cast(str, created.json()['id'])


@pytest.fixture
def zone_shelves(
    db_session: Session,
    doc_org: Organization,
    doc_user: User,
    doc_source_location: StorageLocation,
) -> tuple[StorageLocation, StorageLocation]:
    """Two shelves under the warehouse, which is the zone the document names."""
    return (
        _shelf(db_session, doc_org, doc_user, doc_source_location, 'Bin A1'),
        _shelf(db_session, doc_org, doc_user, doc_source_location, 'Bin B2'),
    )


@pytest.mark.integration
class TestADispatchFromAZoneSplitsOverItsShelves:
    def test_fefo_takes_the_earlier_expiry_first_and_pins_each_share(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_org: Organization,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        zone_shelves: tuple[StorageLocation, StorageLocation],
    ) -> None:
        """Bin B2's batch expires first, so 5 leave it; the rest comes off Bin A1."""
        shelf_a, shelf_b = zone_shelves
        doc_template.removal_strategy = 'FEFO'
        db_session.commit()
        today = date.today()
        later = _sow(
            db_session,
            async_engine_fixture,
            doc_org,
            doc_template,
            shelf_a.id,
            '6',
            expiry_date=today + timedelta(days=30),
        )
        sooner = _sow(
            db_session,
            async_engine_fixture,
            doc_org,
            doc_template,
            shelf_b.id,
            '5',
            expiry_date=today + timedelta(days=10),
        )

        doc_id = _draft(
            client,
            doc_auth_headers,
            doc_partner,
            doc_source_location,
            doc_target_location,
            later,
            doc_template,
            7,
        )
        confirm = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        assert confirm.status_code == status.HTTP_200_OK, confirm.text

        lines = _lines(client, doc_auth_headers, doc_id)
        assert [
            (line['source_location_id'], float(line['expected_quantity']))
            for line in lines
        ] == [
            (str(shelf_b.id), 5.0),
            (str(shelf_a.id), 2.0),
        ]
        assert lines[0]['item_id'] == str(sooner.id)
        assert lines[1]['item_id'] == str(later.id)
        # The shelf is named for a reader who does not hold ids.
        assert [line['source_location_name'] for line in lines] == [
            'Bin B2',
            'Bin A1',
        ]

        db_session.expire_all()
        assert (
            float(
                _shelf_quant(
                    db_session, doc_org.id, doc_template.id, shelf_b.id
                ).reserved_quantity
            )
            == 5.0
        )
        assert (
            float(
                _shelf_quant(
                    db_session, doc_org.id, doc_template.id, shelf_a.id
                ).reserved_quantity
            )
            == 2.0
        )

    def test_fifo_takes_the_oldest_record_first_across_the_shelves(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_org: Organization,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        zone_shelves: tuple[StorageLocation, StorageLocation],
    ) -> None:
        """The record received first on Bin A1 goes first, whatever shelf is next to it."""
        shelf_a, shelf_b = zone_shelves
        doc_template.removal_strategy = 'FIFO'
        db_session.commit()
        oldest = _sow(
            db_session,
            async_engine_fixture,
            doc_org,
            doc_template,
            shelf_a.id,
            '6',
            backdate_days=30,
        )
        _sow(db_session, async_engine_fixture, doc_org, doc_template, shelf_b.id, '5')

        doc_id = _draft(
            client,
            doc_auth_headers,
            doc_partner,
            doc_source_location,
            doc_target_location,
            oldest,
            doc_template,
            7,
        )
        confirm = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        assert confirm.status_code == status.HTTP_200_OK, confirm.text

        lines = _lines(client, doc_auth_headers, doc_id)
        assert [
            (line['source_location_id'], float(line['expected_quantity']))
            for line in lines
        ] == [
            (str(shelf_a.id), 6.0),
            (str(shelf_b.id), 1.0),
        ]

    def test_a_zone_that_cannot_cover_the_line_refuses_confirmation(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_org: Organization,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        zone_shelves: tuple[StorageLocation, StorageLocation],
    ) -> None:
        """Eleven on the shelves below, twelve asked: the document stays a draft."""
        shelf_a, shelf_b = zone_shelves
        record = _sow(
            db_session, async_engine_fixture, doc_org, doc_template, shelf_a.id, '6'
        )
        _sow(db_session, async_engine_fixture, doc_org, doc_template, shelf_b.id, '5')

        doc_id = _draft(
            client,
            doc_auth_headers,
            doc_partner,
            doc_source_location,
            doc_target_location,
            record,
            doc_template,
            12,
        )
        confirm = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        assert confirm.status_code == status.HTTP_400_BAD_REQUEST, confirm.text

        shown = client.get(
            f'/api/v1/warehouse/documents/{doc_id}', headers=doc_auth_headers
        )
        assert shown.json()['status'] == 'DRAFT'
        assert all(line['source_location_id'] is None for line in shown.json()['lines'])

    def test_completion_draws_from_the_pinned_shelves_and_names_them(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_org: Organization,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        zone_shelves: tuple[StorageLocation, StorageLocation],
    ) -> None:
        """One movement per shelf taken, each from its own shelf; the lines say where."""
        shelf_a, shelf_b = zone_shelves
        doc_template.removal_strategy = 'FIFO'
        db_session.commit()
        oldest = _sow(
            db_session,
            async_engine_fixture,
            doc_org,
            doc_template,
            shelf_a.id,
            '6',
            backdate_days=30,
        )
        _sow(db_session, async_engine_fixture, doc_org, doc_template, shelf_b.id, '5')
        doc_id = _draft(
            client,
            doc_auth_headers,
            doc_partner,
            doc_source_location,
            doc_target_location,
            oldest,
            doc_template,
            7,
        )
        confirmed = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        assert confirmed.status_code == status.HTTP_200_OK, confirmed.text

        completed = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert completed.status_code == status.HTTP_200_OK, completed.text

        lines = _lines(client, doc_auth_headers, doc_id)
        assert [line['executed_location_id'] for line in lines] == [
            str(shelf_a.id),
            str(shelf_b.id),
        ]

        db_session.expire_all()
        moves = db_session.scalars(
            select(StockMove).where(
                StockMove.organization_id == doc_org.id,
                StockMove.product_template_id == doc_template.id,
                StockMove.state == 'done',
                StockMove.from_location_id.in_([shelf_a.id, shelf_b.id]),
            )
        ).all()
        taken = {(move.from_location_id, move.quantity) for move in moves}
        assert taken == {(shelf_a.id, Decimal('6')), (shelf_b.id, Decimal('1'))}

    def test_a_rejected_dispatch_lets_its_pins_go_and_plans_the_zone_again(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_approval_workflow: ApprovalWorkflow,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_org: Organization,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        zone_shelves: tuple[StorageLocation, StorageLocation],
    ) -> None:
        """Rework to draft releases the holds and clears the pins; confirming again plans afresh.

        The dispatch waits for approval, so its holds stand while it is
        parked. A rejection sends it back to draft: the shares stay as lines,
        unpinned and unheld, and the next confirmation pins them again.
        """
        shelf_a, shelf_b = zone_shelves
        doc_template.removal_strategy = 'FIFO'
        db_session.commit()
        oldest = _sow(
            db_session,
            async_engine_fixture,
            doc_org,
            doc_template,
            shelf_a.id,
            '6',
            backdate_days=30,
        )
        _sow(db_session, async_engine_fixture, doc_org, doc_template, shelf_b.id, '5')
        profile = client.get(
            '/api/v1/warehouse/profile', headers=doc_auth_headers
        ).json()
        updated = client.put(
            '/api/v1/warehouse/profile',
            headers=doc_auth_headers,
            json={
                **{
                    key: value
                    for key, value in profile.items()
                    if key not in ('id', 'organization_id', 'created_at', 'updated_at')
                },
                'approval_threshold': None,
                'approval_required_for_types': ['OUT'],
            },
        )
        assert updated.status_code == status.HTTP_200_OK, updated.text
        doc_id = _draft(
            client,
            doc_auth_headers,
            doc_partner,
            doc_source_location,
            doc_target_location,
            oldest,
            doc_template,
            7,
        )
        parked = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        assert parked.status_code == status.HTTP_200_OK, parked.text
        assert parked.json()['status'] == 'PENDING_APPROVAL'
        assert [
            line['source_location_id']
            for line in _lines(client, doc_auth_headers, doc_id)
        ] == [
            str(shelf_a.id),
            str(shelf_b.id),
        ]

        approval = client.get(
            f'/api/v1/approvals/documents/{doc_id}/approval', headers=doc_auth_headers
        ).json()
        rejected = client.post(
            f'/api/v1/approvals/requests/{approval["id"]}/reject',
            headers=doc_auth_headers,
        )
        assert rejected.status_code == status.HTTP_200_OK, rejected.text
        assert (
            client.get(
                f'/api/v1/warehouse/documents/{doc_id}', headers=doc_auth_headers
            ).json()['status']
            == 'DRAFT'
        )
        assert [
            line['source_location_id']
            for line in _lines(client, doc_auth_headers, doc_id)
        ] == [
            None,
            None,
        ]
        db_session.expire_all()
        assert (
            float(
                _shelf_quant(
                    db_session, doc_org.id, doc_template.id, shelf_a.id
                ).reserved_quantity
            )
            == 0.0
        )
        assert (
            float(
                _shelf_quant(
                    db_session, doc_org.id, doc_template.id, shelf_b.id
                ).reserved_quantity
            )
            == 0.0
        )

        parked_again = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        assert parked_again.status_code == status.HTTP_200_OK, parked_again.text
        lines = _lines(client, doc_auth_headers, doc_id)
        assert [
            (line['source_location_id'], float(line['expected_quantity']))
            for line in lines
        ] == [
            (str(shelf_a.id), 6.0),
            (str(shelf_b.id), 1.0),
        ]

    def test_a_line_naming_a_batch_splits_over_that_batch_only(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_org: Organization,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        zone_shelves: tuple[StorageLocation, StorageLocation],
    ) -> None:
        """The earlier batch on Bin A1 is passed over: the line asks for LOT-LATE.

        Both shares keep the batch the line names, so each is drawn from it on
        its own shelf.
        """
        shelf_a, shelf_b = zone_shelves
        doc_template.removal_strategy = 'FEFO'
        today = date.today()
        soon = StockLot(
            organization_id=doc_org.id,
            product_template_id=doc_template.id,
            name='LOT-SOON',
            expiry_date=today + timedelta(days=10),
        )
        late = StockLot(
            organization_id=doc_org.id,
            product_template_id=doc_template.id,
            name='LOT-LATE',
            expiry_date=today + timedelta(days=30),
        )
        db_session.add_all([soon, late])
        db_session.commit()
        _sow(
            db_session,
            async_engine_fixture,
            doc_org,
            doc_template,
            shelf_a.id,
            '5',
            lot_id=soon.id,
        )
        late_on_a = _sow(
            db_session,
            async_engine_fixture,
            doc_org,
            doc_template,
            shelf_a.id,
            '3',
            lot_id=late.id,
            backdate_days=2,
        )
        late_on_b = _sow(
            db_session,
            async_engine_fixture,
            doc_org,
            doc_template,
            shelf_b.id,
            '3',
            lot_id=late.id,
            backdate_days=1,
        )

        created = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'OUT',
                'partner_id': str(doc_partner.id),
                'source_location_id': str(doc_source_location.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'item_id': str(late_on_a.id),
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 5,
                        'batch_number': 'LOT-LATE',
                    }
                ],
            },
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        doc_id = created.json()['id']
        confirm = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        assert confirm.status_code == status.HTTP_200_OK, confirm.text

        assert [
            (
                line['source_location_id'],
                line['item_id'],
                line['batch_number'],
                float(line['expected_quantity']),
            )
            for line in _lines(client, doc_auth_headers, doc_id)
        ] == [
            (str(shelf_a.id), str(late_on_a.id), 'LOT-LATE', 3.0),
            (str(shelf_b.id), str(late_on_b.id), 'LOT-LATE', 2.0),
        ]
