"""A booking is a promise for a window, and the window is checked when it is made."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.modules.rentals.tests.conftest import END, START, booking_payload

pytestmark = pytest.mark.integration

RENTALS = '/api/v1/rentals'


def _create(client: TestClient, auth: dict[str, str], **kwargs):
    return client.post(
        f'{RENTALS}/bookings', headers=auth, json=booking_payload(**kwargs)
    )


class TestCreateBooking:
    def test_an_asset_booking_is_reserved(
        self,
        client: TestClient,
        rental_auth: dict[str, str],
        projectors,
    ) -> None:
        response = _create(client, rental_auth, item_id=projectors[0].id)
        assert response.status_code == 201, response.text
        booking = response.json()
        assert booking['status'] == 'RESERVED'
        assert booking['is_late'] is False
        assert booking['borrower_kind'] == 'external'
        assert booking['borrower_name'] == 'Jan Wiśniewski'
        assert len(booking['lines']) == 1
        assert booking['lines'][0]['item_id'] == str(projectors[0].id)
        assert booking['lines'][0]['resolved_count'] == 1

    def test_a_model_booking_counts_units(
        self,
        client: TestClient,
        rental_auth: dict[str, str],
        projectors,
    ) -> None:
        response = _create(client, rental_auth, model='Projektor 4K', quantity=2)
        assert response.status_code == 201, response.text
        line = response.json()['lines'][0]
        assert line['model'] == 'Projektor 4K'
        assert line['quantity'] == 2
        assert line['resolved_count'] == 0

    def test_an_overlapping_booking_of_one_asset_is_refused(
        self,
        client: TestClient,
        rental_auth: dict[str, str],
        projectors,
        borrower,
    ) -> None:
        assert _create(client, rental_auth, item_id=projectors[0].id).status_code == 201
        response = _create(
            client,
            rental_auth,
            item_id=projectors[0].id,
            partner_id=borrower.id,
            starts_at=START + timedelta(days=1),
            ends_at=END + timedelta(days=1),
        )
        assert response.status_code == 409, response.text
        detail = response.json()['detail']
        assert detail['code'] == 'RENTAL_BOOKING_CONFLICT'
        conflicts = detail['lines'][0]['conflicts']
        assert len(conflicts) == 1
        assert conflicts[0]['kind'] == 'reserved'
        assert conflicts[0]['item_id'] == str(projectors[0].id)
        assert conflicts[0]['label'] == 'Jan Wiśniewski'
        # The sheet's way out is offered by the check it makes while typing:
        # the nearest window of the same length in which the asset is free.
        check = client.post(
            f'{RENTALS}/bookings/check',
            headers=rental_auth,
            json=booking_payload(item_id=projectors[0].id),
        )
        assert check.status_code == 200, check.text
        nearest = check.json()['lines'][0]['nearest_window']
        assert nearest is not None
        assert nearest['starts_at'] >= END.isoformat().replace('+00:00', 'Z')

    def test_a_model_booking_beyond_the_free_units_is_refused(
        self,
        client: TestClient,
        rental_auth: dict[str, str],
        projectors,
    ) -> None:
        assert _create(client, rental_auth, item_id=projectors[0].id).status_code == 201
        assert _create(client, rental_auth, item_id=projectors[1].id).status_code == 201
        response = _create(client, rental_auth, model='Projektor 4K', quantity=2)
        assert response.status_code == 409, response.text
        line = response.json()['detail']['lines'][0]
        assert line['available'] == 1
        assert line['max_quantity'] == 1
        assert {conflict['item_id'] for conflict in line['conflicts']} == {
            str(projectors[0].id),
            str(projectors[1].id),
        }

    def test_the_check_says_which_line_does_not_fit(
        self,
        client: TestClient,
        rental_auth: dict[str, str],
        projectors,
    ) -> None:
        assert _create(client, rental_auth, item_id=projectors[0].id).status_code == 201
        response = client.post(
            f'{RENTALS}/bookings/check',
            headers=rental_auth,
            json=booking_payload(item_id=projectors[0].id),
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body['ok'] is False
        assert body['lines'][0]['ok'] is False
        assert body['lines'][0]['nearest_window']['starts_at']

    def test_an_unknown_asset_is_refused(
        self,
        client: TestClient,
        rental_auth: dict[str, str],
        screen,
    ) -> None:
        import uuid

        response = _create(client, rental_auth, item_id=uuid.uuid4())
        assert response.status_code == 400, response.text
        assert 'cannot be booked' in response.json()['detail']['message']


class TestOneOrganization:
    def test_a_booking_of_another_organization_is_not_found(
        self,
        client: TestClient,
        rental_auth: dict[str, str],
        projectors,
        h,
    ) -> None:
        booking = _create(client, rental_auth, item_id=projectors[0].id).json()
        other_org = h.create_org(
            'Other Rentals',
            ['core', 'items', 'locations', 'categories', 'equipment', 'rentals'],
        )
        other_user = h.create_user(other_org, email='other-rentals@example.com')
        response = client.get(
            f'{RENTALS}/bookings/{booking["id"]}',
            headers=h.get_auth_headers(other_user),
        )
        assert response.status_code == 404, response.text
