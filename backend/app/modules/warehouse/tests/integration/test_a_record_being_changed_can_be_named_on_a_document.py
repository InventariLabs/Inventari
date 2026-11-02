"""A record being changed can still be named on a new document.

Changing a record's quantity locks its row first. The lock was FOR UPDATE,
which also stops the FOR KEY SHARE that every insert referring to the row
takes to check its foreign key — a document line naming the record, say. A
document being drafted therefore waited for every record it named to finish
changing, and a two-line document drafted while another document completed
could close a circle with it: each held one of two records the other wanted,
and the database aborted one of them, which the person saw as an error on a
document nothing was wrong with.

The quantity is not part of the record's key. FOR NO KEY UPDATE keeps two
changes of one record apart just the same and lets the foreign key check
through. Here one transaction holds the record as a change would, and the
draft naming it must go through within a second.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.core.public_api import core_api
from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.modules.warehouse._document_workflow_crud import create_document
from app.modules.warehouse.document_profile_service import get_or_create_profile
from app.modules.warehouse.schemas import DocumentCreate, DocumentLineCreate
from tests.integration._shelf import put_on_shelf

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _async_test_url() -> str:
    return settings.DATABASE_URL.replace('postgresql://', 'postgresql+asyncpg://', 1)


async def test_a_draft_names_a_record_another_transaction_is_changing(
    real_async_db_session: AsyncSession,
) -> None:
    db = real_async_db_session
    org = Organization(
        name=f'Named while changing {uuid.uuid4().hex[:6]}',
        enabled_modules=['core', 'items', 'locations', 'warehouse'],
    )
    db.add(org)
    await db.flush()
    user = await ModuleTestHelper.create_user_async(
        db, org, email=f'named_{uuid.uuid4().hex[:8]}@test.com', role='admin'
    )
    shelf = StorageLocation(organization_id=org.id, created_by=user.id, name='Pantry')
    db.add(shelf)
    template = ProductTemplate(
        organization_id=org.id, name='Lentils', sku=f'lentils-{uuid.uuid4().hex[:8]}'
    )
    db.add(template)
    await db.flush()
    record = await put_on_shelf(db, user, template, shelf.id, 10)
    await get_or_create_profile(db, org.id)
    await db.commit()
    org_id, user_id, shelf_id, template_id, record_id = (
        org.id,
        user.id,
        shelf.id,
        template.id,
        record.id,
    )

    engine = create_async_engine(_async_test_url(), echo=False, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    waited: DBAPIError | None = None
    try:
        async with factory() as changing, factory() as drafting:
            # Held as the door that changes a record's quantity holds it.
            assert await core_api.items.get_for_update_async(
                changing, org_id, record_id
            )
            await drafting.execute(text("SET lock_timeout = '1s'"))
            try:
                await create_document(
                    drafting,
                    org_id,
                    DocumentCreate(
                        type='OUT',
                        source_location_id=shelf_id,
                        lines=[
                            DocumentLineCreate(
                                item_id=record_id,
                                product_template_id=template_id,
                                expected_quantity=Decimal('1'),
                            )
                        ],
                    ),
                    user_id,
                )
            except DBAPIError as exc:
                waited = exc
                await drafting.rollback()
            await changing.rollback()
    finally:
        await engine.dispose()

    assert waited is None, (
        f'the draft waited for the record to finish changing: {waited}'
    )
