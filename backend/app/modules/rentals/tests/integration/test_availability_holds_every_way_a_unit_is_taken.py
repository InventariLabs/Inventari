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
from sqlalchemy.orm import Session

from app.modules.rentals.tests.conftest import START, booking_payload, make_overdue

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


def _return_all(
    client: TestClient,
    auth: dict[str, str],
    booking_id: str,
    units: list[dict],
    moves: list[dict] | None = None,
):
    return client.post(
        f'{RENTALS}/bookings/{booking_id}/return',
        headers=auth,
        json={'units': units, 'moves': moves or []},
    )


def _manual_checkout(client: TestClient, auth: dict[str, str], item_id):
    return client.post(
        '/api/v1/equipment/assignments',
        headers=auth,
        json={'item_id': str(item_id), 'assigned_to_name': 'Manual holder'},
    )


class TestALateLoan:
    def test_a_late_loan_holds_its_unit_until_it_comes_back(
        self,
        client: TestClient,
        rental_auth: dict[str, str],
        projectors,
        db_session: Session,
    ) -> None:
        now = datetime.now(UTC)
        booking = _create(
            client,
            rental_auth,
            item_id=projectors[0].id,
            starts_at=now - timedelta(days=2),
            ends_at=now + timedelta(hours=1),
        )
        assert booking.status_code == 201, booking.text
        picked = _pickup(client, rental_auth, booking.json()['id'], [projectors[0].id])
        assert picked.status_code == 200, picked.text
        make_overdue(db_session, booking.json()['id'], now - timedelta(hours=1))

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
        db_session: Session,
    ) -> None:
        now = datetime.now(UTC)
        booking = _create(
            client,
            rental_auth,
            item_id=projectors[0].id,
            starts_at=now - timedelta(days=2),
            ends_at=now + timedelta(hours=1),
        )
        assert booking.status_code == 201, booking.text
        assert (
            _pickup(
                client, rental_auth, booking.json()['id'], [projectors[0].id]
            ).status_code
            == 200
        )
        due = now - timedelta(days=1)
        make_overdue(db_session, booking.json()['id'], due)

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
        for instant in (out['ends_at'], late['starts_at']):
            drawn = datetime.fromisoformat(instant.replace('Z', '+00:00'))
            assert abs(drawn - due) < timedelta(seconds=1)
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


