"""The audit trail of a production run.

A closed run moved fifteen thousand dollars of stock and the organization
log answered with four anonymous "10.0 -> 6.0" rows plus a cancelled draft
— the only maker entry in the whole log was the cancel. The stock_moves
ledger always knew (``reference_type='maker_production'``); the log and the
item history never repeated it.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from tests.integration._shelf import post_on_shelf

from .test_role_guards import _template

pytestmark = pytest.mark.integration


def _seed_run(
    db: Session,
    client: TestClient,
    org: Organization,
    headers: dict[str, str],
    input_loc: StorageLocation,
    output_loc: StorageLocation,
    *,
    ingredient_qty: str = '10.000',
) -> dict[str, Any]:
    """Formula + the ingredient's record on the shelf, which the run will take off.

    Returns ``{'order_id', 'ingredient_template_id', 'ingredient_item_id'}``.
    """
    ingredient = _template(db, org, name='Soy wax')
    output = _template(db, org, name='Candle')

    create_resp = client.post(
        '/api/v1/maker/recipes',
        headers=headers,
        json={
            'output_template_id': str(output.id),
            'name': 'Candle formula',
            'batch_yield_qty': '1',
            'is_default': True,
        },
    )
    assert create_resp.status_code == 201, create_resp.text
    recipe_id = create_resp.json()['id']

    line_resp = client.post(
        f'/api/v1/maker/recipes/{recipe_id}/bom-lines',
        headers=headers,
        json={
            'child_template_id': str(ingredient.id),
            'qty_per_batch': '0.2',
            'unit': 'kg',
        },
    )
    assert line_resp.status_code == 201, line_resp.text

    record = post_on_shelf(client, headers, ingredient, input_loc.id, ingredient_qty)

    order_resp = client.post(
        '/api/v1/maker/production/orders',
        headers=headers,
        json={
            'output_template_id': str(output.id),
            'planned_qty': '1.000',
            'output_location_id': str(output_loc.id),
        },
    )
    assert order_resp.status_code == 201, order_resp.text

    return {
        'order_id': str(order_resp.json()['id']),
        'ingredient_template_id': str(ingredient.id),
        'ingredient_item_id': record['id'],
        'output_template_id': str(output.id),
    }


def _log_entries(
    client: TestClient,
    headers: dict[str, str],
    **params: str,
) -> list[dict[str, Any]]:
    resp = client.get(
        '/api/v1/audit-log',
        headers=headers,
        params={**params, 'limit': 500},
    )
    assert resp.status_code == 200, resp.text
    items: list[dict[str, Any]] = resp.json()['items']
    return items


class TestProductionRunAuditTrail:
    def test_closing_a_run_names_the_event_and_its_reasons(
        self,
        client: TestClient,
        mk_org: Organization,
        mk_auth_headers: dict[str, str],
        mk_input_loc: StorageLocation,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        run = _seed_run(
            db_session, client, mk_org, mk_auth_headers, mk_input_loc, mk_output_loc
        )

        complete_resp = client.post(
            f'/api/v1/maker/production/orders/{run["order_id"]}/complete',
            headers=mk_auth_headers,
        )
        assert complete_resp.status_code == 200, complete_resp.text
        number = complete_resp.json()['number']

        # The event: the log names the run, what it made and how much.
        order_events = _log_entries(
            client, mk_auth_headers, target_type='maker_production_order'
        )
        actions = {e['action'] for e in order_events}
        assert 'CREATE' in actions, f'no CREATE entry: {order_events}'
        completed = [
            e
            for e in order_events
            if e['action'] == 'UPDATE'
            and (e.get('snapshot') or {}).get('new_status') == 'COMPLETED'
        ]
        assert completed, f'no COMPLETED entry: {order_events}'
        snapshot = completed[0]['snapshot']
        assert snapshot['name'] == number
        assert snapshot['output'] == 'Candle'
        # Exact digits as text, never a float: the screen rounds a float to six figures.
        assert isinstance(snapshot['quantity'], str)
        assert Decimal(snapshot['quantity']) > 0
        assert isinstance(snapshot['total_cost'], str)

        # The consequences: every mirrored quantity change says what took it.
        qty_changes = [
            e
            for e in _log_entries(client, mk_auth_headers)
            if e['action'] == 'QUANTITY_CHANGE'
        ]
        assert qty_changes, 'production wrote no quantity changes'
        for entry in qty_changes:
            assert entry['reason'] == 'production_run', entry
            # The code carries no number; two runs on one day must still be
            # told apart on the screens.
            assert (entry.get('meta_data') or {}).get(
                'production_order_number'
            ) == number, entry
            assert (entry.get('meta_data') or {}).get('production_order_id') == run[
                'order_id'
            ], entry

    def test_item_history_carries_the_reason(
        self,
        client: TestClient,
        mk_org: Organization,
        mk_auth_headers: dict[str, str],
        mk_input_loc: StorageLocation,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        """The item's own history says "production run", not just old/new."""
        run = _seed_run(
            db_session, client, mk_org, mk_auth_headers, mk_input_loc, mk_output_loc
        )
        complete_resp = client.post(
            f'/api/v1/maker/production/orders/{run["order_id"]}/complete',
            headers=mk_auth_headers,
        )
        assert complete_resp.status_code == 200, complete_resp.text

        history = client.get(
            f'/api/v1/items/{run["ingredient_item_id"]}/history',
            headers=mk_auth_headers,
        )
        assert history.status_code == 200, history.text
        rows = history.json()
        assert rows, 'no history rows for the consumed item'
        blob = str(rows)
        assert 'production_run' in blob, blob[:400]
        assert complete_resp.json()['number'] in blob, blob[:400]

    def test_taking_a_run_back_writes_a_code_the_screens_can_translate(
        self,
        client: TestClient,
        mk_org: Organization,
        mk_auth_headers: dict[str, str],
        mk_input_loc: StorageLocation,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        """The reason is a code, not a sentence in one language.

        An English "Production run … taken back" read in a Polish journal; the
        screens resolve the code through the interface language instead.
        """
        run = _seed_run(
            db_session, client, mk_org, mk_auth_headers, mk_input_loc, mk_output_loc
        )
        base = f'/api/v1/maker/production/orders/{run["order_id"]}'
        assert (
            client.post(f'{base}/complete', headers=mk_auth_headers).status_code == 200
        )
        reversed_resp = client.post(f'{base}/reverse', headers=mk_auth_headers)
        assert reversed_resp.status_code == 200, reversed_resp.text

        reasons = {
            entry['reason']
            for entry in _log_entries(client, mk_auth_headers)
            if entry['action'] == 'QUANTITY_CHANGE'
        }
        assert reasons == {'production_run', 'production_run_reversed'}
