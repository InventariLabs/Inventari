"""The unit's precision gate measures the number the client named.

A kilogram keeps three places, and so does the store: the schema cuts every
quantity to three places on the way in, so 1.1234 reached the kilogram's
gate as 1.123 — a number the kilogram can hold — and the form, the edit and
the quantity endpoint all wrote 1.123 without a word. Only the scan, which
built its schema from its own float, refused. The rule is now one rule for
every door: the gate sees the quantity as named, and the store's rounding
applies only to a quantity the unit has already let through.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.models.uom import Uom, UomCategory

pytestmark = pytest.mark.integration

POLISH = {'Accept-Language': 'pl'}

KILOGRAM_REFUSAL = (
    'Jednostka kg przyjmuje liczby z dokładnością do 3 miejsc po przecinku, '
    'więc 1,1234 nie da się zapisać. Zaokrąglij ilość do tej dokładności.'
)

#: A code the scan reads as a barcode rather than a label.
BARCODE = '5901234123457'


def _message(response: Any) -> str:
    message: str = response.json()['detail']['message']
    return message


def _kilogram(db: Session) -> Uom:
    uom = db.scalars(select(Uom).where(Uom.symbol == 'kg')).first()
    assert uom is not None, "'kg' is not in the seeded catalogue"
    return uom


def _create(
    client: TestClient,
    storage: StorageLocation,
    headers: dict[str, str],
    *,
    quantity: float,
    uom: Uom,
    name: str = 'Mąka żytnia',
) -> Any:
    return client.post(
        '/api/v1/items',
        headers=headers,
        json={
            'name': name,
            'location_id': str(storage.id),
            'quantity': quantity,
            'uom_id': str(uom.id),
        },
    )


def _scan_barcode(
    client: TestClient,
    storage: StorageLocation,
    headers: dict[str, str],
    *,
    quantity: float,
    uom: Uom,
) -> Any:
    return client.post(
        f'/api/v1/labels/scan/{BARCODE}/assign',
        headers=headers,
        json={
            'name': 'Mąka ze skanu',
            'location_id': str(storage.id),
            'quantity': quantity,
            'uom_id': str(uom.id),
        },
    )


class TestEveryDoorRefusesTheFourthPlaceOnAKilogram:
    def test_the_form_refuses_it(
        self,
        client: TestClient,
        db_session: Session,
        test_storage_location: StorageLocation,
        auth_headers: dict[str, str],
    ) -> None:
        response = _create(
            client,
            test_storage_location,
            {**auth_headers, **POLISH},
            quantity=1.1234,
            uom=_kilogram(db_session),
            name='Odmówiona mąka',
        )

        assert response.status_code == 400, response.text
        assert _message(response) == KILOGRAM_REFUSAL
        left_over = db_session.scalars(
            select(Item).where(Item.name == 'Odmówiona mąka')
        )
        assert left_over.first() is None

    def test_the_edit_refuses_it(
        self,
        client: TestClient,
        db_session: Session,
        test_storage_location: StorageLocation,
        auth_headers: dict[str, str],
    ) -> None:
        headers = {**auth_headers, **POLISH}
        created = _create(
            client,
            test_storage_location,
            headers,
            quantity=1,
            uom=_kilogram(db_session),
        )
        assert created.status_code == 201, created.text

        response = client.put(
            f'/api/v1/items/{created.json()["id"]}',
            headers=headers,
            json={'quantity': 1.1234},
        )

        assert response.status_code == 400, response.text
        assert _message(response) == KILOGRAM_REFUSAL

    def test_the_quantity_endpoint_refuses_it(
        self,
        client: TestClient,
        db_session: Session,
        test_storage_location: StorageLocation,
        auth_headers: dict[str, str],
    ) -> None:
        headers = {**auth_headers, **POLISH}
        created = _create(
            client,
            test_storage_location,
            headers,
            quantity=1,
            uom=_kilogram(db_session),
        )
        assert created.status_code == 201, created.text

        response = client.patch(
            f'/api/v1/items/{created.json()["id"]}/quantity',
            headers=headers,
            json={'quantity': 1.1234},
        )

        assert response.status_code == 400, response.text
        assert _message(response) == KILOGRAM_REFUSAL

    def test_a_rescan_of_a_stocked_code_refuses_it_and_leaves_the_stock(
        self,
        client: TestClient,
        db_session: Session,
        test_storage_location: StorageLocation,
        auth_headers: dict[str, str],
    ) -> None:
        headers = {**auth_headers, **POLISH}
        kilogram = _kilogram(db_session)
        first = _scan_barcode(
            client, test_storage_location, headers, quantity=1, uom=kilogram
        )
        assert first.status_code == 200, first.text

        response = _scan_barcode(
            client, test_storage_location, headers, quantity=1.1234, uom=kilogram
        )

        assert response.status_code == 400, response.text
        assert _message(response) == KILOGRAM_REFUSAL
        db_session.expire_all()
        stocked = db_session.get(Item, first.json()['id'])
        assert stocked is not None
        assert stocked.quantity == Decimal('1')


class TestTheStoreRoundsOnlyWhatTheUnitLetThrough:
    def test_a_unit_finer_than_the_store_is_rounded_to_three_places(
        self,
        client: TestClient,
        db_session: Session,
        test_household: Organization,
        test_storage_location: StorageLocation,
        auth_headers: dict[str, str],
    ) -> None:
        """A unit keeping four places lets 1.0005 through; the store keeps
        three, so the record holds 1.001 — half up, as the schema promises."""
        category = UomCategory(organization_id=test_household.id, name='Fine mass')
        db_session.add(category)
        db_session.flush()
        fine = Uom(
            organization_id=test_household.id,
            category_id=category.id,
            name='fine gram',
            symbol='fg',
            rounding=0.0001,
        )
        db_session.add(fine)
        db_session.commit()

        response = _create(
            client, test_storage_location, auth_headers, quantity=1.0005, uom=fine
        )

        assert response.status_code == 201, response.text
        assert Decimal(str(response.json()['quantity'])) == Decimal('1.001')