class TestAModelPromiseHoldsItsWholeWindow:
    def test_asset_bookings_take_the_promised_units_one_by_one(
        self,
        client: TestClient,
        rental_auth: dict[str, str],
        projectors,
    ) -> None:
        week = START + timedelta(days=12)
        promised = _create(
            client,
            rental_auth,
            model='Projektor 4K',
            quantity=1,
            starts_at=week,
            ends_at=week + timedelta(days=4),
        )
        assert promised.status_code == 201, promised.text

        first = _create(
            client,
            rental_auth,
            item_id=projectors[0].id,
            starts_at=week + timedelta(days=1, hours=1),
            ends_at=week + timedelta(days=1, hours=3),
        )
        assert first.status_code == 201, first.text

        second = _create(
            client,
            rental_auth,
            item_id=projectors[1].id,
            starts_at=week + timedelta(days=3, hours=1),
            ends_at=week + timedelta(days=3, hours=3),
        )
        assert second.status_code == 201, second.text

        # One unit is still free for the whole week; the third is the last
        # unit the promise is counting on, on any day of that week.
        last = _create(
            client,
            rental_auth,
            item_id=projectors[2].id,
            starts_at=week + timedelta(days=2, hours=1),
            ends_at=week + timedelta(days=2, hours=3),
        )
        assert last.status_code == 409, last.text
        conflicts = last.json()['detail']['lines'][0]['conflicts']
        assert any(
            conflict['booking_id'] == promised.json()['id'] for conflict in conflicts
        ), conflicts

    def test_blocks_take_the_promised_units_one_by_one(
        self,
        client: TestClient,
        rental_auth: dict[str, str],
        projectors,
    ) -> None:
        week = START + timedelta(days=12)
        promised = _create(
            client,
            rental_auth,
            model='Projektor 4K',
            quantity=1,
            starts_at=week,
            ends_at=week + timedelta(days=4),
        )
        assert promised.status_code == 201, promised.text

        first = _block(
            client,
            rental_auth,
            projectors[0].id,
            week + timedelta(days=1, hours=1),
            week + timedelta(days=1, hours=3),
        )
        assert first.status_code == 201, first.text

        second = _block(
            client,
            rental_auth,
            projectors[1].id,
            week + timedelta(days=3, hours=1),
            week + timedelta(days=3, hours=3),
        )
        assert second.status_code == 201, second.text

        last = _block(
            client,
            rental_auth,
            projectors[2].id,
            week + timedelta(days=2, hours=1),
            week + timedelta(days=2, hours=3),
        )
        assert last.status_code == 409, last.text
        conflicts = last.json()['detail']['conflicts']
        assert any(
            conflict['booking_id'] == promised.json()['id'] for conflict in conflicts
        ), conflicts

    def test_an_extension_into_a_promised_window_is_refused(
        self,
        client: TestClient,
        rental_auth: dict[str, str],
        racks,
    ) -> None:
        promised = _create(
            client,
            rental_auth,
            model='Rack 42U',
            quantity=1,
            starts_at=START + timedelta(days=20),
            ends_at=START + timedelta(days=24),
        )
        assert promised.status_code == 201, promised.text

        # One unit is busy inside the promise; the other is what the promise
        # still counts on, and it is booked just before the promise starts.
        inside = _create(
            client,
            rental_auth,
            item_id=racks[0].id,
            starts_at=START + timedelta(days=23),
            ends_at=START + timedelta(days=23, hours=2),
        )
        assert inside.status_code == 201, inside.text
        before = _create(
            client,
            rental_auth,
            item_id=racks[1].id,
            starts_at=START + timedelta(days=19),
            ends_at=START + timedelta(days=19, hours=2),
        )
        assert before.status_code == 201, before.text

        response = client.post(
            f'{RENTALS}/bookings/{before.json()["id"]}/extend',
            headers=rental_auth,
            json={'ends_at': (START + timedelta(days=20, hours=3)).isoformat()},
        )
        assert response.status_code == 409, response.text
        detail = response.json()['detail']
        assert detail['code'] == 'RENTAL_EXTENSION_BLOCKED'
        assert any(
            conflict.get('booking_id') == promised.json()['id']
            for conflict in detail['conflicts']
        ), detail['conflicts']


class TestAPickupScanThatResolvesAPromise:
    def test_a_scan_that_takes_the_last_unit_of_another_promise_is_refused(
        self,
        client: TestClient,
        rental_auth: dict[str, str],
        racks,
    ) -> None:
        week = _create(
            client,
            rental_auth,
            model='Rack 42U',
            quantity=1,
            starts_at=START + timedelta(days=24),
            ends_at=START + timedelta(days=28),
        )
        assert week.status_code == 201, week.text
        # The promise can still use either unit; one of them is taken for a
        # stretch inside its window.
        inside = _create(
            client,
            rental_auth,
            item_id=racks[0].id,
            starts_at=START + timedelta(days=27),
            ends_at=START + timedelta(days=27, hours=2),
        )
        assert inside.status_code == 201, inside.text

        short = _create(
            client,
            rental_auth,
            model='Rack 42U',
            quantity=1,
            starts_at=START + timedelta(days=25),
            ends_at=START + timedelta(days=25, hours=2),
        )
        assert short.status_code == 201, short.text

        response = _pickup(client, rental_auth, short.json()['id'], [racks[1].id])
        assert response.status_code == 409, response.text
        detail = response.json()['detail']
        assert detail['code'] == 'RENTAL_PICKUP_ASSET_TAKEN'
        assert detail['units'][0]['item_id'] == str(racks[1].id)
        assert any(
            reason.get('booking_id') == week.json()['id']
            for reason in detail['units'][0]['reasons']
        ), detail['units']


