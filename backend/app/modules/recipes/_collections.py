"""Recipe collection CRUD + membership."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import AuditAction, AuditTargetType
from app.core.exceptions import ConflictException, ServiceRejectionError
from app.core.module_sdk import hit_constraint
from app.core.public_api import core_api
from app.i18n.service import get_current_lang, get_error_message

from .models import RecipeCollection, RecipeCollectionMember
from .schemas import RecipeCollectionCreate, RecipeCollectionUpdate

_COLLECTION_NAME_UNIQUE = 'uq_recipe_collections_org_name'


def _name_taken(name: str) -> ConflictException:
    return ConflictException(
        'RECIPE_COLLECTION_NAME_TAKEN',
        get_error_message(
            'recipe_collection_name_taken', get_current_lang(), name=name
        ),
    )


def _collection_to_node(
    collection: RecipeCollection,
    counts: dict[UUID, int],
    children: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        'id': collection.id,
        'name': collection.name,
        'icon': collection.icon,
        'parent_id': collection.parent_id,
        'recipe_count': counts.get(collection.id, 0),
        'children': children,
    }


async def list_collections_async(
    db: AsyncSession, org_id: UUID
) -> list[dict[str, Any]]:
    """Return the org's collection tree (children nested), with recipe counts."""
    collections = (
        await db.scalars(
            select(RecipeCollection).where(RecipeCollection.organization_id == org_id)
        )
    ).all()
    if not collections:
        return []

    count_rows = (
        await db.execute(
            select(
                RecipeCollectionMember.collection_id,
                func.count(RecipeCollectionMember.id),
            )
            .where(
                RecipeCollectionMember.collection_id.in_([c.id for c in collections])
            )
            .group_by(RecipeCollectionMember.collection_id)
        )
    ).all()
    counts: dict[UUID, int] = {row[0]: row[1] for row in count_rows}

    by_id: dict[UUID, RecipeCollection] = {c.id: c for c in collections}
    roots: list[dict[str, Any]] = []
    nodes: dict[UUID, dict[str, Any]] = {}

    for collection in collections:
        nodes[collection.id] = _collection_to_node(collection, counts, [])

    for collection in collections:
        node = nodes[collection.id]
        parent_id = collection.parent_id
        parent = by_id.get(parent_id) if parent_id is not None else None
        if parent is not None:
            nodes[parent.id]['children'].append(node)
        else:
            roots.append(node)

    def _sort(nodes_list: list[dict[str, Any]]) -> list[dict[str, Any]]:
        nodes_list.sort(key=lambda n: n['name'].lower())
        for n in nodes_list:
            _sort(n['children'])
        return nodes_list

    return _sort(roots)


async def create_collection_async(
    db: AsyncSession,
    org_id: UUID,
    user_id: UUID,
    data: RecipeCollectionCreate,
) -> RecipeCollection:
    if data.parent_id is not None:
        parent = await db.scalar(
            select(RecipeCollection)
            .where(
                RecipeCollection.id == data.parent_id,
                RecipeCollection.organization_id == org_id,
            )
            .with_for_update()
        )
        if parent is None:
            raise ServiceRejectionError('recipe_collection_parent_not_found')

    name = data.name.strip()
    collection = RecipeCollection(
        organization_id=org_id,
        name=name,
        icon=data.icon,
        parent_id=data.parent_id,
        created_by=user_id,
    )
    try:
        # A duplicate is what this insert realistically runs into, and the
        # savepoint keeps the failure from poisoning the request's
        # transaction: the constraint answers 409 here instead of a bare 500
        # at commit. Any other integrity error is re-raised untouched.
        async with db.begin_nested():
            db.add(collection)
            await db.flush()
    except IntegrityError as exc:
        if hit_constraint(exc, _COLLECTION_NAME_UNIQUE):
            raise _name_taken(name) from exc
        raise
    await db.flush()
    await db.refresh(collection)
    return collection


