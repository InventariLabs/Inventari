"""Every path that decides free time answers with the same busy intervals.

A unit is unavailable while it is out, whatever wrote the hold: a booking
that has not come back, a block, a model-level promise, or the buffer the
next booking needs. These tests take each path that once read only part of
that picture and pin the answer the availability engine gives.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.modules.rentals.tests.conftest import START, booking_payload

pytestmark = pytest.mark.integration

RENTALS = '/api/v1/rentals'


def _create(client: TestClient, auth: dict[str, str], **kwargs):
    return client.post(
        f'{RENTALS}/bookings', headers=auth, json=booking_payload(**kwargs)
    )


def _pickup(client: TestClient, auth: dict[str, str], booking_id: str, item_ids):
    return client.post(
        f'{RENTALS}/bookings/{booking_id}/pickup',
        headers=auth,
        json={'item_ids': [str(item_id) for item_id in item_ids]},
    )


def _buffer_rule(client: TestClient, auth: dict[str, str], **kwargs):
    return client.put(f'{RENTALS}/buffer-rules', headers=auth, json=kwargs)


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


def _return(
    client: TestClient, auth: dict[str, str], booking_id: str, unit: dict, **kwargs
):
    body = {'unit_id': unit['id'], 'condition': 'NEEDS_REPAIR'}
    body.update(kwargs)
    return client.post(
        f'{RENTALS}/bookings/{booking_id}/return',
        headers=auth,
        json={'units': [body]},
    )


class TestALateLoan:
    def test_a_late_loan_holds_its_unit_until_it_comes_back(
        self,
        client: TestClient,
        rental_auth: dict[str, str],
        projectors,
    ) -> None:
        now = datetime.now(UTC)
        booking = _create(
            client,
            rental_auth,
            item_id=projectors[0].id,
            starts_at=now - timedelta(days=2),
            ends_at=now - timedelta(hours=1),
        )
        assert booking.status_code == 201, booking.text
        picked = _pickup(client, rental_auth, booking.json()['id'], [projectors[0].id])
        assert picked.status_code == 200, picked.text

        tomorrow = (now + timedelta(days=1)).replace(
            hour=10, minute=0, second=0, microsecond=0
        )
        response = _create(
            client,
            rental_auth,
            item_id=projectors[0].id,
            starts_at=tomorrow,
            ends_at=tomorrow + timedelta(hours=2),
        )
        assert response.status_code == 409, response.text
        kinds = {
            conflict['kind']
            for conflict in response.json()['detail']['lines'][0]['conflicts']
        }
        assert 'late' in kinds

        availability = client.get(
            f'{RENTALS}/availability',
            headers=rental_auth,
            params={
                'item_id': str(projectors[0].id),
                'starts_at': tomorrow.isoformat(),
                'ends_at': (tomorrow + timedelta(hours=2)).isoformat(),
            },
        )
        assert availability.status_code == 200, availability.text
        assert availability.json()['free_units'] == 0

    def test_the_calendar_draws_the_late_stretch_up_to_now(
        self,
        client: TestClient,
        rental_auth: dict[str, str],
        projectors,
    ) -> None:
        now = datetime.now(UTC)
        booking = _create(
            client,
            rental_auth,
            item_id=projectors[0].id,
            starts_at=now - timedelta(days=2),
            ends_at=now - timedelta(days=1),
        )
        assert booking.status_code == 201, booking.text
        assert (
            _pickup(
                client, rental_auth, booking.json()['id'], [projectors[0].id]
            ).status_code
            == 200
        )

        response = client.get(
            f'{RENTALS}/calendar',
            headers=rental_auth,
            params={
                'starts_at': (now - timedelta(days=2)).isoformat(),
                'ends_at': (now + timedelta(days=2)).isoformat(),
            },
        )
        assert response.status_code == 200, response.text
        groups = response.json()['groups']
        unit = next(
            entry
            for group in groups
            for entry in group['units']
            if entry['item_id'] == str(projectors[0].id)
        )
        out = next(bar for bar in unit['bars'] if bar['kind'] == 'out')
        late = next(bar for bar in unit['bars'] if bar['kind'] == 'late')
        due = datetime.fromisoformat(booking.json()['ends_at'].replace('Z', '+00:00'))
        assert datetime.fromisoformat(out['ends_at'].replace('Z', '+00:00')) == due
        assert datetime.fromisoformat(late['starts_at'].replace('Z', '+00:00')) == due
        late_end = datetime.fromisoformat(late['ends_at'].replace('Z', '+00:00'))
        assert late_end > now - timedelta(minutes=1)
        assert late_end <= now + timedelta(minutes=1)


class TestTheNewBookingBuffer:
    def test_a_buffer_is_applied_in_both_directions(
        self,
        client: TestClient,
        rental_auth: dict[str, str],
        projectors,
    ) -> None:
        rule = _buffer_rule(
            client, rental_auth, model='Projektor 4K', hours_before=4, hours_after=0
        )
        assert rule.status_code == 200, rule.text

        first = _create(
            client,
            rental_auth,
            item_id=projectors[0].id,
            starts_at=START,
            ends_at=START + timedelta(hours=2),
        )
        assert first.status_code == 201, first.text

        later = _create(
            client,
            rental_auth,
            item_id=projectors[0].id,
            starts_at=START + timedelta(hours=2),
            ends_at=START + timedelta(hours=4),
        )
        assert later.status_code == 409, later.text
        kinds = {
            conflict['kind']
            for conflict in later.json()['detail']['lines'][0]['conflicts']
        }
        assert 'buffer' in kinds

        # The same pair on another unit, asked in the other order.
        later_other = _create(
            client,
            rental_auth,
            item_id=projectors[1].id,
            starts_at=START + timedelta(hours=2),
            ends_at=START + timedelta(hours=4),
        )
        assert later_other.status_code == 201, later_other.text
        earlier_other = _create(
            client,
            rental_auth,
            item_id=projectors[1].id,
            starts_at=START,
            ends_at=START + timedelta(hours=2),
        )
        assert earlier_other.status_code == 409, earlier_other.text


class TestACategoryBuffer:
    def test_a_category_buffer_binds_an_any_unit_booking(
        self,
        client: TestClient,
        rental_auth: dict[str, str],
        rental_category,
        screen,
    ) -> None:
        rule = _buffer_rule(
            client,
            rental_auth,
            category_id=str(rental_category.id),
            hours_before=0,
            hours_after=24,
        )
        assert rule.status_code == 200, rule.text

        first = _create(
            client,
            rental_auth,
            model='Ekran 2 m',
            quantity=1,
            starts_at=START,
            ends_at=START + timedelta(hours=2),
        )
        assert first.status_code == 201, first.text

        later = _create(
            client,
            rental_auth,
            model='Ekran 2 m',
            quantity=1,
            starts_at=START + timedelta(hours=3),
            ends_at=START + timedelta(hours=5),
        )
        assert later.status_code == 409, later.text
        kinds = {
            conflict['kind']
            for conflict in later.json()['detail']['lines'][0]['conflicts']
        }
        assert 'model_booking' in kinds

        specific = _create(
            client,
            rental_auth,
            item_id=screen.id,
            starts_at=START + timedelta(hours=3),
            ends_at=START + timedelta(hours=5),
        )
        assert specific.status_code == 409, specific.text


class TestABlockOverAnAnyUnitBooking:
    def test_a_manual_block_that_takes_the_last_unit_is_refused(
        self,
        client: TestClient,
        rental_auth: dict[str, str],
        screen,
    ) -> None:
        booking = _create(
            client,
            rental_auth,
            model='Ekran 2 m',
            quantity=1,
            starts_at=START,
            ends_at=START + timedelta(hours=4),
        )
        assert booking.status_code == 201, booking.text

        response = _block(
            client,
            rental_auth,
            screen.id,
            START,
            START + timedelta(hours=4),
        )
        assert response.status_code == 409, response.text
        conflict = response.json()['detail']['conflicts'][0]
        assert conflict['booking_id'] == booking.json()['id']
        assert conflict['borrower_name'] == 'Jan Wiśniewski'

    def test_a_service_block_that_takes_the_last_unit_names_the_booking(
        self,
        client: TestClient,
        rental_auth: dict[str, str],
        screen,
    ) -> None:
        now = datetime.now(UTC)
        booking = _create(
            client,
            rental_auth,
            item_id=screen.id,
            starts_at=now - timedelta(hours=2),
            ends_at=now + timedelta(hours=1),
        )
        assert booking.status_code == 201, booking.text
        picked = _pickup(client, rental_auth, booking.json()['id'], [screen.id]).json()

        later_end = now + timedelta(days=1)
        later = _create(
            client,
            rental_auth,
            model='Ekran 2 m',
            quantity=1,
            starts_at=now + timedelta(hours=2),
            ends_at=later_end,
            name='Studio Foto',
        )
        assert later.status_code == 201, later.text

        response = _return(
            client,
            rental_auth,
            booking.json()['id'],
            picked['lines'][0]['units'][0],
            service_reason='uszkodzony ekran',
            service_until=later_end.isoformat(),
        )
        assert response.status_code == 409, response.text
        detail = response.json()['detail']
        assert detail['code'] == 'RENTAL_SERVICE_BLOCK_CONFLICT'
        assert detail['conflicts'][0]['booking_id'] == later.json()['id']


class TestAnExtensionIntoAnAnyUnitBooking:
    def test_a_tail_that_takes_the_last_unit_is_refused_naming_the_booking(
        self,
        client: TestClient,
        rental_auth: dict[str, str],
        screen,
    ) -> None:
        booking = _create(
            client,
            rental_auth,
            item_id=screen.id,
            starts_at=START,
            ends_at=START + timedelta(hours=2),
        )
        assert booking.status_code == 201, booking.text
        later = _create(
            client,
            rental_auth,
            model='Ekran 2 m',
            quantity=1,
            starts_at=START + timedelta(hours=4),
            ends_at=START + timedelta(hours=6),
            name='Studio Foto',
        )
        assert later.status_code == 201, later.text

        response = client.post(
            f'{RENTALS}/bookings/{booking.json()["id"]}/extend',
            headers=rental_auth,
            json={'ends_at': (START + timedelta(hours=5)).isoformat()},
        )
        assert response.status_code == 409, response.text
        detail = response.json()['detail']
        assert detail['code'] == 'RENTAL_EXTENSION_BLOCKED'
        assert any(
            conflict.get('booking_id') == later.json()['id']
            for conflict in detail['conflicts']
        )