class TestAHandOutMadeOutsideABooking:
    def test_an_early_return_does_not_hide_a_new_manual_hand_out(
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
            ends_at=now + timedelta(days=3),
        )
        assert booking.status_code == 201, booking.text
        picked = _pickup(client, rental_auth, booking.json()['id'], [screen.id]).json()
        returned = _return_all(
            client,
            rental_auth,
            booking.json()['id'],
            [
                {
                    'unit_id': picked['lines'][0]['units'][0]['id'],
                    'condition': 'GOOD',
                }
            ],
        )
        assert returned.status_code == 200, returned.text

        handed = _manual_checkout(client, rental_auth, screen.id)
        assert handed.status_code == 201, handed.text

        tomorrow = (now + timedelta(days=1)).replace(
            hour=10, minute=0, second=0, microsecond=0
        )
        availability = client.get(
            f'{RENTALS}/availability',
            headers=rental_auth,
            params={
                'item_id': str(screen.id),
                'starts_at': tomorrow.isoformat(),
                'ends_at': (tomorrow + timedelta(hours=2)).isoformat(),
            },
        )
        assert availability.status_code == 200, availability.text
        assert availability.json()['free_units'] == 0

        response = _create(
            client,
            rental_auth,
            item_id=screen.id,
            starts_at=tomorrow,
            ends_at=tomorrow + timedelta(hours=2),
        )
        assert response.status_code == 409, response.text
        conflicts = response.json()['detail']['lines'][0]['conflicts']
        assert any(conflict['kind'] == 'out' for conflict in conflicts), conflicts


class TestAReturnThatSendsUnitsToService:
    def _picked_up_pair(self, client, auth, racks):
        now = datetime.now(UTC)
        booking = _create(
            client,
            auth,
            model='Rack 42U',
            quantity=2,
            starts_at=now - timedelta(hours=2),
            ends_at=now + timedelta(hours=1),
        )
        assert booking.status_code == 201, booking.text
        picked = _pickup(client, auth, booking.json()['id'], [racks[0].id, racks[1].id])
        assert picked.status_code == 200, picked.text
        later_start = now + timedelta(days=2)
        later = _create(
            client,
            auth,
            item_id=racks[0].id,
            starts_at=later_start,
            ends_at=later_start + timedelta(hours=2),
            name='Studio Foto',
        )
        assert later.status_code == 201, later.text
        return booking.json(), picked.json(), later.json(), now

    def test_the_sheet_is_never_offered_the_unit_it_sends_to_service(
        self,
        client: TestClient,
        rental_auth: dict[str, str],
        racks,
    ) -> None:
        booking, picked, later, now = self._picked_up_pair(client, rental_auth, racks)
        units = picked['lines'][0]['units']
        service_until = now + timedelta(days=5)

        def plan(order):
            return [
                {
                    'unit_id': unit['id'],
                    'condition': 'NEEDS_REPAIR',
                    'service_reason': 'uszkodzona szyna',
                    'service_until': service_until.isoformat(),
                }
                for unit in order
            ]

        response = _return_all(client, rental_auth, booking['id'], plan(units))
        assert response.status_code == 409, response.text
        conflict = response.json()['detail']['conflicts'][0]
        assert conflict['booking_id'] == later['id']
        assert conflict['free_units'] == []

        move = {
            'line_id': later['lines'][0]['id'],
            'from_item_id': str(racks[0].id),
            'to_item_id': str(racks[1].id),
        }
        with_move = _return_all(client, rental_auth, booking['id'], plan(units), [move])
        assert with_move.status_code == 409, with_move.text
        assert with_move.json()['detail']['conflicts'][0]['free_units'] == []

        reversed_order = _return_all(
            client, rental_auth, booking['id'], plan(list(reversed(units))), [move]
        )
        assert reversed_order.status_code == 409, reversed_order.text

        # The way out the sheet offers: end the block before the later
        # booking, which leaves it where it is.
        ended = _return_all(
            client,
            rental_auth,
            booking['id'],
            [
                {
                    'unit_id': unit['id'],
                    'condition': 'NEEDS_REPAIR',
                    'service_reason': 'uszkodzona szyna',
                    'service_until': conflict['suggested_until'],
                }
                for unit in units
            ],
        )
        assert ended.status_code == 200, ended.text
        still = client.get(
            f'{RENTALS}/bookings/{later["id"]}', headers=rental_auth
        ).json()
        assert still['lines'][0]['item_id'] == str(racks[0].id)


