"""Whose records these are: the predicates every list filters by.

One question with two directions — what a named vertical module counts as
its own, and what a general (non-module) list may show — and they are
mirrors of each other by construction. They sit in the core rather than in
``app.services`` because the modules themselves ask them: the equipment
list used to hold its own copy of "is this equipment", and the copy
disagreed with the core in both directions — a location row promising an
asset the list could not produce, and an asset in a location the module's
own map did not show.
"""

from collections.abc import Callable, Iterable
from uuid import UUID

from sqlalchemy import Select, and_, bindparam, false, func, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.elements import ColumnElement

from app.core.module_scope import get_claimed_modules, get_context_tags_of
from app.models.category import Category
from app.models.item import Item


def unclaimed_by_a_module(claimed_tags: set[str]) -> ColumnElement[bool]:
    """Rows a general (non-module) list is allowed to show.

    Where a record is filed is the answer: a category claimed by a module
    hides it, any other category keeps it. Filing an asset under an ordinary
    category is the organization saying it is an ordinary record, and the
    module that created it does not overrule that afterwards.

    Only a record with no category at all falls through to its own
    ``module_name``, and that fall-through is the whole point. The rule used
    to be the category alone, so an asset saved without one — the equipment
    form never required a category — was indistinguishable from an ordinary
    product. The equipment module had already learned to ask two questions
    about its own records; the core still asked one.
    """
    claimed_modules = get_claimed_modules()
    if not claimed_tags and not claimed_modules:
        return true()

    return or_(
        Item.category.has(
            or_(
                Category.context_tag.is_(None),
                Category.context_tag.notin_(claimed_tags),
            )
        ),
        and_(
            Item.category_id.is_(None),
            or_(
                Item.module_name.is_(None),
                Item.module_name.notin_(claimed_modules),
            ),
            # The mirror of the namespace fall-through above: a record
            # nobody stamped, carrying a claimed module's meta_data, belongs
            # to that module on both sides or on neither.
            *[
                ~Item.meta_data[claimed].isnot(None)
                for claimed in sorted(claimed_modules)
            ],
        ),
    )


def claimed_by_module(
    module_name: str,
    context_tags: set[str],
    category_ids: Iterable[UUID] | None = None,
) -> ColumnElement[bool]:
    """Rows one named vertical module counts as its own.

    The mirror of :func:`unclaimed_by_a_module`, and it reads the two
    questions in the same order for the same reason: the category speaks
    first, and ``module_name`` answers only for a record filed under none.
    Read in the other order the two would disagree about one record — an
    asset re-filed under an ordinary category would be missing from the
    general list and present in the module's, which is the worst of both.

    *category_ids*, when the caller has read them, are the categories that
    carry those tags (:func:`claimed_category_ids_async`). Named as values
    written into the statement, they let the planner see how few records
    stand under them and read them through the category index; asked
    through the categories table, it guessed a fifth of the organization and
    walked every record of a warehouse that keeps no equipment at all.
    """
    if category_ids is not None:
        category_side: ColumnElement[bool] = Item.category_id.in_(
            bindparam(
                'claimed_category_ids',
                list(category_ids),
                expanding=True,
                literal_execute=True,
                unique=True,
            )
        )
    elif context_tags:
        category_side = Item.category.has(Category.context_tag.in_(context_tags))
    else:
        category_side = false()
    return or_(
        category_side,
        and_(
            Item.category_id.is_(None),
            or_(
                Item.module_name == module_name,
                # The namespace answers where ``module_name`` was never
                # filled: a record written straight to the table (an import,
                # a fixture, anything predating the column) carries the
                # module's meta_data and nothing else. The equipment module
                # read this marker in its own list while the core did not,
                # which is how one record could be listed by the module and
                # missing from the module's own locations.
                Item.meta_data[module_name].isnot(None),
            ),
        ),
    )


def item_belongs_to_module(
    item: Item, module_name: str, context_tags: set[str]
) -> bool:
    """Whether one loaded record is *module_name*'s own.

    The Python reading of :func:`claimed_by_module`, for a row already read:
    the category speaks first, and ``module_name`` — or the module's
    ``meta_data`` namespace — answers only for a record filed under none. The
    card route already holds its one row; a list asks the database the same
    question.
    """
    if item.category_id is not None:
        return item.category is not None and item.category.context_tag in context_tags
    return item.module_name == module_name or (
        (item.meta_data or {}).get(module_name) is not None
    )


