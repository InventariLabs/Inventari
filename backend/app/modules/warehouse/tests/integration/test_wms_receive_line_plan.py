"""The floor screen carries the same plan the office screen has.

The putaway preview and the shelf picker were built on ``DocumentDetailPage``
— the office screen. The WMS receiving row showed name, quantity and status
and nothing about where the goods were going, while being the screen that
actually executes the receipt. So the premise the whole preview was built on
— the worker standing in front of a full shelf — was answered everywhere
except in front of the shelf.

These tests follow the plan from the rule that decides it to the row the
worker reads, and they pin the part that matters most: the floor row is fed
by ``attach_receipt_plans``, the one function the document read and the
executor both go through. A second decision for this screen would be free to
disagree with the booking, which is the failure the shared planner exists to
prevent.
"""

from __future__ import annotations

from decimal import Decimal
from typing import cast
from uuid import uuid4

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.storage_location import StorageLocation
from app.models.user import User
from tests.integration._shelf import anchor_pending_records

from .test_receipt_line_target import _make_category, _make_location


def _receipt_with_rule(
    client: TestClient,
    headers: dict[str, str],
    *,
    db_session: Session,
    org: Organization,
    user: User,
    target: StorageLocation,
    partner: Partner,
    quantity: int = 3,
    rule_shelf_name: str = 'PAW10 Rule shelf',
) -> tuple[str, StorageLocation, Item]:
    """A confirmed receipt whose line a putaway rule sends somewhere else."""
    from app.core.testing import ModuleTestHelper

    category = _make_category(db_session, org, f'PAW10 {uuid4().hex[:6]}')
    rule_loc = _make_location(db_session, org, target, user, rule_shelf_name)
    # Capacity is kept per (organization, location, product), so the record
    # has to name a catalogue entry for the overflow half of these tests to
    # have anything to be over.
    template = ModuleTestHelper(db_session).create_template(
        org, name=f'PAW10 {uuid4().hex[:6]}'
    )
    item = Item(
        name=f'PAW10 {uuid4().hex[:6]}',
        organization_id=org.id,
        storage_location_id=target.id,
        quantity=Decimal('1'),
        category_id=category.id,
        template_id=template.id,
    )
    db_session.add(item)
    anchor_pending_records(db_session)
    db_session.commit()

    rule = client.post(
        '/api/v1/warehouse/putaway-rules',
        headers=headers,
        json={
            'category_id': str(category.id),
            'target_location_id': str(rule_loc.id),
        },
    )
    assert rule.status_code == status.HTTP_201_CREATED, rule.text

    created = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'IN',
            'partner_id': str(partner.id),
            'target_location_id': str(target.id),
            'lines': [{'item_id': str(item.id), 'expected_quantity': quantity}],
        },
    )
    assert created.status_code == status.HTTP_201_CREATED, created.text
    doc_id = cast(str, created.json()['id'])
    confirm = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=headers
    )
    assert confirm.status_code == status.HTTP_200_OK, confirm.text
    return doc_id, rule_loc, item