class TestAReturnWithAServiceDateInThePast:
    def test_a_service_end_before_the_return_is_refused(
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
        ).json()
        picked = _pickup(client, rental_auth, booking['id'], [screen.id]).json()
        response = _return(
            client,
            rental_auth,
            booking['id'],
            picked['lines'][0]['units'][0],
            service_reason='uszkodzony ekran',
            service_until=(now - timedelta(days=2)).isoformat(),
        )
        assert response.status_code == 422, response.text


class TestAPickupThatResolvesItsOwnLine:
    def test_a_resolution_does_not_count_the_same_unit_against_the_booking(
        self,
        client: TestClient,
        rental_auth: dict[str, str],
        racks,
    ) -> None:
        # Two bookings exactly fill the model: one unit for a day inside a
        # week, one for the week. Pinning the day's unit satisfies the day's
        # own promise; the week must still see one unit free, rather than the
        # day being read as a promise still waiting *and* its unit as taken.
        week = _create(
            client,
            rental_auth,
            model='Rack 42U',
            quantity=1,
            starts_at=START + timedelta(days=12),
            ends_at=START + timedelta(days=16),
            name='Week',
        )
        assert week.status_code == 201, week.text
        day = _create(
            client,
            rental_auth,
            model='Rack 42U',
            quantity=1,
            starts_at=START + timedelta(days=13, hours=1),
            ends_at=START + timedelta(days=13, hours=3),
            name='Day',
        )
        assert day.status_code == 201, day.text

        picked_day = _pickup(client, rental_auth, day.json()['id'], [racks[0].id])
        assert picked_day.status_code == 200, picked_day.text
        picked_week = _pickup(client, rental_auth, week.json()['id'], [racks[1].id])
        assert picked_week.status_code == 200, picked_week.text


class TestAUnitBookingsOwnBuffer:
    def test_a_before_buffer_counts_against_a_model_promise(
        self,
        client: TestClient,
        rental_auth: dict[str, str],
        projectors,
    ) -> None:
        rule = _buffer_rule(
            client, rental_auth, model='Projektor 4K', hours_before=4, hours_after=0
        )
        assert rule.status_code == 200, rule.text

        week = START + timedelta(days=12)
        promised = _create(
            client,
            rental_auth,
            model='Projektor 4K',
            quantity=1,
            starts_at=week,
            ends_at=week + timedelta(days=4, hours=8),
        )
        assert promised.status_code == 201, promised.text

        for index, day in ((0, 1), (1, 2)):
            inside = _create(
                client,
                rental_auth,
                item_id=projectors[index].id,
                starts_at=week + timedelta(days=day, hours=1),
                ends_at=week + timedelta(days=day, hours=3),
            )
            assert inside.status_code == 201, inside.text

        # The last unit is booked after the promise ends, but its four-hour
        # before-buffer starts inside the promised window.
        last = _create(
            client,
            rental_auth,
            item_id=projectors[2].id,
            starts_at=week + timedelta(days=4, hours=9),
            ends_at=week + timedelta(days=4, hours=11),
        )
        assert last.status_code == 409, last.text
        conflicts = last.json()['detail']['lines'][0]['conflicts']
        assert any(
            conflict.get('booking_id') == promised.json()['id']
            for conflict in conflicts
        ), conflicts


