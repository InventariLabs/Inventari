"""Async variants of meal plan CRUD / entries / shopping / suggestions."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import Select, delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.contracts import AuditAction, AuditTargetType
from app.core.db_utils import get_org_owned_or_404_async
from app.core.exceptions import (
    ConflictException,
    NotFoundException,
    ServiceRejectionError,
)
from app.core.public_api import core_api
from app.i18n import Language
from app.i18n.service import get_current_lang, get_error_message

from ._meal_plan_async_schema import (
    _auto_plan_name,
    _entry_to_schema_async,
    _plan_to_schema_async,
    _require_plan_async,
)
from ._meal_plan_helpers import (
    _MAX_PLAN_DAYS,
    _next_order_in_cell_async,
    _plan_is_too_long,
    _validate_entry,
)
from ._meal_plan_shopping import generate_shopping_list_async  # noqa: F401
from ._meal_plan_suggestions import get_suggestions_async  # noqa: F401
from .models import (
    MealPlan,
    MealPlanEntry,
    MealSlot,
    Recipe,
)
from .schemas import (
    BulkEntriesSave,
    CopyPlanRequest,
    MealPlanCreate,
    MealPlanEntryCreate,
    MealPlanEntrySchema,
    MealPlanEntryUpdate,
    MealPlanSchema,
    MealPlanUpdate,
)

# ── CRUD ───────────────────────────────────────────────────────────────────────


async def create_meal_plan_async(
    db: AsyncSession,
    data: MealPlanCreate,
    org_id: UUID,
    user_id: UUID,
    lang: Language | None = None,
) -> MealPlanSchema:
    if data.end_date < data.start_date:
        raise ServiceRejectionError('meal_plan_end_before_start')
    if _plan_is_too_long(data.start_date, data.end_date):
        raise ServiceRejectionError('meal_plan_too_long', days=_MAX_PLAN_DAYS)
    if not data.enabled_slots:
        raise ServiceRejectionError('meal_plan_no_slots')

    plan_name = data.name or _auto_plan_name(data.start_date, data.end_date, lang)

    plan = MealPlan(
        organization_id=org_id,
        name=plan_name,
        start_date=data.start_date,
        end_date=data.end_date,
        enabled_slots=[s.value for s in data.enabled_slots],
        default_servings=data.default_servings,
        notes=data.notes,
        created_by=user_id,
    )
    db.add(plan)
    await db.flush()
    await db.refresh(plan)
    plan = await _require_plan_async(db, plan.id, org_id)
    return await _plan_to_schema_async(plan, db, org_id)


async def get_meal_plan_async(
    db: AsyncSession, plan_id: UUID, org_id: UUID
) -> MealPlanSchema | None:
    plan = await db.scalar(
        select(MealPlan)
        .options(joinedload(MealPlan.entries).joinedload(MealPlanEntry.recipe))
        .where(MealPlan.id == plan_id, MealPlan.organization_id == org_id)
    )
    if plan is None:
        return None
    return await _plan_to_schema_async(plan, db, org_id)


def _plans_in_window(
    org_id: UUID, start_date: date | None, end_date: date | None
) -> Select[tuple[MealPlan]]:
    stmt = select(MealPlan).where(MealPlan.organization_id == org_id)
    if start_date:
        stmt = stmt.where(MealPlan.end_date >= start_date)
    if end_date:
        stmt = stmt.where(MealPlan.start_date <= end_date)
    return stmt


async def count_meal_plans_async(
    db: AsyncSession,
    org_id: UUID,
    start_date: date | None = None,
    end_date: date | None = None,
) -> int:
    stmt = _plans_in_window(org_id, start_date, end_date)
    return (await db.scalar(select(func.count()).select_from(stmt.subquery()))) or 0


async def list_meal_plans_async(
    db: AsyncSession,
    org_id: UUID,
    start_date: date | None = None,
    end_date: date | None = None,
    offset: int = 0,
    limit: int = 20,
) -> list[dict[str, Any]]:
    stmt = _plans_in_window(org_id, start_date, end_date)
    plans = (
        await db.scalars(
            stmt.order_by(MealPlan.start_date.desc(), MealPlan.id)
            .offset(offset)
            .limit(limit)
        )
    ).all()

    result = []
    entry_counts: dict[UUID, int] = {
        row[0]: row[1]
        for row in (
            await db.execute(
                select(MealPlanEntry.meal_plan_id, func.count(MealPlanEntry.id))
                .where(MealPlanEntry.meal_plan_id.in_([p.id for p in plans]))
                .group_by(MealPlanEntry.meal_plan_id)
            )
        ).all()
    }
    for plan in plans:
        result.append(
            {
                'id': plan.id,
                'name': plan.name,
                'start_date': plan.start_date,
                'end_date': plan.end_date,
                'enabled_slots': [MealSlot(s) for s in plan.enabled_slots],
                'default_servings': plan.default_servings,
                'shopping_list_id': plan.shopping_list_id,
                'entry_count': entry_counts.get(plan.id, 0),
                'created_at': plan.created_at,
                'updated_at': plan.updated_at,
            }
        )
    return result


async def update_meal_plan_async(
    db: AsyncSession, plan_id: UUID, data: MealPlanUpdate, org_id: UUID
) -> MealPlanSchema:
    plan = await _require_plan_async(db, plan_id, org_id)

    removed_conflicting_entries = False

    if data.enabled_slots is not None:
        if not data.enabled_slots:
            raise ServiceRejectionError('meal_plan_no_slots')
        new_slot_values = {s.value for s in data.enabled_slots}
        old_slot_values = set(plan.enabled_slots)
        disabled_slots = old_slot_values - new_slot_values
        if disabled_slots:
            # report only the slots that actually hold entries, in a
            # deterministic order, with per-slot counts — the old code blamed
            # every disabled slot (even empty ones) in set order.
            counts = {
                row[0]: row[1]
                for row in (
                    await db.execute(
                        select(
                            MealPlanEntry.slot,
                            func.count(MealPlanEntry.id),
                        )
                        .where(
                            MealPlanEntry.meal_plan_id == plan_id,
                            MealPlanEntry.slot.in_(list(disabled_slots)),
                        )
                        .group_by(MealPlanEntry.slot)
                    )
                ).all()
            }
            conflicts = [
                {'slot': str(slot), 'count': counts[slot]}
                for slot in sorted(disabled_slots)
                if counts.get(slot, 0) > 0
            ]
            if conflicts:
                if data.remove_conflicting_entries:
                    await db.execute(
                        delete(MealPlanEntry).where(
                            MealPlanEntry.meal_plan_id == plan_id,
                            MealPlanEntry.slot.in_([c['slot'] for c in conflicts]),
                        )
                    )
                    removed_conflicting_entries = True
                else:
                    raise ConflictException(
                        'MEAL_PLAN_SLOT_CONFLICT',
                        get_error_message(
                            'meal_plan_slot_conflict',
                            get_current_lang(),
                            slots=', '.join(c['slot'] for c in conflicts),
                        ),
                        details={'conflicts': conflicts},
                    )
        plan.enabled_slots = [s.value for s in data.enabled_slots]

    if data.start_date is not None or data.end_date is not None:
        new_start = data.start_date or plan.start_date
        new_end = data.end_date or plan.end_date
        if new_end < new_start:
            raise ServiceRejectionError('meal_plan_end_before_start')
        if _plan_is_too_long(new_start, new_end):
            raise ServiceRejectionError('meal_plan_too_long', days=_MAX_PLAN_DAYS)
        conflict = await db.scalar(
            select(MealPlanEntry).where(
                MealPlanEntry.meal_plan_id == plan_id,
                (MealPlanEntry.date < new_start) | (MealPlanEntry.date > new_end),
            )
        )
        if conflict:
            raise ConflictException(
                'MEAL_PLAN_DATE_CONFLICT',
                get_error_message(
                    'meal_plan_dates_exclude_entries', get_current_lang()
                ),
            )
        plan.start_date = new_start
        plan.end_date = new_end

    if data.name is not None:
        plan.name = data.name
    # Explicit null clears the plan-wide default; an absent field leaves it
    # alone. Without the distinction the field could be set and never unset.
    if 'default_servings' in data.model_fields_set:
        plan.default_servings = data.default_servings
    if data.notes is not None:
        plan.notes = data.notes

    await db.flush()
    if removed_conflicting_entries:
        # the session keeps the pre-delete entries collection
        # loaded on the identity-map plan — expire so the re-fetch below
        # sees the rows we just removed.
        db.expire(plan)
    plan = await _require_plan_async(db, plan_id, org_id)
    return await _plan_to_schema_async(plan, db, org_id)


async def delete_meal_plan_async(
    db: AsyncSession, plan_id: UUID, org_id: UUID, user_id: UUID
) -> bool:
    plan = await db.scalar(
        select(MealPlan).where(
            MealPlan.id == plan_id, MealPlan.organization_id == org_id
        )
    )
    if plan is None:
        return False
    # The plan is gone for good once the request commits — its entries cascade with
    # it — so the deletion takes a row in the organization journal, and the
    # name rides in the snapshot (see ``AuditTargetType``; the plan's own
    # edits and additions deliberately write nothing). One transaction with
    # the delete: ``log_action_async`` flushes, the caller commits.
    await core_api.audit_log.log_action_async(
        db,
        organization_id=org_id,
        user_id=user_id,
        action=AuditAction.HARD_DELETE,
        target_type=AuditTargetType.MEAL_PLAN,
        target_id=plan.id,
        snapshot={'name': plan.name},
    )
    await db.delete(plan)
    await db.flush()
    return True


# ── Entries ────────────────────────────────────────────────────────────────────


_ORDER_RETRIES = 3


async def _insert_entry_at_a_free_position_async(
    db: AsyncSession, entry: MealPlanEntry
) -> None:
    """Write the entry, stepping past a position another request just took.

    Two people filling the same meal both read the same free position and both
    try to write it; the loser used to leave the API with a bare
    ``IntegrityError``, which is a 500 for something the plan allows. The
    insert runs inside a SAVEPOINT so the outer transaction survives the
    collision, and the position is recomputed before trying again.
    """
    for attempt in range(_ORDER_RETRIES):
        try:
            async with db.begin_nested():
                db.add(entry)
                await db.flush()
            return
        except IntegrityError:
            if attempt == _ORDER_RETRIES - 1:
                raise ConflictException(
                    'MEAL_PLAN_ENTRY_POSITION_TAKEN',
                    get_error_message('meal_plan_position_taken', get_current_lang()),
                ) from None
            if entry in db:
                db.expunge(entry)
            entry.order = await _next_order_in_cell_async(
                db, entry.meal_plan_id, entry.date, entry.slot
            )


async def add_entry_async(
    db: AsyncSession, plan_id: UUID, data: MealPlanEntryCreate, org_id: UUID
) -> MealPlanEntrySchema:
    plan = await _require_plan_async(db, plan_id, org_id)
    _validate_entry(plan, data.date, data.slot)

    recipe = await db.scalar(
        select(Recipe)
        .where(
            Recipe.id == data.recipe_id,
            Recipe.organization_id == org_id,
        )
        .with_for_update()
    )
    if recipe is None:
        raise NotFoundException('recipe', get_current_lang())

    entry = MealPlanEntry(
        meal_plan_id=plan_id,
        date=data.date,
        slot=data.slot,
        recipe_id=data.recipe_id,
        servings=data.servings,
        notes=data.notes,
        order=data.order
        if data.order is not None
        else await _next_order_in_cell_async(db, plan_id, data.date, data.slot),
    )
    await _insert_entry_at_a_free_position_async(db, entry)
    await db.flush()
    await db.refresh(entry)
    entry_with_recipe = await db.scalar(
        select(MealPlanEntry)
        .options(joinedload(MealPlanEntry.recipe))
        .where(MealPlanEntry.id == entry.id)
    )
    assert entry_with_recipe is not None
    return await _entry_to_schema_async(entry_with_recipe, plan, db, org_id)


async def update_entry_async(
    db: AsyncSession,
    plan_id: UUID,
    entry_id: UUID,
    data: MealPlanEntryUpdate,
    org_id: UUID,
) -> MealPlanEntrySchema:
    plan = await _require_plan_async(db, plan_id, org_id)
    entry = await db.scalar(
        select(MealPlanEntry)
        .options(joinedload(MealPlanEntry.recipe))
        .where(MealPlanEntry.id == entry_id, MealPlanEntry.meal_plan_id == plan_id)
        .with_for_update(of=MealPlanEntry)
    )
    if entry is None:
        raise NotFoundException('meal_plan_entry', get_current_lang())

    if data.recipe_id is not None:
        await get_org_owned_or_404_async(
            db, Recipe, data.recipe_id, org_id, lang=get_current_lang()
        )
        entry.recipe_id = data.recipe_id

    if data.servings is not None:
        entry.servings = data.servings
    if data.notes is not None:
        entry.notes = data.notes
    if data.order is not None:
        entry.order = data.order

    if data.date is not None or data.slot is not None:
        new_date = data.date or entry.date
        new_slot = data.slot or entry.slot
        _validate_entry(plan, new_date, new_slot)

        moved_to_same_cell = (new_date, new_slot) == (entry.date, entry.slot)
        if not moved_to_same_cell:
            # Avoid a (date, slot, order) collision with an existing entry:
            # place the moved entry at the end of the target cell instead.
            collision = await db.scalar(
                select(MealPlanEntry.id).where(
                    MealPlanEntry.meal_plan_id == plan_id,
                    MealPlanEntry.date == new_date,
                    MealPlanEntry.slot == new_slot,
                    MealPlanEntry.order == entry.order,
                    MealPlanEntry.id != entry_id,
                )
            )
            if collision is not None:
                entry.order = await _next_order_in_cell_async(
                    db, plan_id, new_date, new_slot
                )
        entry.date = new_date
        entry.slot = new_slot

    await db.flush()
    # Reload fresh state: the same-session identity map would otherwise serve
    # the pre-update `recipe` relationship (stale recipe_name) —.
    # populate_existing() expires only instances returned by THIS query, so
    # the plan object stays loaded and no greenlet-unsafe lazy load follows.
    entry = await db.scalar(
        select(MealPlanEntry)
        .options(joinedload(MealPlanEntry.recipe))
        .where(MealPlanEntry.id == entry_id)
        .execution_options(populate_existing=True)
    )
    assert entry is not None
    return await _entry_to_schema_async(entry, plan, db, org_id)


async def delete_entry_async(
    db: AsyncSession, plan_id: UUID, entry_id: UUID, org_id: UUID
) -> bool:
    entry = await db.scalar(
        select(MealPlanEntry)
        .where(MealPlanEntry.id == entry_id, MealPlanEntry.meal_plan_id == plan_id)
        .join(MealPlan)
        .where(MealPlan.organization_id == org_id)
    )
    if entry is None:
        return False
    await db.delete(entry)
    await db.flush()
    return True


async def bulk_save_entries_async(
    db: AsyncSession, plan_id: UUID, data: BulkEntriesSave, org_id: UUID
) -> MealPlanSchema:
    plan = await _require_plan_async(db, plan_id, org_id)

    for entry_data in data.entries:
        _validate_entry(plan, entry_data.date, entry_data.slot)
        recipe = await db.scalar(
            select(Recipe)
            .where(
                Recipe.id == entry_data.recipe_id,
                Recipe.organization_id == org_id,
            )
            .with_for_update()
        )
        if recipe is None:
            raise NotFoundException('recipe', get_current_lang())

    await db.execute(delete(MealPlanEntry).where(MealPlanEntry.meal_plan_id == plan_id))
    await db.flush()

    for idx, entry_data in enumerate(data.entries):
        entry = MealPlanEntry(
            meal_plan_id=plan_id,
            date=entry_data.date,
            slot=entry_data.slot,
            recipe_id=entry_data.recipe_id,
            servings=entry_data.servings,
            notes=entry_data.notes,
            order=entry_data.order if entry_data.order is not None else idx,
        )
        db.add(entry)
    await db.flush()
    # Reload fresh state: the same-session identity map would otherwise serve
    # the pre-replacement `entries` collection in the returned schema —.
    # Expire only the collection so the plan's columns stay loaded and the
    # re-fetch below repopulates entries via joinedload.
    db.expire(plan, ['entries'])

    plan = await _require_plan_async(db, plan_id, org_id)
    return await _plan_to_schema_async(plan, db, org_id)


async def copy_plan_to_week_async(
    db: AsyncSession,
    plan_id: UUID,
    data: CopyPlanRequest,
    org_id: UUID,
    user_id: UUID,
    lang: Language | None = None,
) -> tuple[MealPlanSchema, int, int]:
    """Clone the plan's entries into a NEW plan covering the target range.

    Entries are shifted by the day delta between the source start date and the
    target start date; entries that would fall outside the target range are
    skipped. The source plan is left untouched. Returns (schema, copied, skipped).
    """
    plan = await _require_plan_async(db, plan_id, org_id)
    # Lock the source plan row so a concurrent entry edit mid-copy cannot
    # produce a half-updated clone (also keeps the TOCTOU linter satisfied —
    # the copy itself writes only to a brand-new plan).
    await db.execute(
        select(MealPlan.id).where(MealPlan.id == plan_id).with_for_update()
    )

    if data.end_date < data.start_date:
        raise ServiceRejectionError('meal_plan_end_before_start')
    if _plan_is_too_long(data.start_date, data.end_date):
        raise ServiceRejectionError('meal_plan_too_long', days=_MAX_PLAN_DAYS)
    if data.start_date < datetime.now(UTC).date():
        raise ServiceRejectionError('meal_plan_start_in_past')

    source_entries = (
        await db.scalars(
            select(MealPlanEntry).where(MealPlanEntry.meal_plan_id == plan_id)
        )
    ).all()

    shift = (data.start_date - plan.start_date).days
    new_plan = MealPlan(
        organization_id=org_id,
        name=_auto_plan_name(data.start_date, data.end_date, lang),
        start_date=data.start_date,
        end_date=data.end_date,
        enabled_slots=list(plan.enabled_slots),
        default_servings=plan.default_servings,
        created_by=user_id,
    )
    db.add(new_plan)
    await db.flush()  # assign new_plan.id for the entry FKs
    new_plan_id = new_plan.id

    copied = 0
    skipped = 0
    for entry in source_entries:
        target_date = entry.date + timedelta(days=shift)
        if target_date < data.start_date or target_date > data.end_date:
            skipped += 1
            continue
        db.add(
            MealPlanEntry(
                meal_plan_id=new_plan.id,
                date=target_date,
                slot=entry.slot,
                recipe_id=entry.recipe_id,
                servings=entry.servings,
                notes=entry.notes,
                order=entry.order,
            )
        )
        copied += 1

    await db.flush()
    # Expire so the identity map doesn't serve the stale entries collection
    # (the session keeps the pre-copy relationship loaded).
    db.expire(new_plan)
    new_plan = await _require_plan_async(db, new_plan_id, org_id)
    schema = await _plan_to_schema_async(new_plan, db, org_id)
    return schema, copied, skipped


async def require_entry_of_recipe_async(
    db: AsyncSession, entry_id: UUID, recipe_id: UUID, org_id: UUID
) -> None:
    """404 unless the card is on one of this organization's plans and is
    this recipe's: a cook may be attributed only to a card it could be."""
    found = await db.scalar(
        select(MealPlanEntry.id)
        .join(MealPlan, MealPlan.id == MealPlanEntry.meal_plan_id)
        .where(
            MealPlanEntry.id == entry_id,
            MealPlanEntry.recipe_id == recipe_id,
            MealPlan.organization_id == org_id,
        )
    )
    if found is None:
        raise NotFoundException('meal_plan_entry', get_current_lang())
