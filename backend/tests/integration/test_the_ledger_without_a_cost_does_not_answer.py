"""A ledger holding only unknown layers is a quantity, not a valuation.

The archived ``openbal01`` migration opened every shelf the register did not know with
a cost layer valued at the organization's own rate — and at 0.00 marked
``unknown`` where there was none (:class:`CostBasis`). Stock that a person
typed onto a record with its own price landed on the books as an unknown
layer, and the screens that choose between the ledger and the records read
the 0.00 as a valuation: the value tile, the list footer and the stock-as-of
report all answered "0.00, from the cost ledger" over a shelf whose records
carried the price the organization had typed.

The rule is the one every other reader of these layers already applies
(``StockValuationLayer.carries_a_cost``): an unknown layer's quantity is
real and its figure is not a cost. An organization whose ledger holds no
cost at all has nothing to say from it, and the records answer as they did
before the ledger existed. One layer carrying a cost puts the ledger back
in charge — for all three screens at once, because they ask one question
in ``org_uses_valuation_layers_async``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.public_api import core_api
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.stock_move import StockMove
from app.models.stock_valuation_layer import CostBasis, StockValuationLayer
from app.models.user import User
from app.services.token_service import create_access_token
from tests.integration._shelf import put_on_shelf, shelf_keeper

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_NOW = datetime(2026, 6, 30, 12, 0, tzinfo=UTC)
_A_DAY_AGO = _NOW - timedelta(days=1)
_TWO_DAYS_AGO = _NOW - timedelta(days=2)


def _auth(user: User) -> dict[str, str]:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


class _StockedWarehouse:
    def __init__(self) -> None:
        self.org: Organization
        self.user: User
        self.location_id: object
        self.priced: ProductTemplate
        self.unpriced: ProductTemplate


async def _backdate_async(
    db: AsyncSession, template_id: object, when: datetime
) -> None:
    """Date what the ledger wrote today to the day this test asks about."""
    for move in await db.scalars(
        select(StockMove).where(StockMove.product_template_id == template_id)
    ):
        move.completed_at = when
    for layer in await db.scalars(
        select(StockValuationLayer).where(
            StockValuationLayer.product_template_id == template_id
        )
    ):
        layer.created_at = when
    await db.flush()


async def _mark_layers_costless_async(db: AsyncSession, template_id: object) -> None:
    """Give the card's layers the shape the opening-balance migration writes."""
    layers = (
        await db.scalars(
            select(StockValuationLayer).where(
                StockValuationLayer.product_template_id == template_id,
                StockValuationLayer.direction == 'IN',
            )
        )
    ).all()
    assert layers, 'the bridge was supposed to post a layer'
    for layer in layers:
        layer.cost_basis = CostBasis.UNKNOWN
        layer.unit_cost = Decimal('0')
        layer.total_value = Decimal('0')
    await db.flush()


@pytest.fixture
async def records_only_ledger(
    real_async_db_session: AsyncSession,
    async_test_household: Organization,
    async_test_user: User,
    async_test_storage_location,
) -> _StockedWarehouse:
    """Records carrying prices, and a ledger holding nothing but 0.00 unknowns."""
    db = real_async_db_session
    fixture = _StockedWarehouse()
    fixture.org = async_test_household
    fixture.user = async_test_user
    fixture.location_id = async_test_storage_location.id
    keeper = await shelf_keeper(db, fixture.org.id)

    fixture.priced = ProductTemplate(organization_id=fixture.org.id, name='Priced rice')
    fixture.unpriced = ProductTemplate(
        organization_id=fixture.org.id, name='Unpriced salt'
    )
    db.add_all([fixture.priced, fixture.unpriced])
    await db.flush()
    await put_on_shelf(
        db,
        keeper,
        fixture.priced,
        fixture.location_id,
        10,
        purchase_price=Decimal('3.00'),
    )
    await put_on_shelf(db, keeper, fixture.unpriced, fixture.location_id, 5)
    await _backdate_async(db, fixture.priced.id, _NOW)
    await _backdate_async(db, fixture.unpriced.id, _NOW)
    await _mark_layers_costless_async(db, fixture.priced.id)
    await _mark_layers_costless_async(db, fixture.unpriced.id)
    await db.commit()
    return fixture


async def _overview(client: AsyncClient, user: User) -> dict:
    response = await client.get('/api/v1/stats/overview', headers=_auth(user))
    assert response.status_code == 200, response.text
    return response.json()


async def _footer(client: AsyncClient, user: User) -> dict:
    response = await client.get('/api/v1/items/aggregates', headers=_auth(user))
    assert response.status_code == 200, response.text
    return response.json()


