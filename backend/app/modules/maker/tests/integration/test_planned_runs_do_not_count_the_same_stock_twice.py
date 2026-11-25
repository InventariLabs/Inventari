"""Planned runs are measured one after another against the same shelf.

Each draft reads the availability left by the runs planned before it: two drafts
that each need six of ten flour are not both covered when together they need
twelve. A planned run counts what the runs planned before it need — by planned
day, then by creation — and the list shows each draft as covered, partly covered
or short. Completion's own verdict (``shortage_count``) judges the shelf as it is
when the run is closed.
"""

from datetime import date, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.modules.maker.tests.integration.test_a_run_opens_the_card_at_its_cost import (
    _recipe,
    _template,
)
from tests.integration._shelf import post_on_shelf

pytestmark = pytest.mark.integration


def _day() -> date:
    return date.today() + timedelta(days=30)


def _plan(
    client: TestClient,
    headers: dict[str, str],
    output_id: Any,
    out_loc: Any,
    qty: str,
    day: date | None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        'output_template_id': str(output_id),
        'planned_qty': qty,
        'output_location_id': str(out_loc),
        'confirm_shortage': True,
    }
    if day is not None:
        body['production_date'] = day.isoformat()
    created = client.post('/api/v1/maker/production/orders', headers=headers, json=body)
    assert created.status_code == 201, created.text
    order: dict[str, Any] = created.json()
    return order


def _by_id(client: TestClient, headers: dict[str, str]) -> dict[str, dict[str, Any]]:
    listed = client.get('/api/v1/maker/production/orders', headers=headers)
    assert listed.status_code == 200, listed.text
    return {row['id']: row for row in listed.json()['items']}


class TestPlannedRunsDoNotCountTheSameStockTwice:
    def _world(
        self,
        client: TestClient,
        headers: dict[str, str],
        org: Organization,
        in_loc: StorageLocation,
        db: Session,
        stock: str,
    ) -> Any:
        flour = _template(db, org, 'Flour')
        bread = _template(db, org, 'Bread')
        _recipe(db, org, output_id=bread.id, child_id=flour.id)
        post_on_shelf(client, headers, flour, in_loc.id, stock, purchase_price='1.00')
        return bread

    def test_the_second_run_reads_only_what_the_first_leaves(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_input_loc: StorageLocation,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        bread = self._world(
            client, mk_auth_headers, mk_org, mk_input_loc, db_session, '10'
        )
        first = _plan(client, mk_auth_headers, bread.id, mk_output_loc.id, '6', _day())
        second = _plan(
            client,
            mk_auth_headers,
            bread.id,
            mk_output_loc.id,
            '6',
            _day() + timedelta(days=1),
        )

        rows = _by_id(client, mk_auth_headers)

        assert rows[first['id']]['coverage'] == 'covered'
        assert rows[second['id']]['coverage'] == 'partial'
        # Ten on the shelf, six taken by the first: four are left for the
        # second, which needs six.
        item = rows[second['id']]['coverage_items'][0]
        assert float(item['available']) == 4.0
        assert float(item['shortage']) == 2.0
        # Completion judges the shelf as it is: each run alone fits in ten.
        assert rows[first['id']]['shortage_count'] == 0
        assert rows[second['id']]['shortage_count'] == 0

    def test_the_earlier_day_goes_first_whatever_was_planned_first(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_input_loc: StorageLocation,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        bread = self._world(
            client, mk_auth_headers, mk_org, mk_input_loc, db_session, '10'
        )
        later = _plan(
            client,
            mk_auth_headers,
            bread.id,
            mk_output_loc.id,
            '6',
            _day() + timedelta(days=5),
        )
        earlier = _plan(
            client, mk_auth_headers, bread.id, mk_output_loc.id, '6', _day()
        )

        rows = _by_id(client, mk_auth_headers)

        assert rows[earlier['id']]['coverage'] == 'covered'
        assert rows[later['id']]['coverage'] == 'partial'

    def test_the_same_day_goes_in_the_order_the_runs_were_made(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_input_loc: StorageLocation,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        bread = self._world(
            client, mk_auth_headers, mk_org, mk_input_loc, db_session, '10'
        )
        first = _plan(client, mk_auth_headers, bread.id, mk_output_loc.id, '6', _day())
        second = _plan(client, mk_auth_headers, bread.id, mk_output_loc.id, '6', _day())

        rows = _by_id(client, mk_auth_headers)

        assert rows[first['id']]['coverage'] == 'covered'
        assert rows[second['id']]['coverage'] == 'partial'

    def test_a_run_with_nothing_left_is_short(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_input_loc: StorageLocation,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        bread = self._world(
            client, mk_auth_headers, mk_org, mk_input_loc, db_session, '10'
        )
        _plan(client, mk_auth_headers, bread.id, mk_output_loc.id, '10', _day())
        starved = _plan(
            client,
            mk_auth_headers,
            bread.id,
            mk_output_loc.id,
            '3',
            _day() + timedelta(days=1),
        )

        rows = _by_id(client, mk_auth_headers)

        assert rows[starved['id']]['coverage'] == 'short'

    def test_a_run_past_the_draft_has_no_coverage(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_input_loc: StorageLocation,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        bread = self._world(
            client, mk_auth_headers, mk_org, mk_input_loc, db_session, '10'
        )
        made = _plan(client, mk_auth_headers, bread.id, mk_output_loc.id, '2', _day())
        done = client.post(
            f'/api/v1/maker/production/orders/{made["id"]}/complete',
            headers=mk_auth_headers,
        )
        assert done.status_code == 200, done.text

        rows = _by_id(client, mk_auth_headers)

        assert rows[made['id']]['coverage'] is None

    def test_moving_a_run_to_another_day_moves_it_in_the_queue(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_input_loc: StorageLocation,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        bread = self._world(
            client, mk_auth_headers, mk_org, mk_input_loc, db_session, '10'
        )
        first = _plan(client, mk_auth_headers, bread.id, mk_output_loc.id, '6', _day())
        second = _plan(
            client,
            mk_auth_headers,
            bread.id,
            mk_output_loc.id,
            '6',
            _day() + timedelta(days=1),
        )

        moved = client.patch(
            f'/api/v1/maker/production/orders/{second["id"]}',
            headers=mk_auth_headers,
            json={'production_date': (_day() - timedelta(days=1)).isoformat()},
        )
        assert moved.status_code == 200, moved.text
        rows = _by_id(client, mk_auth_headers)

        assert rows[second['id']]['coverage'] == 'covered'
        assert rows[first['id']]['coverage'] == 'partial'

    def test_the_list_filters_runs_by_their_planned_day_not_when_they_were_made(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_input_loc: StorageLocation,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        # Runs are made today and planned weeks ahead: the plan screen asks
        # for a period of planned days, and the creation date has nothing to
        # say about it.
        bread = self._world(
            client, mk_auth_headers, mk_org, mk_input_loc, db_session, '10'
        )
        inside = _plan(client, mk_auth_headers, bread.id, mk_output_loc.id, '1', _day())
        _plan(
            client,
            mk_auth_headers,
            bread.id,
            mk_output_loc.id,
            '1',
            _day() + timedelta(days=20),
        )
        _plan(client, mk_auth_headers, bread.id, mk_output_loc.id, '1', None)

        listed = client.get(
            '/api/v1/maker/production/orders',
            headers=mk_auth_headers,
            params={
                'planned_from': _day().isoformat(),
                'planned_to': (_day() + timedelta(days=6)).isoformat(),
            },
        )

        assert listed.status_code == 200, listed.text
        assert [row['id'] for row in listed.json()['items']] == [inside['id']]
