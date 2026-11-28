"""Promises that never overlap each other do not use the same unit twice.

A fleet of five units with two units promised on each of Monday, Wednesday
and Friday is never more than two units busy: a week-long booking of one unit
fits, and the week answers three free. Summing the six promises would answer
nothing is free for a fleet that is half idle every day.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.modules.rentals.tests.conftest import booking_payload

pytestmark = pytest.mark.integration

RENTALS = '/api/v1/rentals'
MONDAY = datetime(2099, 1, 5, 9, 0, tzinfo=UTC)


def _day(offset: int) -> tuple[datetime, datetime]:
    start = MONDAY + timedelta(days=offset)
    return start, start + timedelta(hours=8)


def _create(client: TestClient, auth: dict[str, str], **kwargs):
    return client.post(
        f'{RENTALS}/bookings', headers=auth, json=booking_payload(**kwargs)
    )


def test_six_separate_day_promises_leave_the_week_free(
    client: TestClient,
    rental_auth: dict[str, str],
    projectors,
    db_session,
) -> None:
    # A five-unit model: the fixture has three, the test adds two.
    from app.models.category import Category
    from app.models.organization import Organization
    from app.models.storage_location import StorageLocation
    from app.modules.rentals.tests.conftest import make_asset

    org = db_session.get(Organization, projectors[0].organization_id)
    category = db_session.get(Category, projectors[0].category_id)
    place = db_session.get(StorageLocation, projectors[0].storage_location_id)
    fleet = list(projectors) + [
        make_asset(
            db_session,
            org,
            place,
            category,
            f'Projektor 4K extra #{index}',
            serial=f'PRJ-X{index}',
        )
        for index in (1, 2)
    ]
    assert len(fleet) == 5

    # Two single-unit promises on each of Monday, Wednesday and Friday.
    for day in (0, 2, 4):
        starts_at, ends_at = _day(day)
        for borrower in ('Anna', 'Bartek'):
            response = _create(
                client,
                rental_auth,
                model='Projektor 4K',
                quantity=1,
                starts_at=starts_at,
                ends_at=ends_at,
                name=borrower,
            )
            assert response.status_code == 201, response.text

    week_start, week_end = MONDAY, MONDAY + timedelta(days=5, hours=8)
    check = client.post(
        f'{RENTALS}/bookings/check',
        headers=rental_auth,
        json={
            'starts_at': week_start.isoformat(),
            'ends_at': week_end.isoformat(),
            'lines': [{'model': 'Projektor 4K', 'quantity': 1}],
        },
    )
    assert check.status_code == 200, check.text
    line = check.json()['lines'][0]
    # Two promises on a day, five units: three stay free all week.
    assert line['available'] == 3, line
    assert line['ok'] is True, line

    response = _create(
        client,
        rental_auth,
        model='Projektor 4K',
        quantity=1,
        starts_at=week_start,
        ends_at=week_end,
        name='Celina',
    )
    assert response.status_code == 201, response.text


def test_a_unit_inside_a_long_promise_is_judged_by_its_own_window(
    client: TestClient,
    rental_auth: dict[str, str],
    projectors,
    screen,
    db_session,
) -> None:
    """The unit is free every day the promise needs it, except its own day."""
    week_start, week_end = MONDAY, MONDAY + timedelta(days=5, hours=8)
    promise = _create(
        client,
        rental_auth,
        model='Projektor 4K',
        quantity=1,
        starts_at=week_start,
        ends_at=week_end,
    )
    assert promise.status_code == 201, promise.text

    tuesday, tuesday_end = _day(1)
    unit_booking = _create(
        client,
        rental_auth,
        item_id=projectors[0].id,
        starts_at=tuesday,
        ends_at=tuesday_end,
    )
    assert unit_booking.status_code == 201, unit_booking.text

    # And a block on a second unit, the same day, does not take the promise's
    # last unit either: the other two are free all week.
    block = client.post(
        f'{RENTALS}/blocks',
        headers=rental_auth,
        json={
            'item_id': str(projectors[1].id),
            'starts_at': tuesday.isoformat(),
            'ends_at': tuesday_end.isoformat(),
            'reason': 'Service',
        },
    )
    assert block.status_code == 201, block.text