async def update_collection_async(
    db: AsyncSession,
    org_id: UUID,
    collection_id: UUID,
    data: RecipeCollectionUpdate,
) -> RecipeCollection | None:
    collection = await db.scalar(
        select(RecipeCollection)
        .where(
            RecipeCollection.id == collection_id,
            RecipeCollection.organization_id == org_id,
        )
        .with_for_update()
    )
    if collection is None:
        return None

    payload = data.model_dump(exclude_unset=True)
    new_parent_id = payload.get('parent_id')
    if new_parent_id is not None:
        if new_parent_id == collection.id:
            raise ServiceRejectionError('recipe_collection_own_parent')
        parent = await db.scalar(
            select(RecipeCollection).where(
                RecipeCollection.id == new_parent_id,
                RecipeCollection.organization_id == org_id,
            )
        )
        if parent is None:
            raise ServiceRejectionError('recipe_collection_parent_not_found')
        # Reject cycles: walk up from the new parent and ensure we never
        # reach the collection being moved.
        cursor: RecipeCollection | None = parent
        while cursor is not None:
            if cursor.id == collection.id:
                raise ServiceRejectionError('recipe_collection_under_descendant')
            if cursor.parent_id is None:
                break
            cursor = await db.scalar(
                select(RecipeCollection).where(
                    RecipeCollection.id == cursor.parent_id,
                    RecipeCollection.organization_id == org_id,
                )
            )

    new_name = payload.get('name')
    if new_name is not None:
        new_name = new_name.strip()
        payload['name'] = new_name

    for field, value in payload.items():
        setattr(collection, field, value)

    try:
        async with db.begin_nested():
            await db.flush()
    except IntegrityError as exc:
        if new_name is not None and hit_constraint(exc, _COLLECTION_NAME_UNIQUE):
            raise _name_taken(new_name) from exc
        raise
    await db.flush()
    await db.refresh(collection)
    return collection


async def _descendants_async(
    db: AsyncSession, org_id: UUID, collection_id: UUID
) -> list[RecipeCollection]:
    """Every sub-collection under *collection_id*, level by level."""
    found: list[RecipeCollection] = []
    level = [collection_id]
    while level:
        rows = (
            await db.scalars(
                select(RecipeCollection)
                .where(
                    RecipeCollection.organization_id == org_id,
                    RecipeCollection.parent_id.in_(level),
                )
                .order_by(RecipeCollection.name)
            )
        ).all()
        found.extend(rows)
        level = [row.id for row in rows]
    return found


async def delete_collection_async(
    db: AsyncSession, org_id: UUID, collection_id: UUID, user_id: UUID
) -> bool:
    collection = await db.scalar(
        select(RecipeCollection).where(
            RecipeCollection.id == collection_id,
            RecipeCollection.organization_id == org_id,
        )
    )
    if collection is None:
        return False
    # The collection and everything under it is gone for good once the
    # request commits, so the deletion takes a row in the organization journal
    # (see ``AuditTargetType``: a working note's edits write nothing, its
    # deletion does). The sub-collections that go with it ride in the entry,
    # because no other table keeps their names. Same transaction as the delete.
    removed = await _descendants_async(db, org_id, collection.id)
    await core_api.audit_log.log_action_async(
        db,
        organization_id=org_id,
        user_id=user_id,
        action=AuditAction.HARD_DELETE,
        target_type=AuditTargetType.RECIPE_COLLECTION,
        target_id=collection.id,
        snapshot={'name': collection.name},
        meta_data=(
            {
                'removed_collections': [
                    {'id': str(child.id), 'name': child.name} for child in removed
                ]
            }
            if removed
            else None
        ),
    )
    # Children and members are removed via cascade (DB-level ondelete=CASCADE
    # plus ORM cascade for in-session deletes).
    await db.delete(collection)
    await db.flush()
    return True


async def add_recipe_to_collection_async(
    db: AsyncSession, org_id: UUID, collection_id: UUID, recipe_id: UUID
) -> bool:
    """Add a recipe to a collection. Returns True when added, False when it
    was already a member."""
    collection = await db.scalar(
        select(RecipeCollection)
        .where(
            RecipeCollection.id == collection_id,
            RecipeCollection.organization_id == org_id,
        )
        .with_for_update()
    )
    if collection is None:
        raise ServiceRejectionError('recipe_collection_not_found')

    from ._crud import get_recipe

    recipe = await get_recipe(db, recipe_id, org_id)
    if recipe is None:
        raise ServiceRejectionError('recipe_not_found')

    existing = await db.scalar(
        select(RecipeCollectionMember).where(
            RecipeCollectionMember.collection_id == collection_id,
            RecipeCollectionMember.recipe_id == recipe_id,
        )
    )
    if existing is not None:
        return False

    db.add(
        RecipeCollectionMember(
            collection_id=collection_id,
            recipe_id=recipe_id,
        )
    )
    await db.flush()
    return True


async def remove_recipe_from_collection_async(
    db: AsyncSession, org_id: UUID, collection_id: UUID, recipe_id: UUID
) -> bool:
    member = await db.scalar(
        select(RecipeCollectionMember)
        .join(
            RecipeCollection,
            RecipeCollection.id == RecipeCollectionMember.collection_id,
        )
        .where(
            RecipeCollectionMember.collection_id == collection_id,
            RecipeCollectionMember.recipe_id == recipe_id,
            RecipeCollection.organization_id == org_id,
        )
        .with_for_update()
    )
    if member is None:
        return False
    await db.delete(member)
    await db.flush()
    return True
