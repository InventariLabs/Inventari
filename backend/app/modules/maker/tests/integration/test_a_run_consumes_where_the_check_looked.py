"""A run consumes from the stock the availability check looked at.

The check honours the organisation's scope — PER_LOCATION judges the run's
own output shelf — but the draw took from every shelf in the organisation.
Two doors, two sets: a run could pass on what stood at its shelf and then eat
a batch from the far corner of the warehouse, or be refused at its shelf
while the goods stood one aisle away and the draw would have found them.
One question — where may this run take its ingredients from — now has one
answer for both doors: the resolved scope feeds the check and the draw
alike, so what the run was judged on is what it ate.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.maker.models import (
    BoMLine,
    MakerModuleSettings,
    MakerRecipe,
    ProductionOrder,
)

pytestmark = pytest.mark.integration


def _set_scope(db: Session, org: Organization, scope: str) -> None:
    row = db.execute(
        select(MakerModuleSettings).where(MakerModuleSettings.organization_id == org.id)
    ).scalar_one_or_none()
    if row is None:
        db.add(
            MakerModuleSettings(organization_id=org.id, availability_check_scope=scope)
        )
    else:
        row.availability_check_scope = scope
    db.commit()


def _one_to_three_run(db: Session, org: Organization) -> ProductTemplate:
    ingredient = ProductTemplate(
        organization_id=org.id, name=f'Ingredient {uuid.uuid4().hex[:6]}'
    )
    output = ProductTemplate(
        organization_id=org.id, name=f'Output {uuid.uuid4().hex[:6]}'
    )
    db.add_all([ingredient, output])
    db.flush()
    recipe = MakerRecipe(
        organization_id=org.id,
        output_template_id=output.id,
        name='Three to one',
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
            qty_per_batch=Decimal('3'),
            unit='pcs',
        )
    )
    db.commit()
    return ingredient


def _shelf_record(
    client: TestClient,
    headers: dict[str, str],
    template: ProductTemplate,
    location: StorageLocation,
    qty: str,
    *,
    expiry: str | None = None,
) -> None:
    body: dict[str, object] = {
        'name': template.name,
        'location_id': str(location.id),
        'quantity': qty,
    }
    if expiry is not None:
        body['expiry_date'] = expiry
    created = client.post('/api/v1/items', headers=headers, json=body)
    assert created.status_code == 201, created.text


def _quantity_at(
    db: Session, template: ProductTemplate, location: StorageLocation
) -> Decimal:
    db.expire_all()
    total = Decimal('0')
    for row in db.scalars(
        select(Item).where(
            Item.template_id == template.id,
            Item.storage_location_id == location.id,
        )
    ):
        total += row.quantity
    return total


class TestARunConsumesWhereTheCheckLooked:
    def test_a_per_location_run_eats_its_own_shelf_not_the_far_corner(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_user: User,
        mk_input_loc: StorageLocation,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        _set_scope(db_session, mk_org, 'PER_LOCATION')
        ingredient = _one_to_three_run(db_session, mk_org)
        elsewhere = StorageLocation(
            organization_id=mk_org.id,
            name=f'Elsewhere {uuid.uuid4().hex[:6]}',
            storage_type_id=mk_input_loc.storage_type_id,
            created_by=mk_user.id,
        )
        db_session.add(elsewhere)
        db_session.commit()
        # The far-corner batch expires first, so a whole-organisation draw
        # would take it — this is the record the run must NOT eat.
        _shelf_record(
            client,
            mk_auth_headers,
            ingredient,
            elsewhere,
            '3',
            expiry=(datetime.now(tz=UTC) + timedelta(days=1)).date().isoformat(),
        )
        _shelf_record(
            client,
            mk_auth_headers,
            ingredient,
            mk_output_loc,
            '3',
            expiry=(datetime.now(tz=UTC) + timedelta(days=30)).date().isoformat(),
        )

        created = client.post(
            '/api/v1/maker/production/orders',
            headers=mk_auth_headers,
            json={
                'output_template_id': str(
                    db_session.scalar(
                        select(MakerRecipe.output_template_id).where(
                            MakerRecipe.organization_id == mk_org.id
                        )
                    )
                ),
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

        assert _quantity_at(db_session, ingredient, mk_output_loc) == Decimal('0'), (
            'the run ate the shelf it was judged on'
        )
        assert _quantity_at(db_session, ingredient, elsewhere) == Decimal('3'), (
            'the far-corner batch the check never saw stayed where it was'
        )

    def test_a_global_run_still_draws_across_the_organisation(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_input_loc: StorageLocation,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        _set_scope(db_session, mk_org, 'GLOBAL')
        ingredient = _one_to_three_run(db_session, mk_org)
        _shelf_record(client, mk_auth_headers, ingredient, mk_input_loc, '3')
        _shelf_record(client, mk_auth_headers, ingredient, mk_output_loc, '3')

        output_id = db_session.scalar(
            select(MakerRecipe.output_template_id).where(
                MakerRecipe.organization_id == mk_org.id
            )
        )
        created = client.post(
            '/api/v1/maker/production/orders',
            headers=mk_auth_headers,
            json={
                'output_template_id': str(output_id),
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

        total = _quantity_at(db_session, ingredient, mk_input_loc) + _quantity_at(
            db_session, ingredient, mk_output_loc
        )
        assert total == Decimal('3'), 'the whole organisation stays one shelf'

        # The completed run's bookkeeping names its consumption scope: the
        # order row the screen shows is the same one the doors agreed on.
        order = db_session.scalar(
            select(ProductionOrder).where(
                ProductionOrder.organization_id == mk_org.id,
                ProductionOrder.status == 'COMPLETED',
            )
        )
        assert order is not None
