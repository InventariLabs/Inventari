"""Integration tests for recipe-level ops: child names, cost estimate, bulk delete."""

from __future__ import annotations

from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.modules.maker.models import BoMLine, MakerRecipe

from .conftest import post_bom_line

pytestmark = pytest.mark.integration


def _seed_recipe(
    client: TestClient,
    headers: dict[str, str],
    db_session: Session,
    org_id: UUID,
    parent_name: str = 'Cake',
    child_name: str = 'Flour',
) -> tuple[ProductTemplate, ProductTemplate]:
    parent = ProductTemplate(organization_id=org_id, name=parent_name)
    child = ProductTemplate(organization_id=org_id, name=child_name)
    db_session.add_all([parent, child])
    db_session.commit()
    db_session.refresh(parent)
    db_session.refresh(child)
    resp = post_bom_line(
        client,
        headers,
        db_session,
        org_id,
        {
            'parent_template_id': str(parent.id),
            'child_template_id': str(child.id),
            'qty_per_batch': '0.500',
            'unit': 'kg',
        },
    )
    assert resp.status_code == 201, resp.text
    return parent, child


class TestBomLineNames:
    """BOM line reads carry the child template's display name."""

    def test_list_lines_includes_child_name(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        parent, child = _seed_recipe(client, mk_auth_headers, db_session, mk_org.id)

        resp = client.get(f'/api/v1/maker/bom/{parent.id}', headers=mk_auth_headers)
        assert resp.status_code == 200
        lines = resp.json()['items']
        assert len(lines) == 1
        assert lines[0]['child_template_name'] == child.name

    def test_tree_includes_child_name(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        parent, child = _seed_recipe(client, mk_auth_headers, db_session, mk_org.id)

        resp = client.get(
            f'/api/v1/maker/bom/tree/{parent.id}', headers=mk_auth_headers
        )
        assert resp.status_code == 200
        children = resp.json()['root']['children']
        assert len(children) == 1
        assert children[0]['line']['child_template_name'] == child.name


class TestBomCostEstimate:
    """GET /bom/{template_id}/cost-estimate — per-ingredient cost at qty=1."""

    def test_cost_estimate_returns_entries(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        parent, child = _seed_recipe(client, mk_auth_headers, db_session, mk_org.id)

        resp = client.get(
            f'/api/v1/maker/bom/{parent.id}/cost-estimate',
            headers=mk_auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body['output_template_id'] == str(parent.id)
        assert len(body['entries']) == 1
        entry = body['entries'][0]
        assert entry['child_template_id'] == str(child.id)
        assert entry['unit'] == 'kg'
        # No stock/AVCO seeded → cost unknown, flagged as missing
        assert entry['cost_source'] == 'none'
        assert str(child.id) in body['missing_cost_lines']

    def test_cost_estimate_404_for_unknown_template(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
    ) -> None:
        import uuid

        resp = client.get(
            f'/api/v1/maker/bom/{uuid.uuid4()}/cost-estimate',
            headers=mk_auth_headers,
        )
        assert resp.status_code == 404


class TestRecipeDelete:
    """DELETE /maker/recipes/{recipe_id} — remove one formula.

    The legacy ``DELETE /bom/parent/{template_id}`` deleted "the recipe of
    this product", which stopped meaning anything once a product could have
    more than one. Deletion is addressed by recipe now.
    """

    def _default_recipe_id(
        self, db_session: Session, org_id: UUID, template_id: UUID
    ) -> UUID:
        recipe = (
            db_session.query(MakerRecipe)
            .filter(
                MakerRecipe.organization_id == org_id,
                MakerRecipe.output_template_id == template_id,
            )
            .one()
        )
        return recipe.id

    def test_delete_recipe_removes_all_lines(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        parent, _ = _seed_recipe(client, mk_auth_headers, db_session, mk_org.id)
        other_parent, _ = _seed_recipe(
            client,
            mk_auth_headers,
            db_session,
            mk_org.id,
            parent_name='Bread',
            child_name='Yeast',
        )
        recipe_id = self._default_recipe_id(db_session, mk_org.id, parent.id)

        resp = client.delete(
            f'/api/v1/maker/recipes/{recipe_id}', headers=mk_auth_headers
        )
        assert resp.status_code == 204

        lines = client.get(
            f'/api/v1/maker/bom/{parent.id}', headers=mk_auth_headers
        ).json()['items']
        assert lines == []

        # Other recipe untouched
        other_lines = client.get(
            f'/api/v1/maker/bom/{other_parent.id}', headers=mk_auth_headers
        ).json()['items']
        assert len(other_lines) == 1

    def test_delete_recipe_404_for_other_org(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
        h: ModuleTestHelper,
    ) -> None:
        parent, _ = _seed_recipe(client, mk_auth_headers, db_session, mk_org.id)
        recipe_id = self._default_recipe_id(db_session, mk_org.id, parent.id)

        other_org = h.create_org('Delete Other Org', ['core', 'items', 'maker'])
        other_user = h.create_user(other_org, email='del-other@example.com')
        other_headers = h.get_auth_headers(other_user)

        resp = client.delete(
            f'/api/v1/maker/recipes/{recipe_id}', headers=other_headers
        )
        assert resp.status_code == 404

        # Still intact for the owning org
        lines = client.get(
            f'/api/v1/maker/bom/{parent.id}', headers=mk_auth_headers
        ).json()['items']
        assert len(lines) == 1


class TestLegacyBomWritesAreGone:
    """The parallel write path the second editor used no longer answers."""

    def test_post_bom_is_not_routed(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        parent, child = _seed_recipe(client, mk_auth_headers, db_session, mk_org.id)
        resp = client.post(
            '/api/v1/maker/bom',
            headers=mk_auth_headers,
            json={
                'parent_template_id': str(parent.id),
                'child_template_id': str(child.id),
                'qty_per_batch': '1',
                'unit': 'kg',
            },
        )
        assert resp.status_code in (404, 405), resp.text

    def test_delete_bom_parent_is_not_routed(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        parent, _ = _seed_recipe(client, mk_auth_headers, db_session, mk_org.id)
        resp = client.delete(
            f'/api/v1/maker/bom/parent/{parent.id}', headers=mk_auth_headers
        )
        assert resp.status_code in (404, 405), resp.text


class TestBomCostEstimateAnswersTheCallersFormula:
    def test_the_estimate_answers_a_specific_formula_at_a_batch(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        """A variant asking about its own batch gets its own numbers: the
        tab passes ``recipe_id`` and a batch ``qty`` instead of dividing a
        per-unit default-formula answer a second time."""
        from decimal import Decimal

        from app.models.stock_valuation_layer import StockValuationLayer

        parent = ProductTemplate(organization_id=mk_org.id, name='Granola')
        flour = ProductTemplate(organization_id=mk_org.id, name='Oats')
        db_session.add_all([parent, flour])
        db_session.commit()
        db_session.refresh(parent)
        db_session.refresh(flour)

        default_recipe = MakerRecipe(
            organization_id=mk_org.id,
            output_template_id=parent.id,
            name='Granola default',
            batch_yield_qty=Decimal('2'),
            is_default=True,
        )
        variant = MakerRecipe(
            organization_id=mk_org.id,
            output_template_id=parent.id,
            name='Granola variant',
            batch_yield_qty=Decimal('2'),
            is_default=False,
        )
        db_session.add_all([default_recipe, variant])
        db_session.commit()
        db_session.refresh(default_recipe)
        db_session.refresh(variant)
        # Default: 4 kg per batch of 2; variant: 1 kg per batch of 2.
        db_session.add_all(
            [
                BoMLine(
                    organization_id=mk_org.id,
                    recipe_id=default_recipe.id,
                    parent_template_id=parent.id,
                    child_template_id=flour.id,
                    qty_per_batch=Decimal('4'),
                    unit='kg',
                ),
                BoMLine(
                    organization_id=mk_org.id,
                    recipe_id=variant.id,
                    parent_template_id=parent.id,
                    child_template_id=flour.id,
                    qty_per_batch=Decimal('1'),
                    unit='kg',
                ),
            ]
        )
        db_session.add(
            StockValuationLayer(
                organization_id=mk_org.id,
                product_template_id=flour.id,
                quantity=Decimal('100'),
                remaining_qty=Decimal('100'),
                unit_cost=Decimal('2.00'),
                total_value=Decimal('200'),
                direction='IN',
                cost_basis='stated',
            )
        )
        db_session.commit()

        # The variant, one batch (2 units): 1 kg at 2.00.
        variant_batch = client.get(
            f'/api/v1/maker/bom/{parent.id}/cost-estimate',
            headers=mk_auth_headers,
            params={'recipe_id': str(variant.id), 'qty': '2'},
        )
        assert variant_batch.status_code == 200, variant_batch.text
        body = variant_batch.json()
        assert len(body['entries']) == 1
        assert Decimal(str(body['entries'][0]['consumed_qty'])) == Decimal('1')
        assert body['entries'][0]['cost'] == '2.00'

        # Without params: one unit of the default formula (half its batch:
        # 2 kg at 2.00) — the historical answer, unchanged.
        default_unit = client.get(
            f'/api/v1/maker/bom/{parent.id}/cost-estimate',
            headers=mk_auth_headers,
        )
        assert default_unit.status_code == 200, default_unit.text
        assert Decimal(
            str(default_unit.json()['entries'][0]['consumed_qty'])
        ) == Decimal('2')
