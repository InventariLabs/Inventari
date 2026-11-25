"""Recipe collections stay a tree when two moves cross.

A move checks for a cycle by walking up from the new parent. Two moves that
cross -- Dinners under Carbonara (a child of Pasta) in one request, Pasta under
Dinners in another -- would each walk a tree in which the other move has not
happened yet, both pass, and the three would end up parented on each other in a
ring: off the sidebar, which builds the tree from its roots, and a loop for
anything that walks down from any of them. Every move under a parent therefore
queues on one lock per organization's tree, so the second walk sees what the
first committed.

The descendant walk of a delete keeps the ids it has seen, so even a loop
already in the table ends the walk instead of holding the worker.
"""

from __future__ import annotations

import asyncio
from uuid import UUID

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ServiceRejectionError
from app.core.testing import ModuleTestHelper
from app.models.audit_log import AuditLog
from app.models.organization import Organization
from app.models.user import User
from app.modules.recipes._collections import (
    create_collection_async,
    delete_collection_async,
    update_collection_async,
)
from app.modules.recipes.models import RecipeCollection
from app.modules.recipes.schemas import RecipeCollectionCreate, RecipeCollectionUpdate

pytestmark = pytest.mark.integration


async def _org_and_user(db: AsyncSession, email: str) -> tuple[Organization, User]:
    org = Organization(name='Collection Tree Org', enabled_modules=['core', 'recipes'])
    db.add(org)
    await db.flush()
    user = await ModuleTestHelper.create_user_async(db, org, email=email, role='admin')
    return org, user


async def _waiting_on_a_lock(db: AsyncSession, pid: int) -> bool:
    """Whether backend *pid* is queued on a lock it has not been granted."""
    waiting = await db.scalar(
        text('SELECT count(*) FROM pg_locks WHERE pid = :pid AND NOT granted'),
        {'pid': pid},
    )
    return bool(waiting)


async def test_the_second_of_two_crossed_moves_is_refused(
    real_async_db_session: AsyncSession,
) -> None:
    db = real_async_db_session
    org, user = await _org_and_user(db, 'crossed-moves@example.com')
    dinners = await create_collection_async(
        db, org.id, user.id, RecipeCollectionCreate(name='Dinners')
    )
    pasta = await create_collection_async(
        db, org.id, user.id, RecipeCollectionCreate(name='Pasta')
    )
    carbonara = await create_collection_async(
        db,
        org.id,
        user.id,
        RecipeCollectionCreate(name='Carbonara', parent_id=pasta.id),
    )
    await db.commit()

    first = AsyncSession(bind=db.bind, expire_on_commit=False)
    second = AsyncSession(bind=db.bind, expire_on_commit=False)
    try:
        # The first request moves Dinners under Carbonara and has not
        # committed yet.
        await update_collection_async(
            first, org.id, dinners.id, RecipeCollectionUpdate(parent_id=carbonara.id)
        )
        second_pid = await second.scalar(text('SELECT pg_backend_pid()'))
        assert second_pid is not None

        async def move_pasta_under_dinners() -> str:
            try:
                await update_collection_async(
                    second,
                    org.id,
                    pasta.id,
                    RecipeCollectionUpdate(parent_id=dinners.id),
                )
            except ServiceRejectionError as refusal:
                await second.rollback()
                return refusal.key
            await second.commit()
            return 'moved'

        crossing = asyncio.create_task(move_pasta_under_dinners())
        # Let the second move run until it either finishes or queues behind
        # the first; only then does the first commit.
        for _ in range(500):
            if crossing.done() or await _waiting_on_a_lock(db, second_pid):
                break
            await asyncio.sleep(0.01)
        await first.commit()
        outcome = await asyncio.wait_for(crossing, timeout=10)
    finally:
        await first.close()
        await second.close()

    parents: dict[UUID, UUID | None] = {
        row.id: row.parent_id
        for row in (
            await db.execute(
                select(RecipeCollection.id, RecipeCollection.parent_id).where(
                    RecipeCollection.organization_id == org.id
                )
            )
        ).all()
    }
    assert parents == {
        dinners.id: carbonara.id,
        carbonara.id: pasta.id,
        pasta.id: None,
    }
    assert outcome == 'recipe_collection_under_descendant'


async def test_a_delete_ends_on_a_loop_already_in_the_table(
    real_async_db_session: AsyncSession,
) -> None:
    db = real_async_db_session
    org, user = await _org_and_user(db, 'looped-delete@example.com')
    dinners = await create_collection_async(
        db, org.id, user.id, RecipeCollectionCreate(name='Dinners')
    )
    pasta = await create_collection_async(
        db, org.id, user.id, RecipeCollectionCreate(name='Pasta')
    )
    # A loop written past the service: what two unserialised crossed moves leave.
    dinners.parent_id = pasta.id
    pasta.parent_id = dinners.id
    await db.flush()

    deleted = await asyncio.wait_for(
        delete_collection_async(db, org.id, dinners.id, user.id), timeout=10
    )

    assert deleted is True
    left = await db.scalars(
        select(RecipeCollection.id).where(RecipeCollection.organization_id == org.id)
    )
    assert left.all() == []
    entry = await db.scalar(
        select(AuditLog).where(
            AuditLog.organization_id == org.id,
            AuditLog.target_type == 'recipe_collection',
        )
    )
    assert entry is not None
    assert entry.meta_data == {
        'removed_collections': [{'id': str(pasta.id), 'name': 'Pasta'}]
    }
