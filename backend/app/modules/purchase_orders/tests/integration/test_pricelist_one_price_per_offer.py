"""One supplier, one product, one set of terms — one price.

Measured on real data: 'Salted crisps' from one supplier stood in the table
twice, PLN 29.85 and PLN 62.62, both valid from 2026-01-01, both open-ended,
both minimum quantity 1. Two answers to one question, and
``get_best_price_async`` orders by price, so a buyer who corrected 62.62 to
55.00 kept getting 29.85 on the order with nothing to say why.

Refused rather than overwritten: which of the two is right is a fact about
the supplier, and this code has no way of knowing it.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.user import User


async def _offer_setup(
    db: AsyncSession, org: Organization, user: User
) -> tuple[Partner, ProductTemplate]:
    template = ProductTemplate(
        organization_id=org.id,
        name='Salted crisps',
        sku=f'SKU-DUP-{uuid4().hex[:8]}',
    )
    partner = Partner(
        organization_id=org.id,
        name='Euro-Data',
        type='SUPPLIER',
        created_by=user.id,
    )
    db.add_all([template, partner])
    await db.flush()
    return partner, template


@pytest.mark.integration
@pytest.mark.asyncio
class TestOnePricePerOffer:
    async def test_a_second_price_for_the_same_terms_is_refused(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
    ) -> None:
        db = real_async_db_session
        partner, template = await _offer_setup(
            db, async_test_household, async_test_user
        )
        from app.modules.purchase_orders.pricelist_service import create_async

        common: dict[str, Any] = {
            'organization_id': async_test_household.id,
            'partner_id': partner.id,
            'product_template_id': template.id,
            'valid_from': date(2026, 1, 1),
            'min_quantity': Decimal('1'),
        }
        await create_async(db, unit_price=Decimal('29.8500'), **common)
        await db.commit()

        with pytest.raises(HTTPException) as caught:
            await create_async(db, unit_price=Decimal('62.6200'), **common)

        assert caught.value.status_code == 409
        detail = cast(dict[str, Any], caught.value.detail)
        assert detail['code'] == 'PRICELIST_DUPLICATE'

    async def test_different_terms_are_a_price_list_not_a_contradiction(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
    ) -> None:
        """Volume tiers and dated contracts are how a real one is written."""
        db = real_async_db_session
        partner, template = await _offer_setup(
            db, async_test_household, async_test_user
        )
        from app.modules.purchase_orders.pricelist_service import create_async

        common: dict[str, Any] = {
            'organization_id': async_test_household.id,
            'partner_id': partner.id,
            'product_template_id': template.id,
        }
        await create_async(
            db,
            unit_price=Decimal('29.8500'),
            valid_from=date(2026, 1, 1),
            min_quantity=Decimal('1'),
            **common,
        )
        await create_async(
            db,
            unit_price=Decimal('24.0000'),
            valid_from=date(2026, 1, 1),
            min_quantity=Decimal('100'),
            **common,
        )
        await create_async(
            db,
            unit_price=Decimal('31.0000'),
            valid_from=date(2026, 7, 1),
            min_quantity=Decimal('1'),
            **common,
        )
        await db.commit()

        from app.modules.purchase_orders.pricelist_service import (
            list_for_partner_async,
        )

        rows = await list_for_partner_async(db, async_test_household.id, partner.id)
        assert len(rows) == 3

    async def test_an_edit_cannot_walk_onto_another_entry_s_terms(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
    ) -> None:
        db = real_async_db_session
        partner, template = await _offer_setup(
            db, async_test_household, async_test_user
        )
        from app.modules.purchase_orders.pricelist_service import (
            create_async,
            update_async,
        )

        common: dict[str, Any] = {
            'organization_id': async_test_household.id,
            'partner_id': partner.id,
            'product_template_id': template.id,
            'min_quantity': Decimal('1'),
        }
        first = await create_async(
            db, unit_price=Decimal('29.8500'), valid_from=date(2026, 1, 1), **common
        )
        second = await create_async(
            db, unit_price=Decimal('31.0000'), valid_from=date(2026, 7, 1), **common
        )
        await db.commit()

        with pytest.raises(HTTPException) as caught:
            await update_async(
                db,
                organization_id=async_test_household.id,
                entry_id=second.id,
                valid_from=first.valid_from,
            )

        assert caught.value.status_code == 409

    async def test_editing_an_entry_in_place_is_still_allowed(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
    ) -> None:
        """The check has to not see the row it is checking."""
        db = real_async_db_session
        partner, template = await _offer_setup(
            db, async_test_household, async_test_user
        )
        from app.modules.purchase_orders.pricelist_service import (
            create_async,
            update_async,
        )

        entry = await create_async(
            db,
            organization_id=async_test_household.id,
            partner_id=partner.id,
            product_template_id=template.id,
            unit_price=Decimal('62.6200'),
            valid_from=date(2026, 1, 1),
            min_quantity=Decimal('1'),
        )
        await db.commit()

        updated = await update_async(
            db,
            organization_id=async_test_household.id,
            entry_id=entry.id,
            unit_price=Decimal('55.0000'),
        )
        assert updated is not None
        assert updated.unit_price == Decimal('55.0000')
