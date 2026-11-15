"""Order what a formula's ingredients the records do not hold.

The recipe page says at the top that its ingredients are missing, and the
next click orders them: a draft purchase order with one line per short
ingredient, the shortfall rounded up to what is bought, and the price typed
on the product where somebody typed one. The user never leaves production.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.maker.models import MakerIngredientPrice
from app.modules.purchase_orders.models import PurchaseOrder
from tests.integration._shelf import post_on_shelf

pytestmark = pytest.mark.integration


@pytest.fixture
def org(h: ModuleTestHelper) -> Organization:
    return h.create_org(
        'Soap Studio',
        [
            'core',
            'items',
            'locations',
            'categories',
            'maker',
            'purchase_orders',
        ],
    )


@pytest.fixture
def user(h: ModuleTestHelper, org: Organization) -> User:
    return h.create_user(org, email='soap@example.com')


@pytest.fixture
def headers(h: ModuleTestHelper, user: User) -> dict[str, str]:
    return h.get_auth_headers(user)


@pytest.fixture
def pantry(h: ModuleTestHelper, org: Organization, user: User) -> StorageLocation:
    return h.create_storage_location(
        org, h.create_storage_type('Pantry', 'PANTRY'), user, name='Pantry'
    )


def _template(db: Session, org: Organization, name: str) -> ProductTemplate:
    template = ProductTemplate(
        organization_id=org.id, name=name, sku=f'SKU-{uuid.uuid4().hex[:8]}'
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    return template


def _soap_recipe(
    client: TestClient,
    headers: dict[str, str],
    db: Session,
    org: Organization,
) -> tuple[ProductTemplate, str]:
    """A batch of ten needs 1.5 kg of lye, priced at 12.00 a kilogram."""
    soap = _template(db, org, 'Soap')
    lye = _template(db, org, 'Lye')
    db.add(
        MakerIngredientPrice(
            organization_id=org.id,
            product_template_id=lye.id,
            unit_price=Decimal('12.00'),
        )
    )
    db.commit()
    recipe = client.post(
        '/api/v1/maker/recipes',
        headers=headers,
        json={
            'output_template_id': str(soap.id),
            'name': 'Cold process',
            'batch_yield_qty': '10',
        },
    )
    assert recipe.status_code == 201, recipe.text
    recipe_id = recipe.json()['id']
    line = client.post(
        f'/api/v1/maker/recipes/{recipe_id}/bom-lines',
        headers=headers,
        json={
            'child_template_id': str(lye.id),
            'qty_per_batch': '1.5',
            'unit': 'kg',
        },
    )
    assert line.status_code == 201, line.text
    return lye, recipe_id


def test_the_recipe_orders_what_its_batch_lacks(
    client: TestClient,
    headers: dict[str, str],
    org: Organization,
    db_session: Session,
) -> None:
    lye, recipe_id = _soap_recipe(client, headers, db_session, org)

    response = client.post(
        f'/api/v1/maker/recipes/{recipe_id}/shortages/purchase-order',
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['added_count'] == 1
    assert body['purchase_order_id'] is not None
    assert body['number']

    order = db_session.execute(
        select(PurchaseOrder).where(PurchaseOrder.id == body['purchase_order_id'])
    ).scalar_one()
    assert order.status == 'DRAFT'
    assert len(order.lines) == 1
    line = order.lines[0]
    assert line.product_template_id == lye.id
    # The batch of ten needs 1.5 kg; none is on the shelf.
    assert line.quantity_ordered == Decimal('1.5')
    # The price typed on the product is what the order is raised at.
    assert line.unit_price == Decimal('12.00')


def test_a_batch_the_records_cover_orders_nothing(
    client: TestClient,
    headers: dict[str, str],
    org: Organization,
    pantry: StorageLocation,
    db_session: Session,
) -> None:
    lye, recipe_id = _soap_recipe(client, headers, db_session, org)
    post_on_shelf(client, headers, lye, pantry.id, '10')

    response = client.post(
        f'/api/v1/maker/recipes/{recipe_id}/shortages/purchase-order',
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()['purchase_order_id'] is None
    assert response.json()['added_count'] == 0
    assert db_session.execute(select(PurchaseOrder)).scalars().all() == []


def test_a_second_click_does_not_order_the_same_shortage_again(
    client: TestClient,
    headers: dict[str, str],
    org: Organization,
    db_session: Session,
) -> None:
    """An open order is what the next click remembers.

    Neither click moves stock, so the same shortage is computed both times
    and the second used to raise an identical draft. The quantity an open
    order already expects comes off the shortfall, so the second click
    orders nothing and says the ingredient is already on its way.
    """
    lye, recipe_id = _soap_recipe(client, headers, db_session, org)

    first = client.post(
        f'/api/v1/maker/recipes/{recipe_id}/shortages/purchase-order',
        headers=headers,
    )
    assert first.status_code == 200, first.text
    assert first.json()['purchase_order_id'] is not None
    assert first.json()['already_ordered_count'] == 0

    second = client.post(
        f'/api/v1/maker/recipes/{recipe_id}/shortages/purchase-order',
        headers=headers,
    )
    assert second.status_code == 200, second.text
    assert second.json()['purchase_order_id'] is None
    assert second.json()['added_count'] == 0
    assert second.json()['already_ordered_count'] == 1
    assert len(db_session.execute(select(PurchaseOrder)).scalars().all()) == 1


def test_an_open_order_covers_only_what_it_expects(
    client: TestClient,
    headers: dict[str, str],
    org: Organization,
    db_session: Session,
) -> None:
    """A partial open order leaves the rest to be ordered, not duplicated.

    The batch needs 1.5 kg and an open draft expects 1 kg of it: the click
    orders the missing half kilogram, and the line it does not re-raise
    stays a single line.
    """
    lye, recipe_id = _soap_recipe(client, headers, db_session, org)
    partial = client.post(
        '/api/v1/purchase-orders',
        headers=headers,
        json={
            'lines': [
                {
                    'product_template_id': str(lye.id),
                    'name': lye.name,
                    'quantity_ordered': '1',
                }
            ]
        },
    )
    assert partial.status_code == 201, partial.text

    response = client.post(
        f'/api/v1/maker/recipes/{recipe_id}/shortages/purchase-order',
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['purchase_order_id'] is not None
    assert body['added_count'] == 1
    assert body['already_ordered_count'] == 0

    order = db_session.execute(
        select(PurchaseOrder).where(PurchaseOrder.id == body['purchase_order_id'])
    ).scalar_one()
    assert order.lines[0].quantity_ordered == Decimal('0.5')
