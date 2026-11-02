"""The stock-value figure travels with the reason it is short.

The overview screen showed "$0.00 -- approximate total value across all
items" over sixty priced products. The domain layer had it right: prices in
a currency that is not the organization's are dropped, because two
currencies do not add, and it returned the count of what it dropped beside
the figure. The front end already had the warning text, in five languages.

The number never reached the browser. ``OverviewStats`` -- the endpoint's
response model -- declared neither ``excluded_other_currency_count`` nor
``value_source``, so Pydantic cut both off on the way out. Nothing caught
it: the browser's type for this response is hand-written and marks both
fields optional, so the contract gate had nothing to compare.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.models.item import Item
from app.services.token_service import create_access_token

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _auth(user) -> dict:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


@pytest.fixture
async def priced_in_another_currency(
    real_async_db_session,
    async_test_household,
    async_test_user,
    async_test_storage_location,
):
    """Two products on the shelf, both priced in money the organization does not keep."""
    async_test_household.currency = 'USD'
    for name in ('Imported flour', 'Imported sugar'):
        real_async_db_session.add(
            Item(
                organization_id=async_test_household.id,
                storage_location_id=async_test_storage_location.id,
                name=name,
                quantity=Decimal('2'),
                purchase_price=Decimal('10.00'),
                currency='PLN',
            )
        )
    await real_async_db_session.commit()
    return async_test_user


class TestTheOverviewSaysWhatItLeftOut:
    async def test_the_count_of_uncounted_records_reaches_the_caller(
        self, real_async_client, priced_in_another_currency
    ):
        response = await real_async_client.get(
            '/api/v1/stats/overview', headers=_auth(priced_in_another_currency)
        )

        assert response.status_code == 200
        body = response.json()
        assert body['total_value'] == 0.0
        assert body['excluded_other_currency_count'] == 2

    async def test_the_figure_names_where_it_came_from(
        self, real_async_client, priced_in_another_currency
    ):
        """A number whose source cannot be named is a number nobody can check."""
        response = await real_async_client.get(
            '/api/v1/stats/overview', headers=_auth(priced_in_another_currency)
        )

        assert response.json()['value_source'] in ('purchase_price', 'valuation_layers')