class TestAnExtensionOfABookingThatHoldsTwoUnits:
    def test_a_pair_extension_into_a_promised_window_is_refused(
        self,
        client: TestClient,
        rental_auth: dict[str, str],
        racks,
    ) -> None:
        # The promise needs one of the two units for its whole window. Each
        # unit of the pair is free before that window, so the extension is
        # judged on the stay it creates, not on the one stored.
        week = START + timedelta(days=16)
        promised = _create(
            client,
            rental_auth,
            model='Rack 42U',
            quantity=1,
            starts_at=week,
            ends_at=week + timedelta(days=4),
            name='Studio Foto',
        )
        assert promised.status_code == 201, promised.text

        pair_start = week - timedelta(days=2)
        pair = client.post(
            f'{RENTALS}/bookings',
            headers=rental_auth,
            json={
                'borrower_name': 'Jan Wiśniewski',
                'starts_at': pair_start.isoformat(),
                'ends_at': (pair_start + timedelta(hours=2)).isoformat(),
                'lines': [
                    {'item_id': str(racks[0].id)},
                    {'item_id': str(racks[1].id)},
                ],
            },
        )
        assert pair.status_code == 201, pair.text

        response = client.post(
            f'{RENTALS}/bookings/{pair.json()["id"]}/extend',
            headers=rental_auth,
            json={'ends_at': (week + timedelta(hours=3)).isoformat()},
        )
        assert response.status_code == 409, response.text
        detail = response.json()['detail']
        assert detail['code'] == 'RENTAL_EXTENSION_BLOCKED'
        assert any(
            conflict.get('booking_id') == promised.json()['id']
            for conflict in detail['conflicts']
        ), detail['conflicts']


class TestTwoLinesOfOneRequest:
    def test_two_unit_lines_cannot_together_take_a_promised_unit(
        self,
        client: TestClient,
        rental_auth: dict[str, str],
        racks,
    ) -> None:
        # Each line pins a unit the promise does not need that day; together
        # they take both units the promise counts on for its whole window.
        week = START + timedelta(days=12)
        promised = _create(
            client,
            rental_auth,
            model='Rack 42U',
            quantity=1,
            starts_at=week,
            ends_at=week + timedelta(days=4),
            name='Studio Foto',
        )
        assert promised.status_code == 201, promised.text

        body = {
            'starts_at': (week + timedelta(days=1, hours=1)).isoformat(),
            'ends_at': (week + timedelta(days=1, hours=3)).isoformat(),
            'lines': [
                {'item_id': str(racks[0].id)},
                {'item_id': str(racks[1].id)},
            ],
        }
        check = client.post(f'{RENTALS}/bookings/check', headers=rental_auth, json=body)
        assert check.status_code == 200, check.text
        assert check.json()['ok'] is False, check.json()

        response = client.post(
            f'{RENTALS}/bookings',
            headers=rental_auth,
            json={**body, 'borrower_name': 'Jan Wiśniewski'},
        )
        assert response.status_code == 409, response.text
        lines = response.json()['detail']['lines']
        assert any(
            conflict.get('booking_id') == promised.json()['id']
            for line in lines
            if not line['ok']
            for conflict in line['conflicts']
        ), lines

    def test_one_unit_cannot_be_on_two_lines(
        self,
        client: TestClient,
        rental_auth: dict[str, str],
        screen,
    ) -> None:
        response = client.post(
            f'{RENTALS}/bookings',
            headers=rental_auth,
            json={
                'borrower_name': 'Jan Wiśniewski',
                'starts_at': START.isoformat(),
                'ends_at': (START + timedelta(days=2)).isoformat(),
                'lines': [{'item_id': str(screen.id)}, {'item_id': str(screen.id)}],
            },
        )
        assert response.status_code == 422, response.text

    def test_two_lines_of_one_model_cannot_promise_more_units_than_the_fleet_has(
        self,
        client: TestClient,
        rental_auth: dict[str, str],
        screen,
    ) -> None:
        response = client.post(
            f'{RENTALS}/bookings',
            headers=rental_auth,
            json={
                'borrower_name': 'Jan Wiśniewski',
                'starts_at': START.isoformat(),
                'ends_at': (START + timedelta(days=2)).isoformat(),
                'lines': [
                    {'item_id': str(screen.id)},
                    {'model': 'Ekran 2 m', 'quantity': 1},
                ],
            },
        )
        assert response.status_code == 409, response.text
        lines = response.json()['detail']['lines']
        assert any(not line['ok'] for line in lines), lines

    def test_a_sibling_already_busy_for_the_promise_is_not_counted_twice(
        self,
        client: TestClient,
        rental_auth: dict[str, str],
        projectors,
    ) -> None:
        # The first unit is booked inside the promised week, so the promise
        # cannot use it anyway. Booking it again on another day, beside the
        # second unit, leaves the third free for the whole week.
        week = START + timedelta(days=12)
        promised = _create(
            client,
            rental_auth,
            model='Projektor 4K',
            quantity=1,
            starts_at=week,
            ends_at=week + timedelta(days=4),
            name='Studio Foto',
        )
        assert promised.status_code == 201, promised.text
        thursday = _create(
            client,
            rental_auth,
            item_id=projectors[0].id,
            starts_at=week + timedelta(days=3, hours=1),
            ends_at=week + timedelta(days=3, hours=3),
        )
        assert thursday.status_code == 201, thursday.text

        body = {
            'starts_at': (week + timedelta(days=1, hours=1)).isoformat(),
            'ends_at': (week + timedelta(days=1, hours=3)).isoformat(),
            'lines': [
                {'item_id': str(projectors[0].id)},
                {'item_id': str(projectors[1].id)},
            ],
        }
        check = client.post(f'{RENTALS}/bookings/check', headers=rental_auth, json=body)
        assert check.json()['ok'] is True, check.json()
        response = client.post(
            f'{RENTALS}/bookings',
            headers=rental_auth,
            json={**body, 'borrower_name': 'Jan Wiśniewski'},
        )
        assert response.status_code == 201, response.text


