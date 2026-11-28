"""A borrower and an asset both carry their booking history."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.modules.rentals.tests.conftest import booking_payload

pytestmark = pytest.mark.integration

RENTALS = '/api/v1/rentals'


def test_the_partner_history_is_only_that_partner(
    client: TestClient, rental_auth: dict[str, str], projectors, borrower
) -> None:
    for partner_id, name, item in (
        (borrower.id, None, projectors[0]),
        (None, 'Someone Else', projectors[1]),
    ):
        payload = booking_payload(item_id=item.id, partner_id=partner_id, name=name)
        created = client.post(f'{RENTALS}/bookings', headers=rental_auth, json=payload)
        assert created.status_code == 201, created.text

    rows = client.get(
        f'{RENTALS}/bookings',
        headers=rental_auth,
        params={'partner_id': str(borrower.id)},
    ).json()
    assert rows['total'] == 1
    assert rows['items'][0]['borrower_name'] == borrower.name
    assert rows['items'][0]['borrower_partner_id'] == str(borrower.id)


def test_the_asset_history_names_both_pinned_and_resolved_units(
    client: TestClient, rental_auth: dict[str, str], projectors, screen
) -> None:
    pinned = client.post(
        f'{RENTALS}/bookings',
        headers=rental_auth,
        json=booking_payload(item_id=projectors[0].id),
    )
    assert pinned.status_code == 201, pinned.text
    model = client.post(
        f'{RENTALS}/bookings',
        headers=rental_auth,
        json=booking_payload(model='Projektor 4K', quantity=1),
    )
    assert model.status_code == 201, model.text
    picked = client.post(
        f'{RENTALS}/bookings/{model.json()["id"]}/pickup',
        headers=rental_auth,
        json={'item_ids': [str(projectors[1].id)]},
    )
    assert picked.status_code == 200, picked.text
    other = client.post(
        f'{RENTALS}/bookings',
        headers=rental_auth,
        json=booking_payload(item_id=screen.id),
    )
    assert other.status_code == 201, other.text

    rows = client.get(
        f'{RENTALS}/bookings',
        headers=rental_auth,
        params={'item_id': str(projectors[1].id)},
    ).json()
    assert rows['total'] == 1
    assert rows['items'][0]['id'] == model.json()['id']

    pinned_rows = client.get(
        f'{RENTALS}/bookings',
        headers=rental_auth,
        params={'item_id': str(projectors[0].id)},
    ).json()
    assert pinned_rows['total'] == 1
    assert pinned_rows['items'][0]['id'] == pinned.json()['id']
