"""The precision gate sees the unit the row lands with.

A unit's ``rounding`` says the smallest step it is counted in, and the gate
that reads it asked the question only when the request named a unit. When the
request did not, the default piece row was assigned *after* the gate, so
``quantity 2.5`` entered as 2.500 pcs — through the form and through the scan
alike — while the same 2.5 with ``uom_id: pcs`` was refused 400 on both
doors. One quantity, one unit, two answers, and the difference between them
was whether the caller filled a field or left it to the default: invisible on
the screen, and impossible to explain to whoever holds the shelf.

The unit is settled first now, so the gate reads the unit the row will land
with — the caller's, the matched template's, else the piece default — and a
module that named a unit keeps winning, because the hooks still run before
both of them.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.interceptors import ItemInterceptor, interceptor_pipeline
from app.i18n.service import get_error_message, get_unit_label
from app.models.item import Item
from app.models.label_pool import LabelPool
from app.models.storage_location import StorageLocation
from app.models.uom import Uom
from app.models.user import User

pytestmark = pytest.mark.integration

POLISH = {'Accept-Language': 'pl'}

ITEMS_URL = '/api/v1/items'
TEMPLATES_URL = '/api/v1/items/product-templates'

#: The refusal a whole-number unit answers a fractional quantity with — read
#: from the catalogue in the request's language, so the assertion pins the key
#: the gate raises and not the wording a translator may revise. Both doors
#: state the same number: the schema quantizes 2.5 to 2.500 on one, the scan
#: carries the float on the other — and the sentence states it the Polish
#: way, with the reader's comma.
REFUSAL = get_error_message(
    'uom_quantity_requires_whole_number',
    'pl',
    unit=get_unit_label('pcs', 'pl'),
    quantity='2,5',
)


def _uom(db: Session, symbol: str) -> Uom:
    uom = db.scalars(select(Uom).where(Uom.symbol == symbol)).first()
    assert uom is not None, f"'{symbol}' is not in the seeded catalogue"
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


def _manual_create(
    client: TestClient,
    headers: dict[str, str],
    storage: StorageLocation,
    *,
    name: str,
    quantity: float,
    uom_id: Any | None = None,
) -> Any:
    payload: dict[str, Any] = {
        'name': name,
        'location_id': str(storage.id),
        'quantity': quantity,
    }
    if uom_id is not None:
        payload['uom_id'] = str(uom_id)
    return client.post(ITEMS_URL, headers=headers, json=payload)


def _scan(
    client: TestClient,
    db: Session,
    user: User,
    storage: StorageLocation,
    headers: dict[str, str],
    *,
    short_code: str,
    name: str,
    quantity: float,
    uom_id: Any | None = None,
) -> Any:
    label = _free_label(db, user, short_code=short_code)
    payload: dict[str, Any] = {
        'name': name,
        'location_id': str(storage.id),
        'quantity': quantity,
    }
    if uom_id is not None:
        payload['uom_id'] = str(uom_id)
    return client.post(
        f'/api/v1/labels/scan/{label.short_code}/assign', headers=headers, json=payload
    )


def _message(response: Any) -> str:
    message: str = response.json()['detail']['message']
    return message


def _left_behind(db: Session, name: str) -> Item | None:
    return db.scalars(select(Item).where(Item.name == name)).first()


class _NamingTheUnit(ItemInterceptor):
    """A module answering "a quantity of what" for the products it understands."""

    priority = 10

    def __init__(self, uom_id: Any) -> None:
        self._uom_id = uom_id

    async def before_create(self, data: dict[str, Any], context: Any) -> dict[str, Any]:
        data['uom_id'] = self._uom_id
        return data

    async def before_update(
        self, item_id: Any, changes: dict[str, Any], context: Any
    ) -> dict[str, Any]:
        return changes


class TestTheFractionWithoutAUnitIsMeasuredToo:
    """The differential: the 2.5 the old order waved through, on both doors."""

    def test_the_manual_create_refuses_a_fraction_with_no_unit(
        self,
        client: TestClient,
        db_session: Session,
        auth_headers: dict[str, str],
        test_storage_location: StorageLocation,
    ) -> None:
        response = _manual_create(
            client,
            {**auth_headers, **POLISH},
            test_storage_location,
            name='Half of something',
            quantity=2.5,
        )

        assert response.status_code == 400, response.text
        assert _message(response) == REFUSAL
        # The default is assigned to a row that never lands, so nothing is
        # written on the way to the refusal.
        db_session.expire_all()
        assert _left_behind(db_session, 'Half of something') is None

    def test_the_scan_refuses_a_fraction_with_no_unit(
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
            short_code='PL-NOUNIT',
            name='Zeskanowana połowa',
            quantity=2.5,
        )

        assert response.status_code == 400, response.text
        assert _message(response) == REFUSAL
        db_session.expire_all()
        assert _left_behind(db_session, 'Zeskanowana połowa') is None


class TestBothDoorsAnswerTheSameWay:
    def test_the_same_quantity_answers_the_same_with_and_without_a_unit(
        self,
        client: TestClient,
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
        auth_headers: dict[str, str],
    ) -> None:
        """Naming the unit changes nothing, on either door.

        The four answers are one answer: the unit is the piece row whichever
        way it was settled, so the gate reads the same 1.0 rounding four
        times. Before, the two requests that left the field out came back 201
        and 200 while their twins came back 400.
        """
        pieces = _uom(db_session, 'pcs')
        headers = {**auth_headers, **POLISH}

        manual_default = _manual_create(
            client,
            headers,
            test_storage_location,
            name='Ręcznie bez jednostki',
            quantity=2.5,
        )
        manual_named = _manual_create(
            client,
            headers,
            test_storage_location,
            name='Ręcznie z jednostką',
            quantity=2.5,
            uom_id=pieces.id,
        )
        scan_default = _scan(
            client,
            db_session,
            test_user,
            test_storage_location,
            headers,
            short_code='PL-BOTH',
            name='Skan bez jednostki',
            quantity=2.5,
        )
        scan_named = _scan(
            client,
            db_session,
            test_user,
            test_storage_location,
            headers,
            short_code='PL-NAMED',
            name='Skan z jednostką',
            quantity=2.5,
            uom_id=pieces.id,
        )

        for response in (manual_default, manual_named, scan_default, scan_named):
            assert response.status_code == 400, response.text
            assert _message(response) == REFUSAL

    def test_a_whole_number_needs_no_unit_on_either_door(
        self,
        client: TestClient,
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
        auth_headers: dict[str, str],
    ) -> None:
        """The control: the rule is about halves, not about the default."""
        headers = auth_headers

        manual = _manual_create(
            client,
            headers,
            test_storage_location,
            name='Three chairs',
            quantity=3,
        )
        scan = _scan(
            client,
            db_session,
            test_user,
            test_storage_location,
            headers,
            short_code='PL-WHOLE',
            name='Three scanned chairs',
            quantity=3,
        )

        assert manual.status_code == 201, manual.text
        assert manual.json()['uom']['symbol'] == 'pcs'
        assert scan.status_code == 200, scan.text
        assert scan.json()['uom']['symbol'] == 'pcs'


class TestTheUnitOnTheRowIsTheOneMeasured:
    def test_a_fraction_lands_in_the_unit_the_matched_template_names(
        self,
        client: TestClient,
        db_session: Session,
        auth_headers: dict[str, str],
        test_storage_location: StorageLocation,
    ) -> None:
        """The template's kilogram beats the piece default — in the gate too.

        The gate has to read the unit that lands, not the one the caller
        left unsaid: this product's catalogue row says kilograms, so 2.5 kg
        is a quantity and must not be refused as 2.5 pieces.
        """
        kg = _uom(db_session, 'kg')
        client.post(
            TEMPLATES_URL,
            headers=auth_headers,
            json={'name': 'Rye flour', 'uom_id': str(kg.id)},
        )

        response = _manual_create(
            client,
            auth_headers,
            test_storage_location,
            name='Rye flour',
            quantity=2.5,
        )

        assert response.status_code == 201, response.text
        assert response.json()['uom']['symbol'] == 'kg'

    def test_a_hook_that_names_a_unit_is_measured_in_that_unit(
        self,
        client: TestClient,
        db_session: Session,
        auth_headers: dict[str, str],
        test_storage_location: StorageLocation,
    ) -> None:
        """A module that answers "a quantity of what" still wins.

        The hooks are what a module writes in, and they run before the unit
        is settled and before it is measured: a scan of half a crate is a
        quantity when the module that understands crates says so, and the
        piece default has nothing to add.
        """
        kg = _uom(db_session, 'kg')
        hook = _NamingTheUnit(kg.id)
        interceptor_pipeline.register_item_interceptor(hook)
        try:
            response = _manual_create(
                client,
                auth_headers,
                test_storage_location,
                name='Half a crate',
                quantity=2.5,
            )
        finally:
            interceptor_pipeline.unregister_item_interceptor(hook)

        assert response.status_code == 201, response.text
        assert response.json()['uom']['symbol'] == 'kg'
