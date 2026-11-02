"""Nutrition contributes a scan provider, and that provider asks about stock.

This module has no routes and no tenant-owned table of its own -- its only
model is a local copy of the Open Food Facts catalogue, which is global by
design and keyed by barcode. So "cross-organization test for nutrition"
needed a surface before it could have a test, and the surface is the scan
provider it registers.

``OFFScanProvider.handle`` asks about the *caller's* organization before it
looks anything up: is the module enabled, and does this organization already
have the product — an active item under this barcode, or the catalogue row
that names it. Those last questions decide whether the reader is shown their
own stock and catalogue or the products database's entry. If they were not
scoped, a barcode anyone can photograph would answer differently depending
on what a *stranger* happens to have on their shelf — a side channel saying
"somebody else stocks this", from a question the reader is entitled to ask
about themselves.

The scan route is the whole chain, so these go through it.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.public_api import core_api
from app.core.testing import ModuleTestHelper
from app.models.item import Item
from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.models.user import User

_BARCODE = '5901234123457'
_THEIR_ITEM_NAME = 'Stranger Cereal'
_MODULES = ['core', 'items', 'locations', 'nutrition']


_PUBLIC_ENTRY = {'name': 'Public Cereal', 'brand': 'Anyone Mills'}


@contextmanager
def _products_database_answering(entry: dict[str, str] | None) -> Iterator[None]:
    """The shared catalogue answers ``entry`` for the code being scanned.

    The products database is the installation's, not this test's: whether it
    holds this EAN depends on which dump was imported, and an instance whose
    catalogue has it answers with the product's public entry — correctly, as
    what the catalogue knows is not a stranger's stock. Standing the lookup in
    both ways keeps the claim these tests make — no other organization's
    stock, shelf or item name in the answer — from depending on those rows.
    """
    with (
        patch('app.modules.nutrition.scan_provider.off_service') as off,
        patch('app.core.db_facade.ProductsSessionLocal', return_value=MagicMock()),
    ):
        off.fetch_product = MagicMock(return_value=entry)
        yield


@pytest.fixture
def helper(db_session: Session) -> ModuleTestHelper:
    return ModuleTestHelper(db_session)


@pytest.fixture
def stranger_org(helper: ModuleTestHelper) -> Organization:
    return helper.create_org('Strangers Grocery', _MODULES)


@pytest.fixture
def stranger_user(helper: ModuleTestHelper, stranger_org: Organization) -> User:
    return helper.create_user(stranger_org, email='grocer@strangers.example')


@pytest.fixture
def their_stocked_item(
    helper: ModuleTestHelper,
    db_session: Session,
    stranger_org: Organization,
    stranger_user: User,
) -> Item:
    """An active item under the barcode, on somebody else's shelf."""
    storage_type = helper.create_storage_type(
        'Stranger Aisle', 'STRANGER_AISLE', organization_id=stranger_org.id
    )
    storage = helper.create_storage_location(
        stranger_org, storage_type, stranger_user, name='Their Aisle 4'
    )
    item = Item(
        name=_THEIR_ITEM_NAME,
        organization_id=stranger_org.id,
        storage_location_id=storage.id,
        barcode=_BARCODE,
        quantity=Decimal('12'),
    )
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)
    return item


@pytest.mark.integration
class TestTheStockQuestionIsAboutTheAsker:
    @pytest.mark.asyncio
    async def test_a_strangers_item_does_not_count_as_mine(
        self,
        real_async_db_session: AsyncSession,
        helper: ModuleTestHelper,
        their_stocked_item: Item,
        test_household: Organization,
    ) -> None:
        """The question the provider asks, asked directly, both ways."""
        mine = await core_api.items.has_active_barcode_async(
            real_async_db_session, test_household.id, _BARCODE
        )
        theirs = await core_api.items.has_active_barcode_async(
            real_async_db_session, their_stocked_item.organization_id, _BARCODE
        )

        assert mine is False
        assert theirs is True


@pytest.mark.integration
class TestScanningACodeAStrangerStocks:
    @pytest.mark.parametrize(
        'catalogue_entry',
        [None, _PUBLIC_ENTRY],
        ids=['code-not-in-the-catalogue', 'code-in-the-catalogue'],
    )
    def test_the_scan_answers_with_none_of_their_stock(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_storage_location: StorageLocation,
        their_stocked_item: Item,
        catalogue_entry: dict[str, str] | None,
    ) -> None:
        with _products_database_answering(catalogue_entry):
            response = client.get(
                f'/api/v1/labels/scan/{_BARCODE}', headers=auth_headers
            )

        assert response.status_code == status.HTTP_200_OK, response.text
        body = response.json()
        # "I have never seen this code" — which is the truth for this reader,
        # whatever the stranger keeps on their shelf. At most the public
        # catalogue's entry, with nothing stocked under it.
        assert body['status'] == 'unassigned'
        if catalogue_entry is None:
            assert body['stock_summary'] is None
        else:
            summary = body['stock_summary']
            assert summary['template']['name'] == 'Public Cereal'
            assert summary['total_quantity'] == 0
            assert summary['items'] == []
        assert _THEIR_ITEM_NAME not in response.text
        assert 'Their Aisle 4' not in response.text

    def test_the_owner_does_see_their_own_stock(
        self,
        client: TestClient,
        helper: ModuleTestHelper,
        stranger_user: User,
        their_stocked_item: Item,
    ) -> None:
        """The other half: the lookup works, it is only scoped."""
        response = client.get(
            f'/api/v1/labels/scan/{_BARCODE}',
            headers=helper.get_auth_headers(stranger_user),
        )

        assert response.status_code == status.HTTP_200_OK, response.text
        assert _THEIR_ITEM_NAME in response.text
