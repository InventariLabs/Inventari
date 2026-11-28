"""A borrower and an asset both carry their booking history."""

from __future__ import annotations

from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.core.testing import ModuleTestHelper
from app.models.partner import Partner
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


def _book_for(client: TestClient, auth: dict[str, str], item_id, name, email) -> dict:
    payload = booking_payload(item_id=item_id, name=name)
    payload['borrower_email'] = email
    response = client.post(f'{RENTALS}/bookings', headers=auth, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_a_name_and_an_email_become_one_partner_profile(
    client: TestClient, rental_auth: dict[str, str], projectors, db_session
) -> None:
    first = _book_for(
        client, rental_auth, projectors[0].id, 'Anna Nowak', 'anna@example.com'
    )
    # The address names the person in any casing: no second profile.
    second = _book_for(
        client, rental_auth, projectors[1].id, 'Anna N.', 'Anna@Example.com'
    )

    assert first['borrower_kind'] == 'partner'
    assert second['borrower_partner_id'] == first['borrower_partner_id']
    assert second['borrower_name'] == 'Anna N.'
    partner = db_session.get(Partner, UUID(first['borrower_partner_id']))
    assert partner is not None
    assert (partner.name, partner.type, partner.email) == (
        'Anna Nowak',
        'CUSTOMER',
        'anna@example.com',
    )
    history = client.get(
        f'{RENTALS}/bookings',
        headers=rental_auth,
        params={'partner_id': first['borrower_partner_id']},
    ).json()
    assert history['total'] == 2


def test_a_namesake_with_another_address_gets_a_profile_of_their_own(
    client: TestClient, rental_auth: dict[str, str], projectors, db_session
) -> None:
    first = _book_for(
        client, rental_auth, projectors[0].id, 'Jan Kowal', 'jan@one.example.com'
    )
    second = _book_for(
        client, rental_auth, projectors[1].id, 'Jan Kowal', 'jan@two.example.com'
    )

    assert second['borrower_partner_id'] != first['borrower_partner_id']
    partner = db_session.get(Partner, UUID(second['borrower_partner_id']))
    assert partner is not None
    assert partner.name == 'Jan Kowal (jan@two.example.com)'


def test_a_name_without_an_email_stays_on_the_booking(
    client: TestClient, rental_auth: dict[str, str], projectors, db_session
) -> None:
    created = client.post(
        f'{RENTALS}/bookings',
        headers=rental_auth,
        json=booking_payload(item_id=projectors[0].id, name='Passer-by'),
    ).json()

    assert created['borrower_kind'] == 'external'
    assert db_session.query(Partner).count() == 0


def test_without_the_right_to_add_partners_no_profile_is_created(
    client: TestClient,
    h: ModuleTestHelper,
    rental_org,
    projectors,
    db_session,
) -> None:
    desk = h.create_user(rental_org, email='desk@example.com', role='user')
    h.grant_permissions(desk, ['rentals:read', 'rentals:write'])

    created = _book_for(
        client,
        h.get_auth_headers(desk),
        projectors[0].id,
        'Anna Nowak',
        'anna@example.com',
    )

    assert created['borrower_kind'] == 'external'
    assert created['borrower_email'] == 'anna@example.com'
    assert db_session.query(Partner).count() == 0
