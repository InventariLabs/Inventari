"""A production run files its output where the product already lives.

The production executor called ``items.create`` for the output without a
category: the goods went on the shelf and the category filter, the
counters and the searches could not see them — a run's output stood
outside the register the product's other records are filed in.

The run now inherits the filing the product's records carry, the same
rule a receipt follows: no source record is named, so the product
answers.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.category import Category
from app.models.item import Item
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.maker.models import BoMLine, MakerRecipe, ProductionOrder
from tests.integration._shelf import post_on_shelf

pytestmark = pytest.mark.integration


def _template(db: Session, org: Organization, *, name: str) -> ProductTemplate:
    template = ProductTemplate(
        organization_id=org.id,
        name=name,
        sku=f'SKU-{uuid4().hex[:8]}',
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    return template


def _recipe(db: Session, org: Organization, template_id: UUID) -> MakerRecipe:
    recipe = MakerRecipe(
        organization_id=org.id,
        output_template_id=template_id,
        name='Cat recipe',
        batch_yield_qty=Decimal('1'),
        is_default=True,
    )
    db.add(recipe)
    db.commit()
    db.refresh(recipe)
    return recipe


def _bom_line(
    db: Session, org: Organization, *, recipe_id: UUID, parent_id: UUID, child_id: UUID
) -> None:
    db.add(
        BoMLine(
            organization_id=org.id,
            recipe_id=recipe_id,
            parent_template_id=parent_id,
            child_template_id=child_id,
            qty_per_batch=Decimal('2'),
            unit='szt',
        )
    )
    db.commit()


@pytest.mark.integration
class TestProducedRecordInheritsTheCategory:
    def test_a_production_output_takes_the_products_category(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        db_session: Session,
        mk_org: Organization,
        mk_user: User,
        mk_input_loc: StorageLocation,
        mk_output_loc: StorageLocation,
    ) -> None:
        """A product with records in a category produces into the same one."""
        output = _template(db_session, mk_org, name=f'prod-cat-out-{uuid4().hex[:6]}')
        ingredient = _template(
            db_session, mk_org, name=f'prod-cat-ing-{uuid4().hex[:6]}'
        )
        recipe = _recipe(db_session, mk_org, output.id)
        _bom_line(
            db_session,
            mk_org,
            recipe_id=recipe.id,
            parent_id=output.id,
            child_id=ingredient.id,
        )
        post_on_shelf(client, mk_auth_headers, ingredient, mk_input_loc.id, '10')

        category = Category(
            organization_id=mk_org.id, name=f'prod-cat-{uuid4().hex[:6]}'
        )
        db_session.add(category)
        db_session.commit()
        db_session.refresh(category)
        standing = post_on_shelf(client, mk_auth_headers, output, mk_output_loc.id, '1')
        item = db_session.get(Item, UUID(standing['id']))
        assert item is not None
        item.category_id = category.id
        db_session.commit()

        order = ProductionOrder(
            organization_id=mk_org.id,
            output_template_id=output.id,
            recipe_id=None,
            planned_qty=Decimal('1'),
            output_storage_location_id=mk_output_loc.id,
            status='DRAFT',
            created_by=mk_user.id,
        )
        db_session.add(order)
        db_session.commit()
        db_session.refresh(order)

        resp = client.post(
            f'/api/v1/maker/production/orders/{order.id}/complete',
            headers=mk_auth_headers,
        )
        assert resp.status_code == 200, resp.text

        db_session.expire_all()
        db_session.refresh(order)
        produced = db_session.get(Item, order.produced_item_id)
        assert produced is not None, 'the run put its output on the shelf'
        assert produced.category_id == category.id, (
            'the output is filed where the product already lives'
        )
