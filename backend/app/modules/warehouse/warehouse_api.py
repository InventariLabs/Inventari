"""Public API for document operations — exposed for other modules (e.g., purchase_orders).

Follows the approvals_api pattern: module owns its API, other modules import directly.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Literal, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import (
    CountDifferenceDTO,
    DocumentStateDTO,
    ReceiptLineFromPODTO,
    ReplenishmentProposalDTO,
)
from app.core.logging import get_logger

from ._over_receipt import OverReceiptRefusedError, order_surplus_async

if TYPE_CHECKING:
    from .document_filters import DocumentFilterProvider
    from .document_numbering_service import HighestInUse
    from .pick_order_strategies import PickOrderStrategy
    from .pre_post_checks import PrePostCheck, WithdrawalListener
    from .putaway_criteria import PutawayCriterion
    from .schemas import DocumentCreate
    from .work_item_providers import WorkItemProvider

logger = get_logger(__name__)


class WarehouseAPI:
    """Public API for document operations.

    Provides a stable interface for other modules (e.g., purchase_orders) to create
    and query documents without importing from the warehouse module directly.
    """

    async def putaway_capacity_for_pair_async(
        self,
        db: AsyncSession,
        org_id: UUID,
        *,
        location_id: UUID,
        product_template_id: UUID,
    ) -> Decimal | None:
        """The shelf's limit for this product, in the product's stock unit.

        None when nobody set a capacity — which is not zero: a shelf with
        no entry has no limit, and a caller must not read the absence as a
        full or an empty shelf.
        """
        from .models import PutawayCapacity

        max_quantity = await db.scalar(
            select(PutawayCapacity.max_quantity).where(
                PutawayCapacity.organization_id == org_id,
                PutawayCapacity.location_id == location_id,
                PutawayCapacity.product_template_id == product_template_id,
            )
        )
        return max_quantity

    async def putaway_capacity_map_async(
        self,
        db: AsyncSession,
        org_id: UUID,
        *,
        pairs: Iterable[tuple[UUID, UUID]],
    ) -> dict[tuple[UUID, UUID], Decimal]:
        """The shelves' limits for many (location, product) pairs in one read.

        List endpoints enrich every row with its pair's capacity, and a
        per-pair read there is an N+1. A pair with no entry is absent from
        the map — no limit is not zero, the same contract as the single
        read above.
        """
        from .models import PutawayCapacity

        wanted = set(pairs)
        if not wanted:
            return {}
        rows = await db.execute(
            select(
                PutawayCapacity.location_id,
                PutawayCapacity.product_template_id,
                PutawayCapacity.max_quantity,
            ).where(
                PutawayCapacity.organization_id == org_id,
                PutawayCapacity.location_id.in_({loc for loc, _ in wanted}),
                PutawayCapacity.product_template_id.in_({tpl for _, tpl in wanted}),
            )
        )
        return {
            (location_id, template_id): max_quantity
            for location_id, template_id, max_quantity in rows
            if (location_id, template_id) in wanted
        }

    async def generate_number_async(
        self,
        db: AsyncSession,
        org_id: UUID,
        doc_type: str,
        *,
        document_date: date | None = None,
        highest_in_use: HighestInUse | None = None,
        sequence_format: str | None = None,
        sequence_width: int | None = None,
    ) -> str:
        """The next number of *doc_type* in this organization's register.

        One numbering engine for everything an organization numbers: the
        format, the padding and the counter are the ones its documents use,
        so changing the format reaches every type rather than the ones that
        happen to be documents.

        A type whose records live outside the ``documents`` table passes
        ``highest_in_use`` — the engine cannot find its floor by itself, and
        seeding a counter at one on a register that is a year deep hands out
        a number somebody already has.

        ``sequence_format`` is the per-type override from ``DocumentTypeConfig``,
        passed by the caller that already loaded it. A type carrying numbers
        already printed at a width of its own states that width here through
        ``sequence_width``, so the register does not hand out a number shaped
        differently from its history: the organization's format stays the
        organization's, and only the digits on the paper stay put.
        """
        from .document_numbering_service import generate_number

        return await generate_number(
            db,
            org_id,
            doc_type,
            sequence_format,
            document_date=document_date,
            highest_in_use=highest_in_use,
            sequence_width=sequence_width,
        )

    async def renumber_for_date_async(
        self,
        db: AsyncSession,
        org_id: UUID,
        doc_type: str,
        number: str,
        document_date: date | None,
        *,
        highest_in_use: HighestInUse | None = None,
    ) -> str:
        """*number* if it is still filed where *document_date* says, else a new one.

        A record moved to another period carries the period its number was
        drawn in; left alone, the register and the number disagree.
        """
        from .document_numbering_service import number_for_date_async

        return await number_for_date_async(
            db,
            org_id,
            doc_type,
            number,
            None,
            document_date,
            highest_in_use,
        )

    @staticmethod
    def highest_sequence(numbers: Iterable[str], prefix: str) -> int:
        """The highest number already in use among *numbers* drawn for *prefix*.

        A caller whose records live outside the ``documents`` table seeds its
        register with this instead of importing the numbering service
        directly — same floor-finding the engine itself uses.
        """
        from .document_numbering_service import highest_sequence

        return highest_sequence(numbers, prefix)

    async def create_and_confirm_document_async(
        self,
        db: AsyncSession,
        org_id: UUID,
        data: Any,
        user_id: UUID,
        *,
        currency: str | None = None,
    ) -> Any:
        """Create and confirm a document from an async caller.

        Pass ``currency`` when the document is derived from something already
        priced — the amounts travel unconverted, so the sign in front of them
        has to travel too.
        """
        from .document_workflow_service import confirm_document, create_document
        from .models import Document

        doc = await create_document(db, org_id, data, user_id, currency=currency)
        doc = await confirm_document(db, org_id, doc.id, user_id)
        return cast('Document', doc)

    async def create_document_draft_async(
        self,
        db: AsyncSession,
        org_id: UUID,
        data: DocumentCreate,
        user_id: UUID,
    ) -> Any:
        """Create a DRAFT document without confirming or executing stock.

        For callers that already applied the stock movement themselves
        (e.g. recipe picking) and only need an audit-trail document in
        the register. The document stays DRAFT, and it is marked as a record
        of a movement already applied: confirming holds nothing and
        completing it moves nothing, so finishing it cannot take the goods
        off the shelf a second time.
        """
        from ._document_workflow_crud import create_document
        from .models import Document

        doc = await create_document(
            db, org_id, data, user_id, stock_already_applied=True
        )
        return cast('Document', doc)

    async def record_count_differences_async(
        self,
        db: AsyncSession,
        org_id: UUID,
        user_id: UUID,
        *,
        location_id: UUID,
        differences: list[CountDifferenceDTO],
        reference: str,
        notes: str | None = None,
    ) -> tuple[UUID, str] | None:
        """Write the one completed adjustment that records a count's differences.

        For a count that has already moved the stock: the document is the
        register's copy and moves nothing (see ``record_count_differences``).
        Runs in the caller's transaction and commits nothing. Returns the
        document's id and number, or ``None`` when there is no difference or
        the warehouse module is off for the organization.
        """
        from app.core.public_api import core_api

        if not differences:
            return None
        if not await core_api.organizations.is_module_enabled_async(
            db, org_id, 'warehouse'
        ):
            return None
        from .document_correction_service import record_count_differences

        doc = await record_count_differences(
            db,
            org_id,
            user_id,
            location_id=location_id,
            differences=differences,
            reference=reference,
            notes=notes,
        )
        return doc.id, doc.number

    def _build_receipt_from_po_data(
        self,
        partner_id: UUID | None,
        target_location_id: UUID,
        po_number: str,
        scheduled_date: date | None = None,
        notes: str | None = None,
        lines: list[ReceiptLineFromPODTO] | None = None,
    ) -> Any:
        from .schemas import DocumentCreate, DocumentLineCreate

        doc_lines = [
            DocumentLineCreate(
                product_template_id=line.product_template_id,
                name=line.name,
                expected_quantity=line.quantity,
                unit_price=line.unit_price,
                uom_id=line.uom_id,
                tax_rate=line.tax_rate,
                notes=line.notes,
                source_po_line_id=line.source_po_line_id,
            )
            for line in (lines or [])
        ]

        return DocumentCreate(
            type='IN',
            partner_id=partner_id,
            target_location_id=target_location_id,
            scheduled_date=scheduled_date,
            notes=notes,
            external_reference=po_number,
            lines=doc_lines,
        )

    async def create_receipt_from_po_async(
        self,
        db: AsyncSession,
        org_id: UUID,
        user_id: UUID,
        partner_id: UUID | None,
        target_location_id: UUID,
        po_number: str,
        scheduled_date: date | None = None,
        notes: str | None = None,
        lines: list[ReceiptLineFromPODTO] | None = None,
        currency: str | None = None,
    ) -> Any:
        """Create and confirm an IN receipt document from an async caller.

        ``currency`` is the order's — the line prices below are copied off it
        digit for digit, so reading them under the organization's sign is how
        100 × 40.10 PLN came to be shown as $601.50.
        """
        doc_data = self._build_receipt_from_po_data(
            partner_id,
            target_location_id,
            po_number,
            scheduled_date=scheduled_date,
            notes=notes,
            lines=lines,
        )

        return await self.create_and_confirm_document_async(
            db, org_id, doc_data, user_id, currency=currency
        )

    async def list_by_source_po_line_ids_async(
        self,
        db: AsyncSession,
        org_id: UUID,
        po_line_ids: list[UUID],
    ) -> list[Any]:
        """Async: list IN documents linked to the given PO line IDs."""
        from .models import Document, DocumentLine

        if not po_line_ids:
            return []

        result = await db.execute(
            select(DocumentLine.document_id)
            .where(DocumentLine.source_po_line_id.in_(po_line_ids))
            .distinct()
        )
        receipt_ids_raw = result.scalars().all()
        receipt_ids = list(receipt_ids_raw)
        if not receipt_ids:
            return []

        result2 = await db.execute(
            select(Document)
            .where(
                Document.id.in_(receipt_ids),
                Document.organization_id == org_id,
            )
            .order_by(Document.created_at.desc())
        )
        return list(result2.scalars().all())

    async def post_reserve_replenishment_async(
        self,
        db: AsyncSession,
        org_id: UUID,
        user_id: UUID,
        proposal: ReplenishmentProposalDTO,
        *,
        scanned_code: str | None = None,
    ) -> DocumentStateDTO:
        """Carry out the reserve move a reorder rule's alert proposes.

        The caller derives *proposal* from live stock; the warehouse owns the
        move: the shelf scan the profile asks for is checked, then one
        internal transfer is created and posted through the door every
        transfer uses, under the period, approval and stock rules. An empty
        proposal — the shortage went away meanwhile — is refused.
        """
        from ._replenishment_move import post_reserve_replenishment_async

        doc = await post_reserve_replenishment_async(
            db, org_id, user_id, proposal, scanned_code=scanned_code
        )
        return DocumentStateDTO(
            id=doc.id,
            number=doc.number,
            type=doc.type,
            status=doc.status,
            confirmed_by=doc.confirmed_by,
            held_by=doc.held_by,
        )

    async def committed_to_order_lines_async(
        self,
        db: AsyncSession,
        org_id: UUID,
        order_line_ids: list[UUID],
        *,
        excluding_document_id: UUID | None = None,
    ) -> dict[UUID, Decimal]:
        """``{order_line_id: quantity documents have already spoken for}``.

        In the product's stock unit, for the order lines a module's own
        ceiling is weighed against. A completed receipt counts what it
        brought, an open one what it expects, a cancelled one nothing, and
        the document being weighed (*excluding_document_id*) is left out.
        """
        from ._po_receipt_guard import committed_by_others_async

        return await committed_by_others_async(
            db, org_id, excluding_document_id, order_line_ids
        )

    async def order_surplus_async(
        self,
        db: AsyncSession,
        org_id: UUID,
        *,
        quantity: Decimal,
        remaining: Decimal,
        may_exceed: bool,
        product: str | None,
        order_label: tuple[str, int] | None,
    ) -> tuple[str, str] | None:
        """Whether *quantity*, past *remaining* on an order line, may stand.

        The over-receipt rule, asked by the module that owns the order: the
        organization's tolerance and hard ceiling, and the
        ``warehouse:receive_over_tolerance`` permission (*may_exceed*). ``None``
        when it may; otherwise ``(refusal, question)`` — the sentence for a
        reader who may not, and what a holder is asked instead — for the
        caller to raise as ``OverReceiptRefusedError``. Past the ceiling it
        raises a rejection for everyone.
        """
        return await order_surplus_async(
            db,
            org_id,
            quantity=quantity,
            remaining=remaining,
            may_exceed=may_exceed,
            product=product,
            order_label=order_label,
        )

    @staticmethod
    def register_work_item_provider(module: str, provider: WorkItemProvider) -> None:
        """Add your own tasks to To do and the work board.

        Called at the contributing module's import time, like the approvals
        target-summary provider. The provider takes ``(db, org_id, query)`` —
        ``query`` names the day, the page size and the reader — and returns
        ``(tasks, total)`` as ``WorkItemDTO``s: a kind, the sentence (or the
        fields a built-in sentence is made of), the due day, ``todo``,
        ``in_progress`` or ``done`` (the last only when ``query.done_since``
        asks for finished work) read from your own records, and the one next action
        as a label and an in-app link. It is called only while ``module`` is
        enabled for the organization, so a disabled module's tasks
        disappear, and an error in it is logged and leaves the rest of the
        list intact.
        """
        from .work_item_providers import register_work_item_provider

        register_work_item_provider(module, provider)

    @staticmethod
    def register_pre_post_check(
        module: str,
        check: PrePostCheck,
        on_withdrawn: WithdrawalListener | None = None,
    ) -> None:
        """Let your module stop a document from posting, or hold it.

        Called at the contributing module's import time, like a work item
        provider. The check takes ``(db, org_id, document)`` — a
        ``DocumentToPostDTO`` with its lines and who submits it — and is
        asked inside the posting's transaction twice: with
        ``stage='confirm'`` once a draft has drawn its number and before its
        stock is reserved, and with ``stage='post'`` before its stock moves, when each
        line's ``done_quantity`` says what is being posted. Every door goes
        through both: the one-step post, confirm, complete, and a release
        that completes a document.

        Returning ``None`` lets the posting go on. Raising ``InterceptorError``
        with a message in the reader's language (``get_module_error_message``)
        refuses it: the reader gets a 422 with that message and the
        ``error_code`` you give, and the transaction is rolled back, so
        nothing of the posting is written. Any other exception refuses it
        too, as an error. The check is asked only while ``module`` is enabled
        for the organization. It must not commit.

        Returning ``'hold'`` at ``confirm`` lets the confirmation go through
        and parks the document in ``PENDING_APPROVAL`` for your module: it is
        numbered and its stock reserved, and nothing completes it until you
        call ``release_document_async``, ``withdraw_hold_async`` or
        ``return_to_draft_async``. A hold of a module switched off for the
        organization stands down. The approvals module gates documents this
        way.

        ``on_withdrawn`` — ``(db, org_id, document_id, user_id)`` — is told
        when a document is cancelled or deleted, inside that transaction, so
        a module that holds documents can drop what it keeps about one. It
        must not commit, and an exception it raises refuses the withdrawal.
        """
        from .pre_post_checks import register_pre_post_check

        register_pre_post_check(module, check, on_withdrawn)

    @staticmethod
    def register_putaway_criterion(module: str, criterion: PutawayCriterion) -> None:
        """Let your module turn down shelves the putaway ranking would offer.

        Called at the contributing module's import time, like a pre-post
        check. When an operator's putaway rule takes a receipt line, the
        criterion takes ``(db, org_id, candidate)`` — a
        ``PutawayCandidateDTO`` with the line's product, category and
        quantity in the stock unit, and the rule's shelves in walking order
        — and answers the shelves that may not take it (an empty collection
        lets every one through). The ranking walks the rest by capacity, as
        it does without you. When you turn down every shelf, the rule steps
        aside: the line goes to the document's destination, and the plan
        says ``planned_rule_warning='refused'``.

        The same answer serves the preview a reader sees and the booking, so
        the two cannot disagree; it is asked in both, inside their
        transaction, and must not write. A shelf the worker named on the line
        and a serial number's own record are not asked about — stop those
        with a pre-post check. The criterion is asked only while ``module``
        is enabled for the organization; an exception it raises fails the
        read or the posting that asked.
        """
        from .putaway_criteria import register_putaway_criterion

        register_putaway_criterion(module, criterion)

    async def get_document_state_async(
        self, db: AsyncSession, org_id: UUID, document_id: UUID
    ) -> DocumentStateDTO | None:
        """Where a document of this organization stands, or ``None``."""
        from .models import Document

        doc = await db.scalar(
            select(Document).where(
                Document.organization_id == org_id, Document.id == document_id
            )
        )
        if doc is None:
            return None
        return DocumentStateDTO(
            id=doc.id,
            number=doc.number,
            type=doc.type,
            status=doc.status,
            confirmed_by=doc.confirmed_by,
            held_by=doc.held_by,
        )

    async def document_sign_off_async(
        self,
        db: AsyncSession,
        org_id: UUID,
        document_id: UUID,
        *,
        as_status: str | None = None,
    ) -> Literal['required', 'not_required', 'unspecified']:
        """What the document profile says about signing this document off.

        ``required`` — a listed type, or a value over the threshold (or no
        value at all under one); ``not_required`` — the profile names what
        needs signing off and this is not it, or the document is not being
        confirmed or executed; ``unspecified`` — the profile names nothing,
        which leaves the decision to whoever gates documents. ``as_status``
        weighs the document at another status than its own: a draft about
        to be confirmed is asked about as ``CONFIRMED``.
        """
        from ._document_workflow_crud import get_or_raise
        from .approval_service import document_sign_off, weighed_value_async
        from .document_profile_service import get_or_create_profile

        doc = await get_or_raise(db, org_id, document_id)
        profile = await get_or_create_profile(db, org_id)
        return document_sign_off(
            doc,
            profile,
            value=await weighed_value_async(db, doc),
            status=as_status,
        )

    async def fill_line_tax_rates_async(
        self, db: AsyncSession, org_id: UUID, lines: Iterable[Any]
    ) -> None:
        """Put the rate a document line would take on lines that name none.

        For a module pricing lines of its own the way documents do — an order
        line is one: the rate its product or category names, else the
        document default under the profile's tax handling. *lines* carry
        ``product_template_id`` and ``tax_rate``; a rate already on a line
        stays.
        """
        from ._document_workflow_helpers import _apply_line_tax_rates
        from .document_profile_service import get_or_create_profile

        profile = await get_or_create_profile(db, org_id)
        await _apply_line_tax_rates(db, org_id, profile, list(lines))

    async def hold_document_async(
        self, db: AsyncSession, org_id: UUID, document_id: UUID, module: str
    ) -> bool:
        """Park a confirmed document for ``module`` outside a confirmation.

        For a hold asked for by hand — a sign-off requested on a document no
        rule demanded it for. Returns whether the document now waits for the
        module; a document in another state, or waiting for another module,
        is left as it is. Flushes; the caller commits.
        """
        from ._document_workflow_transitions import hold_document

        return await hold_document(db, org_id, document_id, module)

    async def release_document_async(
        self,
        db: AsyncSession,
        org_id: UUID,
        document_id: UUID,
        module: str,
        *,
        user_id: UUID | None = None,
    ) -> None:
        """Let a document ``module`` holds go on, as confirmed.

        The release is announced as the confirmation. A document submitted
        through the one-step action is posted by it as well, in the caller's
        transaction; a posting that is refused raises, and the caller is
        expected to refuse what released it. ``user_id`` is who let it go.
        A document ``module`` does not hold is left as it is.
        """
        from ._document_workflow_transitions import confirm_after_approval

        await confirm_after_approval(db, org_id, document_id, module, user_id=user_id)

    async def withdraw_hold_async(
        self, db: AsyncSession, org_id: UUID, document_id: UUID, module: str
    ) -> None:
        """Take back a hold with nothing decided: the document is confirmed again.

        Nothing is announced — the document was confirmed when it was held.
        A document ``module`` does not hold is left as it is.
        """
        from ._document_workflow_transitions import release_after_approval_withdrawn

        await release_after_approval_withdrawn(db, org_id, document_id, module)

    async def return_to_draft_async(
        self, db: AsyncSession, org_id: UUID, document_id: UUID, module: str
    ) -> None:
        """Refuse a document ``module`` holds: it goes back to a draft.

        Its reservation is released and its confirmation cleared, so the
        person who submitted it can correct it and submit it again. Telling
        them is the refusing module's business. A confirmed document nothing
        holds can be sent back the same way. The caller's transaction commits it.
        """
        from ._document_rework_service import rework_to_draft_after_reject

        await rework_to_draft_after_reject(db, org_id, document_id, module)

    @staticmethod
    def register_pick_order_strategy(
        module: str, name: str, strategy: PickOrderStrategy
    ) -> None:
        """Let your module walk the warehouse its own way.

        Called at the contributing module's import time, like a work item
        provider. The strategy takes ``(db, org_id, lines)`` — the session's
        lines, each with its product, quantity, shelf and the shelf's path
        (the walk-in: the zone before the shelf) as ``PickOrderLineDTO`` —
        and returns those same lines in the order the picker walks to them.

        The organization chooses one in the warehouse settings, where every
        entry is offered under ``<module>:pickOrderStrategies.<name>`` from
        your module's catalogue. The default (``location_sequence``, the
        order the locations are numbered) is registered the same way and is
        what the walk uses when nothing is chosen or the chosen strategy's
        module is switched off for the organization. The strategy is asked
        once per session start, inside the start's transaction; it must not
        commit.
        """
        from .pick_order_strategies import register_pick_order_strategy

        register_pick_order_strategy(module, name, strategy)

    @staticmethod
    def register_document_filter(
        module: str, name: str, provider: DocumentFilterProvider
    ) -> None:
        """Add a filter of your own to the documents list.

        Called at the contributing module's import time, like a pick order.
        The list names it ``<module>:<name>`` (``GET /warehouse/documents
        ?module_filter=<module>:<name>``; the frontend's
        ``documentFilterContributors`` send it). When a reader turns it on,
        the provider takes ``(db, org_id)`` and answers a
        ``DocumentFilterDTO``: the fields of your module's ``meta_data`` a
        line must carry for its document to stay on the list. It reads your
        own tables if it needs to — "the certificates that lapse this month"
        — and must not write. A filter of a module switched off for the
        organization is refused with a 400, never silently dropped.
        """
        from .document_filters import register_document_filter

        register_document_filter(module, name, provider)

    async def set_module_meta_data_async(
        self,
        db: AsyncSession,
        org_id: UUID,
        doc_id: UUID,
        module: str,
        values: dict[str, Any],
        user_id: UUID,
        *,
        line_id: UUID | None = None,
    ) -> None:
        """Keep your module's own fields on a document, or on one of its lines.

        They are stored under ``module`` in the record's ``meta_data``
        (``{'<module>': values}``), replacing what the module kept there
        before; empty ``values`` remove the key. Other modules' keys stay as
        they are. The pre-post checks read them in ``DocumentToPostDTO``, and
        a correction or a return copies them from the document it restates.
        Refused once the document is completed or cancelled. Flushes; the
        caller's transaction commits.
        """
        from ._document_workflow_crud import set_module_meta_data_async

        await set_module_meta_data_async(
            db, org_id, doc_id, module, values, user_id, line_id=line_id
        )

    async def list_po_line_ids_with_confirmed_receipt_async(
        self, db: AsyncSession, org_id: UUID
    ) -> set[UUID]:
        """Order lines a confirmed receipt is already waiting to receive.

        A receipt that is confirmed (or waiting for its approval) stands for
        the delivery on the floor, so an order that shows up in To do beside
        it would be the same work twice. A draft receipt does not: nobody
        has asked the floor to receive anything yet.
        """
        from .models import Document, DocumentLine

        rows = await db.scalars(
            select(DocumentLine.source_po_line_id)
            .join(Document, DocumentLine.document_id == Document.id)
            .where(
                DocumentLine.source_po_line_id.is_not(None),
                Document.status.in_(['CONFIRMED', 'PENDING_APPROVAL']),
                Document.organization_id == org_id,
            )
            .distinct()
        )
        return {line_id for line_id in rows if line_id is not None}

    async def get_pending_receipt_quantities_async(
        self,
        db: AsyncSession,
        org_id: UUID,
        po_line_ids: list[UUID],
    ) -> dict[UUID, Decimal]:
        """Async: return ``{po_line_id: pending_qty}`` for active (non-terminal) receipts.

        "Pending" covers receipts that are not yet COMPLETED and not CANCELLED
        (DRAFT, PENDING_APPROVAL, CONFIRMED). They reserve PO-line capacity via
        ``expected_quantity`` but are not yet reflected in ``quantity_received``
        (which only counts COMPLETED receipts). Used by the over-receipt guard so
        two receipts created before the first completes cannot over-receive.
        """
        from .models import Document, DocumentLine

        if not po_line_ids:
            return {}

        result = await db.execute(
            select(
                DocumentLine.source_po_line_id,
                DocumentLine.expected_quantity,
            )
            .join(Document, DocumentLine.document_id == Document.id)
            .where(
                DocumentLine.source_po_line_id.in_(po_line_ids),
                Document.status.notin_(['COMPLETED', 'CANCELLED']),
                Document.organization_id == org_id,
            )
        )
        rows = result.all()

        totals: dict[UUID, Decimal] = {}
        for po_line_id, expected_qty in rows:
            totals[po_line_id] = totals.get(po_line_id, Decimal('0')) + (
                expected_qty or Decimal('0')
            )
        return totals

    async def in_flight_inbound_map_async(
        self,
        db: AsyncSession,
        org_id: UUID,
        *,
        product_template_ids: Iterable[UUID],
    ) -> dict[tuple[UUID, UUID], Decimal]:
        """What transfers have promised into each shelf, in the stock unit.

        A transfer reserves its stock at confirmation and moves it only when
        it completes; an approval in between can hold it for as long as the
        signature takes. Until the posting the destination still reads short,
        although the goods are on their way — a caller deciding what to buy
        has to count them, or it buys the same goods twice.

        The promise is the line's expected quantity, not what is left after
        its done quantity. ``done_quantity`` records execution: a picking
        scan writes it while the goods still stand on the source shelf, and
        only completion posts the stock. Subtracting it would drop the
        promise exactly when the boxes are picked.

        Keyed by ``(location_id, product_template_id)``, in the product's
        stock unit, the grain ``list_quants_async`` answers in. A draft is
        not here: it holds nothing and may never be posted. A line that
        names only a record takes its product from the record.
        """
        from app.core.public_api import core_api

        from . import document_types as dt
        from .models import Document, DocumentLine, DocumentStatus

        wanted = set(product_template_ids)
        if not wanted:
            return {}
        rows = await db.execute(
            select(
                Document.target_location_id,
                DocumentLine.product_template_id,
                DocumentLine.item_id,
                DocumentLine.uom_id,
                DocumentLine.expected_quantity,
            )
            .join(Document, DocumentLine.document_id == Document.id)
            .where(
                Document.organization_id == org_id,
                Document.type == dt.INT,
                Document.status.in_(
                    (
                        DocumentStatus.CONFIRMED.value,
                        DocumentStatus.PENDING_APPROVAL.value,
                    )
                ),
                Document.target_location_id.is_not(None),
                DocumentLine.product_template_id.in_(wanted)
                | DocumentLine.item_id.is_not(None),
            )
        )
        # A line may be stated in its own unit; the shelf is counted in the
        # product's (see ``_reserve_quants_for_doc``). Convert once per
        # (product, unit) the documents name.
        stated: dict[tuple[UUID, UUID, UUID | None], Decimal] = {}
        for location_id, template_id, item_id, uom_id, quantity in rows:
            if quantity is None or quantity <= 0:
                continue
            if template_id is None:
                item = (
                    await core_api.items.get_async(db, org_id, item_id)
                    if item_id is not None
                    else None
                )
                template_id = item.template_id if item is not None else None
            if template_id is None or template_id not in wanted:
                continue
            key = (location_id, template_id, uom_id)
            stated[key] = stated.get(key, Decimal('0')) + quantity
        inbound: dict[tuple[UUID, UUID], Decimal] = {}
        for (location_id, template_id, uom_id), quantity in stated.items():
            converted = await core_api.uoms.to_stock_uom_async(
                db, org_id, template_id, quantity, uom_id
            )
            pair = (location_id, template_id)
            inbound[pair] = inbound.get(pair, Decimal('0')) + converted
        return inbound

    async def get_active_received_quantities_async(
        self,
        db: AsyncSession,
        org_id: UUID,
        po_line_ids: list[UUID],
    ) -> dict[UUID, Decimal]:
        """Async: return ``{po_line_id: total_received}`` for completed receipts only.

        Only COMPLETED receipt documents represent goods physically received.
        CONFIRMED receipts are pending and excluded.
        """
        from .models import Document, DocumentLine

        if not po_line_ids:
            return {}

        result = await db.execute(
            select(
                DocumentLine.source_po_line_id,
                DocumentLine.done_quantity,
            )
            .join(Document, DocumentLine.document_id == Document.id)
            .where(
                DocumentLine.source_po_line_id.in_(po_line_ids),
                Document.status == 'COMPLETED',
                Document.organization_id == org_id,
            )
        )
        rows = result.all()

        totals: dict[UUID, Decimal] = {}
        for po_line_id, done_qty in rows:
            # Held goods are delivered goods: the order stops waiting for
            # them and the quarantine decides what happens to them.
            totals[po_line_id] = totals.get(po_line_id, Decimal('0')) + (
                done_qty or Decimal('0')
            )
        return totals

    async def search_document_ids_by_number_async(
        self,
        db: AsyncSession,
        org_id: UUID,
        pattern: str,
    ) -> list[UUID]:
        """Return document IDs whose ``number`` contains *pattern* (case-insensitive).

        The pattern must begin the number or follow a separator: a number
        that merely ends with another type's code is not the document the
        caller named (see ``number_matches``). Cross-module helper for the
        approvals queue search: lets the approvals module filter requests by
        target document number without importing
        ``app.modules.warehouse.models`` directly. Unscoped by status —
        callers combine with their own request filters.
        """
        from .document_query_service import number_matches
        from .models import Document

        result = await db.execute(
            select(Document.id).where(
                Document.organization_id == org_id,
                number_matches(pattern),
            )
        )
        return list(result.scalars().all())

    async def get_target_summaries_by_ids_async(
        self,
        db: AsyncSession,
        org_id: UUID,
        target_ids: list[UUID],
    ) -> dict[UUID, Any]:
        """Return lightweight document summaries for cross-module consumers.

        Returns a dict ``{doc_id: DocumentTargetSummaryDTO}`` keyed by document
        id. Documents not in the given org, or missing from the input, are
        simply omitted from the result (no exception). Empty input returns
        an empty dict.

        One IN-query for the documents (with a COUNT subquery for
        lines_count) plus per-location core_api lookups for source/target
        names — bounded by the working set (max 2 locations per doc,
        typically < 20 docs on the approvals dashboard → < 40 calls).
        No ``selectinload(Document.lines)``; no N+1 on the lines count.
        """
        # Also collect source/target location
        # names so the approvals card can render a meaningful fallback
        # for documents without a partner (typically INT). Stored
        # locations are Core entities; resolved via core_api to keep
        # the architecture boundary clean (one batched get_by_ids).
        from sqlalchemy import func

        from app.core.public_api import core_api

        from .models import Document, DocumentLine
        from .schemas import DocumentTargetSummaryDTO

        if not target_ids:
            return {}

        lines_count_subq = (
            select(
                DocumentLine.document_id.label('doc_id'),
                func.count(DocumentLine.id).label('lines_count'),
            )
            .group_by(DocumentLine.document_id)
            .subquery()
        )

        rows = await db.execute(
            select(
                Document.id,
                Document.number,
                Document.type,
                Document.partner_snapshot['name'].astext.label('partner_name'),
                Document.total_net,
                Document.currency,
                Document.source_location_id,
                Document.target_location_id,
                Document.complete_on_approval,
                func.coalesce(lines_count_subq.c.lines_count, 0).label('lines_count'),
            )
            .outerjoin(lines_count_subq, lines_count_subq.c.doc_id == Document.id)
            .where(
                Document.id.in_(target_ids),
                Document.organization_id == org_id,
            )
        )
        rows_list = rows.all()

        # Resolve location names via core_api (Core entity, no direct
        # DB access). Per-location get_async — N is bounded (max 2 per
        # doc, typically < 20 docs on the approvals dashboard → < 40
        # calls). A single batched lookup is not available on
        # core_api.locations, and a per-doc N+1 here is acceptable given
        # the bounded working set.
        location_ids = {
            loc_id
            for row in rows_list
            for loc_id in (row.source_location_id, row.target_location_id)
            if loc_id is not None
        }
        location_name_by_id: dict[UUID, str] = {}
        for loc_id in location_ids:
            try:
                loc = await core_api.locations.get_async(db, org_id, loc_id)
            except Exception:  # noqa: BLE001 — an unreadable location only hides the route
                # Graceful: skip on failure, the card hides the route.
                continue
            if loc is not None and loc.name:
                location_name_by_id[loc_id] = loc.name

        result: dict[UUID, Any] = {}
        for row in rows_list:
            src_name = (
                location_name_by_id.get(row.source_location_id)
                if row.source_location_id
                else None
            )
            tgt_name = (
                location_name_by_id.get(row.target_location_id)
                if row.target_location_id
                else None
            )
            summary = DocumentTargetSummaryDTO(
                id=row.id,
                number=row.number,
                type=row.type,
                partner_name=row.partner_name,
                # Net: the figure the approval threshold is set against, and
                # the one a purchase order's summary reports.
                total_value=row.total_net,
                currency=row.currency,
                lines_count=int(row.lines_count or 0),
                source_location_name=src_name,
                target_location_name=tgt_name,
                posts_on_approval=bool(row.complete_on_approval),
            )
            result[row.id] = summary
        return result


warehouse_api = WarehouseAPI()

__all__ = ['OverReceiptRefusedError', 'WarehouseAPI', 'warehouse_api']
