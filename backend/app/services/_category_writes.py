from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import build_module_context
from app.core.contracts import UserContextDTO
from app.core.events import SystemEvent, TenantEventPayload, event_bus
from app.core.exceptions import ServiceRejectionError
from app.core.interceptors import interceptor_pipeline
from app.core.logging import get_logger
from app.models.audit_log import AuditAction, AuditTargetType
from app.models.category import Category
from app.schemas.category import CategoryCreate, CategoryUpdate
from app.services.audit_service import audit_key, audit_value, log_action_async

from ._category_reads import _merge_field_definitions

logger = get_logger(__name__)


def _org_id(user: UserContextDTO) -> UUID:
    """The caller's organization, asserted — every write path here has
    already refused to run without one."""
    assert user.organization_id is not None
    return user.organization_id


async def _get_or_create_fork(
    db: AsyncSession,
    category: Category,
    org_id: UUID | None,
    *,
    is_active: bool,
    deactivate_existing: bool = False,
) -> Category:
    """Return the org's fork of a system category, creating it if missing.

    Unified fork logic — the update path copied the full visual
    identity (emoji/color) while the delete path dropped it and
    hardcoded ``is_active=False``. The fork now always copies the full
    identity; the caller chooses the activation state.
    """
    # A NULL code cannot be matched (multiple system categories could
    # share NULL code), and self-match must be excluded. Guard both.
    result = await db.scalars(
        select(Category).where(
            Category.code == category.code,
            Category.code.is_not(None),
            Category.organization_id == org_id,
            Category.id != category.id,
        )
    )
    existing = result.first()
    if existing:
        if deactivate_existing:
            existing.is_active = False
        return existing
    new_cat = Category(
        name=category.name,
        code=category.code,
        organization_id=org_id,
        context_tag=category.context_tag,
        group_label=category.group_label,
        icon=category.icon,
        emoji=category.emoji,
        color=category.color,
        sort_order=category.sort_order,
        meta_data=category.meta_data,
        field_definitions=category.field_definitions,
        is_active=is_active,
    )
    db.add(new_cat)
    return new_cat


async def create_category(
    db: AsyncSession, category_in: CategoryCreate, user: UserContextDTO
) -> Category:
    """Create a new category after running interceptors."""
    category_data = category_in.model_dump(exclude_unset=True)

    # is_system is the catalog's flag: module declarations and seed profiles
    # grant it, clients never do — the update merge already strips attempted
    # grants, and create must not become the side door around it.
    if category_data.get('field_definitions'):
        category_data['field_definitions'] = [
            {k: v for k, v in fd.items() if k != 'is_system'}
            for fd in category_data['field_definitions']
        ]

    context = build_module_context(db, user.organization_id, user)

    # Run before-create interceptors
    category_data = await interceptor_pipeline.run_before_category_create(
        category_data, context
    )

    # Check if category with this name already exists for this org (or global)
    result = await db.scalars(
        select(Category).where(
            Category.name == category_data['name'],
            (Category.organization_id == user.organization_id)
            | (Category.organization_id.is_(None)),
        )
    )
    existing = result.first()

    if existing:
        raise ServiceRejectionError('category_name_taken')

    # Remove fields not in model
    model_columns = Category.__table__.columns.keys()
    final_data = {k: v for k, v in category_data.items() if k in model_columns}

    category = Category(**final_data)
    category.organization_id = user.organization_id

    db.add(category)
    # The id is assigned by the database; flush before the journal names it.
    await db.flush()
    await log_action_async(
        db,
        organization_id=_org_id(user),
        user_id=user.id,
        action=AuditAction.CREATE,
        target_type=AuditTargetType.CATEGORY,
        target_id=category.id,
        snapshot={
            'name': category.name,
            'context_tag': category.context_tag,
        },
    )
    await db.flush()
    await db.refresh(category)
    await event_bus.emit_transactional(
        db,
        SystemEvent.CATEGORY_CREATED,
        TenantEventPayload.model_validate(
            {
                'organization_id': str(user.organization_id),
                'category_id': str(category.id),
            }
        ),
    )
    await interceptor_pipeline.run_after_category_create(
        category.id, category_data, context
    )
    return category


# The pair this module's journal keys come from: the update path builds its
# `before` from the payload (`audited_fields` below), so every key it can
# write is a field the schema and the model share. The snapshot-key exporter
# reads this declaration (backend/scripts/export_audit_snapshot_keys.py); a
# writer of the same shape declares its own pair beside its own loop.
AUDIT_PAYLOAD_SCHEMA = ('CategoryUpdate', 'Category')


