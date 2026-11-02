"""A product's home shelf, learned from where the goods were put away.

A small business writes no putaway rules; the knowledge of where things go
stays in the worker's head. Putting goods on a shelf other than the suggested
one therefore offers to make that shelf the product's home, and the home is
written as an ordinary product-scoped putaway rule, so the existing ranking,
the capacity walk and the journal's "the rule said A-12, it landed on A-13"
take it unchanged. There is no second suggestion source: a module that wants
to suggest a shelf of its own has the same door as the operator, the rule.

The question is asked only where it means something (``home_shelf_offer_async``
says when) and a shelf that cannot be a home — a receiving area, the
quarantine location, one off the lists — is refused with its reason.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import AuditAction, AuditTargetType
from app.core.exceptions import ServiceRejectionError
from app.core.public_api import core_api

from ._receiving_area import list_receiving_modes_async
from .document_profile_service import get_profile
from .models import PutawayHomeSilenced, PutawayRule, PutawayRuleLocation
from .putaway_schemas import HomeShelfOffer

#: Why a shelf cannot be a home, as the offer and the refusal name it.
REFUSED_RECEIVING = 'receiving'
REFUSED_QUARANTINE = 'quarantine'
REFUSED_NOT_STOCK = 'not_stock'

#: The refusal each reason is answered with, named in full so the catalogue
#: of refusal codes can read them.
_REFUSAL_KEYS = {
    REFUSED_RECEIVING: 'home_shelf_receiving',
    REFUSED_QUARANTINE: 'home_shelf_quarantine',
    REFUSED_NOT_STOCK: 'home_shelf_not_stock',
}

#: A learned home wins its tier over every other rule naming the product.
_HOME_PRIORITY = 0


async def _under_async(db: AsyncSession, org_id: UUID, root_id: UUID) -> set[UUID]:
    """The location and everything inside it."""
    return {
        root_id,
        *await core_api.locations.descendant_ids_async(db, org_id, root_id),
    }


async def home_refusal_async(
    db: AsyncSession, org_id: UUID, location_id: UUID
) -> str | None:
    """Why ``location_id`` cannot be a home shelf, or ``None`` when it can.

    A receiving area is where goods wait, a quarantine location is where they
    are held back, and a location that does not take stock (virtual, archived,
    not found) takes no goods at all — none of them is where a product lives.
    """
    location = await core_api.locations.get_async(db, org_id, location_id)
    if (
        location is None
        or location.usage != 'internal'
        or (location.settings or {}).get('archived') is True
    ):
        return REFUSED_NOT_STOCK
    for row in await list_receiving_modes_async(db, org_id):
        if row.receiving_location_id is not None and location_id in (
            await _under_async(db, org_id, row.receiving_location_id)
        ):
            return REFUSED_RECEIVING
    profile = await get_profile(db, org_id)
    quarantine_id = profile.quarantine_location_id if profile else None
    if quarantine_id is not None and location_id in (
        await _under_async(db, org_id, quarantine_id)
    ):
        return REFUSED_QUARANTINE
    return None


async def _product_rule_async(
    db: AsyncSession, org_id: UUID, template_id: UUID, *, for_update: bool = False
) -> PutawayRule | None:
    """The product's own rule: one that names the product and nothing else."""
    query = (
        select(PutawayRule)
        .where(
            PutawayRule.organization_id == org_id,
            PutawayRule.product_template_id == template_id,
            PutawayRule.category_id.is_(None),
            PutawayRule.context_tag.is_(None),
            PutawayRule.storage_type_code.is_(None),
            PutawayRule.is_active.is_(True),
        )
        .order_by(PutawayRule.priority, PutawayRule.created_at.desc())
        .limit(1)
    )
    if for_update:
        query = query.with_for_update()
    return (await db.execute(query)).scalar_one_or_none()


async def is_silenced_async(db: AsyncSession, org_id: UUID, template_id: UUID) -> bool:
    """True when the product's put-away is not asked about a home shelf."""
    return (
        await db.scalar(
            select(PutawayHomeSilenced.id).where(
                PutawayHomeSilenced.organization_id == org_id,
                PutawayHomeSilenced.product_template_id == template_id,
            )
        )
    ) is not None


