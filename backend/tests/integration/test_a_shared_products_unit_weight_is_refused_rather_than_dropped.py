"""A unit weight a shared product does not record is refused, not dropped.

The weight of one piece is the product's (ADR-015), and a product from the
shared catalogue is every organization's, so one of them cannot change it for
all. Both doors used to drop the weight and answer success: the form said
"Updated", and the card — with every line weight read from it — kept the old
one. The removal strategy beside it is already refused this way. The weight
the card already records is not a change, because the form posts its whole
state.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.product_template import ProductTemplate
from app.models.uom import Uom

pytestmark = pytest.mark.integration

ITEM_URL = '/api/v1/items'


def _grams(db: Session) -> str:
    uom = db.scalars(select(Uom).where(Uom.symbol == 'g')).first()
    assert uom is not None
    return str(uom.id)


def _shared_product(
    db: Session, name: str, *, grams: str | None = None
) -> ProductTemplate:
    """A catalogue product: no organization owns it, every one reads it."""
    template = ProductTemplate(
        organization_id=None,
        name=name,
        weight_value=Decimal(grams) if grams is not None else None,
        weight_uom_id=_grams(db) if grams is not None else None,
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    return template


def _weight_of(db: Session, template: ProductTemplate) -> Decimal | None:
    db.expire_all()
    card = db.get(ProductTemplate, template.id)
    assert card is not None
    return card.weight_value


def _record_on(client, auth_headers, storage_id, card: ProductTemplate) -> str:
    created = client.post(
        ITEM_URL,
        headers=auth_headers,
        json={
            'name': card.name,
            'location_id': str(storage_id),
            'template_id': str(card.id),
        },
    )
    assert created.status_code == 201, created.text
    return str(created.json()['id'])


def test_an_edit_that_weighs_a_shared_product_is_refused(
    client, auth_headers, db_session: Session, test_storage_location
) -> None:
    shared = _shared_product(db_session, 'Shared flour')
    item_id = _record_on(client, auth_headers, test_storage_location.id, shared)

    response = client.put(
        f'{ITEM_URL}/{item_id}',
        headers=auth_headers,
        json={'weight_value': 500, 'weight_uom_id': _grams(db_session)},
    )

    assert response.status_code == 400, response.text
    assert response.json()['detail']['code'] == 'UNIT_WEIGHT_OF_SHARED_PRODUCT'
    assert _weight_of(db_session, shared) is None


def test_the_weight_a_shared_product_already_records_does_not_stop_the_edit(
    client, auth_headers, db_session: Session, test_storage_location
) -> None:
    shared = _shared_product(db_session, 'Shared rice', grams='500')
    item_id = _record_on(client, auth_headers, test_storage_location.id, shared)

    # The whole form, weight and unit included, and the same weight with no
    # unit at all, which reads in the card's own.
    for weight in (
        {'weight_value': 500.0, 'weight_uom_id': _grams(db_session)},
        {'weight_value': '500'},
    ):
        response = client.put(
            f'{ITEM_URL}/{item_id}',
            headers=auth_headers,
            json={'name': 'Shared rice, top shelf', **weight},
        )
        assert response.status_code == 200, response.text
        assert response.json()['name'] == 'Shared rice, top shelf'
    assert _weight_of(db_session, shared) == Decimal('500')


def test_emptying_a_shared_products_weight_is_refused_too(
    client, auth_headers, db_session: Session, test_storage_location
) -> None:
    shared = _shared_product(db_session, 'Shared oats', grams='500')
    item_id = _record_on(client, auth_headers, test_storage_location.id, shared)

    response = client.put(
        f'{ITEM_URL}/{item_id}',
        headers=auth_headers,
        json={'weight_value': None, 'weight_uom_id': None},
    )

    assert response.status_code == 400, response.text
    assert _weight_of(db_session, shared) == Decimal('500')


def test_a_new_record_cannot_weigh_a_shared_product(
    client, auth_headers, db_session: Session, test_storage_location
) -> None:
    shared = _shared_product(db_session, 'Shared milk', grams='1000')
    body = {
        'name': 'Shared milk',
        'location_id': str(test_storage_location.id),
        'template_id': str(shared.id),
    }

    refused = client.post(
        ITEM_URL,
        headers=auth_headers,
        json={**body, 'weight_value': 250, 'weight_uom_id': _grams(db_session)},
    )
    assert refused.status_code == 400, refused.text
    assert refused.json()['detail']['code'] == 'UNIT_WEIGHT_OF_SHARED_PRODUCT'
    assert _weight_of(db_session, shared) == Decimal('1000')

    accepted = client.post(
        ITEM_URL,
        headers=auth_headers,
        json={**body, 'weight_value': 1000, 'weight_uom_id': _grams(db_session)},
    )
    assert accepted.status_code == 201, accepted.text
    assert accepted.json()['template_id'] == str(shared.id)
