"""Settle what a record's response will read without asking the database twice."""

from __future__ import annotations

from typing import Any

from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value

from app.core.posting_batch import current_batch
from app.models.category import Category
from app.models.item import Item
from app.models.product_template import ProductTemplate
from app.models.uom import Uom

#: The relationships a record is read with; a response reads all of them.
_EAGER = frozenset({'category', 'uom', 'template', 'storage_location'})


async def settle_category(db: AsyncSession, item: Item) -> None:
    """Make ``item.category`` the category ``item.category_id`` names.

    Read again, as it always was. Inside a posting, a record whose
    relationships were all loaded with it and whose category still agrees
    with its ``category_id`` is settled already, and reading it again cost a
    statement per write, which a document of two hundred lines paid two
    hundred times. A response that reads further into the record (a product
    card's weight unit) needs the read, so only the posting skips it.
    """
    if current_batch(db) is not None:
        state = inspect(item)
        if not _EAGER & state.unloaded:
            loaded = item.category
            if (loaded.id if loaded is not None else None) == item.category_id:
                return
    await db.refresh(item, ['category'])


async def read_back_a_new_record(
    db: AsyncSession,
    item: Item,
    *,
    storage: Any,
    category: Any,
    template: Any,
) -> None:
    """Make a record just written ready to be read: its relationships loaded.

    Read back from the database, as a request creating one record does. A
    posting opening a record per line has the rows its relationships would
    load in hand already, and reading the record back to fetch them again was
    three statements a line; it gives them to the record instead. The columns
    carry Python-side defaults only, so nothing else in the record was waiting
    for the database.
    """
    if current_batch(db) is None:
        await db.refresh(item)
        return
    set_committed_value(item, 'storage_location', storage)
    set_committed_value(item, 'category', category)
    set_committed_value(item, 'template', template)
    set_committed_value(
        item,
        'uom',
        await db.get(Uom, item.uom_id) if item.uom_id is not None else None,
    )


async def give_the_card_and_category(db: AsyncSession, record: Item) -> None:
    """Load a record's product and category by identity, as its loaders would.

    For a record read with those two relationships left unloaded: a posting
    has the product in hand already, and a statement per record is what it is
    built not to send.
    """
    set_committed_value(
        record,
        'template',
        await db.get(ProductTemplate, record.template_id)
        if record.template_id is not None
        else None,
    )
    set_committed_value(
        record,
        'category',
        await db.get(Category, record.category_id)
        if record.category_id is not None
        else None,
    )
