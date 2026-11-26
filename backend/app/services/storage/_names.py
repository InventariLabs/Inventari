"""The sibling-name rule: a place's name is taken once per level.

One rule, read here and by every writer that inserts or renames a top-level
place — the storage service, the seeds that create an organization's starting
places, and the module declarations that add their own. The database settles
two writers that both read a free name; the savepoint turns that into the same
refusal the read gives instead of a constraint's own error.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db_utils import hit_constraint
from app.core.exceptions import ConflictException
from app.i18n.service import get_current_lang, get_error_message
from app.models.storage_location import StorageLocation

__all__ = [
    'check_name_unique_async',
    'flush_under_the_name_rule',
    'free_to_take_async',
    'name_rule_held_by_the_database',
    'name_taken',
    'sibling_with_name_async',
]

#: The two unique indexes behind the sibling-name rule (the model declares
#: them): one for the places under a parent, one for the top level.
_NAME_INDEXES = (
    'uq_storage_locations_org_parent_name',
    'uq_storage_locations_org_root_name',
)


def name_taken(name: str) -> ConflictException:
    """The 409 a taken sibling name answers, naming the name."""
    return ConflictException(
        code='STORAGE_CONFLICT',
        message=get_error_message(
            'storage_name_collision', get_current_lang(), name=name
        ),
    )


async def sibling_with_name_async(
    db: AsyncSession,
    organization_id: UUID | None,
    name: str,
    parent_id: UUID | None = None,
    exclude_id: UUID | None = None,
) -> StorageLocation | None:
    """The row that already holds *name* beside the place being written."""
    query = select(StorageLocation).where(
        StorageLocation.organization_id == organization_id,
        StorageLocation.name == name,
        StorageLocation.parent_id == parent_id,
    )
    if exclude_id is not None:
        query = query.where(StorageLocation.id != exclude_id)
    return (await db.scalars(query)).first()


async def check_name_unique_async(
    db: AsyncSession,
    organization_id: UUID | None,
    name: str,
    parent_id: UUID | None = None,
    exclude_id: UUID | None = None,
) -> None:
    """Raise 409 if a sibling with the same name already exists.

    Typed here rather than left to the endpoint, so every caller sees the same
    collision as the same error. Each endpoint mapping one bare ``ValueError``
    its own way would leave a client telling "bad name" from "name taken" to
    read the English sentence, which the copy gate forbids.
    """
    if await sibling_with_name_async(
        db, organization_id, name, parent_id=parent_id, exclude_id=exclude_id
    ):
        raise name_taken(name)


async def free_to_take_async(
    db: AsyncSession, place: StorageLocation, name: str
) -> bool:
    """Whether *place* can be renamed to *name* on the level it stands on.

    The question of a rename nobody asked for, such as a seeded row joining
    the reader's language: the row keeps its name when the answer is no, and
    the operation that ran the seed goes on.
    """
    holder = await sibling_with_name_async(
        db,
        place.organization_id,
        name,
        parent_id=place.parent_id,
        exclude_id=place.id,
    )
    return holder is None


@asynccontextmanager
async def name_rule_held_by_the_database(
    db: AsyncSession, name: str
) -> AsyncIterator[None]:
    """Answer a sibling-name index violation the way the read answers it.

    ``check_name_unique_async`` reads before the write, so two requests that
    both read before either wrote each saw a free name; the second insert then
    meets the unique index. That is the same 409 the read gives, not a 500.
    The savepoint keeps the failed statement from poisoning the caller's
    transaction. Any other integrity error is re-raised untouched.
    """
    try:
        async with db.begin_nested():
            yield
    except IntegrityError as exc:
        if hit_constraint(exc, *_NAME_INDEXES):
            raise name_taken(name) from exc
        raise


async def flush_under_the_name_rule(db: AsyncSession, name: str) -> None:
    async with name_rule_held_by_the_database(db, name):
        await db.flush()
