"""Labour is the formula's step time at the organization's hourly rate.

A craft producer prices a batch from the hours it takes. The fixed LABOR
line could only be a lump sum typed per batch, so a formula whose steps grew
or shrank kept quoting the same labour — and a run never showed what the
work cost. The rate is the organization's; the time is each step's.
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.modules.maker.models import MakerRecipe
from tests.integration._shelf import post_on_shelf

pytestmark = pytest.mark.integration


def _template(db: Session, org: Organization, name: str) -> ProductTemplate:
    template = ProductTemplate(
        organization_id=org.id, name=name, sku=f'SKU-{uuid.uuid4().hex[:8]}'
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    return template


def _recipe_with_steps(
    client: TestClient,
    headers: dict[str, str],
    db: Session,
    org: Organization,
    output: ProductTemplate,
    ingredient: ProductTemplate,
    *,
    minutes: int = 120,
) -> str:
    recipe = client.post(
        '/api/v1/maker/recipes',
        headers=headers,
        json={
            'output_template_id': str(output.id),
            'name': 'Timed batch',
            'batch_yield_qty': '10',
            'process_steps': [
                {'text': 'Mix', 'minutes': '30'},
                {'text': 'Cure', 'minutes': str(minutes - 30)},
            ],
        },
    )
    assert recipe.status_code == 201, recipe.text
    recipe_id = recipe.json()['id']
    line = client.post(
        f'/api/v1/maker/recipes/{recipe_id}/bom-lines',
        headers=headers,
        json={
            'child_template_id': str(ingredient.id),
            'qty_per_batch': '2',
            'unit': 'pcs',
        },
    )
    assert line.status_code == 201, line.text
    return str(recipe_id)


def test_the_recipe_shows_its_labour_from_step_time_at_the_rate(
    client: TestClient,
    mk_auth_headers: dict[str, str],
    mk_org: Organization,
    mk_input_loc: StorageLocation,
    mk_output_loc: StorageLocation,
    db_session: Session,
) -> None:
    output = _template(db_session, mk_org, 'Soap')
    ingredient = _template(db_session, mk_org, 'Oil')
    post_on_shelf(
        client,
        mk_auth_headers,
        ingredient,
        mk_input_loc.id,
        '10',
        purchase_price='2.00',
    )
    recipe_id = _recipe_with_steps(
        client, mk_auth_headers, db_session, mk_org, output, ingredient
    )

    settings = client.patch(
        '/api/v1/maker/settings',
        headers=mk_auth_headers,
        json={'labor_hourly_rate': '20.00'},
    )
    assert settings.status_code == 200, settings.text
    assert settings.json()['labor_hourly_rate'] == '20.00'
    # The rate is read back by the settings screen, not only accepted.
    assert (
        client.get('/api/v1/maker/settings', headers=mk_auth_headers).json()[
            'labor_hourly_rate'
        ]
        == '20.00'
    )

    fixed = client.post(
        f'/api/v1/maker/recipes/{recipe_id}/cost-lines',
        headers=mk_auth_headers,
        json={'kind': 'PACKAGING', 'label': 'Jar', 'amount': '5.00'},
    )
    assert fixed.status_code == 201, fixed.text

    detail = client.get(f'/api/v1/maker/recipes/{recipe_id}', headers=mk_auth_headers)
    assert detail.status_code == 200, detail.text
    body = detail.json()
    # 120 minutes at 20.00 an hour is 40.00 of labour for the batch.
    assert body['labour_cost'] == '40.00'
    assert [step['minutes'] for step in body['process_steps']] == ['30', '90']
    # 2 kg at 2.00 (4.00) + 5.00 of packaging + 40.00 of labour, over 10 units.
    assert body['estimated_unit_cost'] == '4.900000'


def test_a_completed_run_carries_its_labour_beside_the_ingredients(
    client: TestClient,
    mk_auth_headers: dict[str, str],
    mk_org: Organization,
    mk_input_loc: StorageLocation,
    mk_output_loc: StorageLocation,
    db_session: Session,
) -> None:
    output = _template(db_session, mk_org, 'Candle')
    ingredient = _template(db_session, mk_org, 'Wax')
    post_on_shelf(
        client,
        mk_auth_headers,
        ingredient,
        mk_input_loc.id,
        '100',
        purchase_price='2.00',
    )
    recipe_id = _recipe_with_steps(
        client, mk_auth_headers, db_session, mk_org, output, ingredient
    )
    client.patch(
        '/api/v1/maker/settings',
        headers=mk_auth_headers,
        json={'labor_hourly_rate': '20.00'},
    )
    client.post(
        f'/api/v1/maker/recipes/{recipe_id}/cost-lines',
        headers=mk_auth_headers,
        json={'kind': 'PACKAGING', 'label': 'Box', 'amount': '5.00'},
    )

    created = client.post(
        '/api/v1/maker/production/orders',
        headers=mk_auth_headers,
        json={
            'output_template_id': str(output.id),
            'recipe_id': recipe_id,
            'planned_qty': '10',
            'output_location_id': str(mk_output_loc.id),
        },
    )
    assert created.status_code == 201, created.text
    order_id = created.json()['id']
    completed = client.post(
        f'/api/v1/maker/production/orders/{order_id}/complete',
        headers=mk_auth_headers,
        json={'actual_qty': '8'},
    )
    assert completed.status_code == 200, completed.text
    body = client.get(
        f'/api/v1/maker/production/orders/{order_id}', headers=mk_auth_headers
    ).json()

    # Actual: one batch's 2 kg of wax at 2.00 (4.00), 5.00 of packaging,
    # 40.00 of labour.
    assert body['total_cost'] == '49.00'
    # Estimate when it closed: the standard 1.6 kg for the 8 units that came
    # out (3.20), plus the same overheads.
    assert body['estimated_total_cost'] == '48.20'
    line = body['lines'][0]
    assert line['estimated_qty'] == '1.6000'
    assert line['estimated_unit_cost_snapshot'] == '2.0000'
    assert line['unit_cost_snapshot'] == '2.0000'


def test_a_step_saved_as_a_bare_sentence_still_reads(
    client: TestClient,
    mk_auth_headers: dict[str, str],
    mk_org: Organization,
    db_session: Session,
) -> None:
    """A caller written before steps carried time keeps working.

    It reads back as a step with no duration, which is a formula nobody
    timed and costs no labour — not a rejected write.
    """
    output = _template(db_session, mk_org, 'Salve')
    recipe = client.post(
        '/api/v1/maker/recipes',
        headers=mk_auth_headers,
        json={
            'output_template_id': str(output.id),
            'name': 'Old salve',
            'process_steps': ['Melt', 'Pour'],
        },
    )
    assert recipe.status_code == 201, recipe.text
    body = client.get(
        f'/api/v1/maker/recipes/{recipe.json()["id"]}', headers=mk_auth_headers
    ).json()
    assert body['process_steps'] == [
        {'text': 'Melt', 'minutes': None},
        {'text': 'Pour', 'minutes': None},
    ]
    assert body['labour_cost'] == '0'


def test_a_step_stored_before_durations_still_reads(
    client: TestClient,
    mk_auth_headers: dict[str, str],
    mk_org: Organization,
    db_session: Session,
) -> None:
    """A formula saved before this branch opens instead of failing to read.

    The write path above normalises as it saves, so it cannot stand in for
    the rows already in a released database: those hold bare sentences and
    were never rewritten by that path. The row is written straight in the
    old shape, as a released install has it, and both the formula and the
    catalogue must read it.
    """
    output = _template(db_session, mk_org, 'Salve')
    recipe = client.post(
        '/api/v1/maker/recipes',
        headers=mk_auth_headers,
        json={
            'output_template_id': str(output.id),
            'name': 'Salve from before',
            'process_steps': [{'text': 'Melt', 'minutes': '15'}],
        },
    )
    assert recipe.status_code == 201, recipe.text
    recipe_id = recipe.json()['id']
    db_session.execute(
        update(MakerRecipe)
        .where(MakerRecipe.id == uuid.UUID(recipe_id))
        .values(process_steps=['Melt the wax', '', 'Pour'])
    )
    db_session.commit()

    detail = client.get(f'/api/v1/maker/recipes/{recipe_id}', headers=mk_auth_headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()['process_steps'] == [
        {'text': 'Melt the wax', 'minutes': None},
        {'text': 'Pour', 'minutes': None},
    ]

    catalogue = client.get('/api/v1/maker/recipes', headers=mk_auth_headers)
    assert catalogue.status_code == 200, catalogue.text
    assert recipe_id in [item['id'] for item in catalogue.json()['items']]


def test_the_preview_prices_the_labour_before_anything_is_saved(
    client: TestClient,
    mk_auth_headers: dict[str, str],
    mk_org: Organization,
    mk_input_loc: StorageLocation,
    mk_output_loc: StorageLocation,
    db_session: Session,
) -> None:
    output = _template(db_session, mk_org, 'Balm')
    ingredient = _template(db_session, mk_org, 'Butter')
    post_on_shelf(
        client,
        mk_auth_headers,
        ingredient,
        mk_input_loc.id,
        '10',
        purchase_price='1.00',
    )
    recipe_id = _recipe_with_steps(
        client, mk_auth_headers, db_session, mk_org, output, ingredient
    )
    client.patch(
        '/api/v1/maker/settings',
        headers=mk_auth_headers,
        json={'labor_hourly_rate': '30.00'},
    )

    preview = client.post(
        '/api/v1/maker/production/orders/preview',
        headers=mk_auth_headers,
        json={
            'output_template_id': str(output.id),
            'recipe_id': recipe_id,
            'planned_qty': '10',
            'output_location_id': str(mk_output_loc.id),
        },
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    # 2 kg at 1.00, 120 minutes at 30.00 an hour, over the batch's 10 units.
    assert body['labour_cost'] == '60.00'
    assert body['unit_cost'] == '6.2000'
