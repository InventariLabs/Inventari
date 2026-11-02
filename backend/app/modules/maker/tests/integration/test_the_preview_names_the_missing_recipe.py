"""The preview answers what create would say, before the order exists.

A product with no formula and a formula with no lines are two different
truths, and the preview used to flatten them into one (``entries=[]``), so
the screen told the reader a recipe existed and was empty while the create
button answered "no recipe for this product". These cases pin the answer's
own words: ``no_recipe``, ``empty`` or ``has_lines`` — and the id of the
formula the answer is about, which is what turns the sentence into a door.
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

pytestmark = pytest.mark.integration


def _make_template(
    db_session: Session, org: Organization, *, name: str
) -> ProductTemplate:
    template = ProductTemplate(
        organization_id=org.id,
        name=name,
        sku=f'SKU-{uuid.uuid4().hex[:8]}',
    )
    db_session.add(template)
    db_session.commit()
    db_session.refresh(template)
    return template


def _ensure_recipe(
    db_session: Session, org: Organization, template_id: UUID
) -> MakerRecipe:
    """Get or create a default, line-less recipe for *template_id*."""
    recipe = MakerRecipe(
        organization_id=org.id,
        output_template_id=template_id,
        name='Test formula',
        batch_yield_qty=Decimal('1'),
        is_default=True,
    )
    db_session.add(recipe)
    db_session.commit()
    db_session.refresh(recipe)
    return recipe


def _preview(
    client: TestClient,
    headers: dict[str, str],
    template_id: UUID,
    output_location_id: UUID,
) -> dict[str, object]:
    response = client.post(
        '/api/v1/maker/production/orders/preview',
        headers=headers,
        json={
            'output_template_id': str(template_id),
            'planned_qty': '2.000',
            'output_location_id': str(output_location_id),
        },
    )
    assert response.status_code == 200, response.text
    typed: dict[str, object] = response.json()
    return typed


class TestThePreviewNamesTheMissingRecipe:
    def test_a_template_without_a_recipe_is_no_recipe_not_empty(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        orphan = _make_template(db_session, mk_org, name='No formula')

        body = _preview(client, mk_auth_headers, orphan.id, mk_output_loc.id)

        assert body['recipe_state'] == 'no_recipe'
        assert body['recipe_id'] is None
        assert body['entries'] == []

    def test_a_recipe_without_lines_is_empty_and_is_named(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        product = _make_template(db_session, mk_org, name='Empty formula')
        recipe = _ensure_recipe(db_session, mk_org, product.id)

        body = _preview(client, mk_auth_headers, product.id, mk_output_loc.id)

        assert body['recipe_state'] == 'empty'
        assert body['recipe_id'] == str(recipe.id)
        assert body['entries'] == []

    def test_a_recipe_with_lines_says_has_lines(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        soup = _make_template(db_session, mk_org, name='Soup')
        carrot = _make_template(db_session, mk_org, name='Carrot')
        recipe = _ensure_recipe(db_session, mk_org, soup.id)
        db_session.add(
            BoMLine(
                organization_id=mk_org.id,
                recipe_id=recipe.id,
                parent_template_id=soup.id,
                child_template_id=carrot.id,
                qty_per_batch=Decimal('0.5'),
                unit='kg',
            )
        )
        db_session.commit()

        body = _preview(client, mk_auth_headers, soup.id, mk_output_loc.id)

        assert body['recipe_state'] == 'has_lines'
        assert body['recipe_id'] == str(recipe.id)
        entries = body['entries']
        assert isinstance(entries, list) and len(entries) == 1

    def test_a_preview_for_someone_elses_recipe_id_refuses_like_create(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        # The dry-run owes the caller the same refusal the real create
        # would voice, not a 200 about a formula that is not there. Passes
        # on the old code too — ``_resolve_recipe`` already refused inside
        # the explosion; it is kept as the pinned old behaviour, not as
        # proof of the new one.
        product = _make_template(db_session, mk_org, name='Wrong id')

        response = client.post(
            '/api/v1/maker/production/orders/preview',
            headers=mk_auth_headers,
            json={
                'output_template_id': str(product.id),
                'planned_qty': '2.000',
                'output_location_id': str(mk_output_loc.id),
                'recipe_id': str(uuid.uuid4()),
            },
        )

        assert response.status_code == 400, response.text
        # The keyed-refusal shape: a translated sentence for the reader,
        # not the raw key and not a 500.
        detail = response.json()['detail']
        assert detail['message']
        assert 'production_recipe_not_found' not in detail['message']

    def test_the_catalog_breakdown_speaks_the_same_states(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        # GET /breakdown shares the response schema and the resolver; the
        # two doors cannot go back to disagreeing about the same product.
        orphan = _make_template(db_session, mk_org, name='Catalog orphan')
        filled = _make_template(db_session, mk_org, name='Catalog soup')
        carrot = _make_template(db_session, mk_org, name='Catalog carrot')
        recipe = _ensure_recipe(db_session, mk_org, filled.id)
        db_session.add(
            BoMLine(
                organization_id=mk_org.id,
                recipe_id=recipe.id,
                parent_template_id=filled.id,
                child_template_id=carrot.id,
                qty_per_batch=Decimal('0.5'),
                unit='kg',
            )
        )
        db_session.commit()

        orphan_body = client.get(
            f'/api/v1/maker/breakdown/{orphan.id}?qty=1',
            headers=mk_auth_headers,
        )
        filled_body = client.get(
            f'/api/v1/maker/breakdown/{filled.id}?qty=1',
            headers=mk_auth_headers,
        )

        assert orphan_body.status_code == 200, orphan_body.text
        assert orphan_body.json()['recipe_state'] == 'no_recipe'
        assert filled_body.status_code == 200, filled_body.text
        assert filled_body.json()['recipe_state'] == 'has_lines'
        assert filled_body.json()['recipe_id'] == str(recipe.id)


class TestPricingNamesTheMissingRecipeToo:
    """The sale-price calculator answers on the same default formula."""

    def test_pricing_without_a_recipe_is_no_recipe(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        orphan = _make_template(db_session, mk_org, name='Unpriced orphan')

        response = client.post(
            '/api/v1/maker/pricing/compute',
            headers=mk_auth_headers,
            json={
                'template_id': str(orphan.id),
                'produced_qty': '1.000',
                'target_margin_pct': '30',
            },
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body['recipe_state'] == 'no_recipe'
        assert body['recipe_id'] is None
        assert body['ingredient_count'] == 0

    def test_pricing_for_an_empty_recipe_is_empty_and_is_named(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        product = _make_template(db_session, mk_org, name='Empty formula price')
        recipe = _ensure_recipe(db_session, mk_org, product.id)

        response = client.post(
            '/api/v1/maker/pricing/compute',
            headers=mk_auth_headers,
            json={
                'template_id': str(product.id),
                'produced_qty': '1.000',
                'target_margin_pct': '30',
            },
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body['recipe_state'] == 'empty'
        assert body['recipe_id'] == str(recipe.id)
        assert body['ingredient_count'] == 0
