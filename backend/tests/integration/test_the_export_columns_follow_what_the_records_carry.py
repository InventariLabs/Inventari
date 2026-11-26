"""A column of the export exists when a record in it carries a value for it.

The shape of the sheet is asked of the database before the rows are written, so
each question is held against the rows' own reading of the same field: what
counts as a value (a zero threshold or unit weight does not), where it lives
(the product card, ``meta_data``, the unit the record is counted in), and the
order the free-form ``meta_data`` columns appear in.
"""

import io
import uuid
from collections.abc import Awaitable, Callable
from datetime import date, timedelta
from decimal import Decimal

import pandas as pd
import pytest
from sqlalchemy import event, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.contracts import UserContextDTO
from app.models.item import Item
from app.models.uom import Uom, UomCategory
from app.schemas.item import ItemCreate
from app.services.items._create import create_item_async
from app.services.items.export_service import _scan_records, export_items_to_xlsx

pytestmark = pytest.mark.integration

#: The columns every sheet has, whatever its records carry.
ALWAYS = [
    'Name',
    'Quantity',
    'Unit',
    'Location',
    'Category',
    'Barcode',
    'Serial Number',
    'Label Code',
    'Brand',
]

PRICE = 'Purchase price per unit (USD)'

Change = Callable[[AsyncSession, Item], Awaitable[None]]


async def _record(db: AsyncSession, user, location, name: str, **fields) -> Item:
    made = await create_item_async(
        db,
        ItemCreate(name=name, quantity=Decimal('2'), location_id=location.id, **fields),
        UserContextDTO(id=user.id, organization_id=user.organization_id),
    )
    # The form's door gives every record the organization's currency; the
    # sheet's own question about it starts from a record without one.
    await db.execute(update(Item).where(Item.id == made.id).values(currency=None))
    return (
        await db.scalars(
            select(Item).where(Item.id == made.id).options(selectinload(Item.template))
        )
    ).one()


async def _columns(db: AsyncSession, user) -> list[str]:
    await db.commit()
    asker = UserContextDTO(id=user.id, organization_id=user.organization_id)
    # The export reads on a session that holds nothing yet, as in a request.
    db.expunge_all()
    response = await db.run_sync(lambda s: export_items_to_xlsx(s, asker))
    raw = b''.join([chunk async for chunk in response.body_iterator])
    return list(pd.read_excel(io.BytesIO(raw), sheet_name='Inventory').columns)


def _on_the_record(**values) -> Change:
    async def change(db: AsyncSession, item: Item) -> None:
        await db.execute(update(Item).where(Item.id == item.id).values(**values))

    return change


def _on_the_product(**values) -> Change:
    async def change(db: AsyncSession, item: Item) -> None:
        for field, value in values.items():
            setattr(item.template, field, value)

    return change


async def _counted_by_weight(db: AsyncSession, item: Item) -> None:
    category = UomCategory(
        id=uuid.uuid4(), organization_id=item.organization_id, name='Weight'
    )
    unit = Uom(
        id=uuid.uuid4(),
        organization_id=item.organization_id,
        category_id=category.id,
        name='Gram',
        symbol='g',
        factor=Decimal('1'),
    )
    db.add(category)
    await db.flush()
    db.add(unit)
    await db.flush()
    await db.execute(update(Item).where(Item.id == item.id).values(uom_id=unit.id))


async def _priced_not_a_number(db: AsyncSession, item: Item) -> None:
    await db.execute(
        text("UPDATE items SET purchase_price = 'NaN' WHERE id = :id"), {'id': item.id}
    )


async def _expiring(db: AsyncSession, item: Item) -> None:
    a_day = date.today() + timedelta(days=30)
    await _on_the_record(expiry_date=a_day)(db, item)


async def _frozen(db: AsyncSession, item: Item) -> None:
    a_day = date.today().isoformat()
    await _on_the_record(meta_data={'food': {'freeze_date': a_day}})(db, item)


@pytest.fixture
async def open_location(
    real_async_db_session: AsyncSession, async_test_storage_location
):
    """A location with no schema: it allows every field a record carries."""
    async_test_storage_location.context_schema = None
    async_test_storage_location.field_definitions = None
    await real_async_db_session.commit()
    return async_test_storage_location


