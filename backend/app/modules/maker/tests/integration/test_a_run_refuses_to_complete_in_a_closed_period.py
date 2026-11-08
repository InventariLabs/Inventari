"""A production run refuses to complete in a closed inventory period.

Documents, item movements, stock takes and picking for recipes all ask the
period guard before they write stock; completing a maker run did not — the
run posted its consumption, its output layer and its item rows straight
through a month the organization had closed for accounting. The completion
now asks the same guard as a document: the run books itself under its
production date (the completion day when it was never named), and a closed
month answers 409 with the period named, before anything moves. A month
reopened afterwards completes as before.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.modules.maker.models import BoMLine, MakerRecipe
from app.modules.warehouse.models import InventoryPeriod
from tests.integration._shelf import post_on_shelf

pytestmark = pytest.mark.integration


def _one_ingredient_run(
    db: Session, org: Organization
) -> tuple[ProductTemplate, ProductTemplate]:
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
        name='One line',
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


def _month(db: Session, org: Organization, *, reopened: bool) -> None:
    now = datetime.now(tz=UTC)
    period = InventoryPeriod(
        organization_id=org.id,
        year=now.year,
        month=now.month,
        closed_at=now,
    )
    if reopened:
        period.reopened_at = now
    db.add(period)
    db.commit()


def _draft_run(
    client: TestClient,
    headers: dict[str, str],
    output: ProductTemplate,
    input_loc: StorageLocation,
    output_loc: StorageLocation,
) -> str:
    created = client.post(
        '/api/v1/maker/production/orders',
        headers=headers,
        json={
            'output_template_id': str(output.id),
            'planned_qty': '1',
            'input_storage_location_id': str(input_loc.id),
            'output_location_id': str(output_loc.id),
        },
    )
    assert created.status_code == 201, created.text
    return str(created.json()['id'])


class TestARunRefusesToCompleteInAClosedPeriod:
    def test_a_run_in_a_closed_month_answers_409_before_anything_moves(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_input_loc: StorageLocation,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        ingredient, output = _one_ingredient_run(db_session, mk_org)
        post_on_shelf(client, mk_auth_headers, ingredient, mk_input_loc.id, '2')
        _month(db_session, mk_org, reopened=False)

        run_id = _draft_run(
            client, mk_auth_headers, output, mk_input_loc, mk_output_loc
        )
        completed = client.post(
            f'/api/v1/maker/production/orders/{run_id}/complete',
            headers=mk_auth_headers,
        )

        assert completed.status_code == 409, completed.text
        assert completed.json()['detail']['code'] == 'PERIOD_CLOSED'
        assert str(datetime.now(tz=UTC).year) in str(completed.json()['detail'])

    def test_a_run_in_a_reopened_month_completes_as_before(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_input_loc: StorageLocation,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        ingredient, output = _one_ingredient_run(db_session, mk_org)
        post_on_shelf(client, mk_auth_headers, ingredient, mk_input_loc.id, '2')
        _month(db_session, mk_org, reopened=True)

        run_id = _draft_run(
            client, mk_auth_headers, output, mk_input_loc, mk_output_loc
        )
        completed = client.post(
            f'/api/v1/maker/production/orders/{run_id}/complete',
            headers=mk_auth_headers,
        )

        assert completed.status_code == 200, completed.text
        assert completed.json()['status'] == 'COMPLETED'


class TestARunReadsTheOrganizationsDay:
    """A run with no production date is dated on the organization's day.

    The guard asked ``date.today()`` — the server's day — and the date the
    run was stamped with at closing was the UTC date of the instant. Every
    other stock-writing path asks the organization's clock, so around
    midnight a run was booked into a day, and at the end of a month into a
    month, the organization was not in.
    """

    def test_the_run_is_dated_where_the_organization_is(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_input_loc: StorageLocation,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        # A zone a whole day apart from UTC at this hour, whichever hour the
        # suite runs at: twelve hours behind before noon, fourteen ahead after.
        now = datetime.now(tz=UTC)
        zone = 'Etc/GMT+12' if now.hour < 12 else 'Etc/GMT-14'
        org_day = now.astimezone(ZoneInfo(zone)).date()
        assert org_day != now.date()
        mk_org.timezone = zone
        db_session.commit()
        ingredient, output = _one_ingredient_run(db_session, mk_org)
        post_on_shelf(client, mk_auth_headers, ingredient, mk_input_loc.id, '2')

        run_id = _draft_run(
            client, mk_auth_headers, output, mk_input_loc, mk_output_loc
        )
        completed = client.post(
            f'/api/v1/maker/production/orders/{run_id}/complete',
            headers=mk_auth_headers,
        )

        assert completed.status_code == 200, completed.text
        assert completed.json()['production_date'] == org_day.isoformat()
