"""A production order answers with names, not with raw identifiers.

Four places used to print UUIDs at the operator: the source location of a
consumed line, the product and lot of a stock move, and the produced item.
The API resolves all four now; the UI keeps the id in a tooltip.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.modules.maker.models import BoMLine, MakerRecipe
from tests.integration._shelf import post_on_shelf

pytestmark = pytest.mark.integration


def _template(db: Session, org: Organization, *, name: str) -> ProductTemplate:
    template = ProductTemplate(
        organization_id=org.id,
        name=name,
        sku=f'SKU-{uuid.uuid4().hex[:8]}',
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    return template


def _recipe_with_line(
    db: Session,
    org: Organization,
    *,
    output_id: UUID,
    ingredient_id: UUID,
) -> MakerRecipe:
    recipe = MakerRecipe(
        organization_id=org.id,
        output_template_id=output_id,
        name='Display Names',
        batch_yield_qty=Decimal('1'),
        is_default=True,
    )
    db.add(recipe)
    db.commit()
    db.refresh(recipe)
    db.add(
        BoMLine(
            organization_id=org.id,
            recipe_id=recipe.id,
            parent_template_id=output_id,
            child_template_id=ingredient_id,
            qty_per_batch=Decimal('2'),
            unit='kg',
        )
    )
    db.commit()
    return recipe


class TestOrderDisplayNames:
    """GET /orders/{id} and its stock moves resolve every identifier."""

    @pytest.fixture
    def completed_order_id(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        db_session: Session,
        mk_org: Organization,
        mk_input_loc: StorageLocation,
        mk_output_loc: StorageLocation,
    ) -> str:
        output = _template(db_session, mk_org, name='Jam')
        ingredient = _template(db_session, mk_org, name='Strawberries')
        _recipe_with_line(
            db_session,
            mk_org,
            output_id=output.id,
            ingredient_id=ingredient.id,
        )
        post_on_shelf(client, mk_auth_headers, ingredient, mk_input_loc.id, 40)

        create = client.post(
            '/api/v1/maker/production/orders',
            headers=mk_auth_headers,
            json={
                'output_template_id': str(output.id),
                'planned_qty': '3',
                'output_location_id': str(mk_output_loc.id),
            },
        )
        assert create.status_code == 201, create.text
        order_id = str(create.json()['id'])

        complete = client.post(
            f'/api/v1/maker/production/orders/{order_id}/complete',
            headers=mk_auth_headers,
        )
        assert complete.status_code == 200, complete.text
        return order_id

    def test_line_carries_its_source_location_name(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        completed_order_id: str,
    ) -> None:
        resp = client.get(
            f'/api/v1/maker/production/orders/{completed_order_id}',
            headers=mk_auth_headers,
        )

        assert resp.status_code == 200
        lines = resp.json()['lines']
        assert len(lines) == 1
        assert lines[0]['child_template_name'] == 'Strawberries'
        assert lines[0]['source_location_name'] == 'Ingredient Store'

    def test_order_carries_the_produced_item_name(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        completed_order_id: str,
    ) -> None:
        resp = client.get(
            f'/api/v1/maker/production/orders/{completed_order_id}',
            headers=mk_auth_headers,
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body['produced_item_id'] is not None
        assert body['produced_item_name'] == 'Jam'

    def test_stock_moves_carry_product_names(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        completed_order_id: str,
    ) -> None:
        resp = client.get(
            f'/api/v1/maker/production/orders/{completed_order_id}/stock-moves',
            headers=mk_auth_headers,
        )

        assert resp.status_code == 200
        moves = resp.json()['items']
        assert len(moves) == 2
        names = {move['product_template_name'] for move in moves}
        assert names == {'Strawberries', 'Jam'}
        # No lot on this run, so the field is present and empty rather than
        # missing — the UI decides what to render from it.
        assert all(move['lot_code'] is None for move in moves)

    def test_stock_moves_carry_location_names(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        completed_order_id: str,
    ) -> None:
        resp = client.get(
            f'/api/v1/maker/production/orders/{completed_order_id}/stock-moves',
            headers=mk_auth_headers,
        )

        assert resp.status_code == 200
        by_product = {
            move['product_template_name']: move for move in resp.json()['items']
        }
        # The consumption move: off the ingredient shelf, into the run —
        # the destination side never had a location to name.
        consumed = by_product['Strawberries']
        assert consumed['from_location_name'] == 'Ingredient Store'
        assert consumed['to_location_name'] is None
        # The receipt move: out of the run, onto the output shelf.
        received = by_product['Jam']
        assert received['from_location_name'] is None
        assert received['to_location_name'] == 'Output Store'
