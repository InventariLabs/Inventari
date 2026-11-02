"""A production run's movement trace pages through every movement it has.

The trace used to read the newest 200 movements and slice that list, so a
run with more answered a total of 200 and an empty page past it: the oldest
movements of a large run could not be reached and the count was wrong.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.stock_move import StockMove
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.maker.models import BoMLine, MakerRecipe
from tests.integration._shelf import post_on_shelf

pytestmark = pytest.mark.integration

_MOVEMENTS = 205


@pytest.fixture
def long_run_id(
    client: TestClient,
    mk_auth_headers: dict[str, str],
    db_session: Session,
    mk_org: Organization,
    mk_user: User,
    mk_input_loc: StorageLocation,
    mk_output_loc: StorageLocation,
) -> str:
    output = ProductTemplate(
        organization_id=mk_org.id, name='Jam', sku=f'SKU-{uuid.uuid4().hex[:8]}'
    )
    ingredient = ProductTemplate(
        organization_id=mk_org.id, name='Fruit', sku=f'SKU-{uuid.uuid4().hex[:8]}'
    )
    db_session.add_all([output, ingredient])
    db_session.commit()
    recipe = MakerRecipe(
        organization_id=mk_org.id,
        output_template_id=output.id,
        name='Jam',
        batch_yield_qty=Decimal('1'),
        is_default=True,
    )
    db_session.add(recipe)
    db_session.commit()
    db_session.add(
        BoMLine(
            organization_id=mk_org.id,
            recipe_id=recipe.id,
            parent_template_id=output.id,
            child_template_id=ingredient.id,
            qty_per_batch=Decimal('2'),
            unit='kg',
        )
    )
    db_session.commit()
    post_on_shelf(client, mk_auth_headers, ingredient, mk_input_loc.id, 40)
    create = client.post(
        '/api/v1/maker/production/orders',
        headers=mk_auth_headers,
        json={
            'output_template_id': str(output.id),
            'planned_qty': '1',
            'output_location_id': str(mk_output_loc.id),
        },
    )
    assert create.status_code == 201, create.text
    order_id = str(create.json()['id'])
    # One instant for every movement: the order between them is the
    # tiebreak's to decide, and a page boundary must not repeat or skip one.
    posted_at = datetime(2026, 1, 1, tzinfo=UTC)
    db_session.add_all(
        StockMove(
            organization_id=mk_org.id,
            product_template_id=output.id,
            to_location_id=mk_output_loc.id,
            quantity=Decimal('1'),
            reference_type='maker_production',
            reference_id=uuid.UUID(order_id),
            created_by=mk_user.id,
            created_at=posted_at,
        )
        for _ in range(_MOVEMENTS)
    )
    db_session.commit()
    return order_id


def test_every_movement_of_a_long_run_is_reachable_across_pages(
    client: TestClient, mk_auth_headers: dict[str, str], long_run_id: str
) -> None:
    seen: list[str] = []
    for offset in range(0, _MOVEMENTS, 100):
        resp = client.get(
            f'/api/v1/maker/production/orders/{long_run_id}/stock-moves',
            params={'limit': 100, 'offset': offset},
            headers=mk_auth_headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body['total'] == _MOVEMENTS
        assert body['has_more'] is (offset + 100 < _MOVEMENTS)
        seen.extend(item['id'] for item in body['items'])

    assert len(seen) == _MOVEMENTS
    assert len(set(seen)) == _MOVEMENTS


def test_the_order_of_movements_is_the_same_on_every_read(
    client: TestClient, mk_auth_headers: dict[str, str], long_run_id: str
) -> None:
    def read() -> list[str]:
        resp = client.get(
            f'/api/v1/maker/production/orders/{long_run_id}/stock-moves',
            params={'limit': 50, 'offset': 180},
            headers=mk_auth_headers,
        )
        assert resp.status_code == 200, resp.text
        return [item['id'] for item in resp.json()['items']]

    assert read() == read()
