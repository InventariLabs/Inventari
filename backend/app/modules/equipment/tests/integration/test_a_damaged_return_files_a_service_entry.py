"""A return that puts the asset into service files the reason with it.

"Good" and "Needs Repair" are two different acts -- one returns the asset to
the pool, the other opens the workshop door -- and the application already
knows that: the damaged return moves the asset into MAINTENANCE and hides the
check-out button. What it did not do was write the reason anywhere the card
could show it. The Maintenance tab answered "No maintenance records" for the
very asset it was displaying in service, so "why is this laptop in service"
had to be dug out of the release history while the tab built to answer exactly
that question stayed empty.

The return itself now opens the service case: one click enters the state, and
the record explaining it is written in the same transaction.
"""

from __future__ import annotations

from datetime import date
from typing import cast
from unittest.mock import AsyncMock, patch

import pytest
from starlette.testclient import TestClient

from app.models.item import Item

ASSIGNMENTS_URL = '/api/v1/equipment/assignments'
MAINTENANCE_ITEM_URL = '/api/v1/equipment/maintenance/item'


def _check_out_and_in(
    client: TestClient,
    headers: dict[str, str],
    item: Item,
    *,
    condition: str,
    notes: str | None = None,
) -> None:
    checkout = client.post(
        ASSIGNMENTS_URL,
        headers=headers,
        json={'item_id': str(item.id), 'assigned_to_name': 'Anna Nowak'},
    )
    assert checkout.status_code == 201, checkout.text

    checkin = client.post(
        f'{ASSIGNMENTS_URL}/{checkout.json()["id"]}/checkin',
        headers=headers,
        json={'checkin_condition': condition, 'checkin_notes': notes},
    )
    assert checkin.status_code == 200, checkin.text


def _service_entries(
    client: TestClient, headers: dict[str, str], item: Item
) -> list[dict[str, object]]:
    response = client.get(f'{MAINTENANCE_ITEM_URL}/{item.id}', headers=headers)
    assert response.status_code == 200, response.text
    return cast(list[dict[str, object]], response.json()['items'])


@pytest.mark.integration
class TestADamagedReturnFilesAServiceEntry:
    def test_the_case_uses_the_organizations_day(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
    ) -> None:
        org_day = date(2030, 1, 2)
        with patch(
            'app.core.public_api.core_api.organizations.today_async',
            new=AsyncMock(return_value=org_day),
        ):
            _check_out_and_in(client, eq_auth_headers, eq_item, condition='DAMAGED')

        (entry,) = _service_entries(client, eq_auth_headers, eq_item)
        assert entry['performed_at'] == org_day.isoformat()

    def test_a_needs_repair_return_opens_the_service_case(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
    ) -> None:
        _check_out_and_in(
            client,
            eq_auth_headers,
            eq_item,
            condition='NEEDS_REPAIR',
            notes='Keyboard dead on the left half',
        )

        (entry,) = _service_entries(client, eq_auth_headers, eq_item)
        assert entry['maintenance_type'] == 'REPAIR'
        assert entry['title'] == 'Returned — needs repair'
        # The notes the return carried are the only account of what is wrong,
        # and the card must not send the reader back to the assignment for it.
        assert entry['description'] == 'Keyboard dead on the left half'
        assert entry['performed_at'] == str(date.today())

    def test_a_damaged_return_also_opens_the_service_case(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
    ) -> None:
        _check_out_and_in(client, eq_auth_headers, eq_item, condition='DAMAGED')

        (entry,) = _service_entries(client, eq_auth_headers, eq_item)
        assert entry['maintenance_type'] == 'REPAIR'
        assert entry['title'] == 'Returned damaged'

    def test_a_good_return_files_no_service_case(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
    ) -> None:
        """The pool is not a workshop: an untouched asset gets no case."""
        _check_out_and_in(client, eq_auth_headers, eq_item, condition='GOOD')

        assert _service_entries(client, eq_auth_headers, eq_item) == []

    def test_the_case_is_written_in_the_language_of_the_return(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
    ) -> None:
        """The row keeps the language it was born in -- read months later."""
        _check_out_and_in(
            client,
            {**eq_auth_headers, 'Accept-Language': 'pl'},
            eq_item,
            condition='NEEDS_REPAIR',
        )

        (entry,) = _service_entries(client, eq_auth_headers, eq_item)
        assert entry['title'] == 'Zwrócony — wymaga naprawy'

    def test_a_portuguese_return_is_filed_in_portuguese(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
    ) -> None:
        """The dialog promises this wording, so the row cannot fall back to English."""
        _check_out_and_in(
            client,
            {**eq_auth_headers, 'Accept-Language': 'pt'},
            eq_item,
            condition='DAMAGED',
        )

        (entry,) = _service_entries(client, eq_auth_headers, eq_item)
        assert entry['title'] == 'Devolvido danificado'
