"""The precision refusal speaks the reader's language, and names their unit.

A whole-number unit refuses a fractional quantity, and a measured unit
refuses a quantity finer than the step it keeps. Both sentences were raw
English f-strings that named the unit by its symbol, so a Polish reader who
picked "szt." on the scan screen met "Unit 'pcs' requires a whole number
quantity (got 2.5)" under that field — English, and about a code the screen
never showed them.

The refusals now come from the error catalogue, name the unit the way the
catalogue in the reader's language names it, and state the quantity the same
way whichever door it came through: a scan carries the float the form sent
(2.5), the API schema quantizes to the store's three places (2.500). In a
Polish sentence the stated quantity follows the reader's separator — "2,5",
not the store's dot, which is a wire format, not a word.

The assertions are equalities against the Polish sentence, not status codes:
with the service reverted to its literal the responses still answer 400, and
only the sentence tells the two builds apart.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.label_pool import LabelPool
from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.models.uom import Uom, UomCategory
from app.models.user import User

pytestmark = pytest.mark.integration

POLISH = {'Accept-Language': 'pl'}

#: A piece takes whole numbers; the reader picked "szt." in a Polish session.
WHOLE_NUMBER_REFUSAL = (
    'Jednostka szt. przyjmuje tylko liczby całkowite, więc 2,5 nie da się '
    'zapisać. Zaokrąglij ilość do liczby całkowitej.'
)

#: A centimetre keeps two decimal places, a kilogram three — the same
#: sentence for the finer quantity, with the step's own count in it. The
#: column is ``numeric(12, 6)``, so both steps read back padded to six; the
#: count in the sentence is the step's, not the padding's.
DECIMAL_PLACES_REFUSAL = (
    'Jednostka cm przyjmuje liczby z dokładnością do 2 miejsc po przecinku, '
    'więc 1,005 nie da się zapisać. Zaokrąglij ilość do tej dokładności.'
)
KILOGRAM_REFUSAL = (
    'Jednostka kg przyjmuje liczby z dokładnością do 3 miejsc po przecinku, '
    'więc 1,1234 nie da się zapisać. Zaokrąglij ilość do tej dokładności.'
)


def _message(response: Any) -> str:
    message: str = response.json()['detail']['message']
    return message


def _uom(db: Session, symbol: str) -> Uom:
    uom = db.scalars(select(Uom).where(Uom.symbol == symbol)).first()
    assert uom is not None, f"'{symbol}' is not in the seeded catalogue"
    return uom


def _org_unit(db: Session, org: Organization, *, symbol: str) -> Uom:
    """A unit only this organization has — outside the label catalogue."""
    category = UomCategory(organization_id=org.id, name=f'Own {symbol}')
    db.add(category)
    db.flush()
    uom = Uom(
        organization_id=org.id,
        category_id=category.id,
        name=symbol,
        symbol=symbol,
        rounding=1.0,
    )
    db.add(uom)
    db.commit()
    db.refresh(uom)
    return uom


def _free_label(db: Session, user: User, *, short_code: str) -> LabelPool:
    label = LabelPool(
        short_code=short_code,
        organization_id=user.organization_id,
        created_by=user.id,
        is_assigned=False,
    )
    db.add(label)
    db.commit()
    db.refresh(label)
    return label


def _scan(
    client: TestClient,
    db: Session,
    user: User,
    storage: StorageLocation,
    headers: dict[str, str],
    *,
    short_code: str,
    quantity: float,
    uom: Uom,
) -> Any:
    label = _free_label(db, user, short_code=short_code)
    return client.post(
        f'/api/v1/labels/scan/{label.short_code}/assign',
        headers=headers,
        json={
            'name': 'Zeskanowana pozycja',
            'location_id': str(storage.id),
            'quantity': quantity,
            'uom_id': str(uom.id),
        },
    )


def _manual_create(
    client: TestClient,
    storage: StorageLocation,
    headers: dict[str, str],
    *,
    quantity: float,
    uom: Uom,
) -> Any:
    return client.post(
        '/api/v1/items',
        headers=headers,
        json={
            'name': 'Ręcznie dodana pozycja',
            'location_id': str(storage.id),
            'quantity': quantity,
            'uom_id': str(uom.id),
        },
    )


class TestTheScanRefusal:
    """POST /labels/scan/{code}/assign — the quick-add that measured the bug."""

    def test_a_fractional_piece_speaks_polish_and_names_the_unit_szt(
        self,
        client: TestClient,
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
        auth_headers: dict[str, str],
    ) -> None:
        response = _scan(
            client,
            db_session,
            test_user,
            test_storage_location,
            {**auth_headers, **POLISH},
            short_code='PL-PCS',
            quantity=2.5,
            uom=_uom(db_session, 'pcs'),
        )

        assert response.status_code == 400, response.text
        assert _message(response) == WHOLE_NUMBER_REFUSAL
        assert "Unit 'pcs'" not in _message(response)

    @pytest.mark.parametrize(
        ('short_code', 'symbol', 'quantity', 'refusal'),
        [
            ('PL-CM', 'cm', 1.005, DECIMAL_PLACES_REFUSAL),
            ('PL-KG', 'kg', 1.1234, KILOGRAM_REFUSAL),
        ],
    )
    def test_a_quantity_finer_than_the_step_speaks_polish_too(
        self,
        client: TestClient,
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
        auth_headers: dict[str, str],
        short_code: str,
        symbol: str,
        quantity: float,
        refusal: str,
    ) -> None:
        """The twin refusal — same screen, same unit code, same debt."""
        response = _scan(
            client,
            db_session,
            test_user,
            test_storage_location,
            {**auth_headers, **POLISH},
            short_code=short_code,
            quantity=quantity,
            uom=_uom(db_session, symbol),
        )

        assert response.status_code == 400, response.text
        assert _message(response) == refusal

    def test_a_unit_outside_the_catalogue_keeps_its_symbol(
        self,
        client: TestClient,
        db_session: Session,
        test_user: User,
        test_household: Organization,
        test_storage_location: StorageLocation,
        auth_headers: dict[str, str],
    ) -> None:
        """The fallback, end to end: an organization's own unit has no label."""
        response = _scan(
            client,
            db_session,
            test_user,
            test_storage_location,
            {**auth_headers, **POLISH},
            short_code='PL-CRATE',
            quantity=2.5,
            uom=_org_unit(db_session, test_household, symbol='crate'),
        )

        assert response.status_code == 400, response.text
        assert _message(response) == (
            'Jednostka crate przyjmuje tylko liczby całkowite, więc 2,5 nie '
            'da się zapisać. Zaokrąglij ilość do liczby całkowitej.'
        )

    def test_the_refused_scan_left_no_item_behind(
        self,
        client: TestClient,
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
        auth_headers: dict[str, str],
    ) -> None:
        _scan(
            client,
            db_session,
            test_user,
            test_storage_location,
            {**auth_headers, **POLISH},
            short_code='PL-NONE',
            quantity=2.5,
            uom=_uom(db_session, 'pcs'),
        )

        left_over = db_session.scalars(
            select(Item).where(Item.name == 'Zeskanowana pozycja')
        )
        assert left_over.first() is None


