"""An assignment row says which unit, not just which model.

A fleet of sixty machines is ten models. The dashboard listed assignments by
``item_name`` alone, so four rows read "PowerEdge R650" and six read
"OptiPlex 7010", identical to the character — and the person sent to collect
one of them had no way to tell which. Every unit carries a serial or an asset
tag, and the asset list has shown them in one column all along; the
assignment payload simply never carried them.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.item import Item


def _checkout(client: TestClient, headers: dict[str, str], item_id: str) -> str:
    resp = client.post(
        '/api/v1/equipment/assignments',
        headers=headers,
        json={'item_id': item_id, 'assigned_to_name': 'Alice'},
    )
    resp.raise_for_status()
    return str(resp.json()['id'])


@pytest.mark.integration
class TestAssignmentCarriesTheUnitIdentity:
    def test_active_list_sends_the_serial_from_the_core_column(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        eq_item.serial_number = 'SN-CORE-9'
        db_session.commit()
        _checkout(client, eq_auth_headers, str(eq_item.id))

        resp = client.get('/api/v1/equipment/assignments', headers=eq_auth_headers)
        assert resp.status_code == 200, resp.text
        row = resp.json()['items'][0]
        assert row['item_serial'] == 'SN-CORE-9'
        assert row['item_asset_tag'] is None

    def test_a_row_written_before_the_column_existed_still_names_its_unit(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
    ) -> None:
        """``eq_item`` carries its number in the module namespace only."""
        _checkout(client, eq_auth_headers, str(eq_item.id))

        resp = client.get('/api/v1/equipment/assignments', headers=eq_auth_headers)
        row = resp.json()['items'][0]
        assert row['item_serial'] == 'SN-001'

    def test_the_asset_tag_answers_when_there_is_no_serial(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        eq_item.meta_data = {
            'equipment': {'asset_tag': 'TAG-42', 'equipment_status': 'AVAILABLE'}
        }
        db_session.commit()
        _checkout(client, eq_auth_headers, str(eq_item.id))

        resp = client.get('/api/v1/equipment/assignments', headers=eq_auth_headers)
        row = resp.json()['items'][0]
        assert row['item_serial'] is None
        assert row['item_asset_tag'] == 'TAG-42'

    def test_the_overdue_list_names_the_unit_too(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        from app.modules.equipment.models import EquipmentAssignment

        eq_item.serial_number = 'SN-LATE-3'
        db_session.commit()
        assignment_id = _checkout(client, eq_auth_headers, str(eq_item.id))

        assignment = (
            db_session.query(EquipmentAssignment)
            .filter(EquipmentAssignment.id == assignment_id)
            .one()
        )
        assignment.expected_return_at = datetime.now(UTC) - timedelta(days=7)
        db_session.commit()

        resp = client.get(
            '/api/v1/equipment/assignments/overdue', headers=eq_auth_headers
        )
        assert resp.status_code == 200, resp.text
        row = resp.json()['items'][0]
        assert row['item_serial'] == 'SN-LATE-3'
