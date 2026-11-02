from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.category import Category
from app.models.item import Item


def _merge_field_definitions(
    existing: list[dict] | None,
    update: list[dict] | None,
) -> list[dict]:
    """Merge field_definitions while preserving is_system flags.

    - System fields (is_system=True) from the existing list are retained even if
      absent from the update list — they cannot be removed by users.
    - User-supplied fields are added or merged on top by key.
    - Users cannot grant is_system=True to new or existing fields.

    The entry rule: an incoming entry is a patch, not a replacement. It
    overrides the keys it carries and leaves the rest as stored — so an
    entry that changes ``type`` or ``required`` and names no ``label`` keeps
    the stored name instead of erasing it, and need not echo the stored
    label back to be allowed to edit at all. ``label: None`` carries no
    name either (it is the schema's own "unset", and full-model serializers
    always send it), so it does not erase; naming a field blank is
    ``label: ''``. Only a label the entry actually *says* is compared with
    the stored one — by the lock one call up, not here.

    The label lock itself: this merge enforces none. The lock lives one call
    up, in ``update_category`` (``_category_writes``), which refuses a
    payload that renames a system field *before* this function runs — so by
    the time a system field reaches the merge, its label is either the
    stored one (payload omitted the name, stored definition passes its name
    through) or byte-identical to the stored one (the caller has already
    verified the payload's copy). A user field's label is the user's own
    words and merges verbatim — there is nothing to translate and nothing
    to lock.

    The deletion rule — the resolution, recorded because the pin looks like
    a swallow: there is no delete verb for a system field in this contract,
    so omission is silence about one, not a command to remove one. This
    list is the roster of the client's own fields; its entries edit what
    they name and its omissions drop what the client owns. A system field
    is neither — its name AND its presence belong to the catalog
    (``is_system`` is the catalog's flag), and nothing in a payload can say
    "this one goes" any more than it can say "this one is renamed" (which
    ``update_category`` refuses). Keeping the field and answering 200 with
    it still in the body is the truth: the write did not touch it. A
    refusal would invent a deletion the payload never made, and would force
    every client to echo the whole catalog roster to change one field's
    type — the very echo this contract must not require. The screen keeps
    the same rule from its side: a system field's row has no remove control.
    """
    if update is None:
        return existing or []

    existing_by_key: dict[str, dict] = {f['key']: f for f in (existing or [])}
    result: dict[str, dict] = {}

    # Apply user's update as a patch over the stored entry, stripping any
    # attempted is_system grants.
    for field in update:
        key = field['key']
        prior = existing_by_key.get(key)
        merged: dict = {} if prior is None else dict(prior)
        for k, v in field.items():
            if k == 'is_system':
                continue
            if k == 'label' and v is None:
                # No name carried — the stored name stands (see the entry rule).
                continue
            merged[k] = v
        # Carry over existing is_system flag if set — user cannot override it
        if prior and prior.get('is_system'):
            merged['is_system'] = True
        result[key] = merged

    # Preserve existing system fields not included in user's update list
    for key, field in existing_by_key.items():
        if field.get('is_system') and key not in result:
            result[key] = field

    return list(result.values())


async def get_categories_async(
    db: AsyncSession, organization_id: UUID, include_inactive: bool = False
) -> list[Category]:
    """Fetch all categories visible to organization (org-specific + system)."""
    query = select(Category).where(
        or_(
            Category.organization_id == organization_id,
            Category.organization_id.is_(None),
        )
    )
    if not include_inactive:
        query = query.where(Category.is_active.is_(True))

    result = await db.scalars(query.order_by(Category.sort_order, Category.name))
    return list(result.all())


async def count_items_per_category_async(
    db: AsyncSession, organization_id: UUID
) -> dict[UUID, int]:
    """How many products each category holds, keyed by category id.

    A product is counted once however many records it has: a tin held on
    three shelves and in two batches is five records and one product, and the
    card says "products". A record without a catalogue card is its own
    product.

    One grouped query rather than a count per card: a list of 76 categories
    would otherwise be 76 round trips. Categories nobody filed anything under
    are absent from the result — callers default them to zero.
    """
    rows = await db.execute(
        select(
            Item.category_id,
            func.count(func.distinct(func.coalesce(Item.template_id, Item.id))),
        )
        .where(
            Item.organization_id == organization_id,
            Item.is_deleted.is_(False),
            Item.category_id.isnot(None),
        )
        .group_by(Item.category_id)
    )
    return dict(rows.all())  # type: ignore[arg-type]


async def get_by_id_async(
    db: AsyncSession, organization_id: UUID, category_id: UUID
) -> Category | None:
    """Fetch a category by ID visible to *organization_id* (org-specific + system)."""
    result = await db.scalar(
        select(Category).where(
            Category.id == category_id,
            or_(
                Category.organization_id == organization_id,
                Category.organization_id.is_(None),
            ),
        )
    )
    return result


async def existing_category_ids_async(
    db: AsyncSession, organization_id: UUID, category_ids: set[UUID]
) -> set[UUID]:
    """Return the subset of *category_ids* visible to *organization_id*.

    The batch twin of ``get_by_id_async``'s existence question, with its
    exact semantics (the organization's own plus the system catalogue) —
    one query, so a write validating a list of references does not pay
    per line.
    """
    if not category_ids:
        return set()
    rows = await db.scalars(
        select(Category.id).where(
            Category.id.in_(category_ids),
            or_(
                Category.organization_id == organization_id,
                Category.organization_id.is_(None),
            ),
        )
    )
    return set(rows.all())


async def list_with_filters_async(
    db: AsyncSession,
    organization_id: UUID | None,
    *,
    include_inactive: bool = False,
    claimed_tags: set[str] | None = None,
) -> list[Category]:
    """List categories visible to *organization_id* with optional filters.

    Includes system categories (``organization_id IS NULL``) and org-specific
    ones.  When *claimed_tags* is provided, categories whose ``context_tag`` is
    in that set are excluded (module-context isolation).  Inactive categories
    are filtered unless requested.
    """
    from sqlalchemy import ColumnElement

    filters: list[ColumnElement[bool]] = [Category.organization_id.is_(None)]
    if organization_id is not None:
        filters.append(Category.organization_id == organization_id)

    query = select(Category).where(or_(*filters))

    if claimed_tags:
        query = query.where(
            or_(
                Category.context_tag.is_(None),
                Category.context_tag.notin_(claimed_tags),
            )
        )

    result = await db.scalars(query.order_by(Category.sort_order, Category.name))
    categories = list(result.all())
    if include_inactive:
        return categories
    return [c for c in categories if c.is_active]
