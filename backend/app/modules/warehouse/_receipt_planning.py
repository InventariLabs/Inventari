"""The putaway decision, spoken before the goods are booked.

Where a receipt line will land used to be answerable only after execution —
the executor picked the shelf while booking, and the reader found out through
"landed elsewhere". Both the read-side preview and the executor now go through
one planner (``ReceiptLocationPlanner``): the ranking lives once, rules load
once per document (they used to reload per line), and a preview can never
quietly diverge from what execution does, because there is no second copy.

The plan is computed at read time, never stored: rules may change between
opening a document and executing it, and a stored preview would lie exactly
the way the old "landed elsewhere" did.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import PutawayCandidateDTO
from app.core.public_api import core_api

from ._receiving_area import receiving_area_for_async
from ._shelf_fill import ShelfFill, shelf_fill
from .models import (
    Document,
    PutawayCapacity,
    PutawayLocationSetting,
    PutawayRule,
    PutawayRuleLocation,
)
from .putaway_criteria import refused_shelves_async

#: Decision sources, in the order the executor settles them: the serial
#: record is one physical thing; the line's own shelf is the worker's
#: answer to a full rack; then the rule, the document, the record.
#:
#: ``record`` is a safety net rather than a path anybody walks. Every
#: receipt type sits in ``document_types._REQUIRES_TARGET``, so no request
#: can create a receipt whose document target is null; the rung is reached
#: only by a document that lost its target after validation saw it. It is
#: covered by a unit test for exactly that reason — an unmeasured net reads
#: as dead code to the next person tidying up.
SOURCE_SERIAL = 'serial'
SOURCE_LINE = 'line'
SOURCE_RULE = 'rule'
SOURCE_DOCUMENT = 'document'
SOURCE_RECORD = 'record'
#: Not a decision the planner takes but what a two-step warehouse does with
#: it: the goods land in the receiving area, and the decision becomes the
#: shelf the putaway task suggests.
SOURCE_RECEIVING = 'receiving'

#: Deliveries from outside. Goods made in-house or returned internally are
#: put where they belong in one step, receiving area or not.
_RECEIVED_FROM_SUPPLIERS = frozenset({'IN', 'PZ'})


@dataclass(frozen=True)
class ReceiptLocationDecision:
    """Where one line will land, and who decided it.

    ``rule_*`` fields are filled whenever a matching rule existed — even when
    the line lost the ordering to the serial number or a named record — so the
    journal can say "the rule said A-12, it landed on A-13" instead of only
    showing the outcome.
    """

    location_id: UUID | None
    source: str
    rule_id: UUID | None = None
    rule_target_location_id: UUID | None = None
    rule_target_name: str | None = None
    rule_match_key: str | None = None
    rule_match_name: str | None = None
    #: Set when a rule matched but could not take the line — its target is
    #: archived or not a real shelf — and the decision fell to the next
    #: level. The preview says why instead of showing an unexplained shelf.
    rule_warning: str | None = None
    #: True when the rule's shelves are all too full: the plan names the
    #: first shelf on the list anyway — the goods have already arrived —
    #: and the numbers say by how much it is over.
    over_capacity: bool = False
    #: Stock already headed to the chosen shelf (this product, this
    #: document's earlier lines included) and the shelf's limit, in the
    #: product's stock unit. Either can be None: no capacity set means no
    #: limit, and no limit is not an overflow.
    capacity_used: Decimal | None = None
    capacity_max: Decimal | None = None
    #: The chosen shelf's whole fill in percent, set only when other
    #: limited products share it — then this product's own pair alone
    #: cannot explain why the shelf is full.
    shelf_fill: int | None = None


def _stock_by_product(quants: Any) -> dict[UUID, Decimal]:
    """Sum stock quants into one quantity per product."""
    totals: dict[UUID, Decimal] = {}
    for quant in quants:
        if quant.product_template_id is None:
            continue
        totals[quant.product_template_id] = totals.get(
            quant.product_template_id, Decimal('0')
        ) + (quant.quantity or Decimal('0'))
    return totals


@dataclass(frozen=True)
class _Match:
    """A rule that matches a line, with the key that made it match."""

    rule: PutawayRule
    match_key: str
    match_name: str | None


# Specificity tiers (lower index = more specific). Ranking is the resolver's
# contract: product > category > context tag > storage type, then priority
# ASC, then most recently created first.
_TIER_PRODUCT = 0
_TIER_CATEGORY = 1
_TIER_CONTEXT_TAG = 2
_TIER_STORAGE_TYPE = 3


def rank_putaway_matches(
    rules: list[PutawayRule],
    *,
    product_template_id: UUID | None,
    category_id: UUID | None,
    context_tag: str | None,
    storage_type_code: str | None,
    match_names: dict[str, str | None],
) -> _Match | None:
    """The best-matching rule, or None. Pure: no I/O, ranking only.

    A rule with several non-null match keys behaves as an OR — it fires when
    any key matches, and the most specific matching key sets its tier.
    ``match_names`` supplies display names for the keys that resolved to a
    row (product and category); tags and type codes are their own names.
    """
    best: tuple[tuple[int, int, int], _Match] | None = None
    for rule in rules:
        if not rule.is_active:
            continue
        if product_template_id is not None and (
            rule.product_template_id == product_template_id
        ):
            tier = _TIER_PRODUCT
            key = 'product_template'
        elif category_id is not None and rule.category_id == category_id:
            tier = _TIER_CATEGORY
            key = 'category'
        elif context_tag is not None and rule.context_tag == context_tag:
            tier = _TIER_CONTEXT_TAG
            key = 'context_tag'
        elif storage_type_code is not None and (
            rule.storage_type_code == storage_type_code
        ):
            tier = _TIER_STORAGE_TYPE
            key = 'storage_type'
        else:
            continue  # rule doesn't match this line

        # ``created_at`` is a datetime — invert to ordinal so the natural
        # tuple order (lower wins) prefers the most recent rule on a tie.
        created_ord = -rule.created_at.toordinal() if rule.created_at else 0
        order = (tier, rule.priority, created_ord)
        match = _Match(rule=rule, match_key=key, match_name=match_names.get(key))
        if best is None or order < best[0]:
            best = (order, match)
    return best[1] if best else None


class ReceiptPlanTarget:
    """What the planner reads off a document: the organization and the shelf.

    The one-screen receive form decides the plan before a document exists,
    and these two fields are all the planner ever asks the document for.
    Keeping the target this small is what lets the preview and the booking
    share one decision: a preview that had to invent a document would be a
    second copy by another name.
    """

    __slots__ = ('type', 'organization_id', 'target_location_id')

    def __init__(self, organization_id: UUID, target_location_id: UUID | None) -> None:
        # The one-screen form builds a receipt from a supplier, and that type
        # is what decides whether the warehouse receives in one step or into
        # its receiving area — a preview must answer that the way the posting
        # will, or it would promise the shelf the goods never reach.
        self.type = 'IN'
        self.organization_id = organization_id
        self.target_location_id = target_location_id


class ReceiptLocationPlanner:
    """The putaway decision for one receipt document.

    Build one per document (``for_document``) or per destination shelf
    (``for_target``): the organization's rules and the names the decision
    needs are loaded once, not once per line.
    """

    def __init__(self, db: AsyncSession, doc: Document | ReceiptPlanTarget) -> None:
        self._db = db
        self._doc = doc
        self._rules: list[PutawayRule] = []
        self._active_rules: list[PutawayRule] = []
        self._rule_locations: dict[UUID, list[UUID]] = {}
        self._targets: dict[UUID, Any] = {}
        self._location_names: dict[UUID, str | None] = {}
        self._doc_type_code: str | None | None = None  # None = not loaded yet
        self._categories: dict[UUID, Any] = {}
        self._template_names: dict[UUID, str | None] = {}
        # Capacity bookkeeping, all lazily cached per shelf: its limits
        # per product, whether it takes one product only, the stock already
        # standing there, and what THIS document's earlier lines sent there
        # per product. The last one is what makes two lines of one delivery
        # count together instead of each believing the shelf is empty.
        self._limits_at: dict[UUID, dict[UUID, Decimal]] = {}
        self._single_product: dict[UUID, bool] = {}
        self._stock_at: dict[UUID, dict[UUID, Decimal]] = {}
        self._planned_at: dict[UUID, dict[UUID, Decimal]] = {}
        #: Where this receipt lands first when its warehouse receives in two
        #: steps; ``None`` receives in one.
        self.receiving_location_id: UUID | None = None

    @classmethod
    async def for_target(
        cls,
        db: AsyncSession,
        organization_id: UUID,
        target_location_id: UUID | None,
    ) -> ReceiptLocationPlanner:
        """The same planner for a receipt whose document is still a form.

        The one-screen receive screen asks where each line will land before
        it creates anything. It sends the destination shelf and the lines;
        the decision comes from this planner, so what the screen shows and
        what the posting does cannot disagree.
        """
        return await cls.for_document(
            db, ReceiptPlanTarget(organization_id, target_location_id)
        )

    @classmethod
    async def for_document(
        cls,
        db: AsyncSession,
        doc: Document | ReceiptPlanTarget,
        *,
        user_id: UUID | None = None,
        like: ReceiptLocationPlanner | None = None,
    ) -> ReceiptLocationPlanner:
        """The planner for ``doc``; ``user_id`` when the receipt is being posted.

        Posting may have to make the warehouse's receiving area (see
        ``receiving_area_for_async``); a preview only reads it.

        ``like`` is a planner already built for another document of the same
        organization in the same read. Its rules and the shelves they name
        are taken over instead of read again — a reader planning two hundred
        open receipts read them two hundred times. Only those are shared:
        what this document's own lines send where starts empty.
        """
        planner = cls(db, doc)
        if doc.type in _RECEIVED_FROM_SUPPLIERS:
            planner.receiving_location_id = await receiving_area_for_async(
                db, doc.organization_id, doc.target_location_id, user_id=user_id
            )
        if like is not None and like._doc.organization_id == doc.organization_id:
            planner._rules = like._rules
            planner._rule_locations = like._rule_locations
            planner._targets = like._targets
            planner._location_names = like._location_names
            await planner._load_target(doc.target_location_id)
            planner._active_rules = like._active_rules
            return planner
        planner._rules = list(
            (
                await db.execute(
                    select(PutawayRule).where(
                        PutawayRule.organization_id == doc.organization_id,
                        PutawayRule.is_active.is_(True),
                    )
                )
            )
            .scalars()
            .all()
        )
        # Every shelf on every rule's list, in walking order, then each
        # shelf's name and state — one cached read each.
        rows = list(
            (
                await db.execute(
                    select(PutawayRuleLocation)
                    .join(
                        PutawayRule,
                        PutawayRule.id == PutawayRuleLocation.rule_id,
                    )
                    .where(PutawayRule.organization_id == doc.organization_id)
                    .order_by(
                        PutawayRuleLocation.rule_id,
                        PutawayRuleLocation.position,
                    )
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            planner._rule_locations.setdefault(row.rule_id, []).append(row.location_id)
            await planner._load_target(row.location_id)
        await planner._load_target(doc.target_location_id)
        # A rule whose every location is archived, or one of the virtual
        # counterparts, cannot take goods: it is out of the running, and the
        # decision says why it stepped aside instead of quietly ignoring it.
        planner._active_rules = [
            rule
            for rule in planner._rules
            if any(
                planner._target_takes_goods(loc)
                for loc in planner._rule_locations.get(rule.id, [])
            )
        ]
        return planner

    def _target_takes_goods(self, location_id: UUID | None) -> bool:
        if location_id is None:
            return False
        target = self._targets.get(location_id)
        if target is None:
            return False
        if (target.settings or {}).get('archived') is True:
            return False
        return bool(target.usage == 'internal')

    def _target_warning(self, location_id: UUID | None) -> str | None:
        """Why this shelf cannot take goods, for the reader of the plan."""
        if location_id is None:
            return None
        target = self._targets.get(location_id)
        if target is None:
            return 'archived'
        if (target.settings or {}).get('archived') is True:
            return 'archived'
        if target.usage != 'internal':
            return 'not_internal'
        return None

    async def _load_target(self, location_id: UUID | None) -> None:
        if location_id is not None and location_id not in self._targets:
            location = await core_api.locations.get_async(
                self._db, self._doc.organization_id, location_id
            )
            self._targets[location_id] = location
            self._location_names[location_id] = location.name if location else None

    async def decide(
        self,
        *,
        named: Any,
        stock_template_id: UUID | None,
        line_target_id: UUID | None = None,
        quantity_stock: Decimal | None = None,
    ) -> ReceiptLocationDecision:
        """Settle one line: serial record, line target, rule, document, record.

        The serial number is settled first for the same reason as in the
        executor: it is one physical thing, and nothing may put half of it
        on another shelf. A shelf named on the line comes next — the worker
        standing at a full rack outranks a rule written in advance. The rule
        is asked before that ordering either way, so any outcome can say
        which rule it set aside.

        ``quantity_stock`` is this line's quantity in the product's stock
        unit, and it is remembered against the shelf the decision chose —
        the next line of the same document is measured against a shelf that
        already knows what this one sent there.
        """
        match = await self._best_match(
            named=named,
            stock_template_id=stock_template_id,
            rules=self._active_rules,
        )
        # No usable rule matched — but a matching one whose target cannot
        # take goods? Its warning rides along, and the decision falls to the
        # next level.
        skipped = None
        if match is None:
            skipped = await self._best_match(
                named=named,
                stock_template_id=stock_template_id,
                rules=self._rules,
            )

        serial = named is not None and bool(named.serial_number)
        by_rule = None
        warning = None
        if match is not None and not serial and line_target_id is None:
            by_rule = await self._decide_by_rule(
                match,
                stock_template_id,
                named.category_id if named is not None else None,
                quantity_stock,
            )
            if by_rule is None:
                # A module's criterion refused every shelf of the rule: the
                # rule steps aside the way it does for an archived list, and
                # the decision says so.
                match, skipped, warning = None, match, 'refused'

        if serial:
            decision = self._decision(match, named.location_id, SOURCE_SERIAL, skipped)
        elif line_target_id is not None:
            decision = self._decision(match, line_target_id, SOURCE_LINE, skipped)
        elif by_rule is not None:
            decision = by_rule
        elif self._doc.target_location_id is not None:
            decision = self._decision(
                match,
                self._doc.target_location_id,
                SOURCE_DOCUMENT,
                skipped,
                warning=warning,
            )
        else:
            decision = self._decision(
                match,
                named.location_id if named is not None else None,
                SOURCE_RECORD,
                skipped,
                warning=warning,
            )

        if (
            decision.location_id is not None
            and quantity_stock is not None
            and stock_template_id is not None
        ):
            planned = self._planned_at.setdefault(decision.location_id, {})
            planned[stock_template_id] = (
                planned.get(stock_template_id, Decimal('0')) + quantity_stock
            )
        return decision

    async def _decide_by_rule(
        self,
        match: _Match,
        stock_template_id: UUID | None,
        category_id: UUID | None,
        quantity_stock: Decimal | None,
    ) -> ReceiptLocationDecision | None:
        """Walk the rule's list in order and settle on the first shelf the
        goods fit.

        A shelf a module's criterion refuses (``putaway_criteria``) is off
        the list before the walk: it is not full, it is wrong for the goods,
        so it is not the fallback either. ``None`` when every shelf is
        refused — the rule cannot take the line at all.

        A shelf fits while the sum of its products' shares, this line's
        included, stays within 100% (``_shelf_fill``); a product with no
        limit there takes no share and always fits. A single-product shelf
        with another product standing on it never does. A line goes to one
        shelf whole: one that only partly fits sends it on to the next.
        Nothing fits → the first shelf on the list takes the plan with an
        over-capacity mark: the goods have already arrived, and a warning
        can be read while a refusal only strands them.
        """
        locations = [
            loc
            for loc in self._rule_locations.get(match.rule.id, [])
            if self._target_takes_goods(loc)
        ]
        refused = await refused_shelves_async(
            self._db,
            self._doc.organization_id,
            PutawayCandidateDTO(
                product_template_id=stock_template_id,
                category_id=category_id,
                quantity=quantity_stock,
                location_ids=locations,
            ),
        )
        if refused:
            locations = [loc for loc in locations if loc not in refused]
            if not locations:
                return None
        for location_id in locations:
            if await self._fits(location_id, stock_template_id, quantity_stock):
                return await self._rule_decision(
                    match,
                    location_id,
                    stock_template_id,
                    quantity_stock,
                    over_capacity=False,
                )
        fallback = locations[0] if locations else None
        return await self._rule_decision(
            match, fallback, stock_template_id, quantity_stock, over_capacity=True
        )

    async def _rule_decision(
        self,
        match: _Match,
        location_id: UUID | None,
        stock_template_id: UUID | None,
        quantity_stock: Decimal | None,
        *,
        over_capacity: bool,
    ) -> ReceiptLocationDecision:
        """The rule's decision with the chosen shelf's numbers for the reader:
        this product's pair, and the whole shelf's fill when other products
        share it — with this line on it, so an over-full shelf says how full
        it will be rather than how full it was."""
        if location_id is None:
            return self._decision(match, None, SOURCE_RULE, over_capacity=over_capacity)
        quantities = await self._quantities_at(location_id)
        used = (
            quantities.get(stock_template_id, Decimal('0'))
            if stock_template_id is not None
            else Decimal('0')
        )
        limits = await self._limits_of(location_id)
        if stock_template_id is not None and quantity_stock:
            quantities[stock_template_id] = used + quantity_stock
        fill = shelf_fill(quantities, limits)
        shared = any(
            share.share is not None
            and share.quantity > 0
            and share.product_template_id != stock_template_id
            for share in fill.shares
        )
        return self._decision(
            match,
            location_id,
            SOURCE_RULE,
            over_capacity=over_capacity,
            capacity_used=used,
            capacity_max=limits.get(stock_template_id) if stock_template_id else None,
            shelf_fill=fill.percent if shared else None,
        )

    async def _limits_of(self, location_id: UUID) -> dict[UUID, Decimal]:
        """The shelf's limit per product; a product missing has no limit."""
        if location_id not in self._limits_at:
            rows = (
                await self._db.execute(
                    select(
                        PutawayCapacity.product_template_id,
                        PutawayCapacity.max_quantity,
                    ).where(
                        PutawayCapacity.organization_id == self._doc.organization_id,
                        PutawayCapacity.location_id == location_id,
                    )
                )
            ).all()
            self._limits_at[location_id] = {pid: cap for pid, cap in rows if cap}
        return self._limits_at[location_id]

    async def _takes_single_product(self, location_id: UUID) -> bool:
        if location_id not in self._single_product:
            single = await self._db.scalar(
                select(PutawayLocationSetting.single_product).where(
                    PutawayLocationSetting.organization_id == self._doc.organization_id,
                    PutawayLocationSetting.location_id == location_id,
                )
            )
            self._single_product[location_id] = bool(single)
        return self._single_product[location_id]

    async def _standing_stock(self, location_id: UUID) -> dict[UUID, Decimal]:
        """Every product's stock standing on the shelf, in its stock unit."""
        if location_id not in self._stock_at:
            quants = await core_api.stock.list_quants_async(
                self._db,
                self._doc.organization_id,
                storage_location_id=location_id,
            )
            self._stock_at[location_id] = _stock_by_product(quants)
        return self._stock_at[location_id]

    async def _quantities_at(self, location_id: UUID) -> dict[UUID, Decimal]:
        """What stands on the shelf plus what this document already sent."""
        quantities = dict(await self._standing_stock(location_id))
        for pid, qty in self._planned_at.get(location_id, {}).items():
            quantities[pid] = quantities.get(pid, Decimal('0')) + qty
        return quantities

    async def _fill_at(self, location_id: UUID) -> ShelfFill:
        return shelf_fill(
            await self._quantities_at(location_id),
            await self._limits_of(location_id),
        )

    async def _fits(
        self,
        location_id: UUID,
        stock_template_id: UUID | None,
        quantity_stock: Decimal | None,
    ) -> bool:
        """Whether the line's quantity fits on this shelf.

        The single-product promise comes before the capacity question: a
        shelf that vowed to hold one product is full the moment another
        product stands on it, whether or not anybody set a limit."""
        if await self._takes_single_product(location_id) and (
            stock_template_id is not None
            and any(
                pid != stock_template_id
                for pid, qty in (await self._standing_stock(location_id)).items()
                if qty > 0
            )
        ):
            return False
        fill = await self._fill_at(location_id)
        return fill.fits(stock_template_id, quantity_stock or Decimal('0'))

    def _decision(
        self,
        match: _Match | None,
        location_id: UUID | None,
        source: str,
        skipped: _Match | None = None,
        *,
        warning: str | None = None,
        over_capacity: bool = False,
        capacity_used: Decimal | None = None,
        capacity_max: Decimal | None = None,
        shelf_fill: int | None = None,
    ) -> ReceiptLocationDecision:
        """A decision carrying the rule it set aside, if a rule matched.

        The ordering may settle the line before the rule gets a word in —
        a serial number, a named record — but the rule's say still rides
        along, for the journal and for the reader comparing the two. A rule
        skipped for an unusable target is reported the same way, with the
        reason on top; ``warning`` names a reason the shelves' own state does
        not show (``refused``: a module's criterion turned every one down).
        """
        rule_source = match or skipped
        # The rule's shelves, in walking order; the head is what a reader
        # compares the outcome against.
        rule_targets = (
            self._rule_locations.get(rule_source.rule.id, []) if rule_source else []
        )
        rule_head = rule_targets[0] if rule_targets else None
        return ReceiptLocationDecision(
            location_id=location_id,
            source=source,
            rule_id=rule_source.rule.id if rule_source else None,
            rule_target_location_id=rule_head,
            rule_target_name=self._location_name(rule_head),
            rule_match_key=rule_source.match_key if rule_source else None,
            rule_match_name=rule_source.match_name if rule_source else None,
            rule_warning=warning
            or (self._first_location_warning(skipped.rule) if skipped else None),
            over_capacity=over_capacity,
            capacity_used=capacity_used,
            capacity_max=capacity_max,
            shelf_fill=shelf_fill,
        )

    def _first_location_warning(self, rule: PutawayRule) -> str | None:
        """Why a rule could not take the line at all: the state of its
        first shelf — the one a reader would have expected to win."""
        locations = self._rule_locations.get(rule.id, [])
        return self._target_warning(locations[0] if locations else None)

    async def _best_match(
        self,
        *,
        named: Any,
        stock_template_id: UUID | None,
        rules: list[PutawayRule] | None = None,
    ) -> _Match | None:
        """The best matching rule for this line, with match names resolved.

        Match inputs mirror the executor exactly: the context tag comes from
        the record's category, the storage type code from the document's
        target location — a ``FREEZER`` rule fires when the delivery's
        default destination is a freezer, not when the goods stand in one.
        """
        category_id = named.category_id if named is not None else None
        context_tag: str | None = None
        match_names: dict[str, str | None] = {}
        if category_id is not None:
            category = await self._category(category_id)
            if category is not None:
                context_tag = category.context_tag
                match_names['category'] = category.name
        if stock_template_id is not None:
            match_names['product_template'] = await self._template_name(
                stock_template_id
            )

        return rank_putaway_matches(
            rules if rules is not None else self._rules,
            product_template_id=stock_template_id,
            category_id=category_id,
            context_tag=context_tag,
            storage_type_code=await self._doc_target_type_code(),
            match_names=match_names,
        )

    async def _category(self, category_id: UUID) -> Any:
        if category_id not in self._categories:
            self._categories[category_id] = await core_api.categories.get_by_id_async(
                self._db, self._doc.organization_id, category_id
            )
        return self._categories[category_id]

    async def _template_name(self, template_id: UUID) -> str | None:
        if template_id not in self._template_names:
            template = await core_api.product_templates.get_async(
                self._db, self._doc.organization_id, template_id
            )
            self._template_names[template_id] = template.name if template else None
        return self._template_names[template_id]

    async def _doc_target_type_code(self) -> str | None:
        if self._doc_type_code is None:
            code: str | None = None
            if self._doc.target_location_id is not None:
                location = await core_api.locations.get_with_type_async(
                    self._db, self._doc.organization_id, self._doc.target_location_id
                )
                if location is not None and location.location_type is not None:
                    code = location.location_type.type_code
            self._doc_type_code = code
        return self._doc_type_code

    async def location_name(self, location_id: UUID | None) -> str | None:
        """The shelf's name, for a reader who does not hold UUIDs."""
        if location_id is None:
            return None
        if location_id not in self._location_names:
            location = await core_api.locations.get_async(
                self._db, self._doc.organization_id, location_id
            )
            self._location_names[location_id] = location.name if location else None
        return self._location_names[location_id]

    def landing(self, decision: ReceiptLocationDecision) -> UUID | None:
        """Where the goods are booked: the decision, or the receiving area.

        A serial number keeps its own record wherever it stands — it is one
        physical thing, already somewhere.
        """
        if self.receiving_location_id is None or decision.source == SOURCE_SERIAL:
            return decision.location_id
        return self.receiving_location_id

    def booked(self, decision: ReceiptLocationDecision) -> ReceiptLocationDecision:
        """The decision as the booking records it, the landing step included.

        Both readers of a plan — the saved document and the form that has no
        row yet — have to answer where the goods are booked, not only where
        the rules send them afterwards. A warehouse that receives in two
        steps therefore names its receiving area here, whatever source the
        decision came from.
        """
        landing = self.landing(decision)
        if landing == decision.location_id:
            return decision
        return replace(decision, location_id=landing, source=SOURCE_RECEIVING)

    def _location_name(self, location_id: UUID | None) -> str | None:
        """Sync read of a name ``for_document`` already resolved."""
        return self._location_names.get(location_id) if location_id else None


