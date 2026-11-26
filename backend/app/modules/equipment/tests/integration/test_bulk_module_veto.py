"""A module's veto is one asset's refusal in the equipment bulk loops.

An item interceptor that refuses a create or an update is answered for that
asset, with its sentence and code, and the other assets go through.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.context import ModuleContext
from app.core.interceptors import (
    InterceptorError,
    ItemInterceptor,
    interceptor_pipeline,
)
from app.models.category import Category
from app.models.item import Item
from app.models.storage_location import StorageLocation

SENTENCE = 'This asset is frozen by an audit'
CODE = 'ASSET_FROZEN'


class _Veto(ItemInterceptor):
    """Refuses the create of one serial and any update of one item."""

    priority = 1

    def __init__(self, serial: str = '', item_id: uuid.UUID | None = None) -> None:
        self._serial = serial
        self._item_id = item_id

    async def before_create(
        self, data: dict[str, Any], context: ModuleContext
    ) -> dict[str, Any]:
        if self._serial and data.get('serial_number') == self._serial:
            raise InterceptorError(SENTENCE, error_code=CODE)
        return data

    async def before_update(
        self, item_id: uuid.UUID, changes: dict[str, Any], context: ModuleContext
    ) -> dict[str, Any]:
        if item_id == self._item_id:
            raise InterceptorError(SENTENCE, error_code=CODE)
        return changes


@pytest.fixture
def veto() -> Iterator[Any]:
    registered: list[_Veto] = []

    def _register(**kwargs: Any) -> None:
        interceptor = _Veto(**kwargs)
        interceptor_pipeline.register_item_interceptor(interceptor)
        registered.append(interceptor)

    yield _register
    for interceptor in registered:
        interceptor_pipeline.unregister_item_interceptor(interceptor)


@pytest.mark.integration
class TestAVetoIsOneAsset:
    def test_bulk_create_makes_the_other_assets(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_storage_location: StorageLocation,
        eq_category: Category,
        db_session: Session,
        veto: Any,
    ) -> None:
        veto(serial='SN-VETO-2')

        response = client.post(
            '/api/v1/equipment/items/bulk',
            headers=eq_auth_headers,
            json={
                'name': 'Dell Latitude 5540',
                'location_id': str(eq_storage_location.id),
                'category_id': str(eq_category.id),
                'entries': [
                    {'serial_number': 'SN-VETO-1'},
                    {'serial_number': 'SN-VETO-2'},
                    {'serial_number': 'SN-VETO-3'},
                ],
            },
        )

        assert response.status_code == status.HTTP_201_CREATED, response.text
        data = response.json()
        assert data['created'] == 2
        assert data['errors'] == [
            {'index': 1, 'serial_number': 'SN-VETO-2', 'error': SENTENCE, 'code': CODE}
        ]
        names = db_session.scalars(
            select(Item).where(Item.name == 'Dell Latitude 5540')
        ).all()
        assert len(names) == 2

    def test_bulk_edit_moves_the_other_assets(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        eq_storage_location: StorageLocation,
        db_session: Session,
        veto: Any,
    ) -> None:
        other = Item(
            name='ThinkPad T14',
            organization_id=eq_item.organization_id,
            storage_location_id=eq_storage_location.id,
            category_id=eq_item.category_id,
            quantity=1,
            meta_data={'equipment': {'equipment_status': 'AVAILABLE'}},
        )
        target = StorageLocation(
            name='Shelf B',
            organization_id=eq_item.organization_id,
            created_by=eq_storage_location.created_by,
        )
        db_session.add_all([other, target])
        db_session.commit()
        frozen_id, other_id, target_id = eq_item.id, other.id, target.id
        veto(item_id=frozen_id)

        response = client.patch(
            '/api/v1/equipment/assets/bulk',
            headers=eq_auth_headers,
            json={
                'item_ids': [str(frozen_id), str(other_id)],
                'action': 'change_location',
                'data': {'location_id': str(target_id)},
            },
        )

        assert response.status_code == status.HTTP_200_OK, response.text
        data = response.json()
        assert data['updated'] == 1
        assert data['errors'] == [
            {'item_id': str(frozen_id), 'error': SENTENCE, 'code': CODE}
        ]
        db_session.expire_all()
        moved = db_session.get(Item, other_id)
        assert moved is not None
        assert moved.storage_location_id == target_id