@pytest.mark.parametrize(
    ('change', 'added'),
    [
        pytest.param(None, [], id='nothing'),
        pytest.param(_on_the_product(sku='A-1'), ['SKU'], id='sku'),
        pytest.param(_on_the_product(min_quantity=3), ['Stock alert'], id='alert'),
        pytest.param(_on_the_product(min_quantity=0), [], id='alert-of-zero'),
        pytest.param(_on_the_product(weight_value=Decimal('5')), ['Weight'], id='kg'),
        pytest.param(_on_the_product(weight_value=Decimal('0')), [], id='no-weight'),
        pytest.param(_counted_by_weight, ['Weight'], id='counted-by-weight'),
        pytest.param(_expiring, ['Expiry Date'], id='expiry'),
        pytest.param(_frozen, ['Freeze Date'], id='frozen'),
        pytest.param(
            _on_the_record(meta_data={'food': {'freeze_date': None}}),
            [],
            id='never-frozen',
        ),
        pytest.param(_on_the_record(description=''), ['Description'], id='notes'),
        pytest.param(
            _on_the_record(shelf_location='Top'), ['Shelf Location'], id='shelf'
        ),
        pytest.param(
            _on_the_record(purchase_price=Decimal('0')),
            [PRICE, 'Currency'],
            id='price',
        ),
        pytest.param(_on_the_record(currency='EUR'), ['Currency'], id='currency'),
        pytest.param(_priced_not_a_number, [], id='price-not-a-number'),
        pytest.param(_on_the_record(meta_data=None), [], id='meta-null'),
    ],
)
async def test_a_record_that_carries_a_value_adds_its_column(
    real_async_db_session: AsyncSession,
    async_test_user,
    open_location,
    change: Change | None,
    added: list[str],
) -> None:
    db = real_async_db_session
    item = await _record(db, async_test_user, open_location, 'Plain')
    if change is not None:
        await change(db, item)

    assert await _columns(db, async_test_user) == [*ALWAYS, *added]


async def test_meta_columns_come_in_the_order_the_records_introduce_them(
    real_async_db_session: AsyncSession, async_test_user, open_location
) -> None:
    db = real_async_db_session
    first = await _record(db, async_test_user, open_location, 'One')
    second = await _record(db, async_test_user, open_location, 'Two')
    gone = await _record(db, async_test_user, open_location, 'Gone')
    # The records are read in the order of their ids.
    first, second = sorted((first, second), key=lambda item: item.id)
    await _on_the_record(meta_data={'zz': 1, 'equipment': {'asset_tag': 'T'}})(
        db, first
    )
    await _on_the_record(meta_data={'aa': 2, 'zz': 3, 'nutrition': {'kcal': 4}})(
        db, second
    )
    # A record the sheet leaves out adds no column to it.
    await _on_the_record(is_deleted=True, meta_data={'ghost': 1}, shelf_location='X')(
        db, gone
    )

    assert await _columns(db, async_test_user) == [
        *ALWAYS,
        'Custom: zz',
        'Asset Tag',
        'Custom: aa',
        'Nutri: kcal',
    ]


async def test_a_filtered_scan_reads_the_records_in_one_statement_planned_for_all(
    real_async_db_session: AsyncSession, async_test_user, open_location
) -> None:
    """A filter can cost seconds to evaluate, so the columns pay for it once.

    The one statement is read through a cursor, which Postgres plans for the
    first tenth of the rows unless the transaction asks for the whole answer.
    """
    db = real_async_db_session
    await _record(db, async_test_user, open_location, 'Plain')
    await db.commit()
    organization_id = async_test_user.organization_id
    reads: list[str] = []

    def _count(conn, cursor, statement: str, *args) -> None:
        if 'FROM items' in statement:
            reads.append(statement)

    def _scan(session) -> str:
        bind = session.get_bind()
        event.listen(bind, 'before_cursor_execute', _count)
        try:
            _scan_records(session, organization_id, None, {'only_low_stock': True})
        finally:
            event.remove(bind, 'before_cursor_execute', _count)
        return session.scalar(select(func.current_setting('cursor_tuple_fraction')))

    assert await db.run_sync(_scan) == '1'
    assert len(reads) == 1
