"""A refusal about stock says what and where, in the reader's language.

The four refusals raised when a location cannot give up what was asked of it
were English f-strings holding two UUIDs:

    No consumable stock for product 08fd86ab-141d-4a17-aff9-6de133937382
    at location faaa3505-b70a-452f-ac1f-6358281898e1
    — all lots are quarantined or held

which reached the screen verbatim, on a bulk edit and on a single move alike.
Nobody can act on that: the ids name nothing a person has seen, and the
sentence is in a language the workspace may not be in.

The reason the strings had gone unfixed was written above one of them: the
caller decided whether to auto-hydrate a legacy quant by testing
``'No stock found' in str(exc)``. The sentence was load-bearing, so
translating it would have silently switched the healing path off. The reason
now travels as a code on the exception, and the sentence is free to be
a sentence. (The quant and its healing are gone since; the refusal stayed.)

The doors that refuse are the draw off one shelf,
``take_from_the_records_async``, and the movement pass,
``post_movement_async``, when what leaves would leave a grain short of what
its orders hold.
"""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import RecordPostDTO
from app.core.exceptions import StockUnavailableError
from app.i18n.service import get_error_message, set_current_lang
from app.models.product_template import ProductTemplate
from app.models.stock_lot import StockLot
from app.services._stock_quant_ops import (
    post_movement_async,
    take_from_the_records_async,
)
from tests.integration._shelf import put_on_shelf, reserve_for_an_order, shelf_keeper

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

PRODUCT = 'Bananas'


async def _template(db: AsyncSession, org_id) -> ProductTemplate:
    template = ProductTemplate(
        organization_id=org_id,
        name=PRODUCT,
        sku=f'BAN-{uuid.uuid4().hex[:8]}',
    )
    db.add(template)
    await db.flush()
    return template


@pytest.fixture(autouse=True)
def _english_by_default():
    set_current_lang('en')
    yield
    set_current_lang('en')


async def test_a_shelf_that_holds_none_of_it_says_so_by_name(
    real_async_db_session: AsyncSession,
    async_test_household,
    async_test_storage_location,
) -> None:
    db = real_async_db_session
    template = await _template(db, async_test_household.id)

    with pytest.raises(StockUnavailableError) as refusal:
        await take_from_the_records_async(
            db,
            async_test_household.id,
            template.id,
            async_test_storage_location.id,
            Decimal('1'),
        )

    assert refusal.value.code == StockUnavailableError.NO_STOCK
    said = str(refusal.value)
    assert said == get_error_message(
        'stock_none_at_location',
        'en',
        product=PRODUCT,
        location=async_test_storage_location.name,
    )
    assert PRODUCT in said
    assert async_test_storage_location.name in said
    assert str(template.id) not in said
    assert str(async_test_storage_location.id) not in said


async def test_a_shelf_holding_less_than_asked_says_both_numbers(
    real_async_db_session: AsyncSession,
    async_test_household,
    async_test_storage_location,
) -> None:
    db = real_async_db_session
    template = await _template(db, async_test_household.id)
    keeper = await shelf_keeper(db, async_test_household.id)
    await put_on_shelf(db, keeper, template, async_test_storage_location.id, 2)

    with pytest.raises(StockUnavailableError) as refusal:
        await take_from_the_records_async(
            db,
            async_test_household.id,
            template.id,
            async_test_storage_location.id,
            Decimal('5'),
        )

    assert refusal.value.code == StockUnavailableError.NOT_ENOUGH
    said = str(refusal.value)
    assert said == get_error_message(
        'stock_not_enough',
        'en',
        product=PRODUCT,
        location=async_test_storage_location.name,
        available=Decimal('2.000'),
        requested=Decimal('5'),
    )
    assert PRODUCT in said
    assert str(template.id) not in said


async def test_a_movement_leaving_an_order_short_says_it_by_name(
    real_async_db_session: AsyncSession,
    async_test_household,
    async_test_storage_location,
) -> None:
    """The movement pass refuses in the same words, naming the same two things."""
    db = real_async_db_session
    template = await _template(db, async_test_household.id)
    keeper = await shelf_keeper(db, async_test_household.id)
    record = await put_on_shelf(db, keeper, template, async_test_storage_location.id, 5)
    await reserve_for_an_order(db, template, async_test_storage_location.id, 4)

    # Three of five leave, two stay — below the four an order holds.
    with pytest.raises(StockUnavailableError) as refusal:
        await post_movement_async(
            db,
            async_test_household.id,
            template.id,
            Decimal('3'),
            from_location_id=async_test_storage_location.id,
            reference_type='item',
            reference_id=record.id,
            records=[RecordPostDTO(item_id=record.id, new_quantity=Decimal('2'))],
        )

    assert refusal.value.code == StockUnavailableError.NOT_ENOUGH
    said = str(refusal.value)
    assert PRODUCT in said
    assert async_test_storage_location.name in said
    assert str(template.id) not in said
    assert str(async_test_storage_location.id) not in said


async def test_a_shelf_whose_every_batch_is_held_says_that_by_name(
    real_async_db_session: AsyncSession,
    async_test_household,
    async_test_storage_location,
) -> None:
    db = real_async_db_session
    template = await _template(db, async_test_household.id)
    lot = StockLot(
        organization_id=async_test_household.id,
        product_template_id=template.id,
        name=f'LOT-{uuid.uuid4().hex[:6]}',
        status='QUARANTINE',
    )
    db.add(lot)
    await db.flush()
    keeper = await shelf_keeper(db, async_test_household.id)
    await put_on_shelf(
        db, keeper, template, async_test_storage_location.id, 10, lot_id=lot.id
    )

    with pytest.raises(StockUnavailableError) as refusal:
        await take_from_the_records_async(
            db,
            async_test_household.id,
            template.id,
            async_test_storage_location.id,
            Decimal('1'),
        )

    assert refusal.value.code == StockUnavailableError.ALL_HELD
    said = str(refusal.value)
    assert said == get_error_message(
        'stock_all_batches_held',
        'en',
        product=PRODUCT,
        location=async_test_storage_location.name,
    )
    assert PRODUCT in said
    assert async_test_storage_location.name in said
    assert str(template.id) not in said


async def test_the_refusal_speaks_the_workspace_language(
    real_async_db_session: AsyncSession,
    async_test_household,
    async_test_storage_location,
) -> None:
    db = real_async_db_session
    template = await _template(db, async_test_household.id)
    set_current_lang('pl')

    with pytest.raises(StockUnavailableError) as refusal:
        await take_from_the_records_async(
            db,
            async_test_household.id,
            template.id,
            async_test_storage_location.id,
            Decimal('1'),
        )

    said = str(refusal.value)
    assert PRODUCT in said
    # Polish, not the English sentence that used to be the only one there.
    assert 'No stock found' not in said
    assert said != ''
