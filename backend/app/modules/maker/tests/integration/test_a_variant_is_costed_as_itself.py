"""A production order built from a variant must be costed from that variant.

``compute_breakdown`` takes a ``recipe_id`` and its own docstring names the
failure: without one the template's default formula answers, "which is the
right question for a catalogue estimate and the wrong one for an order built
from a variant". The create schema carries ``recipe_id``. The preview
endpoint did not pass it on, so the screen listed the variant's ingredients
beside the default formula's cost.

The recipe card had the same shape one level up: its estimated unit cost was
rolled up from the output template, meaning the default formula, no matter
which recipe the reader had open.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.stock_valuation_layer import StockValuationLayer
from app.models.storage_location import StorageLocation
from app.modules.maker.models import BoMLine, MakerRecipe

pytestmark = pytest.mark.integration


def _template(db: Session, org: Organization, name: str) -> ProductTemplate:
    template = ProductTemplate(
        organization_id=org.id, name=name, sku=f'SKU-{uuid.uuid4().hex[:8]}'
    )
    db.add(template)
    db.flush()
    return template


def _priced(db: Session, org_id: UUID, template_id: UUID, unit_cost: str) -> None:
    cost = Decimal(unit_cost)
    db.add(
        StockValuationLayer(
            organization_id=org_id,
            product_template_id=template_id,
            quantity=Decimal('100'),
            remaining_qty=Decimal('100'),
            unit_cost=cost,
            total_value=Decimal('100') * cost,
            direction='IN',
        )
    )


def _formula(
    db: Session,
    org: Organization,
    *,
    output: ProductTemplate,
    ingredient: ProductTemplate,
    name: str,
    is_default: bool,
) -> MakerRecipe:
    recipe = MakerRecipe(
        organization_id=org.id,
        output_template_id=output.id,
        name=name,
        batch_yield_qty=Decimal('1'),
        is_default=is_default,
    )
    db.add(recipe)
    db.flush()
    db.add(
        BoMLine(
            organization_id=org.id,
            recipe_id=recipe.id,
            parent_template_id=output.id,
            child_template_id=ingredient.id,
            qty_per_batch=Decimal('1'),
            unit='kg',
        )
    )
    db.flush()
    return recipe


class _TwoFormulas:
    def __init__(self) -> None:
        self.output_id: str
        self.default_recipe_id: str
        self.variant_recipe_id: str


@pytest.fixture
def two_formulas(db_session: Session, mk_org: Organization) -> _TwoFormulas:
    """One product, two ways of making it, ten times apart in cost."""
    fixture = _TwoFormulas()

    candle = _template(db_session, mk_org, 'Candle')
    cheap_wax = _template(db_session, mk_org, 'Paraffin')
    dear_wax = _template(db_session, mk_org, 'Beeswax')
    _priced(db_session, mk_org.id, cheap_wax.id, '2.00')
    _priced(db_session, mk_org.id, dear_wax.id, '20.00')

    default = _formula(
        db_session,
        mk_org,
        output=candle,
        ingredient=cheap_wax,
        name='Paraffin candle',
        is_default=True,
    )
    variant = _formula(
        db_session,
        mk_org,
        output=candle,
        ingredient=dear_wax,
        name='Beeswax candle',
        is_default=False,
    )
    db_session.commit()

    fixture.output_id = str(candle.id)
    fixture.default_recipe_id = str(default.id)
    fixture.variant_recipe_id = str(variant.id)
    return fixture


class TestPreviewingAProductionOrder:
    def _preview(
        self,
        client: TestClient,
        headers: dict[str, str],
        location: StorageLocation,
        fixture: _TwoFormulas,
        recipe_id: str | None,
    ) -> dict[str, Any]:
        payload: dict[str, str] = {
            'output_template_id': fixture.output_id,
            'planned_qty': '1.000',
            'output_location_id': str(location.id),
        }
        if recipe_id is not None:
            payload['recipe_id'] = recipe_id
        response = client.post(
            '/api/v1/maker/production/orders/preview',
            json=payload,
            headers=headers,
        )
        assert response.status_code == 200, response.text
        return dict(response.json())

    def test_the_chosen_variant_decides_the_cost(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_output_loc: StorageLocation,
        two_formulas: _TwoFormulas,
    ) -> None:
        body = self._preview(
            client,
            mk_auth_headers,
            mk_output_loc,
            two_formulas,
            two_formulas.variant_recipe_id,
        )
        assert Decimal(body['total_cost']) == Decimal('20.00')

    def test_the_ingredients_are_the_variant_s_own(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_output_loc: StorageLocation,
        two_formulas: _TwoFormulas,
    ) -> None:
        """The screen listed these already; only the total disagreed."""
        body = self._preview(
            client,
            mk_auth_headers,
            mk_output_loc,
            two_formulas,
            two_formulas.variant_recipe_id,
        )
        names = {entry['child_template_name'] for entry in body['entries']}
        assert names == {'Beeswax'}

    def test_without_a_recipe_the_default_still_answers(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_output_loc: StorageLocation,
        two_formulas: _TwoFormulas,
    ) -> None:
        """The control: a catalogue estimate asks about the default formula."""
        body = self._preview(client, mk_auth_headers, mk_output_loc, two_formulas, None)
        assert Decimal(body['total_cost']) == Decimal('2.00')


class TestOpeningARecipeCard:
    def _card(
        self, client: TestClient, headers: dict[str, str], recipe_id: str
    ) -> dict[str, Any]:
        response = client.get(f'/api/v1/maker/recipes/{recipe_id}', headers=headers)
        assert response.status_code == 200, response.text
        return dict(response.json())

    def test_the_variant_card_estimates_the_variant(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        two_formulas: _TwoFormulas,
    ) -> None:
        card = self._card(client, mk_auth_headers, two_formulas.variant_recipe_id)
        assert Decimal(card['estimated_unit_cost']) == Decimal('20.00')

    def test_the_default_card_still_estimates_the_default(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        two_formulas: _TwoFormulas,
    ) -> None:
        card = self._card(client, mk_auth_headers, two_formulas.default_recipe_id)
        assert Decimal(card['estimated_unit_cost']) == Decimal('2.00')