async def receipt_line_card_async(
    db: AsyncSession,
    org_id: UUID,
    *,
    product_template_id: UUID | None,
    named: Any,
    barcode: str | None = None,
) -> UUID | None:
    """The card the planner is asked about for one receipt line.

    The executor settles the card before it asks where the goods go: the
    line's own, its record's, the one a record without a card adopts, and —
    once the receipt is confirmed — the one a bare barcode names. A plan
    shown beforehand (the form's preview, the read of a draft, the count of
    receipts waiting for space) has to ask with the same card, or a rule
    written for it answers in the booking and not in the plan. Nothing is
    minted here: a name no card answers to gets a fresh card at execution,
    and a fresh card has no rules.
    """
    if product_template_id is not None:
        return product_template_id
    if named is not None:
        if named.template_id is not None:
            return UUID(str(named.template_id))
        adopted = await core_api.product_templates.lookup_by_identity_async(
            db, org_id, name=named.name, brand=named.brand, barcode=named.barcode
        )
        return adopted.id if adopted is not None else None
    if barcode:
        known = await core_api.product_templates.lookup_by_barcode_async(
            db, org_id, barcode
        )
        return known.id if known is not None else None
    return None


async def attach_receipt_plans(db: AsyncSession, doc: Document) -> None:
    """Put the planned shelf on every not-yet-executed receipt line.

    Transient by design: set on the ORM objects for the read that asked,
    never written back. The schema picks the attributes up; a document read
    after execution shows ``executed_location_id`` as before and no plan.
    """
    from . import document_types as dt

    if not dt.is_receipt(doc.type):
        return
    planner = await ReceiptLocationPlanner.for_document(db, doc)
    for line in doc.lines:
        if line.executed_location_id is not None:
            continue
        # The lines arrive with their items selectin-loaded, so the record a
        # line names is already in memory — the same record the executor
        # would fetch by id.
        named = line.item
        stock_template_id = await receipt_line_card_async(
            db,
            doc.organization_id,
            product_template_id=line.product_template_id,
            named=named,
            barcode=line.barcode,
        )
        # Capacity speaks the product's stock unit; the line speaks the
        # supplier's. The same conversion the executor makes, so the plan
        # and the booking measure the same number. The plan counts what the
        # document EXPECTS — before execution the done count is zero and
        # would plan every line as an empty delivery.
        quantity_stock = await core_api.uoms.to_stock_uom_async(
            db,
            doc.organization_id,
            stock_template_id,
            line.expected_quantity,
            line.uom_id,
        )
        decision = planner.booked(
            await planner.decide(
                named=named,
                stock_template_id=stock_template_id,
                line_target_id=line.target_location_id,
                quantity_stock=quantity_stock,
            )
        )
        # Transient attributes on the ORM object, the way
        # ``generated_backorder_id`` rides on the document: declared by the
        # schema that reads them, never by the table that stores rows.
        plan = {
            'planned_location_id': decision.location_id,
            'planned_location_name': await planner.location_name(decision.location_id),
            'planned_source': decision.source,
            'planned_rule_id': decision.rule_id,
            'planned_rule_match_key': decision.rule_match_key,
            'planned_rule_match_name': decision.rule_match_name,
            'planned_rule_warning': decision.rule_warning,
            'planned_over_capacity': decision.over_capacity or None,
            'planned_capacity_used': decision.capacity_used,
            'planned_capacity_max': decision.capacity_max,
            'planned_shelf_fill': decision.shelf_fill,
        }
        for field, value in plan.items():
            setattr(line, field, value)


