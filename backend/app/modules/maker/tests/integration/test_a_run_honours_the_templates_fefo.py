"""A run honours the template's removal strategy, FEFO included.

The maker resolved the removal strategy from ``ProductTemplateDTO``, which
does not carry ``removal_strategy`` — the resolver answered FIFO for every
template and sent it as an override, and an override beats the product's own
setting in Core's draw. A template set to FEFO was drawn FIFO, and the cost
breakdown planned the same wrong order, so the plan agreed with the run and
both ignored the card. The draw now overrides only when the carrier in hand
actually names a strategy; otherwise Core reads the product itself.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.stock_lot import StockLot
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.maker.models import BoMLine, MakerRecipe
from tests.integration._shelf import put_on_shelf, run_in_async_session

pytestmark = pytest.mark.integration


def _fefo_run(
    db: Session, org: Organization
) -> tuple[ProductTemplate, ProductTemplate]:
    """A FEFO ingredient in a one-to-one recipe; returns (ingredient, output)."""
    ingredient = ProductTemplate(
        organization_id=org.id, name=f'Ingredient {uuid.uuid4().hex[:6]}'
    )
    db.add(ingredient)
    db.flush()
    ingredient.removal_strategy = 'FEFO'
    output = ProductTemplate(
        organization_id=org.id, name=f'Output {uuid.uuid4().hex[:6]}'
    )
    db.add(output)
    db.flush()
    recipe = MakerRecipe(
        organization_id=org.id,
        output_template_id=output.id,
        name='One to one',
        batch_yield_qty=Decimal('1'),
        is_default=True,
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
            unit='pcs',
        )
    )
    db.commit()
    return ingredient, output


def _batch(
    db: Session, org: Organization, template: ProductTemplate, name: str, use_by: date
) -> StockLot:
    lot = StockLot(
        organization_id=org.id,
        product_template_id=template.id,
        name=name,
        use_by_date=use_by,
    )
    db.add(lot)
    db.commit()
    return lot


def _held_of_batch(db: Session, template: ProductTemplate, lot_id: Any) -> Decimal:
    db.expire_all()
    return sum(
        (
            row.quantity
            for row in db.scalars(
                select(Item).where(
                    Item.template_id == template.id, Item.lot_id == lot_id
                )
            )
        ),
        Decimal('0'),
    )


class TestARunHonoursTheTemplatesFefo:
    def test_the_earlier_expiry_goes_first_for_a_fefo_template(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_user: User,
        mk_input_loc: StorageLocation,
        mk_output_loc: StorageLocation,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        ingredient, output = _fefo_run(db_session, mk_org)
        far_shelf = StorageLocation(
            organization_id=mk_org.id,
            name=f'Far shelf {uuid.uuid4().hex[:6]}',
            created_by=mk_user.id,
        )
        db_session.add(far_shelf)
        db_session.commit()

        now = datetime.now(tz=UTC)
        # Creation and expiry point opposite ways, so the eaten batch names
        # the order the draw followed: FIFO takes the record created first
        # (the far batch), FEFO the one that expires first (the near one).
        far_lot = _batch(
            db_session, mk_org, ingredient, 'older, keeps', now + timedelta(days=90)
        )
        near_lot = _batch(
            db_session, mk_org, ingredient, 'newer, expires', now + timedelta(days=2)
        )
        run_in_async_session(
            async_engine_fixture,
            lambda session: put_on_shelf(
                session, mk_user, ingredient, far_shelf.id, 1, lot_id=far_lot.id
            ),
        )
        run_in_async_session(
            async_engine_fixture,
            lambda session: put_on_shelf(
                session, mk_user, ingredient, mk_input_loc.id, 1, lot_id=near_lot.id
            ),
        )
        db_session.expire_all()

        # The draft's cost breakdown plans the draw before anything leaves
        # stock — under the template's FEFO it names the near batch's shelf.
        breakdown = client.get(
            f'/api/v1/maker/breakdown/{output.id}?qty=1',
            headers=mk_auth_headers,
        )
        assert breakdown.status_code == 200, breakdown.text
        [entry] = breakdown.json()['entries']
        planned_shelves = [d['location_id'] for d in entry['planned_draws']]
        assert planned_shelves == [str(mk_input_loc.id)], (
            'the plan drew in FIFO order: the far shelf first'
        )

        created = client.post(
            '/api/v1/maker/production/orders',
            headers=mk_auth_headers,
            json={
                'output_template_id': str(output.id),
                'planned_qty': '1',
                'input_storage_location_id': str(mk_input_loc.id),
                'output_location_id': str(mk_output_loc.id),
            },
        )
        assert created.status_code == 201, created.text
        completed = client.post(
            f'/api/v1/maker/production/orders/{created.json()["id"]}/complete',
            headers=mk_auth_headers,
        )
        assert completed.status_code == 200, completed.text

        assert _held_of_batch(db_session, ingredient, near_lot.id) == Decimal('0'), (
            'FEFO ate the earlier expiry first'
        )
        assert _held_of_batch(db_session, ingredient, far_lot.id) == Decimal('1'), (
            'the later expiry stayed'
        )
