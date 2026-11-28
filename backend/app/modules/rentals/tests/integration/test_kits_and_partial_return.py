"""Kits: one line to book, one scan to hand out, availability from members."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.modules.rentals.tests.conftest import END, START, booking_payload

pytestmark = pytest.mark.integration

RENTALS = '/api/v1/rentals'


def _create_kit(client: TestClient, auth: dict[str, str], members: list[dict]):
    return client.post(
        f'{RENTALS}/kits',
        headers=auth,
        json={'name': 'Conference kit', 'members': members},
    )


def _kit_members(screen, projectors) -> list[dict]:
    return [
        {'item_id': str(screen.id)},
        {'model': 'Projektor 4K', 'quantity': 1},
    ]


class TestKitCrud:
    def test_a_kit_lists_its_members_and_takes_a_scan_code(
        self, client: TestClient, rental_auth: dict[str, str], screen, projectors
    ) -> None:
        response = _create_kit(client, rental_auth, _kit_members(screen, projectors))
        assert response.status_code == 201, response.text
        kit = response.json()
        assert kit['name'] == 'Conference kit'
        assert kit['code'].startswith('KIT-')
        assert len(kit['members']) == 2
        assert kit['members'][0]['item_name'] == 'Ekran 2 m #1'
        assert kit['members'][1]['model'] == 'Projektor 4K'
        assert kit['members'][1]['quantity'] == 1

        listed = client.get(f'{RENTALS}/kits', headers=rental_auth).json()
        assert [row['id'] for row in listed] == [kit['id']]
        assert listed[0]['member_count'] == 2

        fetched = client.get(f'{RENTALS}/kits/{kit["id"]}', headers=rental_auth)
        assert fetched.status_code == 200
        assert fetched.json()['code'] == kit['code']

    def test_a_kit_name_is_unique_in_the_organization(
        self, client: TestClient, rental_auth: dict[str, str], screen, projectors
    ) -> None:
        members = _kit_members(screen, projectors)
        assert _create_kit(client, rental_auth, members).status_code == 201
        second = _create_kit(client, rental_auth, members)
        assert second.status_code == 400, second.text
        assert second.json()['detail']['message']

    def test_a_member_must_be_in_the_register(
        self, client: TestClient, rental_auth: dict[str, str], screen, projectors
    ) -> None:
        response = _create_kit(client, rental_auth, [{'model': 'No Such Model'}])
        assert response.status_code == 400, response.text


class TestKitBooking:
    def test_a_busy_member_makes_the_kit_unavailable(
        self,
        client: TestClient,
        rental_auth: dict[str, str],
        screen,
        projectors,
    ) -> None:
        kit = _create_kit(client, rental_auth, _kit_members(screen, projectors)).json()
        # The screen alone is promised for the window.
        assert (
            client.post(
                f'{RENTALS}/bookings',
                headers=rental_auth,
                json=booking_payload(item_id=screen.id),
            ).status_code
            == 201
        )

        check = client.post(
            f'{RENTALS}/bookings/check',
            headers=rental_auth,
            json={
                'starts_at': START.isoformat(),
                'ends_at': END.isoformat(),
                'lines': [{'kit_id': kit['id']}],
            },
        )
        assert check.status_code == 200, check.text
        line = check.json()['lines'][0]
        assert line['ok'] is False
        assert any(
            conflict['item_id'] == str(screen.id)
            for conflict in line['conflicts']
            if conflict.get('item_id')
        ), line

        refused = client.post(
            f'{RENTALS}/bookings',
            headers=rental_auth,
            json={
                **booking_payload(),
                'lines': [{'kit_id': kit['id']}],
            },
        )
        assert refused.status_code == 409, refused.text

    def test_one_scan_hands_out_the_whole_kit(
        self,
        client: TestClient,
        rental_auth: dict[str, str],
        screen,
        projectors,
        db_session,
    ) -> None:
        kit = _create_kit(client, rental_auth, _kit_members(screen, projectors)).json()
        created = client.post(
            f'{RENTALS}/bookings',
            headers=rental_auth,
            json={**booking_payload(), 'lines': [{'kit_id': kit['id']}]},
        )
        assert created.status_code == 201, created.text
        booking = created.json()
        # The kit is stored as one line per member, both carrying the kit.
        assert {line['kit_id'] for line in booking['lines']} == {kit['id']}
        assert {line['kit_name'] for line in booking['lines']} == {'Conference kit'}

        picked = client.post(
            f'{RENTALS}/bookings/{booking["id"]}/pickup',
            headers=rental_auth,
            json={'kit_ids': [kit['id']]},
        )
        assert picked.status_code == 200, picked.text
        handed = picked.json()
        assert handed['status'] == 'PICKED_UP'
        assert len(handed['lines']) == 2
        unit_items = {
            unit['item_id'] for line in handed['lines'] for unit in line['units']
        }
        assert str(screen.id) in unit_items
        assert len(unit_items) == 2

    def test_a_kit_scan_cannot_hand_out_another_booking(
        self,
        client: TestClient,
        rental_auth: dict[str, str],
        screen,
        projectors,
    ) -> None:
        kit = _create_kit(client, rental_auth, _kit_members(screen, projectors)).json()
        other = client.post(
            f'{RENTALS}/bookings',
            headers=rental_auth,
            json=booking_payload(item_id=projectors[0].id),
        ).json()
        response = client.post(
            f'{RENTALS}/bookings/{other["id"]}/pickup',
            headers=rental_auth,
            json={'kit_ids': [kit['id']]},
        )
        assert response.status_code == 400, response.text


class TestPartialReturn:
    def test_returning_one_unit_keeps_the_rest_out_and_frees_it(
        self,
        client: TestClient,
        rental_auth: dict[str, str],
        screen,
        projectors,
    ) -> None:
        kit = _create_kit(client, rental_auth, _kit_members(screen, projectors)).json()
        booking = client.post(
            f'{RENTALS}/bookings',
            headers=rental_auth,
            json={**booking_payload(), 'lines': [{'kit_id': kit['id']}]},
        ).json()
        picked = client.post(
            f'{RENTALS}/bookings/{booking["id"]}/pickup',
            headers=rental_auth,
            json={'kit_ids': [kit['id']]},
        ).json()
        units = [unit for line in picked['lines'] for unit in line['units']]
        assert len(units) == 2

        response = client.post(
            f'{RENTALS}/bookings/{booking["id"]}/return',
            headers=rental_auth,
            json={'units': [{'unit_id': units[0]['id'], 'condition': 'GOOD'}]},
        )
        assert response.status_code == 200, response.text
        partly = response.json()
        assert partly['status'] == 'PICKED_UP'
        assert partly['can_return'] is True
        assert partly['returned_count'] == 1
        assert partly['outstanding_count'] == 1

        returned_item = units[0]['item_id']
        still_out = units[1]['item_id']
        # The unit that came back is free for a new booking at once.
        free = client.post(
            f'{RENTALS}/bookings',
            headers=rental_auth,
            json=booking_payload(item_id=returned_item),
        )
        assert free.status_code == 201, free.text
        # The one still out still holds its window.
        blocked = client.post(
            f'{RENTALS}/bookings',
            headers=rental_auth,
            json=booking_payload(item_id=still_out),
        )
        assert blocked.status_code == 409, blocked.text

        # The rest comes back later, and the booking closes then.
        finish = client.post(
            f'{RENTALS}/bookings/{booking["id"]}/return',
            headers=rental_auth,
            json={'units': [{'unit_id': units[1]['id'], 'condition': 'GOOD'}]},
        )
        assert finish.status_code == 200, finish.text
        assert finish.json()['status'] == 'RETURNED'

    def test_returning_a_unit_twice_is_refused(
        self,
        client: TestClient,
        rental_auth: dict[str, str],
        projectors,
    ) -> None:
        booking = client.post(
            f'{RENTALS}/bookings',
            headers=rental_auth,
            json=booking_payload(model='Projektor 4K', quantity=2),
        ).json()
        picked = client.post(
            f'{RENTALS}/bookings/{booking["id"]}/pickup',
            headers=rental_auth,
            json={'item_ids': [str(projectors[0].id), str(projectors[1].id)]},
        ).json()
        units = picked['lines'][0]['units']
        assert (
            client.post(
                f'{RENTALS}/bookings/{booking["id"]}/return',
                headers=rental_auth,
                json={'units': [{'unit_id': units[0]['id'], 'condition': 'GOOD'}]},
            ).status_code
            == 200
        )
        again = client.post(
            f'{RENTALS}/bookings/{booking["id"]}/return',
            headers=rental_auth,
            json={'units': [{'unit_id': units[0]['id'], 'condition': 'GOOD'}]},
        )
        assert again.status_code == 400, again.text


def test_a_partly_returned_booking_stays_on_the_late_list(
    client: TestClient,
    rental_auth: dict[str, str],
    projectors,
    db_session,
) -> None:
    from app.modules.rentals.tests.conftest import make_overdue

    booking = client.post(
        f'{RENTALS}/bookings',
        headers=rental_auth,
        json=booking_payload(model='Projektor 4K', quantity=2),
    ).json()
    picked = client.post(
        f'{RENTALS}/bookings/{booking["id"]}/pickup',
        headers=rental_auth,
        json={'item_ids': [str(projectors[0].id), str(projectors[1].id)]},
    ).json()
    units = picked['lines'][0]['units']
    make_overdue(db_session, booking['id'], datetime.now(UTC) - timedelta(days=1))

    response = client.post(
        f'{RENTALS}/bookings/{booking["id"]}/return',
        headers=rental_auth,
        json={'units': [{'unit_id': units[0]['id'], 'condition': 'GOOD'}]},
    )
    assert response.status_code == 200, response.text
    partly = response.json()
    assert partly['status'] == 'PICKED_UP'
    assert partly['is_late'] is True

    today = client.get(f'{RENTALS}/today', headers=rental_auth)
    assert today.status_code == 200
    assert any(row['booking_id'] == booking['id'] for row in today.json()['late'])
