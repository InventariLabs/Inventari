"""The planned consumption names its shelves before the run takes anything.

A draft's ingredient table used to say how much would leave stock and say
nothing about where from — the run draws FIFO/FEFO across the whole
organization deterministically, so the answer exists before completion,
and the operator only learned which shelf had been emptied after the
action that cannot be undone. The breakdown now carries the draw's own
plan, shelf by shelf.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.user import User
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
    qty_per_batch: Decimal,
) -> MakerRecipe:
    recipe = MakerRecipe(
        organization_id=org.id,
        output_template_id=output_id,
        name='Planned Shelves',
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
            qty_per_batch=qty_per_batch,
            unit='kg',
        )
    )
    db.commit()
    return recipe


class TestPlannedConsumptionNamesItsShelves:
    @pytest.fixture
    def pantry_loc(
        self,
        h: ModuleTestHelper,
        mk_org: Organization,
        mk_storage_type: StorageType,
        mk_user: User,
    ) -> StorageLocation:
        return h.create_storage_location(
            mk_org,
            mk_storage_type,
            mk_user,
            name='Pantry',
        )

    @pytest.fixture
    def kitchen(
        self,
        db_session: Session,
        mk_org: Organization,
    ) -> tuple[ProductTemplate, ProductTemplate]:
        output = _template(db_session, mk_org, name='Jam')
        ingredient = _template(db_session, mk_org, name='Strawberries')
        _recipe_with_line(
            db_session,
            mk_org,
            output_id=output.id,
            ingredient_id=ingredient.id,
            qty_per_batch=Decimal('2'),
        )
        return output, ingredient

    def test_the_breakdown_names_the_shelves_the_draw_would_empty(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_input_loc: StorageLocation,
        pantry_loc: StorageLocation,
        kitchen: tuple[ProductTemplate, ProductTemplate],
    ) -> None:
        output, ingredient = kitchen
        # Eight on the older record, twelve on the younger one: a draw of
        # ten takes the oldest first, so the plan must name the first shelf
        # for all it holds and the second for the rest.
        post_on_shelf(client, mk_auth_headers, ingredient, mk_input_loc.id, 8)
        post_on_shelf(client, mk_auth_headers, ingredient, pantry_loc.id, 12)

        resp = client.get(
            f'/api/v1/maker/breakdown/{output.id}',
            headers=mk_auth_headers,
            params={'qty': '5'},
        )

        assert resp.status_code == 200, resp.text
        entries = resp.json()['entries']
        assert len(entries) == 1
        draws = entries[0]['planned_draws']
        assert [(d['location_name'], d['quantity']) for d in draws] == [
            ('Ingredient Store', '8.000'),
            ('Pantry', '2.000'),
        ]
        assert all(d['location_id'] for d in draws)

    def test_the_plan_is_what_completion_actually_takes(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_input_loc: StorageLocation,
        pantry_loc: StorageLocation,
        mk_output_loc: StorageLocation,
        kitchen: tuple[ProductTemplate, ProductTemplate],
    ) -> None:
        output, ingredient = kitchen
        post_on_shelf(client, mk_auth_headers, ingredient, mk_input_loc.id, 8)
        post_on_shelf(client, mk_auth_headers, ingredient, pantry_loc.id, 12)
        create = client.post(
            '/api/v1/maker/production/orders',
            headers=mk_auth_headers,
            json={
                'output_template_id': str(output.id),
                'planned_qty': '5',
                'output_location_id': str(mk_output_loc.id),
            },
        )
        assert create.status_code == 201, create.text
        order_id = create.json()['id']

        complete = client.post(
            f'/api/v1/maker/production/orders/{order_id}/complete',
            headers=mk_auth_headers,
        )
        assert complete.status_code == 200, complete.text

        moves = client.get(
            f'/api/v1/maker/production/orders/{order_id}/stock-moves',
            headers=mk_auth_headers,
        ).json()['items']
        taken = {
            move['from_location_name']: move['quantity']
            for move in moves
            if move['product_template_name'] == 'Strawberries'
        }
        # The forecast and the ledger are one plan: what the draft's table
        # promised is what the movements off the shelves recorded.
        assert taken == {'Ingredient Store': '8.000', 'Pantry': '2.000'}

    def test_an_ingredient_no_shelf_holds_answers_with_an_empty_plan(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        kitchen: tuple[ProductTemplate, ProductTemplate],
    ) -> None:
        output, _ingredient = kitchen

        resp = client.get(
            f'/api/v1/maker/breakdown/{output.id}',
            headers=mk_auth_headers,
            params={'qty': '5'},
        )

        assert resp.status_code == 200, resp.text
        entries = resp.json()['entries']
        assert len(entries) == 1
        assert entries[0]['planned_draws'] == []
