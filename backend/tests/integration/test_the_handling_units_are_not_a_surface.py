"""The handling units are gone as a surface, not only from the navigation.

A pallet, a box, a cage: ``StockPackage`` modelled them and every quant
could name one (the quant table has since gone too), but nothing in the
product could create one. The screens
that listed them went first, and the endpoint that served them goes with
the model — a route that answers, or a table that exists, for a dimension
nothing produces is a surface nobody asked for, and the next reader has to
check it before deciding it is unused.

So all three are pinned here: no route, no table, no column.
"""

from __future__ import annotations

import pytest
from fastapi import status

from app.database import Base
from app.services.token_service import create_access_token

pytestmark = pytest.mark.integration


def _auth(user) -> dict[str, str]:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


async def test_the_handling_units_route_is_not_mounted(
    real_async_client, async_test_user
) -> None:
    response = await real_async_client.get(
        '/api/v1/stock-packages', headers=_auth(async_test_user)
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_the_handling_units_table_is_not_in_the_metadata() -> None:
    assert 'stock_packages' not in Base.metadata.tables


def test_no_table_has_a_package_column() -> None:
    carrying = sorted(
        table.name
        for table in Base.metadata.tables.values()
        if 'package_id' in table.columns
    )
    assert carrying == []
