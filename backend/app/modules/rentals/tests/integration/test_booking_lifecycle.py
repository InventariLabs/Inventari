"""Hand-out, return, extension, blocks and the today view."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.equipment.models import EquipmentAssignment
from app.modules.rentals.models import RentalBlock
from app.modules.rentals.tests.conftest import END, START, booking_payload

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


class TestPickup:
    def test_a_scan_resolves_a_model_line_to_units(
        self,
        client: TestClient,
        rental_auth: dict[str, str],
        projectors,
        db_session: Session,
    ) -> None:
        booking = _create(client, rental_auth, model='Projektor 4K', quantity=2).json()
        response = _pickup(
            client,
            rental_auth,
            booking['id'],
            [projectors[0].id, projectors[1].id],
        )
        assert response.status_code == 200, response.text
        picked = response.json()
        assert picked['status'] == 'PICKED_UP'
        assert picked['lines'][0]['resolved_count'] == 2
        assert {unit['item_id'] for unit in picked['lines'][0]['units']} == {
            str(projectors[0].id),
            str(projectors[1].id),
        }
        assignments = (
            db_session.execute(
                select(EquipmentAssignment).where(
                    EquipmentAssignment.item_id.in_(
                        [projectors[0].id, projectors[1].id]
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(assignments) == 2
        for assignment in assignments:
            assert assignment.checked_in_at is None
            # The hand-out expects the booking's end, to the minute.
            assert assignment.expected_return_at == END

    def test_a_partial_pickup_is_refused(
        self,
        client: TestClient,
        rental_auth: dict[str, str],
        projectors,
    ) -> None:
        booking = _create(client, rental_auth, model='Projektor 4K', quantity=2).json()
        response = _pickup(client, rental_auth, booking['id'], [projectors[0].id])
        assert response.status_code == 409, response.text
        detail = response.json()['detail']
        assert detail['code'] == 'RENTAL_PICKUP_INCOMPLETE'
        assert detail['missing'] == 1
        # Nothing was handed out: the refusal is before the first write that
        # matters.
        assert (
            client.get(
                f'{RENTALS}/bookings/{booking["id"]}', headers=rental_auth
            ).json()['status']
            == 'RESERVED'
        )

    def test_the_wrong_model_cannot_fill_an_any_unit_line(
        self,
        client: TestClient,
        rental_auth: dict[str, str],
        projectors,
        screen,
    ) -> None:
        booking = _create(client, rental_auth, model='Projektor 4K', quantity=1).json()
        response = _pickup(client, rental_auth, booking['id'], [screen.id])
        assert response.status_code == 409, response.text
        assert response.json()['detail']['unexpected'] == [str(screen.id)]


class TestReturn:
    def test_every_unit_comes_back_with_its_condition(
        self,
        client: TestClient,
        rental_auth: dict[str, str],
        projectors,
        db_session: Session,
    ) -> None:
        booking = _create(client, rental_auth, model='Projektor 4K', quantity=2).json()
        picked = _pickup(
            client,
            rental_auth,
            booking['id'],
            [projectors[0].id, projectors[1].id],
        ).json()
        units = picked['lines'][0]['units']
        response = client.post(
            f'{RENTALS}/bookings/{booking["id"]}/return',
            headers=rental_auth,
            json={
                'units': [
                    {'unit_id': units[0]['id'], 'condition': 'GOOD'},
                    {'unit_id': units[1]['id'], 'condition': 'DAMAGED'},
                ]
            },
        )
        assert response.status_code == 200, response.text
        returned = response.json()
        assert returned['status'] == 'RETURNED'
        assert [unit['condition'] for unit in returned['lines'][0]['units']] == [
            'GOOD',
            'DAMAGED',
        ]
        assignments = (
            db_session.execute(
                select(EquipmentAssignment).where(
                    EquipmentAssignment.item_id.in_(
                        [projectors[0].id, projectors[1].id]
                    )
                )
            )
            .scalars()
            .all()
        )
        assert all(assignment.checked_in_at is not None for assignment in assignments)

    def test_needs_service_creates_a_block_and_a_later_booking_stands_in_the_way(
        self,
        client: TestClient,
        rental_auth: dict[str, str],
        projectors,
        db_session: Session,
    ) -> None:
        booking = _create(client, rental_auth, item_id=projectors[0].id).json()
        picked = _pickup(client, rental_auth, booking['id'], [projectors[0].id]).json()
        unit = picked['lines'][0]['units'][0]

        later_start = END + timedelta(hours=2)
        later_end = END + timedelta(days=2)
        later = _create(
            client,
            rental_auth,
            item_id=projectors[0].id,
            starts_at=later_start,
            ends_at=later_end,
            name='Studio Foto',
        )
        assert later.status_code == 201, later.text

        response = client.post(
            f'{RENTALS}/bookings/{booking["id"]}/return',
            headers=rental_auth,
            json={
                'units': [
                    {
                        'unit_id': unit['id'],
                        'condition': 'NEEDS_REPAIR',
                        'service_reason': 'zabrudzona matryca',
                        'service_until': later_end.isoformat(),
                    }
                ]
            },
        )
        assert response.status_code == 409, response.text
        detail = response.json()['detail']
        assert detail['code'] == 'RENTAL_SERVICE_BLOCK_CONFLICT'
        conflict = detail['conflicts'][0]
        assert conflict['borrower_name'] == 'Studio Foto'
        assert conflict['item_id'] == str(projectors[0].id)
        # The screen offers to end the block before that booking instead.
        assert conflict['suggested_until']

        # And the second way out: move the later booking to a free unit of
        # the same model, together with the return.
        free_unit = projectors[1]
        response = client.post(
            f'{RENTALS}/bookings/{booking["id"]}/return',
            headers=rental_auth,
            json={
                'units': [
                    {
                        'unit_id': unit['id'],
                        'condition': 'NEEDS_REPAIR',
                        'service_reason': 'zabrudzona matryca',
                        'service_until': later_end.isoformat(),
                    }
                ],
                'moves': [
                    {
                        'line_id': conflict['line_id'],
                        'from_item_id': str(projectors[0].id),
                        'to_item_id': str(free_unit.id),
                    }
                ],
            },
        )
        assert response.status_code == 200, response.text
        blocks = db_session.execute(select(RentalBlock)).scalars().all()
        assert len(blocks) == 1
        assert blocks[0].item_id == projectors[0].id
        assert blocks[0].source == 'SERVICE'

        moved = client.get(
            f'{RENTALS}/bookings/{later.json()["id"]}', headers=rental_auth
        ).json()
        assert moved['lines'][0]['item_id'] == str(free_unit.id)


class TestExtend:
    def test_extending_moves_the_hand_out_expected_return(
        self,
        client: TestClient,
        rental_auth: dict[str, str],
        projectors,
        db_session: Session,
    ) -> None:
        booking = _create(client, rental_auth, item_id=projectors[0].id).json()
        _pickup(client, rental_auth, booking['id'], [projectors[0].id])
        new_end = END + timedelta(days=1)
        response = client.post(
            f'{RENTALS}/bookings/{booking["id"]}/extend',
            headers=rental_auth,
            json={'ends_at': new_end.isoformat()},
        )
        assert response.status_code == 200, response.text
        assert response.json()['ends_at'] == new_end.strftime('%Y-%m-%dT%H:%M:%SZ')
        assignment = db_session.execute(
            select(EquipmentAssignment).where(
                EquipmentAssignment.item_id == projectors[0].id
            )
        ).scalar_one()
        assert assignment.expected_return_at == new_end

    def test_an_extension_into_another_booking_is_refused_naming_it(
        self,
        client: TestClient,
        rental_auth: dict[str, str],
        projectors,
    ) -> None:
        booking = _create(client, rental_auth, item_id=projectors[0].id).json()
        later = _create(
            client,
            rental_auth,
            item_id=projectors[0].id,
            starts_at=END + timedelta(hours=1),
            ends_at=END + timedelta(days=2),
            name='Studio Foto',
        )
        assert later.status_code == 201, later.text
        response = client.post(
            f'{RENTALS}/bookings/{booking["id"]}/extend',
            headers=rental_auth,
            json={'ends_at': (END + timedelta(days=1)).isoformat()},
        )
        assert response.status_code == 409, response.text
        detail = response.json()['detail']
        assert detail['code'] == 'RENTAL_EXTENSION_BLOCKED'
        assert any(
            conflict.get('booking_id') == later.json()['id']
            for conflict in detail['conflicts']
        )


class TestCancel:
    def test_a_cancelled_booking_frees_its_time(
        self,
        client: TestClient,
        rental_auth: dict[str, str],
        projectors,
    ) -> None:
        booking = _create(client, rental_auth, item_id=projectors[0].id).json()
        response = client.post(
            f'{RENTALS}/bookings/{booking["id"]}/cancel', headers=rental_auth
        )
        assert response.status_code == 200, response.text
        assert response.json()['status'] == 'CANCELLED'
        again = _create(client, rental_auth, item_id=projectors[0].id)
        assert again.status_code == 201, again.text


class TestBuffer:
    def test_a_booking_inside_the_buffer_is_refused(
        self,
        client: TestClient,
        rental_auth: dict[str, str],
        projectors,
    ) -> None:
        rule = client.put(
            f'{RENTALS}/buffer-rules',
            headers=rental_auth,
            json={'model': 'Projektor 4K', 'hours_before': 0, 'hours_after': 4},
        )
        assert rule.status_code == 200, rule.text
        first = _create(client, rental_auth, item_id=projectors[0].id)
        assert first.status_code == 201, first.text

        back_to_back = _create(
            client,
            rental_auth,
            item_id=projectors[0].id,
            starts_at=END,
            ends_at=END + timedelta(hours=4),
        )
        assert back_to_back.status_code == 409, back_to_back.text
        kinds = {
            conflict['kind']
            for conflict in back_to_back.json()['detail']['lines'][0]['conflicts']
        }
        assert kinds == {'buffer'}

        after = _create(
            client,
            rental_auth,
            item_id=projectors[0].id,
            starts_at=END + timedelta(hours=4),
            ends_at=END + timedelta(hours=8),
        )
        assert after.status_code == 201, after.text


class TestBlocks:
    def test_a_block_over_a_booking_is_refused_naming_the_booking(
        self,
        client: TestClient,
        rental_auth: dict[str, str],
        projectors,
    ) -> None:
        booking = _create(client, rental_auth, item_id=projectors[0].id).json()
        response = client.post(
            f'{RENTALS}/blocks',
            headers=rental_auth,
            json={
                'item_id': str(projectors[0].id),
                'starts_at': START.isoformat(),
                'ends_at': (START + timedelta(days=1)).isoformat(),
                'reason': 'szczotki',
            },
        )
        assert response.status_code == 409, response.text
        conflict = response.json()['detail']['conflicts'][0]
        assert conflict['booking_id'] == booking['id']
        assert conflict['borrower_name'] == 'Jan Wiśniewski'

    def test_a_booking_into_a_block_is_refused(
        self,
        client: TestClient,
        rental_auth: dict[str, str],
        projectors,
    ) -> None:
        block = client.post(
            f'{RENTALS}/blocks',
            headers=rental_auth,
            json={
                'item_id': str(projectors[0].id),
                'starts_at': START.isoformat(),
                'ends_at': END.isoformat(),
                'reason': 'szczotki',
            },
        )
        assert block.status_code == 201, block.text
        response = _create(client, rental_auth, item_id=projectors[0].id)
        assert response.status_code == 409, response.text
        kinds = {
            conflict['kind']
            for conflict in response.json()['detail']['lines'][0]['conflicts']
        }
        assert kinds == {'block'}

        assert (
            client.delete(
                f'{RENTALS}/blocks/{block.json()["id"]}', headers=rental_auth
            ).status_code
            == 204
        )
        assert _create(client, rental_auth, item_id=projectors[0].id).status_code == 201


class TestTodayView:
    def test_the_day_lists_pickups_returns_and_late_loans(
        self,
        client: TestClient,
        rental_auth: dict[str, str],
        projectors,
    ) -> None:
        now = datetime.now(UTC)
        late = _create(
            client,
            rental_auth,
            item_id=projectors[0].id,
            starts_at=now - timedelta(days=3),
            ends_at=now - timedelta(days=1),
        ).json()
        _pickup(client, rental_auth, late['id'], [projectors[0].id])

        pickup_today = _create(
            client,
            rental_auth,
            item_id=projectors[1].id,
            starts_at=now + timedelta(hours=1),
            ends_at=now + timedelta(days=2),
        ).json()

        return_today = _create(
            client,
            rental_auth,
            item_id=projectors[2].id,
            starts_at=now - timedelta(days=1),
            ends_at=now + timedelta(hours=2),
        ).json()
        _pickup(client, rental_auth, return_today['id'], [projectors[2].id])

        response = client.get(f'{RENTALS}/today', headers=rental_auth)
        assert response.status_code == 200, response.text
        today = response.json()
        assert today['late_count'] == 1
        assert today['late'][0]['booking_id'] == late['id']
        assert today['late'][0]['late_days'] >= 1
        assert today['pickups_count'] == 1
        assert today['pickups'][0]['booking_id'] == pickup_today['id']
        assert today['returns_count'] == 1
        assert today['returns'][0]['booking_id'] == return_today['id']

    def test_overdue_is_derived_from_the_window(
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
        ).json()
        assert booking['is_late'] is False
        picked = _pickup(client, rental_auth, booking['id'], [projectors[0].id]).json()
        # No stored flag: the same row is late now because its window passed.
        assert picked['is_late'] is True
        assert picked['late_days'] >= 1


class TestCalendar:
    def test_rows_are_grouped_by_model_with_an_any_unit_row(
        self,
        client: TestClient,
        rental_auth: dict[str, str],
        projectors,
    ) -> None:
        _create(client, rental_auth, model='Projektor 4K', quantity=2)
        _create(client, rental_auth, item_id=projectors[2].id)
        response = client.get(
            f'{RENTALS}/calendar',
            headers=rental_auth,
            params={
                'starts_at': START.isoformat(),
                'ends_at': (START + timedelta(days=14)).isoformat(),
            },
        )
        assert response.status_code == 200, response.text
        groups = response.json()['groups']
        group = next(entry for entry in groups if entry['model'] == 'Projektor 4K')
        assert group['total_units'] == 3
        assert len(group['units']) == 3
        assert group['any_unit'][0]['quantity'] == 2
        ids = {unit['item_id'] for unit in group['units']}
        assert str(projectors[2].id) in ids
        # The specific booking is a bar on its own unit.
        specific = next(
            unit for unit in group['units'] if unit['item_id'] == str(projectors[2].id)
        )
        assert specific['bars'][0]['kind'] == 'reserved'


class TestAvailability:
    def test_a_model_reports_the_units_still_free(
        self,
        client: TestClient,
        rental_auth: dict[str, str],
        projectors,
    ) -> None:
        _create(client, rental_auth, model='Projektor 4K', quantity=2)
        response = client.get(
            f'{RENTALS}/availability',
            headers=rental_auth,
            params={
                'model': 'Projektor 4K',
                'starts_at': START.isoformat(),
                'ends_at': END.isoformat(),
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body['total_units'] == 3
        assert body['free_units'] == 1