async def hidden_module_tags_async(
    db: AsyncSession, organization_id: UUID
) -> set[str] | None:
    """The category tags a general report hides for this organization.

    The organization's own setting decides, the one the general lists follow
    (``show_module_data``): unless it shows module data, a record a vertical
    module claims stays out of a general report the way it stays out of the
    products list. ``None`` when nothing is hidden — the setting is on, or no
    module claims a tag in this build, which is how the item list reads the
    same setting (``claimed_tags or None``).

    A report used to read the organization whole while the products list
    beside it left the module's records out, so a household's statistics
    counted the family laptop among the food.
    """
    from app.core.module_scope import get_claimed_context_tags
    from app.models.organization import Organization

    settings = await db.scalar(
        select(Organization.settings).where(Organization.id == organization_id)
    )
    if (settings or {}).get('show_module_data') is True:
        return None
    return get_claimed_context_tags() or None


def general_rows(hidden_tags: set[str] | None) -> ColumnElement[bool]:
    """The records a general report keeps, given :func:`hidden_module_tags_async`."""
    return unclaimed_by_a_module(hidden_tags) if hidden_tags else true()


def outside_module_products(
    product_column: ColumnElement[UUID] | InstrumentedAttribute[UUID],
    organization_id: UUID,
    hidden_tags: set[str] | None,
) -> ColumnElement[bool]:
    """Rows of a per-product report whose product a general report keeps.

    A report kept per product — the cost ledger, the stock on a date — cannot
    leave out a record, only a product: one with a record a vertical module
    claims goes as a whole. Always true when nothing is hidden.
    """
    if not hidden_tags:
        return true()
    claimed = select(Item.template_id).where(
        Item.organization_id == organization_id,
        Item.template_id.is_not(None),
        ~general_rows(hidden_tags),
    )
    return product_column.notin_(claimed)


async def claimed_category_ids_async(
    db: AsyncSession, organization_id: UUID, tag: str
) -> list[UUID] | None:
    """The categories a module's tag claims, among those an organization uses.

    Its own categories and the shared ones — the only ones its records can
    be filed under. ``None`` when *tag* names no registered module: such a
    tag is a plain label, read off the category column as it was.
    """
    claimed = get_context_tags_of(tag)
    if not claimed:
        return None
    rows = await db.scalars(
        select(Category.id).where(
            Category.context_tag.in_(claimed),
            or_(
                Category.organization_id == organization_id,
                Category.organization_id.is_(None),
            ),
        )
    )
    return list(rows.all())


def items_with_context_tag(
    tag: str, category_ids: Iterable[UUID] | None = None
) -> ColumnElement[bool]:
    """The filter behind a ``context_tag`` ask on items.

    When the tag names a registered module, the ask is that module's own
    question, and :func:`claimed_by_module` answers it — a record filed
    under no category (the equipment form never required one) stands in
    its module's lists, and a filter that read the category column alone
    hid it from the dashboard and the fleet valuation the same ask feeds.

    A tag no module declares is an organisation's plain label, and the
    reading stays where it was: the category column, records filed under
    no category excluded.

    *category_ids* are the claimed categories, read beforehand
    (:func:`claimed_category_ids_async`).
    """
    claimed = get_context_tags_of(tag)
    if claimed:
        return claimed_by_module(tag, claimed, category_ids)
    return and_(
        Item.category_id.isnot(None),
        Item.category.has(Category.context_tag == tag),
    )


#: One organization's records standing away from their own location for a
#: while, as ``select(<item id>, <location id>)`` — at most one row per record.
PlacementFn = Callable[[UUID], Select[tuple[UUID, UUID | None]]]

_placements: dict[str, PlacementFn] = {}


def register_record_placement(module_name: str, fn: PlacementFn) -> None:
    """Let a module say where its records stand while they are away from home.

    A record's ``storage_location_id`` is its home, and a module may put it
    somewhere else for a while without moving it: equipment checked out to a
    place stands in that place until it is returned, and goes back home then.
    The module's own list showed the place while the core's location counts
    still read the home, so one location row promised an asset its link could
    not produce and the place it stood in counted nothing. Registered here,
    the module's answer is the one :func:`standing_location` gives every
    reader of the same question. The owning module calls this at import time;
    a module outside the repository has no placements of its own yet, and its
    records stand at home.
    """
    _placements[module_name] = fn


def standing_location(module_name: str, organization_id: UUID) -> ColumnElement[UUID]:
    """Where one of *module_name*'s records stands now — the place a module
    put it while it lasts, its own location otherwise.

    For a module that registered no placement this is the home column itself.
    """
    fn = _placements.get(module_name)
    if fn is None:
        return Item.storage_location_id.expression
    placed = fn(organization_id).subquery()
    item_id, location_id = placed.c
    return func.coalesce(
        select(location_id).where(item_id == Item.id).limit(1).scalar_subquery(),
        Item.storage_location_id,
    )
