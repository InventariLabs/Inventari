"""A refusal names the booking, and the time the unit is really held."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.modules.rentals.tests.conftest import END, START, booking_payload, make_overdue

pytestmark = pytest.mark.integration

RENTALS = '/api/v1/rentals'


class TestBlockOverABooking:
    def test_an_early_hand_out_is_named_from_when_it_left(
        self, client: TestClient, rental_auth: dict[str, str], projectors
    ) -> None:
        booking = client.post(
            f'{RENTALS}/bookings',
            headers=rental_auth,
            json=booking_payload(item_id=projectors[0].id),
        ).json()
        early = datetime.now(UTC)
        picked = client.post(
            f'{RENTALS}/bookings/{booking["id"]}/pickup',
            headers=rental_auth,
            json={'item_ids': [str(projectors[0].id)]},
        )
        assert picked.status_code == 200, picked.text

        response = client.post(
            f'{RENTALS}/blocks',
            headers=rental_auth,
            json={
                'item_id': str(projectors[0].id),
                'starts_at': (early + timedelta(hours=1)).isoformat(),
                'ends_at': (early + timedelta(hours=2)).isoformat(),
                'reason': 'Service',
            },
        )
        assert response.status_code == 409, response.text
        conflict = response.json()['detail']['conflicts'][0]
        held_from = datetime.fromisoformat(conflict['held_from'])
        # It holds from the hand-out, not from the booked window in 2099.
        assert abs((held_from - early).total_seconds()) < 60
        assert held_from < START
        assert datetime.fromisoformat(conflict['held_until']) == END

    def test_a_loan_past_its_due_date_is_open_ended(
        self,
        client: TestClient,
        rental_auth: dict[str, str],
        projectors,
        db_session,
    ) -> None:
        now = datetime.now(UTC)
        booking = client.post(
            f'{RENTALS}/bookings',
            headers=rental_auth,
            json=booking_payload(
                item_id=projectors[0].id,
                starts_at=now + timedelta(hours=1),
                ends_at=now + timedelta(hours=4),
            ),
        ).json()
        picked = client.post(
            f'{RENTALS}/bookings/{booking["id"]}/pickup',
            headers=rental_auth,
            json={'item_ids': [str(projectors[0].id)]},
        )
        assert picked.status_code == 200, picked.text
        make_overdue(db_session, booking['id'], now - timedelta(days=2))

        response = client.post(
            f'{RENTALS}/blocks',
            headers=rental_auth,
            json={
                'item_id': str(projectors[0].id),
                'starts_at': now.isoformat(),
                'ends_at': (now + timedelta(hours=2)).isoformat(),
                'reason': 'Service',
            },
        )
        assert response.status_code == 409, response.text
        conflict = response.json()['detail']['conflicts'][0]
        # Past the due date the hold has no end: the return is what ends it.
        assert conflict['held_until'] is None
        held_from = datetime.fromisoformat(conflict['held_from'])
        assert held_from < now + timedelta(minutes=1)
        assert held_from < datetime.fromisoformat(booking['starts_at'])


def test_the_sheet_marks_one_unit_on_two_lines(
    client: TestClient, rental_auth: dict[str, str], projectors
) -> None:
    response = client.post(
        f'{RENTALS}/bookings/check',
        headers=rental_auth,
        json={
            'starts_at': START.isoformat(),
            'ends_at': END.isoformat(),
            'lines': [
                {'item_id': str(projectors[0].id)},
                {'item_id': str(projectors[0].id)},
            ],
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['ok'] is False
    for line in body['lines']:
        assert line['ok'] is False
        assert any(
            conflict['kind'] == 'duplicate_unit' for conflict in line['conflicts']
        ), line


class TestAReservationWhoseWindowPassed:
    def test_it_offers_extend_not_hand_out(
        self, client: TestClient, rental_auth: dict[str, str], projectors
    ) -> None:
        now = datetime.now(UTC)
        booking = client.post(
            f'{RENTALS}/bookings',
            headers=rental_auth,
            json=booking_payload(
                item_id=projectors[0].id,
                starts_at=now - timedelta(hours=4),
                ends_at=now - timedelta(hours=1),
            ),
        )
        assert booking.status_code == 201, booking.text
        detail = booking.json()
        assert detail['can_pickup'] is False
        assert detail['can_extend'] is True

        refused = client.post(
            f'{RENTALS}/bookings/{detail["id"]}/pickup',
            headers=rental_auth,
            json={'item_ids': [str(projectors[0].id)]},
        )
        assert refused.status_code == 400, refused.text
        assert refused.json()['detail']['code'] == 'RENTAL_PICKUP_WINDOW_PASSED'

        today = client.get(f'{RENTALS}/today', headers=rental_auth).json()
        row = next(
            item for item in today['expired'] if item['booking_id'] == detail['id']
        )
        assert row['can_pickup'] is False
        assert all(item['booking_id'] != detail['id'] for item in today['pickups'])