async def update_category(
    db: AsyncSession,
    category: Category,
    category_in: CategoryUpdate,
    user: UserContextDTO,
) -> Category:
    """Update category after running interceptors and handling forking."""
    update_data = category_in.model_dump(exclude_unset=True)

    context = build_module_context(db, user.organization_id, user)

    # Run before-update interceptors
    update_data = await interceptor_pipeline.run_before_category_update(
        category.id, update_data, context
    )

    # Before-values read off the category as it arrived: for a system
    # category the update re-binds to the organization's fork, and the diff
    # the journal shows has to stay truthful about what the reader changed.
    audited_fields = [f for f in update_data if hasattr(category, f)]
    before = {f: getattr(category, f) for f in audited_fields}

    # If it's a system category, fork it for the organization
    if category.organization_id is None:
        category = await _get_or_create_fork(
            db, category, user.organization_id, is_active=category.is_active
        )

    for field, value in update_data.items():
        if field == 'field_definitions':
            # The label of a system field is the catalog's word (see
            # _merge_field_definitions): renamed, it would be stored where no
            # screen reads it, because every reader takes the translated
            # catalog label. Refuse the rename instead of swallowing it.
            #
            # A rename is what the entry actually SAYS: a label it carries
            # and that differs from the stored one. An entry with no label
            # (the key absent, or `label: null` — the schema's own "unset",
            # which full-model serializers always send) names no field, so
            # there is no rename in it to refuse; `None != 'Asset Tag'` used
            # to read as one, which answered 400 'the name belongs to the
            # product catalog' to a request that never mentioned a name, and
            # made a change of type or required pass only when the client
            # echoed the raw stored label back. The merge keeps the stored
            # name for such an entry, so the honest answer is to let the
            # edit through.
            existing_by_key = {f['key']: f for f in (category.field_definitions or [])}
            for incoming in value or []:
                prior = existing_by_key.get(incoming.get('key'))
                if (
                    prior
                    and prior.get('is_system')
                    and incoming.get('label') is not None
                    and incoming.get('label') != prior.get('label')
                ):
                    # ServiceRejectionError, not plain ValueError: the key
                    # gives the 400 its code and the reader's language.
                    #
                    # The {field} the keyed message interpolates carries the
                    # stored label, not the key: a key like `asset_tag` is a
                    # word no screen shows. The label is passed in rather
                    # than resolved here on purpose — the backend keeps no
                    # per-locale field-label catalogue, and the frontend
                    # namespaces name one key differently, so a backend-side
                    # lookup would be a third naming authority guaranteed to
                    # drift.
                    #
                    # The decision on one name for one field: the field
                    # builder shows a typed system field under the
                    # catalogue's translated word, lists an untyped
                    # visibility flag (category_id) not at all, and offers no
                    # control to rename either, so this refusal is reached
                    # only by an API client, which reads the definition it
                    # sent — and that carries the stored label. Every seeded
                    # definition names itself (a test pins it); the key is
                    # only the backstop for a definition stored by an older
                    # seeding without a label.
                    raise ServiceRejectionError(
                        'category_system_field_label_locked',
                        field=prior.get('label') or prior.get('key'),
                    )
            setattr(
                category,
                field,
                _merge_field_definitions(category.field_definitions, value),
            )
        elif hasattr(category, field):
            setattr(category, field, value)
    await db.flush()
    await db.refresh(category)

    after = {f: getattr(category, f) for f in audited_fields}
    # Compared as numbers, written down as digits: a form that posts `1`
    # against a stored `1.000` has changed nothing, and the row that does get
    # written must still say what the value was.
    changed = {f for f in audited_fields if audit_key(before[f]) != audit_key(after[f])}
    if changed:
        await log_action_async(
            db,
            organization_id=_org_id(user),
            user_id=user.id,
            action=AuditAction.UPDATE,
            target_type=AuditTargetType.CATEGORY,
            target_id=category.id,
            snapshot={
                'name': category.name,
                'before': {f: audit_value(before[f]) for f in changed},
                'after': {f: audit_value(after[f]) for f in changed},
            },
        )
    await event_bus.emit_transactional(
        db,
        SystemEvent.CATEGORY_UPDATED,
        TenantEventPayload.model_validate(
            {
                'organization_id': str(user.organization_id),
                'category_id': str(category.id),
            }
        ),
    )
    await interceptor_pipeline.run_after_category_update(
        category.id, update_data, context
    )
    return category


