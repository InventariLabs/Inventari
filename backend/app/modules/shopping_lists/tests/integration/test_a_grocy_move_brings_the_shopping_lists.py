"""A move from Grocy brings its shopping lists when the module is on.

The core files Grocy's products and stock, then hands the same file to the
shopping lists (``app.core.move_contributors``) with the products it made.
Each Grocy list becomes a list of the same name, an entry for a product
links to that product in the matched unit, a note-only entry keeps its note
as its name, a ticked-off entry arrives ticked off, and a second run of the
file adds no list twice. With the module off, the entries stay in Grocy and
the summary counts them there.
"""

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.core.grocy_file import read_grocy_file
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.shopping_lists.models import ShoppingList, ShoppingListItem
from app.services.items._grocy_import import import_grocy_file_async
from tests.integration._grocy import GrocyDb

pytestmark = pytest.mark.integration


def _ctx(user: User) -> UserContextDTO:
    return UserContextDTO(
        id=user.id, organization_id=user.organization_id, role='admin'
    )


def _household() -> GrocyDb:
    g = GrocyDb()
    pantry = g.location('Grocy pantry')
    piece = g.unit('Piece', 'Pieces')
    gram = g.unit('Gram', 'Grams')
    milk = g.product('Grocy milk', location=pantry, unit=piece)
    g.stock(milk, 1, location=pantry)
    flour = g.product('Grocy flour', location=pantry, unit=gram)
    weekly = g.shopping_list('Weekly')
    g.shopping_item(
        product=milk, amount=2, unit=piece, list_id=weekly, note='the blue one'
    )
    g.shopping_item(product=flour, amount=500, unit=gram, list_id=weekly)
    g.shopping_item(note='Birthday candles', amount=0, done=True)
    return g


async def _lines(db: AsyncSession, list_name: str) -> list[ShoppingListItem]:
    rows = await db.execute(
        select(ShoppingListItem)
        .join(ShoppingList, ShoppingList.id == ShoppingListItem.shopping_list_id)
        .where(ShoppingList.name == list_name)
        .order_by(ShoppingListItem.name)
    )
    return list(rows.scalars().all())


async def test_each_grocy_list_comes_across_with_its_products_and_notes(
    real_async_db_session: AsyncSession,
    async_test_user: User,
    async_test_storage_location: StorageLocation,
) -> None:
    db = real_async_db_session

    result = await import_grocy_file_async(
        db, read_grocy_file(_household().content()), _ctx(async_test_user)
    )

    flour_product = (
        await db.execute(
            select(ProductTemplate).where(ProductTemplate.name == 'Grocy flour')
        )
    ).scalar_one()
    flour, milk = await _lines(db, 'Weekly')
    assert (milk.quantity, milk.notes, milk.is_purchased) == (
        Decimal('2'),
        'the blue one',
        False,
    )
    assert milk.template_id is not None
    await db.refresh(flour, ['uom'])
    assert flour.template_id == flour_product.id
    assert (flour.quantity, flour.uom.symbol) == (Decimal('500'), 'g')
    (candles,) = await _lines(db, 'Default')
    assert (candles.name, candles.quantity, candles.is_purchased) == (
        'Birthday candles',
        Decimal('1'),
        True,
    )
    assert [b['module'] for b in result['brought_by_modules']] == ['shopping_lists']
    assert 'shopping_list_entries' not in {e['what'] for e in result['left_behind']}


async def test_a_second_run_adds_no_list_twice(
    real_async_db_session: AsyncSession,
    async_test_user: User,
    async_test_storage_location: StorageLocation,
) -> None:
    db = real_async_db_session
    grocy = read_grocy_file(_household().content())
    await import_grocy_file_async(db, grocy, _ctx(async_test_user))

    again = await import_grocy_file_async(db, grocy, _ctx(async_test_user))

    names = (
        await db.execute(
            select(ShoppingList.name).where(
                ShoppingList.organization_id == async_test_user.organization_id
            )
        )
    ).scalars()
    assert sorted(names) == ['Default', 'Weekly']
    assert '3' in again['brought_by_modules'][0]['sentence']


async def test_with_the_module_off_the_entries_stay_in_grocy(
    real_async_db_session: AsyncSession,
    async_test_user: User,
    async_test_storage_location: StorageLocation,
) -> None:
    db = real_async_db_session
    org = await db.get(Organization, async_test_user.organization_id)
    assert org is not None
    org.enabled_modules = [m for m in org.enabled_modules if m != 'shopping_lists']
    await db.flush()

    result = await import_grocy_file_async(
        db, read_grocy_file(_household().content()), _ctx(async_test_user)
    )

    assert result['brought_by_modules'] == []
    assert {
        'what': 'shopping_list_entries',
        'count': 3,
        'names': [],
        'failed': False,
    } in result['left_behind']
    lists = await db.execute(
        select(ShoppingList).where(
            ShoppingList.organization_id == async_test_user.organization_id
        )
    )
    assert lists.scalars().all() == []


async def test_a_part_that_fails_leaves_its_entries_counted_as_staying(
    real_async_db_session: AsyncSession,
    async_test_user: User,
    async_test_storage_location: StorageLocation,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = real_async_db_session

    async def refuse(*args: object, **kwargs: object) -> None:
        raise RuntimeError('no list today')

    monkeypatch.setattr(
        'app.modules.shopping_lists._grocy_move.create_shopping_list', refuse
    )

    result = await import_grocy_file_async(
        db, read_grocy_file(_household().content()), _ctx(async_test_user)
    )

    assert result['imported'] > 0
    assert result['brought_by_modules'] == []
    assert {
        'what': 'shopping_list_entries',
        'count': 3,
        'names': [],
        'failed': True,
    } in result['left_behind']
