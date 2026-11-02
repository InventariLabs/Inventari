"""A generated internal product code is not a package code anybody shares.

An organization's own goods carry no manufacturer's number, so the product
form makes one: an EAN-13 from GS1's restricted-circulation range (prefix
20), numbered per organization. GS1 reserves that range for use inside one
company's walls — the same digits stand for different goods at every shop
that prints them — so a shared catalogue such as Open Food Facts holds
numbers in it that say nothing about the product in hand. The demo's own
seed uses the range too.

The scan of a generated code used to fall through to the products database
like any package barcode, and a code printed in our own warehouse proposed
whatever a stranger once typed into Open Food Facts under that number. The
rule is pinned here, at the scan resolution: restricted-circulation numbers
are not looked up in a shared catalogue, and the reader gets the plain
"new product" answer. A code in the range that the organization itself
holds still answers from its own stock and catalogue, as every code does.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.core.scan_registry import scan_registry
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import LocationUsage, StorageLocation
from app.models.user import User
from tests.integration._shelf import put_on_shelf

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

#: What "Generate code" returned in the report — and what Open Food Facts
#: has filed under it.
_GENERATED_CODE = '2000000000213'
#: A GTIN-8 from the same company-internal range (its first digit is 2),
#: which the scan path pads to 0000020000004 before any lookup.
_RESTRICTED_EAN8 = '20000004'
_STRANGERS_PRODUCT = 'Chaussons au pommes'


@contextmanager
def _the_products_database_knows_apple_turnovers() -> Iterator[MagicMock]:
    """The shared catalogue answers for the code being scanned.

    Only the products table is stood in for: the guard under test reads the
    code itself, before the table is opened.
    """
    product = MagicMock()
    product.name = _STRANGERS_PRODUCT
    product.brand = None
    product.image_url = None
    product.data = {}
    products_session = MagicMock()
    products_session.close = MagicMock()
    products_session.scalars.return_value.first.return_value = product
    with patch(
        'app.core.db_facade.ProductsSessionLocal',
        return_value=products_session,
    ):
        yield products_session


class TestAGeneratedCodeIsNotAStrangersProduct:
    async def test_the_scan_answers_with_the_new_product_form(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
    ) -> None:
        # The products database holds a product under this number; the
        # organization holds nothing. The answer is "new product here", not
        # the stranger's entry filled into the form.
        db = real_async_db_session
        user = UserContextDTO(
            id=async_test_user.id, organization_id=async_test_household.id
        )

        with _the_products_database_knows_apple_turnovers() as products:
            result = await scan_registry.scan(_GENERATED_CODE, user, db)

        assert result is not None
        assert result.status == 'unassigned'
        assert result.message_key == 'scan:result.newProduct'
        assert result.action == 'show_quick_add'
        assert result.message_params is None
        assert result.stock_summary is None
        # Not even read: a restricted-circulation number has no one meaning
        # a shared catalogue could answer with.
        products.scalars.assert_not_called()

    async def test_a_padded_gtin8_is_not_looked_up_either(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
    ) -> None:
        # A scan is normalized to the canonical GTIN-13 before every lookup,
        # so 20000004 reaches the catalogue as 0000020000004 and the EAN-8's
        # leading 2 no longer sits in the first two characters. The rule has
        # to survive that padding, or the stranger answers anyway.
        db = real_async_db_session
        user = UserContextDTO(
            id=async_test_user.id, organization_id=async_test_household.id
        )

        with _the_products_database_knows_apple_turnovers() as products:
            result = await scan_registry.scan(_RESTRICTED_EAN8, user, db)

        assert result is not None
        assert result.status == 'unassigned'
        assert result.message_key == 'scan:result.newProduct'
        assert result.label_code == '0000020000004'
        products.scalars.assert_not_called()

    @pytest.mark.parametrize(
        'code',
        [
            # A 13-digit restricted number in GTIN-14 trade-item form.
            '00200000000219',
            # The EAN-8 above padded all the way to GTIN-14.
            '00000020000004',
        ],
    )
    async def test_a_gtin14_form_is_not_looked_up_either(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
        code: str,
    ) -> None:
        # A scan provider may hand the registry the 14-digit trade-item form
        # of the same number. The leading indicator digit is padding, not a
        # different code, so the restricted rule has to read through it as it
        # reads through the GTIN-13 padding.
        db = real_async_db_session
        user = UserContextDTO(
            id=async_test_user.id, organization_id=async_test_household.id
        )

        with _the_products_database_knows_apple_turnovers() as products:
            result = await scan_registry.scan(code, user, db)

        assert result is not None
        assert result.status == 'unassigned'
        assert result.message_key == 'scan:result.newProduct'
        assert result.label_code == code
        products.scalars.assert_not_called()

    async def test_a_code_the_organization_holds_still_answers_from_its_stock(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
    ) -> None:
        # The same digits, held here: stock answers first, as it does for
        # every code the organization knows.
        db = real_async_db_session
        org_id = async_test_household.id
        user = UserContextDTO(id=async_test_user.id, organization_id=org_id)
        template = ProductTemplate(
            organization_id=org_id,
            name='Tomato Ketchup',
            barcode=_GENERATED_CODE,
            sku='KET-500',
        )
        db.add(template)
        await db.flush()
        pantry = StorageLocation(
            organization_id=org_id,
            created_by=async_test_user.id,
            name='Pantry',
            usage=LocationUsage.INTERNAL,
        )
        db.add(pantry)
        await db.flush()
        await put_on_shelf(db, user, template, pantry.id, '3')
        await db.commit()

        with _the_products_database_knows_apple_turnovers():
            result = await scan_registry.scan(_GENERATED_CODE, user, db)

        assert result is not None
        assert result.status == 'product_stock'
        assert result.message_params == {'product': 'Tomato Ketchup'}
        assert result.stock_summary is not None
        assert result.stock_summary['total_quantity'] == 3.0