class TestAReturnThatMovesALaterBooking:
    def test_a_move_counts_the_buffer_of_the_unit_it_lands_on(
        self,
        client: TestClient,
        rental_auth: dict[str, str],
        projectors,
    ) -> None:
        rule = _buffer_rule(
            client, rental_auth, model='Projektor 4K', hours_before=4, hours_after=0
        )
        assert rule.status_code == 200, rule.text
        now = datetime.now(UTC)
        day = now + timedelta(days=2)
        promised = _create(
            client,
            rental_auth,
            model='Projektor 4K',
            quantity=1,
            starts_at=day,
            ends_at=day + timedelta(hours=8),
            name='Studio Foto',
        )
        assert promised.status_code == 201, promised.text
        inside = _create(
            client,
            rental_auth,
            item_id=projectors[1].id,
            starts_at=day + timedelta(hours=1),
            ends_at=day + timedelta(hours=2),
        )
        assert inside.status_code == 201, inside.text
        # The later booking starts after the promise ends; its buffer does not.
        later = _create(
            client,
            rental_auth,
            item_id=projectors[0].id,
            starts_at=day + timedelta(hours=9),
            ends_at=day + timedelta(hours=11),
            name='Later',
        )
        assert later.status_code == 201, later.text
        out = _create(
            client,
            rental_auth,
            item_id=projectors[0].id,
            starts_at=now - timedelta(hours=2),
            ends_at=now + timedelta(hours=1),
        )
        assert out.status_code == 201, out.text
        picked = _pickup(client, rental_auth, out.json()['id'], [projectors[0].id])
        assert picked.status_code == 200, picked.text
        unit = {
            'unit_id': picked.json()['lines'][0]['units'][0]['id'],
            'condition': 'NEEDS_REPAIR',
            'service_reason': 'lamp',
            'service_until': (day + timedelta(days=1)).isoformat(),
        }

        def move_to(item):
            return [
                {
                    'line_id': later.json()['lines'][0]['id'],
                    'from_item_id': str(projectors[0].id),
                    'to_item_id': str(item.id),
                }
            ]

        refused = _return_all(client, rental_auth, out.json()['id'], [unit])
        assert refused.status_code == 409, refused.text
        offered = {
            conflict['booking_id']: [free['item_id'] for free in conflict['free_units']]
            for conflict in refused.json()['detail']['conflicts']
        }
        # The third projector is the last one the promise can use.
        assert offered[later.json()['id']] == [str(projectors[1].id)]

        starving = _return_all(
            client, rental_auth, out.json()['id'], [unit], move_to(projectors[2])
        )
        assert starving.status_code == 409, starving.text

        moved = _return_all(
            client, rental_auth, out.json()['id'], [unit], move_to(projectors[1])
        )
        assert moved.status_code == 200, moved.text