async def rename_category_group(
    db: AsyncSession,
    *,
    organization_id: UUID,
    user: UserContextDTO,
    current_name: str,
    new_name: str | None,
    category_ids: list[UUID] | None = None,
) -> list[UUID]:
    """Give every category in a group a different group label, or none.

    A group is not a record. It is a label typed on each category that has
    it, so the only way to rename one used to be to open every category
    carrying it — and the food profile seeds a dozen or more per group.

    Each category goes through :func:`update_category`, which is what makes a
    catalogue category belonging to no organisation fork into this one before
    it changes: renaming a group here must not rename it for every tenant
    reading the same shared row.

    ``category_ids`` selects the categories by id instead of by their current
    label: it is how a removed group is put back in one request, since after
    the removal there is no label left to find them by. The ids are the ones
    this function returned, which are the organisation's forks.

    Returns the ids of the categories that were changed.
    """
    from ._category_reads import get_categories_async

    categories = [
        category
        for category in await get_categories_async(
            db, organization_id, include_inactive=True
        )
        if (
            category.id in category_ids
            if category_ids is not None
            else category.group_label == current_name
        )
    ]
    changed: list[UUID] = []
    for category in categories:
        updated = await update_category(
            db, category, CategoryUpdate(group_label=new_name), user
        )
        changed.append(updated.id)
    logger.info(
        'Category group renamed: %r -> %r org=%s categories=%d',
        current_name,
        new_name,
        organization_id,
        len(categories),
    )
    return changed


async def delete_category(
    db: AsyncSession, category: Category, user: UserContextDTO
) -> None:
    """Delete category after running interceptors and handling system categories."""
    from sqlalchemy import func

    from app.models.item import Item

    context = build_module_context(db, user.organization_id, user)

    # Run before-delete interceptors
    await interceptor_pipeline.run_before_category_delete(category.id, context)

    if category.organization_id is None:
        fork = await _get_or_create_fork(
            db,
            category,
            user.organization_id,
            is_active=False,
            deactivate_existing=True,
        )
        # The fork may have been created here; flush so its id exists for
        # the journal entry below.
        await db.flush()
        await log_action_async(
            db,
            organization_id=_org_id(user),
            user_id=user.id,
            # A "delete" of a system category deactivates this
            # organization's fork — the shared row stays for everyone
            # else, so the journal says soft delete, not hard.
            action=AuditAction.SOFT_DELETE,
            target_type=AuditTargetType.CATEGORY,
            target_id=fork.id,
            snapshot={'name': category.name},
        )
        await db.flush()
        category_id = fork.id

        await event_bus.emit_transactional(
            db,
            SystemEvent.CATEGORY_DELETED,
            TenantEventPayload.model_validate(
                {
                    'organization_id': str(user.organization_id),
                    'category_id': str(category_id),
                }
            ),
        )
        return

    # Check if items are using this category
    count_result = await db.scalars(
        select(func.count(Item.id)).where(Item.category_id == category.id)
    )
    items_count = count_result.first() or 0
    if items_count > 0:
        raise ServiceRejectionError(
            'category_delete_blocked_by_items', count=items_count
        )

    category_id = category.id
    # Written before the delete, and written whole: this deletion is permanent
    # by design — the dialog says so — which leaves the journal as the only
    # place the category's configuration survives. A name alone is not enough
    # to put back an icon, a colour, a group and a set of custom fields, so
    # whoever deleted a category they had configured rebuilt it from memory.
    await log_action_async(
        db,
        organization_id=_org_id(user),
        user_id=user.id,
        action=AuditAction.HARD_DELETE,
        target_type=AuditTargetType.CATEGORY,
        target_id=category_id,
        snapshot={
            'name': category.name,
            'code': category.code,
            'icon': category.icon,
            'emoji': category.emoji,
            'color': category.color,
            'group_label': category.group_label,
            'context_tag': category.context_tag,
            'field_definitions': category.field_definitions,
        },
    )
    await db.delete(category)
    await db.flush()
    await event_bus.emit_transactional(
        db,
        SystemEvent.CATEGORY_DELETED,
        TenantEventPayload.model_validate(
            {
                'organization_id': str(user.organization_id),
                'category_id': str(category_id),
            }
        ),
    )
    await interceptor_pipeline.run_after_category_delete(category_id, context)
