"""The warehouse settings offer the registered pick orders, by name.

The picking order is chosen per organization in the warehouse settings, the
way the removal strategy is chosen per product. The screen offers what the
registry holds — the default, and every strategy a module registered — under
the label each owning module's catalogue gives it, and the choice is saved on
the organization's warehouse profile.
"""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.modules.warehouse.warehouse_api import warehouse_api

_MODULE = 'walk_planner'
_BY_CODE = 'by_code'
_DEFAULT = 'location_sequence'


async def _by_code(db: Any, org_id: UUID, lines: list[Any]) -> list[Any]:
    return sorted(lines, key=lambda line: line.product_name or '')


@pytest.fixture
def registered_orders(db_session: Session, doc_org: Organization) -> None:
    doc_org.enabled_modules = [*doc_org.enabled_modules, _MODULE]
    db_session.commit()
    warehouse_api.register_pick_order_strategy(_MODULE, _BY_CODE, _by_code)


@pytest.mark.integration
class TestTheWarehouseSettingsChooseThePickOrder:
    def test_the_settings_offer_the_registered_strategies_with_catalogue_labels(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        registered_orders: None,
    ) -> None:
        listed = client.get(
            '/api/v1/warehouse/profile/pick-order-strategies',
            headers=doc_auth_headers,
        )
        assert listed.status_code == status.HTTP_200_OK, listed.text
        entries = {cast(str, entry['name']): entry for entry in listed.json()}

        # The default is registered the same way, and says so.
        default = entries[_DEFAULT]
        assert default['module'] == 'warehouse'
        assert default['is_default'] is True
        assert default['label_key'] == f'warehouse:pickOrderStrategies.{_DEFAULT}'

        # A module's entry is offered under the label its own catalogue
        # carries: the key is what the screen reads, never the bare name.
        chosen = entries[_BY_CODE]
        assert chosen['module'] == _MODULE
        assert chosen['is_default'] is False
        assert chosen['label_key'] == f'{_MODULE}:pickOrderStrategies.{_BY_CODE}'

    def test_the_choice_is_saved_on_the_warehouse_profile(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        registered_orders: None,
    ) -> None:
        saved = client.put(
            '/api/v1/warehouse/profile',
            headers=doc_auth_headers,
            json={'pick_order_strategy': _BY_CODE},
        )
        assert saved.status_code == status.HTTP_200_OK, saved.text
        assert saved.json()['pick_order_strategy'] == _BY_CODE

        reread = client.get('/api/v1/warehouse/profile', headers=doc_auth_headers)
        assert reread.status_code == status.HTTP_200_OK, reread.text
        assert reread.json()['pick_order_strategy'] == _BY_CODE

        cleared = client.put(
            '/api/v1/warehouse/profile',
            headers=doc_auth_headers,
            json={'pick_order_strategy': None},
        )
        assert cleared.status_code == status.HTTP_200_OK, cleared.text
        assert cleared.json()['pick_order_strategy'] is None
