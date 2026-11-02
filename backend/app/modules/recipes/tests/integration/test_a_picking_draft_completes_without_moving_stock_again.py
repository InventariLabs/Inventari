"""The RW draft a picking session leaves behind records stock that already left.

Picking takes each ingredient off the shelf as it is picked, and the RW document
registered afterwards is the register's copy of that movement. It was an
ordinary draft: confirming it reserved the quantity again and completing it
dispatched it again, so one meal was taken off the shelf twice the moment
someone finished the document the register was offering them.

The draft stays a draft, but it is marked as a record of a movement that was
already applied: confirming holds nothing, completing moves nothing.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.testing import ModuleTestHelper
from app.models.item import Item
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.stock_move import StockMove
from app.models.storage_location import StorageLocation
from app.modules.recipes._picking_document import register_picking_as_document_async
from app.modules.recipes.models import Recipe, RecipeIngredient
from app.modules.warehouse._document_workflow_transitions import (
    complete_document,
    confirm_document,
)
from app.modules.warehouse.models import Document
from app.modules.warehouse.schemas import DocumentComplete
from tests.integration._shelf import put_on_shelf

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _on_shelf(db: AsyncSession, template_id: uuid.UUID) -> Decimal:
    db.expire_all()
    total = await db.scalar(
        select(func.coalesce(func.sum(Item.quantity), 0)).where(
            Item.template_id == template_id, Item.is_deleted.is_(False)
        )
    )
    return Decimal(total or 0)


async def _registered_draft(db: AsyncSession) -> tuple[Document, uuid.UUID, uuid.UUID]:
    """A finished picking session that took 3 of 10 and registered its RW draft."""
    org = Organization(
        name=f'Picking RW {uuid.uuid4().hex[:6]}',
        enabled_modules=['core', 'items', 'locations', 'recipes', 'warehouse'],
    )
    db.add(org)
    await db.flush()
    user = await ModuleTestHelper.create_user_async(
        db, org, email=f'pick_rw_{uuid.uuid4().hex[:8]}@test.com', role='admin'
    )
    shelf = StorageLocation(organization_id=org.id, created_by=user.id, name='Pantry')
    db.add(shelf)
    await db.flush()
    template = ProductTemplate(
        organization_id=org.id, name='Flour', sku=f'flour-{uuid.uuid4().hex[:8]}'
    )
    db.add(template)
    await db.flush()
    record = await put_on_shelf(db, user, template, shelf.id, 10)
    recipe = Recipe(
        organization_id=org.id, name='Bread', servings=1, created_by=user.id
    )
    db.add(recipe)
    await db.flush()
    ingredient = RecipeIngredient(
        recipe_id=recipe.id, name='Flour', quantity=Decimal('3'), sort_order=0
    )
    db.add(ingredient)
    await db.flush()
    await db.commit()

    # What the picking flow did on the way: 3 of the 10 left the record.
    record.quantity = Decimal('7')
    await db.commit()

    picked = MagicMock()
    picked.status = 'picked'
    picked.item_id = record.id
    picked.ingredient_id = ingredient.id
    picked.quantity_consumed = Decimal('3')
    picked.consumed_valuation_rate = None
    session = MagicMock()
    session.id = uuid.uuid4()
    session.recipe_id = recipe.id
    session.recipe = recipe
    session.notes = None
    session.items = [picked]

    with patch(
        'app.modules.recipes._picking_document.core_api.settings.get_async',
        AsyncMock(return_value=True),
    ):
        doc_id = await register_picking_as_document_async(db, session, org.id, user.id)
    assert doc_id is not None
    doc = await db.get(Document, uuid.UUID(doc_id))
    assert doc is not None
    return doc, user.id, template.id


async def test_completing_the_registered_draft_leaves_the_shelf_as_picking_left_it(
    real_async_db_session: AsyncSession,
) -> None:
    db = real_async_db_session
    doc, user_id, template_id = await _registered_draft(db)
    org_id, doc_id = doc.organization_id, doc.id
    assert await _on_shelf(db, template_id) == Decimal('7')

    await confirm_document(db, org_id, doc_id, user_id)
    done = await complete_document(
        db, org_id, doc_id, user_id, DocumentComplete(complete_as_planned=True)
    )

    assert done.status == 'COMPLETED'
    assert await _on_shelf(db, template_id) == Decimal('7')
    issued = await db.scalar(
        select(func.count())
        .select_from(StockMove)
        .where(
            StockMove.product_template_id == template_id,
            StockMove.reference_type == 'document',
            StockMove.reference_id == doc_id,
        )
    )
    assert issued == 0
