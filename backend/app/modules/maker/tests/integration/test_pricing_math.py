"""Integration + math tests for the pricing service and router."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.stock_valuation_layer import StockValuationLayer
from app.modules.maker import pricing
from app.modules.maker.models import BoMLine, MakerRecipe

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_template(
    db_session: Session, org: Organization, *, name: str
) -> ProductTemplate:
    template = ProductTemplate(
        organization_id=org.id,
        name=name,
        removal_strategy='FIFO',
    )
    db_session.add(template)
    db_session.commit()
    db_session.refresh(template)
    return template


def _seed_valuation(
    db_session: Session,
    *,
    org_id: UUID,
    template_id: UUID,
    qty: str,
    unit_cost: str,
) -> StockValuationLayer:
    cost_dec = Decimal(unit_cost)
    layer = StockValuationLayer(
        organization_id=org_id,
        product_template_id=template_id,
        quantity=Decimal(qty),
        remaining_qty=Decimal(qty),
        unit_cost=cost_dec,
        total_value=Decimal(qty) * cost_dec,
        direction='IN',
    )
    db_session.add(layer)
    db_session.commit()
    db_session.refresh(layer)
    return layer


def _ensure_recipe(
    db_session: Session, org: Organization, *, template_id: UUID
) -> MakerRecipe:
    """Get or create a default recipe for ``template_id``."""
    existing = (
        db_session.query(MakerRecipe)
        .filter(
            MakerRecipe.organization_id == org.id,
            MakerRecipe.output_template_id == template_id,
            MakerRecipe.is_default.is_(True),
        )
        .first()
    )
    if existing:
        return existing
    recipe = MakerRecipe(
        organization_id=org.id,
        output_template_id=template_id,
        name='Test',
        batch_yield_qty=Decimal('1'),
        is_default=True,
    )
    db_session.add(recipe)
    db_session.commit()
    db_session.refresh(recipe)
    return recipe


# ---------------------------------------------------------------------------
# Pure math (no DB) — catches regressions in the pricing formula.
# ---------------------------------------------------------------------------


class TestPricingMath:
    def test_zero_margin_returns_unit_cost(self) -> None:
        assert pricing.compute_sale_price(Decimal('10'), Decimal('0')) == Decimal(
            '10.00'
        )

    def test_fifty_percent_gross_margin_doubles_unit_cost(self) -> None:
        # Gross margin model: 50% margin ⇒ price = cost / 0.5 = 2x
        assert pricing.compute_sale_price(Decimal('10'), Decimal('50')) == Decimal(
            '20.00'
        )

    def test_twenty_five_percent_margin(self) -> None:
        # price = 8 / 0.75 = 10.6666… → 10.67 (HALF_UP)
        assert pricing.compute_sale_price(Decimal('8'), Decimal('25')) == Decimal(
            '10.67'
        )

    def test_sub_percent_margin(self) -> None:
        # price = 5 / 0.95 = 5.2631… → 5.26
        assert pricing.compute_sale_price(Decimal('5'), Decimal('5')) == Decimal('5.26')

    def test_negative_margin_raises(self) -> None:
        with pytest.raises(ValueError, match='0% or more'):
            pricing.compute_sale_price(Decimal('10'), Decimal('-1'))

    def test_margin_100_raises_to_avoid_division_by_zero(self) -> None:
        with pytest.raises(ValueError, match='below 100%'):
            pricing.compute_sale_price(Decimal('10'), Decimal('100'))

    def test_coerce_margin_defaults_when_missing(self) -> None:
        assert pricing._coerce_margin(None, Decimal('30')) == Decimal('30')

    def test_coerce_margin_defaults_when_invalid(self) -> None:
        for bad in [-1, 100, 1000, 'not-a-number']:
            assert pricing._coerce_margin(bad, Decimal('30')) == Decimal('30')

    def test_coerce_margin_defaults_for_nan_and_infinity(self) -> None:
        # ``Decimal('nan') < 0`` raises InvalidOperation, so the range check
        # alone would let a stored NaN take the computation down.
        for bad in [
            'nan',
            'NaN',
            'sNaN',
            float('nan'),
            'inf',
            '-Infinity',
            float('inf'),
        ]:
            assert pricing._coerce_margin(bad, Decimal('30')) == Decimal('30')


# ---------------------------------------------------------------------------
# HTTP integration tests against the real router.
# ---------------------------------------------------------------------------


class TestPricingEndpoint:
    URL_COMPUTE = '/api/v1/maker/pricing/compute'
    URL_MARGIN = '/api/v1/maker/pricing/margin/{template_id}'

    def test_compute_with_rated_ingredients(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        """Two ingredients with AVCO rates → total_cost computed correctly."""
        parent = _make_template(db_session, mk_org, name='Powidła')
        plum = _make_template(db_session, mk_org, name='Śliwki')
        sugar = _make_template(db_session, mk_org, name='Cukier')

        # 2 kg plums @ 5 + 0.5 kg sugar @ 4 = 10 + 2 = 12 per 1 kg powidła.
        recipe = _ensure_recipe(db_session, mk_org, template_id=parent.id)
        line_plum = BoMLine(
            organization_id=mk_org.id,
            recipe_id=recipe.id,
            parent_template_id=parent.id,
            child_template_id=plum.id,
            qty_per_batch=Decimal('2.0'),
            unit='kg',
        )
        db_session.add(line_plum)
        line_sugar = BoMLine(
            organization_id=mk_org.id,
            recipe_id=recipe.id,
            parent_template_id=parent.id,
            child_template_id=sugar.id,
            qty_per_batch=Decimal('0.5'),
            unit='kg',
        )
        db_session.add(line_sugar)
        db_session.commit()

        _seed_valuation(
            db_session,
            org_id=mk_org.id,
            template_id=plum.id,
            qty='100',
            unit_cost='5',
        )
        _seed_valuation(
            db_session,
            org_id=mk_org.id,
            template_id=sugar.id,
            qty='50',
            unit_cost='4',
        )

        response = client.post(
            self.URL_COMPUTE,
            headers=mk_auth_headers,
            json={
                'template_id': str(parent.id),
                'produced_qty': '1',
                'target_margin_pct': '50',
            },
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert Decimal(body['total_cost']) == Decimal('12.00')
        assert Decimal(body['unit_cost']) == Decimal('12.00')
        assert Decimal(body['target_margin_pct']) == Decimal('50')
        # 50% gross margin → 12 / 0.5 = 24
        assert Decimal(body['unit_sale_price']) == Decimal('24.00')

    def test_compute_missing_rates_returns_zero_cost(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        """Ingredient without AVCO rate ⇒ zero contribution, no crash."""
        parent = _make_template(db_session, mk_org, name='Mystery')
        mystery = _make_template(db_session, mk_org, name='NoRate')

        recipe = _ensure_recipe(db_session, mk_org, template_id=parent.id)
        line = BoMLine(
            organization_id=mk_org.id,
            recipe_id=recipe.id,
            parent_template_id=parent.id,
            child_template_id=mystery.id,
            qty_per_batch=Decimal('1.0'),
            unit='kg',
        )
        db_session.add(line)
        db_session.commit()

        response = client.post(
            self.URL_COMPUTE,
            headers=mk_auth_headers,
            json={
                'template_id': str(parent.id),
                'produced_qty': '1',
                'target_margin_pct': '25',
            },
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert Decimal(body['total_cost']) == Decimal('0')
        assert Decimal(body['unit_cost']) == Decimal('0')
        # 0 / (1 - 0.25) = 0
        assert Decimal(body['unit_sale_price']) == Decimal('0.00')
        # The zero came from a formula nobody has priced, not from an empty
        # one — the two read identically without these counts.
        assert body['ingredient_count'] == 1
        assert body['unrated_ingredient_count'] == 1

    def test_compute_on_empty_formula_reports_no_ingredients(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        """Nothing to compute from is not the same answer as "it costs 0"."""
        parent = _make_template(db_session, mk_org, name='Nothing')
        _ensure_recipe(db_session, mk_org, template_id=parent.id)

        response = client.post(
            self.URL_COMPUTE,
            headers=mk_auth_headers,
            json={
                'template_id': str(parent.id),
                'produced_qty': '1',
                'target_margin_pct': '25',
            },
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body['ingredient_count'] == 0
        assert body['unrated_ingredient_count'] == 0
        assert Decimal(body['unit_sale_price']) == Decimal('0.00')

    def test_margin_at_100_rejected_as_400(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        parent = _make_template(db_session, mk_org, name='Edge')
        response = client.post(
            self.URL_COMPUTE,
            headers=mk_auth_headers,
            json={
                'template_id': str(parent.id),
                'produced_qty': '1',
                'target_margin_pct': '100',
            },
        )
        assert response.status_code in (400, 422)

    def test_default_margin_when_unset(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        parent = _make_template(db_session, mk_org, name='DefaultTest')
        response = client.get(
            self.URL_MARGIN.format(template_id=parent.id),
            headers=mk_auth_headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert Decimal(body['target_margin_pct']) == pricing.DEFAULT_MARGIN_PCT
        assert body['is_default'] is True

    def test_set_and_get_margin_persists(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        parent = _make_template(db_session, mk_org, name='SetTest')

        put_response = client.put(
            self.URL_MARGIN.format(template_id=parent.id),
            headers=mk_auth_headers,
            json={'target_margin_pct': '42'},
        )
        assert put_response.status_code == 200, put_response.text

        get_response = client.get(
            self.URL_MARGIN.format(template_id=parent.id),
            headers=mk_auth_headers,
        )
        body = get_response.json()
        assert Decimal(body['target_margin_pct']) == Decimal('42')
        assert body['is_default'] is False

    def test_set_margin_at_100_rejected(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        parent = _make_template(db_session, mk_org, name='EdgePut')
        response = client.put(
            self.URL_MARGIN.format(template_id=parent.id),
            headers=mk_auth_headers,
            json={'target_margin_pct': '100'},
        )
        # Pydantic Field(lt=100) rejects 100 at the schema layer (422),
        # the service-level guard catches anything that slips through (400).
        assert response.status_code in (400, 422)

    def test_pricing_requires_maker_module(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        mk_auth_headers: dict[str, str],
        db_session: Session,
    ) -> None:
        """Pricing must enforce the maker module gate."""
        org_without_maker = h.create_org('No Maker Org', ['core'])
        user = h.create_user(org_without_maker, email='no-maker@example.com')
        headers = h.get_auth_headers(user)

        template = _make_template(db_session, org_without_maker, name='X')
        response = client.post(
            self.URL_COMPUTE,
            headers=headers,
            json={
                'template_id': str(template.id),
                'produced_qty': '1',
                'target_margin_pct': '10',
            },
        )
        assert response.status_code in (403, 404)

    def test_margin_other_org_isolated(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        """Org A's margin must not be visible to org B."""
        parent_a = _make_template(db_session, mk_org, name='A')

        # Persist margin in org A
        client.put(
            self.URL_MARGIN.format(template_id=parent_a.id),
            headers=mk_auth_headers,
            json={'target_margin_pct': '77'},
        )

        # Try to read it from a second org
        org_b = h.create_org('Org B', ['core', 'items', 'locations', 'maker'])
        user_b = h.create_user(org_b, email='b@example.com')
        headers_b = h.get_auth_headers(user_b)

        response = client.get(
            self.URL_MARGIN.format(template_id=parent_a.id),
            headers=headers_b,
        )
        assert response.status_code == 404

    def test_compute_missing_template_returns_404(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        db_session: Session,
    ) -> None:
        """A non-existent template must yield 404, not 400 (RESTful)."""
        import uuid

        phantom = uuid.uuid4()
        response = client.post(
            self.URL_COMPUTE,
            headers=mk_auth_headers,
            json={
                'template_id': str(phantom),
                'produced_qty': '1',
                'target_margin_pct': '25',
            },
        )
        assert response.status_code == 404, response.text

    def test_get_margin_missing_template_returns_404(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        db_session: Session,
    ) -> None:
        """GET /margin/{id} for a non-existent template already returns 404."""
        import uuid

        phantom = uuid.uuid4()
        response = client.get(
            self.URL_MARGIN.format(template_id=phantom),
            headers=mk_auth_headers,
        )
        assert response.status_code == 404, response.text