class TestBothDoorsStateTheSameNumber:
    """The quantity reaches the gate as a float on one door, a 3-place
    decimal on the other; the sentence has to be the same sentence."""

    def test_the_scan_and_the_manual_create_agree_on_the_sentence(
        self,
        client: TestClient,
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
        auth_headers: dict[str, str],
    ) -> None:
        pieces = _uom(db_session, 'pcs')
        headers = {**auth_headers, **POLISH}

        scanned = _scan(
            client,
            db_session,
            test_user,
            test_storage_location,
            headers,
            short_code='PL-SAME',
            quantity=2.5,
            uom=pieces,
        )
        manual = _manual_create(
            client, test_storage_location, headers, quantity=2.5, uom=pieces
        )

        assert scanned.status_code == 400, scanned.text
        assert manual.status_code == 400, manual.text
        assert _message(scanned) == WHOLE_NUMBER_REFUSAL
        assert _message(manual) == WHOLE_NUMBER_REFUSAL
        assert _message(manual) == _message(scanned)

    def test_the_manual_create_answers_in_polish_too(
        self,
        client: TestClient,
        db_session: Session,
        test_storage_location: StorageLocation,
        auth_headers: dict[str, str],
    ) -> None:
        """Measured here rather than inferred from the scan: the schema
        quantizes 2.5 to 2.500 on the way in, so the sentence is where the
        two paths would drift apart."""
        response = _manual_create(
            client,
            test_storage_location,
            {**auth_headers, **POLISH},
            quantity=2.5,
            uom=_uom(db_session, 'pcs'),
        )

        assert response.status_code == 400, response.text
        assert _message(response) == WHOLE_NUMBER_REFUSAL
        assert '2.500' not in _message(response)

    def test_the_item_quantity_endpoint_earns_the_language_stamp(
        self,
        client: TestClient,
        db_session: Session,
        test_user: User,
        test_item: Item,
        auth_headers: dict[str, str],
    ) -> None:
        """Where the route does not map the error itself, the 400 envelope
        translates the key and stamps ``lang`` — truthfully, because the
        refusal came from the catalogue."""
        test_item.uom_id = _uom(db_session, 'pcs').id
        db_session.commit()

        response = client.patch(
            f'/api/v1/items/{test_item.id}/quantity',
            headers={**auth_headers, **POLISH},
            json={'quantity': 2.5},
        )

        assert response.status_code == 400, response.text
        detail = response.json()['detail']
        assert detail['message'] == WHOLE_NUMBER_REFUSAL
        assert detail['lang'] == 'pl'

    def test_the_item_update_answers_with_the_refusals_own_code(
        self,
        client: TestClient,
        db_session: Session,
        test_item: Item,
        auth_headers: dict[str, str],
    ) -> None:
        """The edit door re-raised the refusal as a plain ValueError of its
        sentence, so the key was gone before the envelope was built and the
        answer said VALIDATION_ERROR; a client branching on the code could
        not tell a unit's step from any other refusal."""
        test_item.uom_id = _uom(db_session, 'pcs').id
        db_session.commit()

        response = client.put(
            f'/api/v1/items/{test_item.id}',
            headers={**auth_headers, **POLISH},
            json={'quantity': 2.5},
        )

        assert response.status_code == 400, response.text
        detail = response.json()['detail']
        assert detail['code'] == 'UOM_QUANTITY_REQUIRES_WHOLE_NUMBER'
        assert detail['message'] == WHOLE_NUMBER_REFUSAL
