"""Putaway rules CRUD router.

Mounted by ``warehouse/router.py``. Endpoints:
  - GET    /putaway-rules            list rules for the org
  - POST   /putaway-rules            create a rule
  - GET    /putaway-rules/{id}       fetch one rule
  - PUT    /putaway-rules/{id}       update fields
  - DELETE /putaway-rules/{id}       delete rule

Cross-module rule: routers import from CoreAPI for validation
(locations/products/categories) and from this module's service for
business logic — they must NOT import Core models.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts.dtos import UserContextDTO
from app.core.db_utils import get_org_owned_or_404_async
from app.core.deps import get_async_db, get_current_user_context, require_org
from app.core.exceptions import NotFoundException, ServiceRejectionError
from app.core.module_sdk import PaginatedResponse, journal_config_change
from app.core.public_api import core_api

from ._receipt_planning import ReceiptLocationPlanner, receipt_line_card_async
from .document_validation_service import validate_location_async
from .models import PutawayRule, PutawayRuleLocation
from .putaway_schemas import (
    PutawayPreviewLineOut,
    PutawayPreviewRequest,
    PutawayRuleCreate,
    PutawayRuleLocationOut,
    PutawayRuleOut,
    PutawayRuleUpdate,
)

router = APIRouter()


async def _validate_match_keys(
    db: AsyncSession,
    org_id: UUID,
    *,
    product_template_id: UUID | None,
    category_id: UUID | None,
    context_tag: str | None = None,
    storage_type_code: str | None = None,
) -> None:
    """Confirm referenced templates / categories exist and belong to org.

    the two free-text match keys are validated against real values —
       a rule on a context tag or storage type code that exists nowhere can
       never fire, so saving it silently would be a dead rule.
    """
    if product_template_id is not None:
        tpl = await core_api.product_templates.get_async(
            db, org_id, product_template_id
        )
        if tpl is None:
            raise ServiceRejectionError('product_template_not_found')
    if category_id is not None:
        cat = await core_api.categories.get_by_id_async(db, org_id, category_id)
        if cat is None:
            raise ServiceRejectionError('category_not_found')
    if context_tag:
        categories = await core_api.categories.list_async(db, org_id)
        known_tags = {c.context_tag for c in categories if c.context_tag}
        if context_tag not in known_tags:
            # the rejection speaks the language of the request and of
            # the person reading it. The previous text was assembled in code,
            # in English, and named the database column.
            raise ServiceRejectionError(
                'putaway_unknown_context_tag', value=context_tag
            )
    if storage_type_code:
        storage_types = await core_api.location_types.list_for_org_async(db, org_id)
        known_codes = {t.type_code for t in storage_types}
        if storage_type_code not in known_codes:
            raise ServiceRejectionError(
                'putaway_unknown_storage_type', value=storage_type_code
            )


async def _validate_target_location(
    db: AsyncSession, org_id: UUID, target_location_id: UUID
) -> None:
    """Refuse any target that cannot take goods: not this organization's,
    not a real shelf, or archived away. The line picker asks its shelves the
    same questions through the same function (``validate_location_async``) —
    a rule simply answers for a decision that runs unattended."""
    await validate_location_async(
        db,
        org_id,
        target_location_id,
        internal_only=True,
        active_only=True,
    )


async def _resolve_display_names(
    db: AsyncSession, org_id: UUID, rules: list[PutawayRule]
) -> list[PutawayRuleOut]:
    """Enrich rules with human-readable names for UUID references.

    Rule sets are small (dozens), so per-id lookups are acceptable;
    each unique id is resolved at most once.
    """
    template_names: dict[UUID, str] = {}
    category_names: dict[UUID, str] = {}
    location_names: dict[UUID, str] = {}
    location_states: dict[UUID, bool] = {}

    for rule in rules:
        tid = rule.product_template_id
        if tid is not None and tid not in template_names:
            tpl = await core_api.product_templates.get_async(db, org_id, tid)
            if tpl is not None:
                template_names[tid] = tpl.name
        cid = rule.category_id
        if cid is not None and cid not in category_names:
            cat = await core_api.categories.get_by_id_async(db, org_id, cid)
            if cat is not None:
                category_names[cid] = cat.name
        for entry in rule.locations:
            lid = entry.location_id
            if lid not in location_names:
                loc = await core_api.locations.get_async(db, org_id, lid)
                if loc is not None:
                    location_names[lid] = loc.name
                    location_states[lid] = (loc.settings or {}).get(
                        'archived'
                    ) is not True and loc.usage == 'internal'

    out: list[PutawayRuleOut] = []
    for rule in rules:
        dto = PutawayRuleOut.model_validate(rule)
        if rule.product_template_id is not None:
            dto.product_template_name = template_names.get(rule.product_template_id)
        if rule.category_id is not None:
            dto.category_name = category_names.get(rule.category_id)
        ordered = sorted(rule.locations, key=lambda entry: entry.position)
        dto.locations = [
            PutawayRuleLocationOut(
                location_id=entry.location_id,
                position=entry.position,
                location_name=location_names.get(entry.location_id),
                active=location_states.get(entry.location_id, True),
            )
            for entry in ordered
        ]
        # The head of the list keeps the old single-target fields alive for
        # readers that ask "where does this rule point": same shelf the
        # resolver tries first.
        head = ordered[0] if ordered else None
        dto.target_location_id = head.location_id if head else None
        dto.target_location_name = (
            location_names.get(head.location_id) if head else None
        )
        # The rule still works while ANY shelf on its list can take goods;
        # it is parked only when the resolver would walk past every one.
        dto.target_location_active = (
            any(location_states.get(e.location_id, True) for e in ordered)
            if ordered
            else True
        )
        out.append(dto)
    return out


@router.get('/putaway-rules', response_model=PaginatedResponse[PutawayRuleOut])
async def list_putaway_rules(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    org_id = require_org(current_user)
    rules = list(
        (
            await db.execute(
                select(PutawayRule)
                .where(PutawayRule.organization_id == org_id)
                .order_by(PutawayRule.priority.asc(), PutawayRule.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    page = await _resolve_display_names(db, org_id, rules[offset : offset + limit])
    return PaginatedResponse.from_slice(page, offset, limit, len(rules))


@router.post(
    '/putaway-rules',
    response_model=PutawayRuleOut,
    status_code=201,
)
async def create_putaway_rule(
    data: PutawayRuleCreate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    org_id = require_org(current_user)
    await _validate_match_keys(
        db,
        org_id,
        product_template_id=data.product_template_id,
        category_id=data.category_id,
        context_tag=data.context_tag,
        storage_type_code=data.location_type_code,
    )
    location_ids = data.location_ids or (
        [data.target_location_id] if data.target_location_id else []
    )
    for location_id in location_ids:
        await _validate_target_location(db, org_id, location_id)

    rule = PutawayRule(
        organization_id=org_id,
        product_template_id=data.product_template_id,
        category_id=data.category_id,
        context_tag=data.context_tag,
        storage_type_code=data.location_type_code,
        priority=data.priority,
        is_active=data.is_active,
    )
    rule.locations = [
        PutawayRuleLocation(
            organization_id=org_id,
            location_id=location_id,
            position=position,
        )
        for position, location_id in enumerate(location_ids)
    ]
    db.add(rule)
    # keep: refresh below needs the pending rule flushed to a persisted row
    await db.flush()
    await db.refresh(rule)
    created = (await _resolve_display_names(db, org_id, [rule]))[0]
    await _journal_rule(db, current_user, None, created)
    return created


async def _rule_for_update(
    db: AsyncSession, org_id: UUID, rule_id: UUID
) -> PutawayRule:
    """The rule an edit or a removal changes, read under its row lock.

    Both journal the rule as they read it: a request that reached it while
    another was changing or removing it waits for that commit, then reads
    the rule it really changes — or finds it gone and answers not found, as
    a request sent after it would.
    """
    rule = await db.scalar(
        select(PutawayRule)
        .where(
            PutawayRule.id == rule_id,
            PutawayRule.organization_id == org_id,
        )
        .with_for_update()
    )
    if rule is None:
        raise NotFoundException('putaway_rule')
    return rule


@router.get('/putaway-rules/{rule_id}', response_model=PutawayRuleOut)
async def get_putaway_rule(
    rule_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    org_id = require_org(current_user)
    rule = await get_org_owned_or_404_async(
        db, PutawayRule, rule_id, org_id, resource='putaway_rule'
    )
    return (await _resolve_display_names(db, org_id, [rule]))[0]


@router.put('/putaway-rules/{rule_id}', response_model=PutawayRuleOut)
async def update_putaway_rule(
    rule_id: UUID,
    data: PutawayRuleUpdate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    org_id = require_org(current_user)
    rule = await _rule_for_update(db, org_id, rule_id)
    before = (await _resolve_display_names(db, org_id, [rule]))[0]

    # exclude_unset, not exclude_none: a null the client sent is an
    # instruction to clear the column (the update schema declares all four
    # match keys clearable), not noise to be discarded. A key left out of
    # the payload stays unset and leaves the column alone.
    #
    # Clearable is not the same as optional. The schema types every field
    # optional because a PUT is partial, but three of them back NOT NULL
    # columns (target_location_id, priority, is_active): a null naming one
    # of those is refused here, where it is a contract answer, instead of
    # reaching setattr and dying as a driver-level null violation.
    updates = data.model_dump(exclude_unset=True)
    if not updates:
        raise ServiceRejectionError('no_fields_to_update')

    not_clearable = {'target_location_id', 'priority', 'is_active'} & set(updates)
    clear_attempts = sorted(name for name in not_clearable if updates[name] is None)
    if clear_attempts:
        raise ServiceRejectionError(
            'field_cannot_be_cleared', fields=', '.join(clear_attempts)
        )

    # The shelf list arrives either in its own right or as the deprecated
    # single-target spelling; both replace the whole list. An empty list is
    # a refusal, not a clearing — a rule without a shelf points nowhere.
    if 'location_ids' in updates and not updates['location_ids']:
        raise ServiceRejectionError('putaway_rule_needs_location')
    if 'location_ids' in updates or 'target_location_id' in updates:
        location_ids = updates.get('location_ids') or [
            updates.get('target_location_id')
        ]
        for location_id in location_ids:
            if location_id is not None:
                await _validate_target_location(db, org_id, location_id)

    if 'product_template_id' in updates:
        await _validate_match_keys(
            db,
            org_id,
            product_template_id=updates['product_template_id'],
            category_id=None,
        )
    if 'category_id' in updates:
        await _validate_match_keys(
            db,
            org_id,
            product_template_id=None,
            category_id=updates['category_id'],
        )
    if 'context_tag' in updates or 'location_type_code' in updates:
        await _validate_match_keys(
            db,
            org_id,
            product_template_id=None,
            category_id=None,
            context_tag=updates.get('context_tag'),
            storage_type_code=updates.get('location_type_code'),
        )
    merged_product = updates.get('product_template_id', rule.product_template_id)
    merged_category = updates.get('category_id', rule.category_id)
    merged_context = updates.get('context_tag', rule.context_tag)
    merged_storage = updates.get('location_type_code', rule.storage_type_code)
    if (
        merged_product is None
        and merged_category is None
        and not merged_context
        and not merged_storage
    ):
        raise ServiceRejectionError('putaway_rule_needs_match_key')

    location_ids = updates.pop('location_ids', None)
    updates.pop('target_location_id', None)
    for field, value in updates.items():
        setattr(rule, field, value)
    if location_ids is None and 'target_location_id' in data.model_fields_set:
        legacy = data.target_location_id
        location_ids = [legacy] if legacy is not None else None
    if location_ids is not None:
        # keep: orphans must be flushed out before the replacements are
        # appended — the unit of work inserts before it deletes, and a new
        # list keeping any existing (rule, location) pair would collide on
        # uq_putaway_rule_locations_rule_loc
        rule.locations.clear()
        await db.flush()
        rule.locations.extend(
            PutawayRuleLocation(
                organization_id=org_id,
                location_id=location_id,
                position=position,
            )
            for position, location_id in enumerate(location_ids)
        )
    # keep: refresh below re-reads the rule, so pending field changes must be flushed first
    await db.flush()
    await db.refresh(rule)
    updated = (await _resolve_display_names(db, org_id, [rule]))[0]
    await _journal_rule(db, current_user, before, updated)
    return updated


@router.delete('/putaway-rules/{rule_id}', status_code=204)
async def delete_putaway_rule(
    rule_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> None:
    org_id = require_org(current_user)
    rule = await _rule_for_update(db, org_id, rule_id)
    before = (await _resolve_display_names(db, org_id, [rule]))[0]
    await db.delete(rule)
    await _journal_rule(db, current_user, before, None)


#: What picks the goods a rule applies to.
_RULE_MATCH_KEYS = (
    'product_template_id',
    'product_template_name',
    'category_id',
    'category_name',
    'context_tag',
    'location_type_code',
)


def _rule_reading(rule: PutawayRuleOut) -> dict[str, Any]:
    """A rule as its journal entry reads it — its references by id and name,
    and the shelves in order.

    The shelf list lives in rows of its own, so a change to the shelves alone
    would leave every column of the rule as it was and journal nothing. The
    ids are what says whether it moved: two shelves can share a name (one per
    building), and a rule moved from one to the other is a change all the
    same. The names are what the reader reads.
    """
    return {
        **{key: getattr(rule, key) for key in _RULE_MATCH_KEYS},
        'priority': rule.priority,
        'is_active': rule.is_active,
        'location_ids': [entry.location_id for entry in rule.locations],
        'locations': [entry.location_name for entry in rule.locations],
    }


async def _journal_rule(
    db: AsyncSession,
    current_user: UserContextDTO,
    before: PutawayRuleOut | None,
    after: PutawayRuleOut | None,
) -> None:
    """Where the next delivery lands is decided here: journalled.

    A rule has no name of its own, and two rules may match the same goods,
    so every entry carries its id. An edit also carries what stayed as it
    was — what the rule matches, its priority, its shelves by id and name —
    beside whatever moved: the reader sees which rule it was, and a shelf
    whose label did not change is still named.
    """
    before_reading = _rule_reading(before) if before else None
    after_reading = _rule_reading(after) if after else None
    record = after if after is not None else before
    assert record is not None, 'a rule write has a rule on one side'
    context: dict[str, Any] = {'id': record.id}
    if before_reading and after_reading:
        context.update(
            (key, value)
            for key, value in after_reading.items()
            if before_reading[key] == value
        )
    await journal_config_change(
        db,
        require_org(current_user),
        current_user.id,
        module='warehouse',
        subject='putaway-rule',
        keys={
            'product_template_id',
            'product_template_name',
            'category_id',
            'category_name',
            'context_tag',
            'location_type_code',
            'priority',
            'is_active',
            'location_ids',
            'locations',
        },
        before=before_reading,
        after=after_reading,
        context=context,
    )


@router.post(
    '/putaway/preview',
    # list-envelope-exception: one decision per line the request sent, in its order
    response_model=list[PutawayPreviewLineOut],
)
async def preview_receipt_putaway(
    data: PutawayPreviewRequest,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> list[PutawayPreviewLineOut]:
    """Where a receipt's lines will land, before the receipt exists.

    The one-screen form asks this as the reader fills it in, so the shelf
    and the reason are visible — and can be corrected — before anything is
    posted. The answer comes from ``ReceiptLocationPlanner``, the same
    decision the executor runs, so the preview cannot drift from the
    booking. Nothing is stored: the plan is computed from the rules as they
    stand now, exactly as the document read does.
    """
    org_id = require_org(current_user)
    await _validate_target_location(db, org_id, data.target_location_id)
    planner = await ReceiptLocationPlanner.for_target(
        db, org_id, data.target_location_id
    )
    decisions: list[PutawayPreviewLineOut] = []
    for line in data.lines:
        named = (
            await core_api.items.get_async(db, org_id, line.item_id)
            if line.item_id is not None
            else None
        )
        stock_template_id = await receipt_line_card_async(
            db,
            org_id,
            product_template_id=line.product_template_id,
            named=named,
        )
        # Capacity speaks the product's stock unit; the line speaks the
        # unit it was written in. The same conversion the executor makes.
        quantity_stock = await core_api.uoms.to_stock_uom_async(
            db, org_id, stock_template_id, line.quantity, line.uom_id
        )
        # The landing step is the executor's: a warehouse that receives in
        # two steps books its area first, so the preview must say the area
        # rather than the shelf the putaway task will name later.
        decision = planner.booked(
            await planner.decide(
                named=named,
                stock_template_id=stock_template_id,
                line_target_id=line.target_location_id,
                quantity_stock=quantity_stock,
            )
        )
        decisions.append(
            PutawayPreviewLineOut(
                planned_location_id=decision.location_id,
                planned_location_name=await planner.location_name(decision.location_id),
                planned_source=decision.source,
                planned_rule_match_key=decision.rule_match_key,
                planned_rule_match_name=decision.rule_match_name,
                planned_rule_warning=decision.rule_warning,
                planned_over_capacity=decision.over_capacity,
                planned_capacity_used=decision.capacity_used,
                planned_capacity_max=decision.capacity_max,
                planned_shelf_fill=decision.shelf_fill,
            )
        )
    return decisions
