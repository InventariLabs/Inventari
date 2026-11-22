"""A run closed in one step or in portions is stamped with the day it was made.

A draft is planned for a day, and the plan moves. Completing it books the
ingredients and the output on the day it really happened: the organization's
today, or the day the person names. The batch's production date, the run's
production date and the batch name follow that day; the planned day stays
what it was, a plan.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.stock_lot import StockLot
from app.models.storage_location import StorageLocation
from app.modules.maker.models import BoMLine, MakerRecipe
from tests.integration._shelf import post_on_shelf

pytestmark = pytest.mark.integration

ORDERS = '/api/v1/maker/production/orders'


def _template(db: Session, org: Organization, name: str) -> ProductTemplate:
    template = ProductTemplate(
        organization_id=org.id, name=name, sku=f'SKU-{uuid.uuid4().hex[:8]}'
    )
    db.add(template)
    db.flush()
    return template


@pytest.fixture
def jam(
    db_session: Session,
    client: TestClient,
    mk_org: Organization,
    mk_auth_headers: dict[str, str],
    mk_input_loc: StorageLocation,
) -> ProductTemplate:
    """Jam made of plums, 2 per jar, with plenty of plums on the shelf."""
    plums = _template(db_session, mk_org, 'Plums')
    jam = _template(db_session, mk_org, 'Plum jam')
    recipe = MakerRecipe(
        organization_id=mk_org.id,
        output_template_id=jam.id,
        name='Jar',
        batch_yield_qty=Decimal('1'),
        is_default=True,
    )
    db_session.add(recipe)
    db_session.flush()
    db_session.add(
        BoMLine(
            organization_id=mk_org.id,
            recipe_id=recipe.id,
            parent_template_id=jam.id,
            child_template_id=plums.id,
            qty_per_batch=Decimal('2'),
            unit='pcs',
        )
    )
    db_session.commit()
    post_on_shelf(client, mk_auth_headers, plums, mk_input_loc.id, '100')
    return jam


def _draft_planned_for(
    client: TestClient,
    headers: dict[str, str],
    jam: ProductTemplate,
    loc: StorageLocation,
    day: date,
) -> str:
    response = client.post(
        ORDERS,
        headers=headers,
        json={
            'output_template_id': str(jam.id),
            'planned_qty': '4',
            'output_location_id': str(loc.id),
            'production_date': day.isoformat(),
        },
    )
    assert response.status_code == 201, response.text
    return str(response.json()['id'])


def _complete(
    client: TestClient, headers: dict[str, str], run_id: str, **body: Any
) -> dict[str, Any]:
    response = client.post(f'{ORDERS}/{run_id}/complete', headers=headers, json=body)
    assert response.status_code == 200, response.text
    return dict(response.json())


def test_a_run_planned_for_a_later_day_is_stamped_with_the_day_it_is_completed(
    client: TestClient,
    db_session: Session,
    mk_auth_headers: dict[str, str],
    mk_output_loc: StorageLocation,
    jam: ProductTemplate,
) -> None:
    planned = date.today() + timedelta(days=3)
    run_id = _draft_planned_for(client, mk_auth_headers, jam, mk_output_loc, planned)

    done = _complete(client, mk_auth_headers, run_id)

    # Fails without the change: the run, its batch and the batch's name carry
    # the planned day, three days that have not come.
    day = date.fromisoformat(done['production_date'])
    assert abs(day - date.today()) <= timedelta(days=1)
    db_session.expire_all()
    lot = db_session.get(StockLot, UUID(done['output_lot_id']))
    assert lot is not None and lot.production_date == day
    assert done['output_lot_name'].startswith(day.strftime('%Y%m%d'))
    # The plan's day stays on the run beside the day it was made.
    assert done['planned_for'] == planned.isoformat()


def test_a_run_made_on_its_planned_day_carries_no_separate_plan(
    client: TestClient,
    mk_auth_headers: dict[str, str],
    mk_output_loc: StorageLocation,
    jam: ProductTemplate,
) -> None:
    run_id = _draft_planned_for(
        client, mk_auth_headers, jam, mk_output_loc, date.today()
    )

    done = _complete(client, mk_auth_headers, run_id, made_on=date.today().isoformat())

    assert done['planned_for'] is None


def test_the_person_completing_the_run_names_the_day_it_was_made(
    client: TestClient,
    db_session: Session,
    mk_auth_headers: dict[str, str],
    mk_output_loc: StorageLocation,
    jam: ProductTemplate,
) -> None:
    planned = date.today() + timedelta(days=3)
    made_on = date.today() - timedelta(days=2)
    run_id = _draft_planned_for(client, mk_auth_headers, jam, mk_output_loc, planned)

    done = _complete(client, mk_auth_headers, run_id, made_on=made_on.isoformat())

    assert done['production_date'] == made_on.isoformat()
    db_session.expire_all()
    lot = db_session.get(StockLot, UUID(done['output_lot_id']))
    assert lot is not None and lot.production_date == made_on


def _start_and_finish(
    client: TestClient, headers: dict[str, str], run_id: str
) -> dict[str, Any]:
    started = client.post(f'{ORDERS}/{run_id}/start', headers=headers)
    assert started.status_code == 200, started.text
    portion = client.post(
        f'{ORDERS}/{run_id}/portions', headers=headers, json={'qty': '1'}
    )
    assert portion.status_code == 201, portion.text
    finished = client.post(
        f'{ORDERS}/{run_id}/finish', headers=headers, json={'actual_qty': '4'}
    )
    assert finished.status_code == 200, finished.text
    return dict(finished.json())


def test_a_run_finished_in_portions_keeps_the_day_it_was_planned_for(
    client: TestClient,
    mk_auth_headers: dict[str, str],
    mk_output_loc: StorageLocation,
    jam: ProductTemplate,
) -> None:
    planned = date.today() + timedelta(days=3)
    run_id = _draft_planned_for(client, mk_auth_headers, jam, mk_output_loc, planned)

    done = _start_and_finish(client, mk_auth_headers, run_id)

    # Fails without the change: finishing overwrote the planned day and left
    # no trace of it, so the run read as if it had been planned for today.
    assert abs(date.fromisoformat(done['production_date']) - date.today()) <= (
        timedelta(days=1)
    )
    assert done['planned_for'] == planned.isoformat()


def test_a_run_finished_in_portions_on_its_planned_day_carries_no_separate_plan(
    client: TestClient,
    mk_auth_headers: dict[str, str],
    mk_output_loc: StorageLocation,
    jam: ProductTemplate,
) -> None:
    run_id = _draft_planned_for(
        client, mk_auth_headers, jam, mk_output_loc, date.today()
    )

    done = _start_and_finish(client, mk_auth_headers, run_id)

    assert done['planned_for'] is None