async def home_shelf_offer_async(
    db: AsyncSession,
    org_id: UUID,
    *,
    template_id: UUID,
    chosen_id: UUID,
    suggested_by_rule: UUID | None,
    forced: bool,
) -> HomeShelfOffer | None:
    """What the put-away says about the shelf the goods were put on, if anything.

    Nothing is said when the worker followed the rule's suggestion, when the
    choice was forced (the suggested shelf was full or not usable), or when
    the shelf already heads the product's own rule. Otherwise the shelf is
    offered as the product's home — ``set`` when the product has none,
    ``change`` when it has another — or, if it cannot be a home, the offer
    says why (``refused``).

    ``suggested_by_rule`` is the shelf a rule suggested; a shelf offered for
    lack of a rule (where the product already lies) is not a decision to
    follow, so it does not silence the question.
    """
    if forced or suggested_by_rule == chosen_id:
        return None
    rule = await _product_rule_async(db, org_id, template_id)
    homes = [row.location_id for row in rule.locations] if rule else []
    if homes[:1] == [chosen_id]:
        return None
    template = await core_api.product_templates.get_async(db, org_id, template_id)
    location = await core_api.locations.get_async(db, org_id, chosen_id)
    reason = await home_refusal_async(db, org_id, chosen_id)
    return HomeShelfOffer(
        kind='refused' if reason else ('change' if homes else 'set'),
        reason=reason,
        product_template_id=template_id,
        product_name=template.name if template else None,
        location_id=chosen_id,
        location_name=location.name if location else None,
    )


async def _journal_async(
    db: AsyncSession,
    org_id: UUID,
    user_id: UUID,
    template_id: UUID,
    snapshot: dict[str, str | None],
) -> None:
    """Write a product's home-shelf act to the organization log.

    Where goods of a product go is part of what the catalogue says about it,
    so the product is the target and the snapshot names what changed.
    """
    await core_api.audit_log.log_action_async(
        db,
        organization_id=org_id,
        user_id=user_id,
        action=AuditAction.UPDATE,
        target_type=AuditTargetType.PRODUCT_TEMPLATE,
        target_id=template_id,
        snapshot=snapshot,
    )


async def set_home_shelf_async(
    db: AsyncSession,
    org_id: UUID,
    user_id: UUID,
    template_id: UUID,
    location_id: UUID,
) -> PutawayRule:
    """Make ``location_id`` the product's home: the head of its own rule.

    A product that has a rule of its own keeps it: the new home goes first and
    the shelves it had follow, so a full home still overflows to where the
    goods used to go. A product with none gets one.
    """
    if await core_api.product_templates.get_async(db, org_id, template_id) is None:
        raise ServiceRejectionError('product_template_not_found')
    shelf = await core_api.locations.get_async(db, org_id, location_id)
    if shelf is None:
        raise ServiceRejectionError('storage_not_found')
    reason = await home_refusal_async(db, org_id, location_id)
    if reason is not None:
        raise ServiceRejectionError(_REFUSAL_KEYS[reason])
    rule = await _product_rule_async(db, org_id, template_id, for_update=True)
    if rule is None:
        rule = PutawayRule(
            organization_id=org_id,
            product_template_id=template_id,
            priority=_HOME_PRIORITY,
            is_active=True,
        )
        rule.locations = []
        db.add(rule)
    kept = [row.location_id for row in rule.locations if row.location_id != location_id]
    # keep: the unit of work inserts before it deletes, and the new list keeps
    # shelves of the old one — they would collide on the (rule, location) key
    rule.locations.clear()
    await db.flush()
    rule.locations.extend(
        PutawayRuleLocation(organization_id=org_id, location_id=shelf, position=place)
        for place, shelf in enumerate([location_id, *kept])
    )
    await db.flush()
    await _journal_async(db, org_id, user_id, template_id, {'home_shelf': shelf.name})
    return rule


async def silence_async(
    db: AsyncSession, org_id: UUID, user_id: UUID, template_id: UUID
) -> None:
    """Stop asking about this product's home shelf; asking twice changes nothing."""
    if await core_api.product_templates.get_async(db, org_id, template_id) is None:
        raise ServiceRejectionError('product_template_not_found')
    if not await is_silenced_async(db, org_id, template_id):
        db.add(
            PutawayHomeSilenced(organization_id=org_id, product_template_id=template_id)
        )
        await db.flush()
        await _journal_async(
            db, org_id, user_id, template_id, {'home_shelf_question': 'silenced'}
        )


async def unsilence_async(
    db: AsyncSession, org_id: UUID, user_id: UUID, template_id: UUID
) -> None:
    """Ask about this product's home shelf again."""
    row = await db.scalar(
        select(PutawayHomeSilenced)
        .where(
            PutawayHomeSilenced.organization_id == org_id,
            PutawayHomeSilenced.product_template_id == template_id,
        )
        .with_for_update()
    )
    if row is not None:
        await db.delete(row)
        await db.flush()
        await _journal_async(
            db, org_id, user_id, template_id, {'home_shelf_question': 'asked'}
        )


async def list_silenced_async(
    db: AsyncSession, org_id: UUID
) -> list[tuple[UUID, str | None]]:
    """The products not asked about, by name."""
    rows = (
        (
            await db.execute(
                select(PutawayHomeSilenced)
                .where(PutawayHomeSilenced.organization_id == org_id)
                .order_by(PutawayHomeSilenced.created_at)
            )
        )
        .scalars()
        .all()
    )
    named: list[tuple[UUID, str | None]] = []
    for row in rows:
        template = await core_api.product_templates.get_async(
            db, org_id, row.product_template_id
        )
        named.append((row.product_template_id, template.name if template else None))
    return named
