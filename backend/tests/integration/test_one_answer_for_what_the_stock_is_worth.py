"""What the warehouse is worth had three answers and two of them were wrong.

The overview added every price together whatever currency it was in, so
złoty and euro made one number that meant nothing. The dashboard took only
rows matching the organization exactly, so rows carrying no currency at all
vanished from the total. Cost analysis took "ours or unstated" and counted
what it left out — the right answer, and now everyone's.

Underneath that, the figure itself came from `Item.purchase_price`, a field
on a form: correcting a price rewrote the history of what the warehouse was
worth, with no document behind the change. Where an organization keeps a
cost ledger, the value comes from there and the report says so.

Two more places summed a price without multiplying by the quantity, so one
unit at 1000 and a thousand units at 1 came to the same figure.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.item import Item
from app.models.product_template import ProductTemplate
from app.services.analytics._common import (
    VALUE_FROM_LAYERS,
    VALUE_FROM_PURCHASE_PRICE,
    get_internal_storage_ids_async,
    stock_value_async,
)
from app.services.valuation_service import ValuationService
from tests.integration._shelf import anchor_pending_records


@pytest.mark.integration
@pytest.mark.asyncio
class TestOneAnswerForWhatTheStockIsWorth:
    async def test_a_record_priced_in_another_currency_is_counted_out_loud(
        self,
        real_async_db_session: AsyncSession,
        async_test_household,
        async_test_storage_location,
    ) -> None:
        db = real_async_db_session
        org = async_test_household
        # No StockQuant-consuming module: this organization keeps no cost
        # ledger, so the catalogue price is the only figure there is.
        org.enabled_modules = ['core', 'items', 'locations']
        await db.flush()

        for currency, price in (
            (org.currency, Decimal('10')),
            (None, Decimal('5')),
            ('XXX', Decimal('999')),
        ):
            db.add(
                Item(
                    name=f'Priced in {currency}',
                    organization_id=org.id,
                    storage_location_id=async_test_storage_location.id,
                    quantity=Decimal('2'),
                    purchase_price=price,
                    currency=currency,
                )
            )
        await db.flush()

        storage_ids = await get_internal_storage_ids_async(db, org.id)
        value, source, excluded, _ = await stock_value_async(db, org.id, storage_ids)

        # Ours and unstated add up; the third is left out and said so.
        assert source == VALUE_FROM_PURCHASE_PRICE
        assert value == pytest.approx(30.0)
        assert excluded == 1

    async def test_an_organization_with_a_cost_ledger_is_valued_from_it(
        self,
        real_async_db_session: AsyncSession,
        async_test_household,
        async_test_storage_location,
    ) -> None:
        """The layers answer, and editing the catalogue price does not move it."""
        db = real_async_db_session
        org = async_test_household
        org.enabled_modules = list(org.enabled_modules or []) + ['warehouse']
        await db.flush()

        # The WMS gate is cached per organization for the process lifetime.

        template = ProductTemplate(
            organization_id=org.id, name='Valued goods', sku='VG-1'
        )
        db.add(template)
        await db.flush()
        await ValuationService._record_receipt_async(
            db, template, Decimal('4'), Decimal('7.50'), org.id
        )
        item = Item(
            name='Valued goods',
            organization_id=org.id,
            storage_location_id=async_test_storage_location.id,
            template_id=template.id,
            quantity=Decimal('4'),
            purchase_price=Decimal('1'),
        )
        db.add(item)
        await db.run_sync(anchor_pending_records)
        await db.flush()

        storage_ids = await get_internal_storage_ids_async(db, org.id)
        value, source, _, _ = await stock_value_async(db, org.id, storage_ids)
        assert source == VALUE_FROM_LAYERS
        assert value == pytest.approx(30.0)

        # A correction to the catalogue price is not a stock movement.
        item.purchase_price = Decimal('1000')
        await db.flush()
        again, _, _, _ = await stock_value_async(db, org.id, storage_ids)
        assert again == pytest.approx(30.0)


@pytest.mark.integration
@pytest.mark.asyncio
class TestAValueNobodyGaveIsUnknown:
    """Stock with no price anywhere is not worth nothing — its worth is unknown.

    A pantry of seventeen records, none of them priced, read "Estimated value
    0.00": the sum of no prices printed as if somebody had valued the shelf.
    """

    async def test_no_price_anywhere_reads_as_unknown(
        self,
        real_async_db_session: AsyncSession,
        async_test_household,
        async_test_storage_location,
    ) -> None:
        from app.services.analytics.overview import get_overview_async

        db = real_async_db_session
        org = async_test_household
        org.enabled_modules = ['core', 'items', 'locations']
        await db.flush()
        for name in ('Rice', 'Eggs'):
            db.add(
                Item(
                    name=name,
                    organization_id=org.id,
                    storage_location_id=async_test_storage_location.id,
                    quantity=Decimal('2'),
                )
            )
        await db.flush()

        overview = await get_overview_async(db, org.id)

        assert overview.value_known is False
        assert overview.unpriced_item_count == 2

    async def test_a_partly_priced_shelf_says_how_much_it_left_out(
        self,
        real_async_db_session: AsyncSession,
        async_test_household,
        async_test_storage_location,
    ) -> None:
        from app.services.analytics.overview import get_overview_async

        db = real_async_db_session
        org = async_test_household
        org.enabled_modules = ['core', 'items', 'locations']
        await db.flush()
        db.add(
            Item(
                name='Olive oil',
                organization_id=org.id,
                storage_location_id=async_test_storage_location.id,
                quantity=Decimal('2'),
                purchase_price=Decimal('10'),
                currency=org.currency,
            )
        )
        db.add(
            Item(
                name='Salt',
                organization_id=org.id,
                storage_location_id=async_test_storage_location.id,
                quantity=Decimal('1'),
            )
        )
        await db.flush()

        overview = await get_overview_async(db, org.id)

        assert overview.value_known is True
        assert overview.total_value == pytest.approx(20.0)
        assert overview.unpriced_item_count == 1

    def test_the_endpoint_answers_unknown_too(
        self, client, auth_headers, db_session, test_user, test_storage_location
    ) -> None:
        db_session.add(
            Item(
                name='Flour',
                organization_id=test_user.organization_id,
                storage_location_id=test_storage_location.id,
                quantity=Decimal('1'),
            )
        )
        anchor_pending_records(db_session)
        db_session.commit()

        response = client.get('/api/v1/stats/overview', headers=auth_headers)

        assert response.status_code == 200, response.text
        assert response.json()['value_known'] is False
        assert response.json()['unpriced_item_count'] == 1
