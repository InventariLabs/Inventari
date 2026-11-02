"""A scan of what the organization already holds answers from its own stock.

With the nutrition module on, the Open Food Facts provider sat ahead of the
catalogue lookup and could open "add new product" for a product already on
the shelf. Its skip asked whether a *record* carried the code, and the code
lives on the catalogue row — a record created through the application stays
bare whenever its card holds the code — so the check never fired for the
products that have a code at all. The products database then answered a scan
of stock with a new-product form: a second product offered for what the
shelf already held.

So the provider skips when the organization already has the product, and the
scan of stock reaches the provider that answers from stock. A code nobody
has locally is the enrichment's whole job, and keeps it.

The provider order, and the rule an enrichment provider skips by, live in
``docs/subsystems/SCAN.md``.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.barcode import gtin_check_digit
from app.core.contracts import UserContextDTO
from app.core.scan_registry import scan_registry
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import LocationUsage, StorageLocation
from app.models.user import User
from tests.integration._shelf import put_on_shelf

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _barcode() -> str:
    """A package EAN: 13 digits with a valid check digit, so every provider
    that recognises a package barcode recognises this one."""
    body = f'76{uuid4().int % 10**11:011d}'
    return body + gtin_check_digit(body)


@contextmanager
def _the_products_database_knows(**fields: Any) -> Iterator[None]:
    """The Open Food Facts table answers for the code being scanned.

    Only the products database is stood in for: the skip question this test
    is about is asked of the organization's own database, and must be the
    real one.
    """
    off_data: dict[str, Any] = {
        'name': 'Jacobs Espresso',
        'brand': 'Jacobs',
        'image_url': None,
        'nutriscore': 'c',
        'energy_kcal': 400,
        'source': 'local_off_db',
    }
    off_data.update(fields)
    products_session = MagicMock()
    products_session.close = MagicMock()
    with (
        patch('app.modules.nutrition.scan_provider.off_service') as off,
        patch(
            'app.core.db_facade.ProductsSessionLocal',
            return_value=products_session,
        ),
    ):
        off.fetch_product = MagicMock(return_value=off_data)
        yield


async def _shelf(
    db: AsyncSession, org_id: UUID, user_id: UUID, name: str
) -> StorageLocation:
    location = StorageLocation(
        organization_id=org_id,
        created_by=user_id,
        name=name,
        usage=LocationUsage.INTERNAL,
    )
    db.add(location)
    await db.flush()
    return location


async def _template(db: AsyncSession, org_id: UUID, barcode: str) -> ProductTemplate:
    template = ProductTemplate(
        organization_id=org_id,
        name='Kawa mielona Jacobs',
        brand='Jacobs',
        barcode=barcode,
        sku='JAC-250',
    )
    db.add(template)
    await db.flush()
    return template


class TestStockAnswersBeforeTheProductsDatabase:
    async def test_a_product_in_stock_is_scanned_to_its_stock_sheet(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
    ) -> None:
        # The products database knows this EAN; the shelf holds eight of the
        # product it names. What the reader came for is how many there are
        # and where — not a form to add one more of them.
        db = real_async_db_session
        org_id = async_test_household.id
        user = UserContextDTO(id=async_test_user.id, organization_id=org_id)
        barcode = _barcode()
        template = await _template(db, org_id, barcode)
        pantry = await _shelf(db, org_id, async_test_user.id, 'Pantry')
        await put_on_shelf(db, user, template, pantry.id, '8')
        await db.commit()

        with _the_products_database_knows():
            result = await scan_registry.scan(barcode, user, db)

        assert result is not None
        assert result.status == 'product_stock'
        assert result.action == 'show_stock_actions'
        summary = result.stock_summary
        assert summary is not None
        assert summary['total_quantity'] == 8.0
        assert [row['location'] for row in summary['items']] == ['Pantry']

    async def test_a_product_the_catalogue_knows_prefills_the_local_form(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
    ) -> None:
        # None of it in stock — still the organization's own product
        # answering: the quick-add carries the card's id and SKU, so what
        # lands on the shelf is one more of the product already catalogued,
        # not a second card filled in from a public database.
        db = real_async_db_session
        org_id = async_test_household.id
        user = UserContextDTO(id=async_test_user.id, organization_id=org_id)
        barcode = _barcode()
        template = await _template(db, org_id, barcode)
        await db.commit()

        with _the_products_database_knows():
            result = await scan_registry.scan(barcode, user, db)

        assert result is not None
        assert result.action == 'show_quick_add'
        assert result.message_key == 'scan:result.notInStock'
        assert result.stock_summary is not None
        assert result.stock_summary['template']['id'] == str(template.id)
        assert result.stock_summary['template']['sku'] == 'JAC-250'

    async def test_a_code_nobody_has_is_still_filled_in_from_the_products_database(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
    ) -> None:
        # The other half of the rule, and it passes with or without the
        # skip: a code the organization has never seen is what the products
        # database is for.
        db = real_async_db_session
        user = UserContextDTO(
            id=async_test_user.id, organization_id=async_test_household.id
        )
        barcode = _barcode()

        with _the_products_database_knows():
            result = await scan_registry.scan(barcode, user, db)

        assert result is not None
        assert result.action == 'show_quick_add'
        assert result.stock_summary is not None
        template = result.stock_summary['template']
        assert template['name'] == 'Jacobs Espresso'
        assert template['metadata']['off_enriched'] is True