async def _as_of(client: AsyncClient, user: User, *params: tuple[str, str]) -> dict:
    response = await client.get(
        '/api/v1/stock-as-of', params=dict(params), headers=_auth(user)
    )
    assert response.status_code == 200, response.text
    return response.json()


class TestACostlessLedgerDoesNotAnswer:
    async def test_the_tile_lets_the_records_answer(
        self, real_async_client: AsyncClient, records_only_ledger: _StockedWarehouse
    ) -> None:
        overview = await _overview(real_async_client, records_only_ledger.user)

        # The records carry 10 x 3.00; the ledger holds nothing but 0.00.
        assert overview['value_source'] == 'purchase_price'
        assert overview['total_value'] == pytest.approx(30.0)
        assert overview['value_scope'] == 'locations'

    async def test_the_footer_and_the_tile_name_one_source(
        self, real_async_client: AsyncClient, records_only_ledger: _StockedWarehouse
    ) -> None:
        footer = await _footer(real_async_client, records_only_ledger.user)
        overview = await _overview(real_async_client, records_only_ledger.user)

        assert footer['value_source'] == overview['value_source'] == 'purchase_price'
        assert footer['total_value'] == pytest.approx(overview['total_value'])
        assert footer['total_value'] == pytest.approx(30.0)
        # The record nobody priced is left out of the sum and said so.
        assert footer['unpriced_count'] == 1

    async def test_the_as_of_report_states_no_ledger_value(
        self, real_async_client: AsyncClient, records_only_ledger: _StockedWarehouse
    ) -> None:
        report = await _as_of(
            real_async_client, records_only_ledger.user, ('as_of', _NOW.isoformat())
        )

        # The report replays the ledger only; with no cost in it there is no
        # figure to state, and 0.00 dressed as one is the defect.
        assert report['value_source'] is None
        assert report['total_value'] is None
        assert report['items'], 'the shelf is not empty, only unvalued'
        assert all(row['value'] is None for row in report['items'])


class TestOneRealCostPutsTheLedgerBackInCharge:
    async def test_all_three_screens_read_the_ledger_again(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        records_only_ledger: _StockedWarehouse,
    ) -> None:
        db = real_async_db_session
        fixture = records_only_ledger
        priced = ProductTemplate(organization_id=fixture.org.id, name='Priced cocoa')
        db.add(priced)
        await db.flush()
        keeper = await shelf_keeper(db, fixture.org.id)
        await put_on_shelf(
            db, keeper, priced, fixture.location_id, 10, purchase_price=Decimal('2.00')
        )
        await _backdate_async(db, priced.id, _NOW)
        await db.commit()

        overview = await _overview(real_async_client, fixture.user)
        footer = await _footer(real_async_client, fixture.user)
        report = await _as_of(
            real_async_client, fixture.user, ('as_of', _NOW.isoformat())
        )

        # Ten at 2.00 is the only cost in the ledger, and it is the figure
        # all three screens state.
        assert overview['value_source'] == 'valuation_layers'
        assert overview['total_value'] == pytest.approx(20.0)
        assert footer['value_source'] == 'valuation_layers'
        assert footer['total_value'] == pytest.approx(20.0)
        assert report['value_source'] == 'valuation_layers'
        assert Decimal(report['total_value']) == Decimal('20.00')


class TestAnEmptyShelfOnTheQueriedDay:
    async def test_a_costless_organization_is_not_given_zero_from_the_ledger(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        records_only_ledger: _StockedWarehouse,
    ) -> None:
        db = real_async_db_session
        fixture = records_only_ledger
        # A product that arrived and left before the day asked about: the
        # shelf on that day holds none of today's stock, and the only layers
        # the ledger has are the 0.00 unknowns.
        elder = ProductTemplate(organization_id=fixture.org.id, name='Elder flour')
        db.add(elder)
        await db.flush()
        keeper = await shelf_keeper(db, fixture.org.id)
        record = await put_on_shelf(db, keeper, elder, fixture.location_id, 5)
        await core_api.items.update_quantity_async(
            db, fixture.org.id, record.id, Decimal('0'), user_id=fixture.user.id
        )
        await _backdate_async(db, elder.id, _TWO_DAYS_AGO)
        await _mark_layers_costless_async(db, elder.id)
        await db.commit()

        report = await _as_of(
            real_async_client, fixture.user, ('as_of', _A_DAY_AGO.isoformat())
        )

        # Today's arrivals are undone on that day; the shelf is empty and the
        # ledger holds no cost, so the report has no valuation to state.
        assert report['items'] == []
        assert report['value_source'] is None
        assert report['total_value'] is None
