"""A cost layer refuses a figure its columns cannot keep, by name.

``stock_valuation_layers.unit_cost`` is ``numeric(12, 4)`` and ``total_value``
``numeric(14, 2)``. A receipt of a thousand million units at a price inside its
own range multiplies out past the value column, and a cost that arrives after
the goods were received can outgrow the per-unit column over a tiny remainder.
Both reached the driver and ended in a server error after the stock had moved;
the writer now refuses them with the product and the bound named.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.contracts import UserContextDTO
from app.core.exceptions import ServiceRejectionError
from app.core.public_api import core_api
from app.core.testing import ModuleTestHelper
from app.models.item import Item
from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.models.user import User
from tests.integration._shelf import run_in_async_session

pytestmark = pytest.mark.integration

ITEMS_URL = '/api/v1/items'


def test_a_receipt_value_past_the_layer_column_is_refused(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
    test_household: Organization,
    test_storage_location: StorageLocation,
) -> None:
    """A quantity and a price each inside their own range multiply out of it."""
    card = ModuleTestHelper(db_session).create_template(
        test_household, name='A Thousand Million'
    )

    response = client.post(
        ITEMS_URL,
        headers=auth_headers,
        json={
            'name': card.name,
            'template_id': str(card.id),
            'location_id': str(test_storage_location.id),
            'quantity': '999999999',
            'purchase_price': '99999999.99',
        },
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.text
    detail = response.json()['detail']
    assert detail['code'] == 'STOCK_LAYER_VALUE_ABOVE_CEILING'
    assert '999999999999.99' in detail['message'], detail['message']
    assert card.name in detail['message'], detail['message']
    db_session.expire_all()
    assert db_session.scalars(select(Item)).first() is None


def test_a_cost_added_after_posting_past_the_layer_column_is_refused(
    db_session: Session,
    async_engine_fixture: Any,
    test_household: Organization,
    test_user: User,
) -> None:
    """A later cost over a tiny remainder outgrows the per-unit column.

    The cost-variance door: a run whose cost is known only after its goods
    reached the shelf puts the rest of the value on the layer it opened. A
    thousand over a thousandth of a unit is a million per unit, and the column
    keeps tens of millions — the refusal names the bound instead of the
    driver's overflow.
    """
    card = ModuleTestHelper(db_session).create_template(
        test_household, name='A Thousandth of a Unit'
    )
    db_session.commit()
    org_id = test_household.id
    user = UserContextDTO(id=test_user.id, organization_id=org_id)

    async def _work(session: Any) -> str:
        layer_id = await core_api.valuation.record_receipt_async(
            session, org_id, card.id, Decimal('0.001'), Decimal('1')
        )
        assert layer_id is not None
        with pytest.raises(ServiceRejectionError) as refused:
            await core_api.valuation.add_value_to_layer_async(
                session, org_id, UUID(str(layer_id)), Decimal('1000000'), user=user
            )
        return refused.value.key

    assert (
        run_in_async_session(async_engine_fixture, _work)
        == 'stock_layer_unit_cost_above_ceiling'
    )


def test_a_cost_added_after_posting_past_the_layer_value_is_refused(
    db_session: Session,
    async_engine_fixture: Any,
    test_household: Organization,
    test_user: User,
) -> None:
    """A later cost that fits the per-unit column can still outgrow the value."""
    card = ModuleTestHelper(db_session).create_template(
        test_household, name='A Million Units One Zloty Each'
    )
    db_session.commit()
    org_id = test_household.id
    user = UserContextDTO(id=test_user.id, organization_id=org_id)

    async def _work(session: Any) -> str:
        layer_id = await core_api.valuation.record_receipt_async(
            session, org_id, card.id, Decimal('1000000'), Decimal('1')
        )
        assert layer_id is not None
        with pytest.raises(ServiceRejectionError) as refused:
            await core_api.valuation.add_value_to_layer_async(
                session,
                org_id,
                UUID(str(layer_id)),
                Decimal('999999000000'),
                user=user,
            )
        return refused.value.key

    assert (
        run_in_async_session(async_engine_fixture, _work)
        == 'stock_layer_value_above_ceiling'
    )
