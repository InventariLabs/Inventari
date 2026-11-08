"""A product's formula is read one recipe at a time, not every variant at once.

The template-keyed reads — ``GET /bom/{template_id}``, the tree under it and
``maker_api.list_bom_lines_async`` — filtered by the product alone, so a
product with two variants answered both variants' ingredients in one list,
and the tree editor on one variant's page showed the other's lines as its own.
Without a recipe the read is the default recipe, the one a run explodes for a
sub-assembly; with ``recipe_id`` it is that recipe.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.modules.maker.models import BoMLine, MakerRecipe

pytestmark = pytest.mark.integration


def _template(db: Session, org: Organization, name: str) -> ProductTemplate:
    template = ProductTemplate(organization_id=org.id, name=name)
    db.add(template)
    db.flush()
    return template


def _formula(
    db: Session,
    org: Organization,
    *,
    output: ProductTemplate,
    ingredient: ProductTemplate,
    is_default: bool,
) -> MakerRecipe:
    recipe = MakerRecipe(
        organization_id=org.id,
        output_template_id=output.id,
        name=f'Variant {uuid.uuid4().hex[:6]}',
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


_TwoVariants = tuple[
    ProductTemplate, MakerRecipe, MakerRecipe, ProductTemplate, ProductTemplate
]


@pytest.fixture
def two_variants(db_session: Session, mk_org: Organization) -> _TwoVariants:
    soap = _template(db_session, mk_org, 'Soap')
    lavender = _template(db_session, mk_org, 'Lavender oil')
    mint = _template(db_session, mk_org, 'Mint oil')
    default = _formula(
        db_session, mk_org, output=soap, ingredient=lavender, is_default=True
    )
    variant = _formula(
        db_session, mk_org, output=soap, ingredient=mint, is_default=False
    )
    db_session.commit()
    return soap, default, variant, lavender, mint


def _children(client: TestClient, headers: dict[str, str], url: str) -> list[str]:
    resp = client.get(url, headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    if 'root' in body:
        return [node['line']['child_template_id'] for node in body['root']['children']]
    return [line['child_template_id'] for line in body['items']]


class TestTheLinesOfOneRecipe:
    def test_the_product_alone_answers_its_default_recipe(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        two_variants: _TwoVariants,
    ) -> None:
        soap, _default, _variant, lavender, _mint = two_variants

        lines = _children(client, mk_auth_headers, f'/api/v1/maker/bom/{soap.id}')

        assert lines == [str(lavender.id)]

    def test_a_variant_answers_its_own_lines(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        two_variants: _TwoVariants,
    ) -> None:
        soap, _default, variant, _lavender, mint = two_variants

        lines = _children(
            client,
            mk_auth_headers,
            f'/api/v1/maker/bom/{soap.id}?recipe_id={variant.id}',
        )

        assert lines == [str(mint.id)]


class TestTheTreeOfOneRecipe:
    def test_the_tree_on_a_variants_page_holds_that_variant(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        two_variants: _TwoVariants,
    ) -> None:
        soap, _default, variant, _lavender, mint = two_variants

        children = _children(
            client,
            mk_auth_headers,
            f'/api/v1/maker/bom/tree/{soap.id}?recipe_id={variant.id}',
        )

        assert children == [str(mint.id)]

    def test_the_tree_of_the_product_is_its_default_recipe(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        two_variants: _TwoVariants,
    ) -> None:
        soap, _default, _variant, lavender, _mint = two_variants

        children = _children(
            client, mk_auth_headers, f'/api/v1/maker/bom/tree/{soap.id}'
        )

        assert children == [str(lavender.id)]


class TestTheModuleFacade:
    async def test_list_bom_lines_answers_the_default_recipe(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
    ) -> None:
        from app.models.product_template import ProductTemplate as Template
        from app.modules.maker.maker_api import maker_api

        db = real_async_db_session
        soap = Template(organization_id=async_test_household.id, name='Soap')
        lavender = Template(organization_id=async_test_household.id, name='Lavender')
        mint = Template(organization_id=async_test_household.id, name='Mint')
        db.add_all([soap, lavender, mint])
        await db.flush()
        for ingredient, is_default in ((lavender, True), (mint, False)):
            recipe = MakerRecipe(
                organization_id=async_test_household.id,
                output_template_id=soap.id,
                name=f'Variant {ingredient.name}',
                batch_yield_qty=Decimal('1'),
                is_default=is_default,
            )
            db.add(recipe)
            await db.flush()
            db.add(
                BoMLine(
                    organization_id=async_test_household.id,
                    recipe_id=recipe.id,
                    parent_template_id=soap.id,
                    child_template_id=ingredient.id,
                    qty_per_batch=Decimal('1'),
                    unit='kg',
                )
            )
        await db.flush()

        lines = await maker_api.list_bom_lines_async(
            db, async_test_household.id, soap.id
        )

        assert [line.child_template_id for line in lines] == [lavender.id]