def _start_receiving(
    client: TestClient, headers: dict[str, str], doc_id: str
) -> dict[str, object]:
    resp = client.post(
        f'/api/v1/warehouse/documents/{doc_id}/receiving/start', headers=headers
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    return cast(dict[str, object], resp.json())


@pytest.mark.integration
class TestTheFloorRowCarriesThePlan:
    def test_the_row_names_the_shelf_and_who_decided(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        db_session: Session,
        doc_org: Organization,
        doc_user: User,
    ) -> None:
        """The worker reads the shelf, and reads why it is that shelf."""
        doc_id, rule_loc, _ = _receipt_with_rule(
            client,
            doc_auth_headers,
            db_session=db_session,
            org=doc_org,
            user=doc_user,
            target=doc_target_location,
            partner=doc_partner,
        )

        session = _start_receiving(client, doc_auth_headers, doc_id)
        line = cast(list[dict[str, object]], session['lines'])[0]

        assert line['planned_location_id'] == str(rule_loc.id)
        assert line['planned_location_name'] == rule_loc.name
        assert line['planned_source'] == 'rule'
        # Not a bare rule id: the row has to assemble "reguła: kategoria X".
        assert line['planned_rule_match_key'] == 'category'
        assert line['planned_rule_match_name']

    def test_the_row_and_the_document_read_agree(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        db_session: Session,
        doc_org: Organization,
        doc_user: User,
    ) -> None:
        """One planner, so the two screens cannot say different shelves.

        This is the check that outlives the fields: a copy of the
        decision for the floor would pass every other test here and still
        drift from the booking the day a rule changes.
        """
        doc_id, _, _ = _receipt_with_rule(
            client,
            doc_auth_headers,
            db_session=db_session,
            org=doc_org,
            user=doc_user,
            target=doc_target_location,
            partner=doc_partner,
        )

        detail = client.get(
            f'/api/v1/warehouse/documents/{doc_id}', headers=doc_auth_headers
        ).json()
        office = detail['lines'][0]
        floor = cast(
            list[dict[str, object]],
            _start_receiving(client, doc_auth_headers, doc_id)['lines'],
        )[0]

        for field in (
            'planned_location_id',
            'planned_location_name',
            'planned_source',
            'planned_rule_match_key',
            'planned_rule_match_name',
            'planned_rule_warning',
            'planned_over_capacity',
        ):
            assert floor[field] == office[field], field

    def test_the_row_carries_the_overflow_numbers(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        db_session: Session,
        doc_org: Organization,
        doc_user: User,
    ) -> None:
        """A shelf too full to hold the delivery says so by how much.

        The office screen got the numbers; the floor screen is where they
        are actionable, because the person reading them can put the pallet
        somewhere else.
        """
        doc_id, rule_loc, item = _receipt_with_rule(
            client,
            doc_auth_headers,
            db_session=db_session,
            org=doc_org,
            user=doc_user,
            target=doc_target_location,
            partner=doc_partner,
            quantity=50,
        )
        assert item.template_id is not None
        cap = client.post(
            '/api/v1/warehouse/putaway/capacity',
            headers=doc_auth_headers,
            json={
                'location_id': str(rule_loc.id),
                'product_template_id': str(item.template_id),
                'max_quantity': '10',
            },
        )
        assert cap.status_code == status.HTTP_201_CREATED, cap.text

        session = _start_receiving(client, doc_auth_headers, doc_id)
        line = cast(list[dict[str, object]], session['lines'])[0]

        assert line['planned_over_capacity'] is True
        assert Decimal(cast(str, line['planned_capacity_max'])) == Decimal('10')
        assert line['planned_capacity_used'] is not None

    def test_the_row_follows_a_shelf_the_worker_names(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        db_session: Session,
        doc_org: Organization,
        doc_user: User,
    ) -> None:
        """Naming another shelf on the line moves the floor row with it.

        The floor screen changes a shelf through the route the office screen
        already had, so there is one way to override a plan and one place
        that validates the destination.
        """
        doc_id, rule_loc, _ = _receipt_with_rule(
            client,
            doc_auth_headers,
            db_session=db_session,
            org=doc_org,
            user=doc_user,
            target=doc_target_location,
            partner=doc_partner,
        )
        chosen = _make_location(
            db_session, doc_org, doc_target_location, doc_user, 'PAW10 Chosen'
        )
        detail = client.get(
            f'/api/v1/warehouse/documents/{doc_id}', headers=doc_auth_headers
        ).json()
        line_id = detail['lines'][0]['id']

        moved = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/lines/{line_id}',
            headers=doc_auth_headers,
            json={'target_location_id': str(chosen.id)},
        )
        assert moved.status_code == status.HTTP_200_OK, moved.text

        session = _start_receiving(client, doc_auth_headers, doc_id)
        line = cast(list[dict[str, object]], session['lines'])[0]
        assert line['planned_location_id'] == str(chosen.id)
        assert line['planned_location_id'] != str(rule_loc.id)
        assert line['planned_source'] == 'line'

    def test_a_received_line_stops_planning(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        db_session: Session,
        doc_org: Organization,
        doc_user: User,
    ) -> None:
        """Once the goods are down, the plan is history, not a promise.

        A row that keeps promising a shelf after the pallet is on a
        different one is the same lie the document read was fixed for.
        """
        doc_id, _, _ = _receipt_with_rule(
            client,
            doc_auth_headers,
            db_session=db_session,
            org=doc_org,
            user=doc_user,
            target=doc_target_location,
            partner=doc_partner,
        )
        session = _start_receiving(client, doc_auth_headers, doc_id)
        # Taken by hand rather than by scan: these records carry no barcode,
        # and what this test needs is a resolved line, not a scanner.
        session_line = cast(list[dict[str, object]], session['lines'])[0]
        taken = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/{session["id"]}/short-receive',
            headers=doc_auth_headers,
            json={'line_id': session_line['id'], 'received_quantity': '3'},
        )
        assert taken.status_code == status.HTTP_200_OK, taken.text
        # The document refuses to complete under an open session, which is
        # the right order anyway: the floor finishes, then the books do.
        closed = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/{session["id"]}/complete',
            headers=doc_auth_headers,
        )
        assert closed.status_code == status.HTTP_200_OK, closed.text
        complete = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete', headers=doc_auth_headers
        )
        assert complete.status_code == status.HTTP_200_OK, complete.text

        listed = client.get(
            f'/api/v1/warehouse/documents/{doc_id}/receiving', headers=doc_auth_headers
        )
        assert listed.status_code == status.HTTP_200_OK, listed.text
        line = listed.json()['items'][0]['lines'][0]
        assert line['planned_location_id'] is None
        assert line['planned_source'] is None
