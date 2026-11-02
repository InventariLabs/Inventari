"""Service for creating complex storage location hierarchies atomically.

Not a second writer of locations: this module only resolves a *chain* (which
steps exist, which are made) and hands every row it creates to
``storage/_writes.create_storage``, so validation, journal and events live in
one place. ``storage/_reorg`` is the other batch path and answers a different
question — moving and deleting existing locations in one planned operation —
and shares no step logic with this chain-builder.
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.core.exceptions import (
    NotFoundException,
    ServiceRejectionError,
    catalogue_refusal,
)
from app.i18n.service import get_current_lang
from app.models.storage_location import StorageLocation
from app.schemas.storage_location import StorageHierarchyCreate, StorageLocationCreate


async def _find_child_by_name(
    db: AsyncSession,
    organization_id: Any,
    name: str,
    parent_id: Any,
) -> StorageLocation | None:
    """Find the child of *parent_id* that already carries *name*.

    Naming a location that exists is how somebody says *that one*. Resolving
    by id already worked that way; resolving by name only ever created, so
    adding a second shelf under a location the caller named was refused as a
    name collision. Siblings are unique by name, so this answer is unique.
    """
    result = await db.scalars(
        select(StorageLocation).where(
            StorageLocation.organization_id == organization_id,
            StorageLocation.name == name,
            StorageLocation.parent_id == parent_id,
        )
    )
    return result.first()


async def _create_node(
    db: AsyncSession,
    user: UserContextDTO,
    name: str,
    parent_id: Any,
) -> StorageLocation:
    """Add one step of the chain through the audited writer.

    Intermediate steps used to go straight to the model — a bare
    ``StorageLocation`` and a flush — while only the last step passed through
    ``storage/_writes.create_storage``. The journal then held leaf entries
    naming a parent whose own creation it never recorded, and the step skipped
    the interceptors and the ``location.created`` event besides. One writer for
    the whole chain: every created level earns its CREATE entry, written in
    the same transaction as the row.
    """
    from app.services.storage._writes import create_storage

    return await create_storage(
        db, StorageLocationCreate(name=name, parent_id=parent_id), user
    )


async def _get_in_org(db: AsyncSession, organization_id: Any, node_id: Any) -> Any:
    result = await db.scalars(
        select(StorageLocation).where(
            StorageLocation.id == node_id,
            StorageLocation.organization_id == organization_id,
        )
    )
    node = result.first()
    if node is None:
        raise NotFoundException('storage', get_current_lang())
    return node.id


async def _resolve_root(
    db: AsyncSession, data: StorageHierarchyCreate, user: UserContextDTO
) -> Any:
    """Return the id the chain hangs under, or None when it hangs under nothing.

    Naming no parent is not the same as having none: a chain whose first step
    is an ``id`` hangs under *that* location, and the branch below resolves
    it. A chain whose first step is a *name* is a new warehouse, and a new
    warehouse is a root — the same shape as every seeded one and as the one
    ``StorageRequired`` makes.

    Asking for a default root here instead created a top-level location named
    after the organization, flagged ``settings.is_default_site``, and hung
    the reader's warehouse one level beneath it: the storages card then wore
    an overline nobody had typed, the archive dialog offered "QA Many ›
    Magazyn › Regał" beside six paths that started at the warehouse, and the
    level itself could not be deleted from the interface. The organization is
    not a place; it owns them.
    """
    # The route calls require_org() before this runs, so the None branch is
    # unreachable over HTTP — it answers a caller that arrived without one
    # instead of letting the NOT NULL column answer for it.
    if user.organization_id is None:
        raise ServiceRejectionError('organization_required')

    if data.parent_id is not None:
        return await _get_in_org(db, user.organization_id, data.parent_id)

    return None


async def _walk_steps(
    db: AsyncSession,
    steps: list[Any],
    user: UserContextDTO,
    parent_id: Any,
) -> Any:
    """Resolve or create every step but the last, returning the last parent."""
    for step in steps:
        if step.id is not None:
            parent_id = await _get_in_org(db, user.organization_id, step.id)
            continue
        name = (step.name or '').strip()
        if not name:
            raise catalogue_refusal('location_chain_step_incomplete')
        existing = await _find_child_by_name(db, user.organization_id, name, parent_id)
        parent_id = (
            existing.id
            if existing is not None
            else (await _create_node(db, user, name, parent_id)).id
        )
    return parent_id


def _infer_behavior_mode(context_schema: list[str]) -> str:
    """Derive behavior_mode from the chosen tracking fields."""
    if 'freeze_date' in context_schema:
        return 'FREEZING'
    if 'expiry_date' in context_schema:
        return 'EXPIRY'
    return 'STOCK'


async def create_storage_hierarchy(
    db: AsyncSession, data: StorageHierarchyCreate, user: UserContextDTO
) -> StorageLocation:
    """Atomically create a chain of locations of any length (ADR-018).

    Resolves or creates each step inside a single DB transaction. The two
    ways of naming a step mean different things, and the difference is what
    the rest of the payload is for:

    - a step given by ``id`` is *that one* — it exists, and the fields
      describing a location are not applied to it;
    - a step given by ``name`` is *make this* — resolved among the previous
      step's children when it is an intermediate step, and created when it
      is the last one, so a name that is already taken there is a conflict
      rather than a silent hand-back of somebody else's shelf.
    """
    import uuid as _uuid

    from app.models.storage_type import StorageType
    from app.services.storage._writes import create_storage

    parent_id = await _resolve_root(db, data, user)
    *leading, last = data.steps
    parent_id = await _walk_steps(db, leading, user, parent_id)

    # The chain ends on a location that already exists: nothing to create.
    if last.id is not None:
        parent_id = await _get_in_org(db, user.organization_id, last.id)
        node = await db.get(StorageLocation, parent_id)
        if node is None:
            raise NotFoundException('storage', get_current_lang())
        return node

    leaf_name = (last.name or '').strip()
    if not leaf_name:
        raise catalogue_refusal('location_chain_step_incomplete')

    # 3. Resolve or create StorageType
    storage_type_id = data.location_type_id
    if storage_type_id is None and data.location_type is not None:
        st = data.location_type
        base = st.type_code.strip() or st.name.upper().replace(' ', '_').replace(
            '-', '_'
        )
        safe_code = ''.join(c for c in base if c.isalnum() or c == '_')
        safe_code = safe_code + '_' + str(_uuid.uuid4()).replace('-', '')[:6]
        schema = list(set(st.context_schema + ['name', 'quantity']))
        new_type = StorageType(
            organization_id=user.organization_id,
            name=st.name,
            type_code=safe_code,
            icon=st.icon,
            behavior_mode=st.behavior_mode,
            context_schema=schema,
            field_definitions=st.field_definitions,
            created_by=user.id,
        )
        db.add(new_type)
        await db.flush()
        storage_type_id = new_type.id

    location_schema = data.context_schema or []
    location_field_defs: list[Any] = list(data.field_definitions or [])
    if not location_schema and storage_type_id:
        linked_type_result = await db.scalars(
            select(StorageType).where(StorageType.id == storage_type_id)
        )
        linked_type = linked_type_result.first()
        if linked_type:
            location_schema = linked_type.context_schema or []
            if not location_field_defs:
                location_field_defs = linked_type.field_definitions or []

    behavior_mode = _infer_behavior_mode(location_schema)

    # Auto-infer context_tag from behavior_mode when not explicitly set
    context_tag = data.context_tag
    if context_tag is None and behavior_mode in ('EXPIRY', 'FREEZING'):
        context_tag = 'food'

    # 4. Create the Storage itself
    storage_in = StorageLocationCreate(
        name=leaf_name,
        description=data.description,
        parent_id=parent_id,
        location_type_id=storage_type_id,
        context_schema=location_schema,
        behavior_mode=behavior_mode,
        field_definitions=location_field_defs,
        short_code=data.short_code,
        context_tag=context_tag,
    )

    # No commit here — the whole chain (root resolution, the walked
    # steps, this leaf) is one unit of work, and the docstring's
    # "atomically" is the caller's commit to make, not this function's.
    # Use our existing create_storage to ensure interceptors are run!
    return await create_storage(db, storage_in, user)
