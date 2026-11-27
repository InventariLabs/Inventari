"""A handed-out unit is busy from the moment it left, not from the booked start.

A booking may be handed out before its window opens. The unit is then taken
for the stretch up to the window as well, so the hand-out is judged over that
stretch, and every later question about the unit reads it. Times here are
built around the clock, which is what the rules compare them with.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.modules.rentals.tests.conftest import booking_payload, make_overdue

pytestmark = pytest.mark.integration

RENTALS = '/api/v1/rentals'


def _create(client: TestClient, auth: dict[str, str], **kwargs):
    return client.post(
        f'{RENTALS}/bookings', headers=auth, json=booking_payload(**kwargs)
    )


def _booked(client: TestClient, auth: dict[str, str], **kwargs) -> dict:
    response = _create(client, auth, **kwargs)
    assert response.status_code == 201, response.text
    return response.json()


def _pickup(client: TestClient, auth: dict[str, str], booking_id: str, item_ids):
    return client.post(
        f'{RENTALS}/bookings/{booking_id}/pickup',
        headers=auth,
        json={'item_ids': [str(item_id) for item_id in item_ids]},
    )


def _block(client: TestClient, auth: dict[str, str], item_id, starts_at, ends_at):
    return client.post(
        f'{RENTALS}/blocks',
        headers=auth,
        json={
            'item_id': str(item_id),
            'starts_at': starts_at.isoformat(),
            'ends_at': ends_at.isoformat(),
            'reason': 'serwis',
        },
    )


def _instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def _named_in_refusal(response) -> set[str]:
    assert response.status_code == 409, response.text
    detail = response.json()['detail']
    assert detail['code'] == 'RENTAL_PICKUP_ASSET_TAKEN', detail
    return {
        reason['booking_id']
        for unit in detail['units']
        for reason in unit['reasons']
        if reason.get('booking_id')
    }


class TestAHandOutBeforeTheWindow:
    def test_it_is_refused_when_someone_holds_the_unit_before_the_window(
        self,
        client: TestClient,
        rental_auth: dict[str, str],
        screen,
    ) -> None:
        now = datetime.now(UTC)
        sooner = _booked(
            client,
            rental_auth,
            item_id=screen.id,
            starts_at=now + timedelta(hours=2),
            ends_at=now + timedelta(hours=4),
            name='Today',
        )
        later = _booked(
            client,
            rental_auth,
            item_id=screen.id,
            starts_at=now + timedelta(days=2),
            ends_at=now + timedelta(days=3),
            name='Later',
        )

        response = _pickup(client, rental_auth, later['id'], [screen.id])
        assert sooner['id'] in _named_in_refusal(response)
        # The unit stayed in, so the booking that holds it today is handed out.
        assert (
            _pickup(client, rental_auth, sooner['id'], [screen.id]).status_code == 200
        )

    def test_the_unit_is_busy_from_the_hand_out_everywhere(
        self,
        client: TestClient,
        rental_auth: dict[str, str],
        screen,
    ) -> None:
        now = datetime.now(UTC)
        booking = _booked(
            client,
            rental_auth,
            item_id=screen.id,
            starts_at=now + timedelta(days=2),
            ends_at=now + timedelta(days=3),
        )
        picked = _pickup(client, rental_auth, booking['id'], [screen.id])
        assert picked.status_code == 200, picked.text
        handed_out_at = _instant(picked.json()['handed_out_at'])
        window = (now + timedelta(hours=5), now + timedelta(hours=6))

        availability = client.get(
            f'{RENTALS}/availability',
            headers=rental_auth,
            params={
                'item_id': str(screen.id),
                'starts_at': window[0].isoformat(),
                'ends_at': window[1].isoformat(),
            },
        )
        assert availability.status_code == 200, availability.text
        assert availability.json()['free_units'] == 0

        tonight = _create(
            client,
            rental_auth,
            item_id=screen.id,
            starts_at=window[0],
            ends_at=window[1],
            name='Tonight',
        )
        assert tonight.status_code == 409, tonight.text
        conflicts = tonight.json()['detail']['lines'][0]['conflicts']
        assert [(c['kind'], c['booking_id']) for c in conflicts] == [
            ('out', booking['id'])
        ]

        block = _block(client, rental_auth, screen.id, *window)
        assert block.status_code == 409, block.text
        assert block.json()['detail']['conflicts'][0]['booking_id'] == booking['id']

        calendar = client.get(
            f'{RENTALS}/calendar',
            headers=rental_auth,
            params={
                'starts_at': (now - timedelta(days=1)).isoformat(),
                'ends_at': (now + timedelta(days=1)).isoformat(),
            },
        )
        assert calendar.status_code == 200, calendar.text
        bars = [
            bar
            for group in calendar.json()['groups']
            for unit in group['units']
            if unit['item_id'] == str(screen.id)
            for bar in unit['bars']
        ]
        assert [(bar['kind'], bar['booking_id']) for bar in bars] == [
            ('out', booking['id'])
        ]
        assert _instant(bars[0]['starts_at']) == handed_out_at.replace(
            microsecond=_instant(bars[0]['starts_at']).microsecond
        )

    @pytest.mark.parametrize('line', ['unit', 'any unit'])
    def test_it_cannot_take_a_unit_a_model_booking_counts_on_before_the_window(
        self,
        client: TestClient,
        rental_auth: dict[str, str],
        racks,
        line: str,
    ) -> None:
        now = datetime.now(UTC)
        tomorrow = now + timedelta(days=1)
        promised = _booked(
            client,
            rental_auth,
            model='Rack 42U',
            starts_at=tomorrow,
            ends_at=tomorrow + timedelta(hours=4),
            name='Studio Foto',
        )
        # The other rack is busy inside the promise, which leaves one for it.
        _booked(
            client,
            rental_auth,
            item_id=racks[0].id,
            starts_at=tomorrow + timedelta(hours=1),
            ends_at=tomorrow + timedelta(hours=2),
        )
        asked = {'item_id': racks[1].id} if line == 'unit' else {'model': 'Rack 42U'}
        later = _booked(
            client,
            rental_auth,
            starts_at=now + timedelta(days=3),
            ends_at=now + timedelta(days=4),
            **asked,
        )

        response = _pickup(client, rental_auth, later['id'], [racks[1].id])
        assert promised['id'] in _named_in_refusal(response)


class TestAnOverdueUnit:
    def test_a_block_cannot_cover_it(
        self,
        client: TestClient,
        rental_auth: dict[str, str],
        screen,
        db_session: Session,
    ) -> None:
        now = datetime.now(UTC)
        booking = _booked(
            client,
            rental_auth,
            item_id=screen.id,
            starts_at=now - timedelta(days=2),
            ends_at=now + timedelta(hours=1),
        )
        assert (
            _pickup(client, rental_auth, booking['id'], [screen.id]).status_code == 200
        )
        make_overdue(db_session, booking['id'], now - timedelta(hours=1))

        response = _block(
            client,
            rental_auth,
            screen.id,
            now + timedelta(days=1),
            now + timedelta(days=2),
        )
        assert response.status_code == 409, response.text
        assert response.json()['detail']['conflicts'][0]['booking_id'] == booking['id']


class TestABookingWhoseWindowIsOver:
    def test_it_is_extended_before_it_is_handed_out(
        self,
        client: TestClient,
        rental_auth: dict[str, str],
        screen,
    ) -> None:
        now = datetime.now(UTC)
        booking = _booked(
            client,
            rental_auth,
            item_id=screen.id,
            starts_at=now - timedelta(days=2),
            ends_at=now - timedelta(days=1),
        )

        refused = _pickup(client, rental_auth, booking['id'], [screen.id])
        assert refused.status_code == 400, refused.text
        assert refused.json()['detail']['code'] == 'RENTAL_PICKUP_WINDOW_PASSED'

        extended = client.post(
            f'{RENTALS}/bookings/{booking["id"]}/extend',
            headers=rental_auth,
            json={'ends_at': (datetime.now(UTC) + timedelta(days=1)).isoformat()},
        )
        assert extended.status_code == 200, extended.text
        picked = _pickup(client, rental_auth, booking['id'], [screen.id])
        assert picked.status_code == 200, picked.text