async def most_stocked_shelf_async(
    db: AsyncSession,
    organization_id: UUID,
    shelves: list[UUID],
    template_id: UUID,
) -> UUID | None:
    """The shelf among *shelves* holding most of the product, if any does.

    The one fallback both floor offers share — the phone's receiving card and
    a put-away task nobody's rule names a shelf for — so the two cannot
    disagree about where the product "already lies".
    """
    quants = await core_api.stock.list_quants_async(
        db,
        organization_id,
        product_template_id=template_id,
        storage_location_ids=shelves,
    )
    held: dict[UUID, Decimal] = {}
    for quant in quants:
        held[quant.location_id] = held.get(quant.location_id, Decimal('0')) + (
            quant.quantity or Decimal('0')
        )
    stocked = [(qty, loc) for loc, qty in held.items() if qty > 0]
    return max(stocked, key=lambda pair: pair[0])[1] if stocked else None


async def floor_shelf_offer_async(
    db: AsyncSession,
    organization_id: UUID,
    zone_id: UUID,
    template_id: UUID | None,
) -> tuple[UUID, str] | None:
    """The shelf to offer the phone's card when the plan is a whole zone.

    A delivery addressed to the warehouse, with no rule for its product,
    plans onto the warehouse itself — true, and useless to the person
    holding the box. Below that zone the card offers the shelf with most of
    the product already on it (``stock``), else the shelf the last completed
    receipt put goods on (``zone``). ``None`` when the zone has no shelves
    below it — the document named a shelf, and that is the answer — or when
    there is nothing to offer and the worker chooses.

    An offer, not a decision: the executor never reads it. The card books it
    by naming it as the line's shelf, which the planner then ranks as the
    worker's own answer.
    """
    from . import document_types as dt
    from .models import Document, DocumentLine, DocumentStatus

    shelves = await core_api.locations.descendant_ids_async(
        db, organization_id, zone_id
    )
    if not shelves:
        return None
    if template_id is not None:
        stocked = await most_stocked_shelf_async(
            db, organization_id, shelves, template_id
        )
        if stocked is not None:
            return stocked, 'stock'
    last = await db.scalar(
        select(DocumentLine.executed_location_id)
        .join(Document, Document.id == DocumentLine.document_id)
        .where(
            Document.organization_id == organization_id,
            Document.type.in_(sorted(dt._RECEIPT)),
            Document.status == DocumentStatus.COMPLETED.value,
            DocumentLine.executed_location_id.in_(shelves),
        )
        .order_by(Document.completed_at.desc().nulls_last())
        .limit(1)
    )
    return (last, 'zone') if last is not None else None
