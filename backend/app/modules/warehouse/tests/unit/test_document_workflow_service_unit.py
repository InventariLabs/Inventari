from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.core.contracts import AuditAction
from app.core.exceptions import ServiceRejectionError
from app.modules.warehouse._document_workflow_crud import (
    _apply_execution_quantities,
)
from app.modules.warehouse._document_workflow_transitions import (
    _require_positive_quantities,
    confirm_after_approval,
)
from app.modules.warehouse.document_workflow_service import (
    cancel_document,
    delete_document,
)
from app.modules.warehouse.models import DocumentLine, DocumentStatus
from app.modules.warehouse.schemas import DocumentComplete, DocumentLineExecution


def _make_doc(
    *,
    status: str = DocumentStatus.DRAFT.value,
    doc_type: str = 'IN',
    lines: list[MagicMock] | None = None,
    partner_id: UUID | None = None,
    corrects_document_id: UUID | None = None,
) -> MagicMock:
    doc = MagicMock()
    doc.id = uuid4()
    doc.organization_id = uuid4()
    doc.type = doc_type
    doc.status = status
    doc.partner_id = partner_id
    doc.source_location_id = (
        uuid4() if doc_type in {'OUT', 'INT', 'WZ', 'INTERNAL_OUT', 'MM'} else None
    )
    doc.target_location_id = (
        uuid4() if doc_type in {'IN', 'INT', 'PZ', 'MM', 'INTERNAL_IN'} else None
    )
    doc.lines = lines or []
    doc.corrects_document_id = corrects_document_id
    doc.created_at = datetime.now(UTC)
    doc.scheduled_date = None
    doc.complete_on_approval = False
    doc.held_by = None
    return doc


def _make_line(
    *,
    line_id: UUID | None = None,
    expected_quantity: Decimal = Decimal('10'),
    done_quantity: Decimal | None = Decimal('0'),
    product_template_id: UUID | None = None,
    discrepancy_code: str | None = None,
    discrepancy_reason: str | None = None,
) -> MagicMock:
    line = MagicMock()
    line.id = line_id or uuid4()
    line.expected_quantity = expected_quantity
    line.done_quantity = done_quantity
    line.product_template_id = product_template_id
    line.discrepancy_code = discrepancy_code
    line.discrepancy_reason = discrepancy_reason
    line.held_quantity = Decimal('0')
    line.expected_is_count = False
    return line


@pytest.mark.unit
class TestApplyLineTaxRates:
    """The rate is resolved (goods, then profile entry, then country), not read raw.

    The resolution itself is covered against a database in
    ``tests/integration/test_the_country_supplies_the_law.py`` and
    ``test_goods_name_their_tax_rate.py``; here the resolvers are stood in
    for, so these tests pin the branch around them.
    """

    def _apply(
        self,
        monkeypatch: pytest.MonkeyPatch,
        profile: MagicMock,
        lines: list[Any],
        resolver: Any,
        named: dict[Any, Decimal] | None = None,
    ) -> None:
        import asyncio

        from app.modules.warehouse import _document_workflow_helpers as helpers

        async def _goods(db: Any, org_id: UUID, ids: Any) -> dict[Any, Decimal]:
            list(ids)
            return named or {}

        monkeypatch.setattr(helpers, 'resolve_document_tax_rate', resolver)
        monkeypatch.setattr(helpers, 'product_tax_rates_async', _goods)
        asyncio.run(
            helpers._apply_line_tax_rates(
                cast(Any, None),
                uuid4(),
                profile,
                cast(list[DocumentLine], lines),
            )
        )

    def test_applies_tax_to_lines_without_rate(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def _resolved(db: Any, org_id: UUID, profile: Any) -> Decimal:
            return Decimal('23')

        profile = MagicMock()
        profile.tax_handling = 'SIMPLE_RATE'
        line1 = MagicMock()
        line1.tax_rate = None
        line2 = MagicMock()
        line2.tax_rate = Decimal('8')
        self._apply(monkeypatch, profile, [line1, line2], _resolved)
        assert line1.tax_rate == Decimal('23')
        assert line2.tax_rate == Decimal('8')

    def test_does_nothing_on_an_untaxed_profile(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def _must_not_run(db: Any, org_id: UUID, profile: Any) -> Decimal:
            raise AssertionError('the resolver must not run outside SIMPLE_RATE')

        profile = MagicMock()
        profile.tax_handling = 'NONE'
        line = MagicMock()
        line.tax_rate = None
        self._apply(monkeypatch, profile, [line], _must_not_run)
        assert line.tax_rate is None

    def test_does_nothing_when_no_default_rate(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def _resolved(db: Any, org_id: UUID, profile: Any) -> None:
            return None

        profile = MagicMock()
        profile.tax_handling = 'SIMPLE_RATE'
        line = MagicMock()
        line.tax_rate = None
        self._apply(monkeypatch, profile, [line], _resolved)
        assert line.tax_rate is None

    def test_the_goods_rate_beats_the_documents(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def _resolved(db: Any, org_id: UUID, profile: Any) -> Decimal:
            return Decimal('19')

        bread, soap = uuid4(), uuid4()
        profile = MagicMock()
        profile.tax_handling = 'SIMPLE_RATE'
        lines = [MagicMock(tax_rate=None, product_template_id=t) for t in (bread, soap)]
        self._apply(monkeypatch, profile, lines, _resolved, {bread: Decimal('7')})
        assert [line.tax_rate for line in lines] == [Decimal('7'), Decimal('19')]

    def test_a_per_line_profile_takes_the_goods_rate_and_no_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Rates per line are what goods naming a rate are for; the
        document's single default is ``SIMPLE_RATE``'s alone."""

        async def _must_not_run(db: Any, org_id: UUID, profile: Any) -> Decimal:
            raise AssertionError('no document default outside SIMPLE_RATE')

        bread, soap = uuid4(), uuid4()
        profile = MagicMock()
        profile.tax_handling = 'PER_LINE_RATE'
        lines = [MagicMock(tax_rate=None, product_template_id=t) for t in (bread, soap)]
        self._apply(monkeypatch, profile, lines, _must_not_run, {bread: Decimal('7')})
        assert [line.tax_rate for line in lines] == [Decimal('7'), None]


@pytest.mark.unit
class TestApplyExecutionQuantities:
    def test_full_execution_when_asked_to_complete_as_planned(self) -> None:
        line = _make_line(expected_quantity=Decimal('10'), done_quantity=None)
        doc = _make_doc(lines=[line])
        _apply_execution_quantities(doc, DocumentComplete(complete_as_planned=True))
        assert line.done_quantity == Decimal('10')
        assert line.discrepancy_code is None
        assert line.discrepancy_reason is None

    @pytest.mark.parametrize(
        'execution_data', [None, DocumentComplete(unit_confirmed_over_template=True)]
    )
    def test_refuses_unanswered_lines_without_per_line_answers(
        self, execution_data: DocumentComplete | None
    ) -> None:
        """A bodiless completion names the lines nobody answered for."""
        answered = _make_line(
            expected_quantity=Decimal('4'), done_quantity=Decimal('4')
        )
        answered.line_number = 1
        unanswered = _make_line(expected_quantity=Decimal('10'), done_quantity=None)
        unanswered.line_number = 2
        short = _make_line(
            expected_quantity=Decimal('6'),
            done_quantity=Decimal('0'),
            discrepancy_code='SHORTAGE',
        )
        short.line_number = 3
        doc = _make_doc(lines=[answered, unanswered, short])
        with pytest.raises(ValueError, match='2'):
            _apply_execution_quantities(doc, execution_data)
        assert unanswered.done_quantity is None

    def test_a_body_that_answers_only_some_lines_is_refused(self) -> None:
        """A line the body does not name is not silently booked in full."""
        named = _make_line(expected_quantity=Decimal('3'), done_quantity=Decimal('0'))
        named.line_number = 1
        unnamed = _make_line(expected_quantity=Decimal('4'), done_quantity=Decimal('0'))
        unnamed.line_number = 2
        doc = _make_doc(lines=[named, unnamed])
        execution = DocumentComplete(
            lines=[DocumentLineExecution(line_id=named.id, done_quantity=Decimal('3'))]
        )

        with pytest.raises(ValueError) as refused:
            _apply_execution_quantities(doc, execution)

        assert 'Unanswered lines: 2' in str(refused.value)
        assert 'complete_as_planned' in str(refused.value)
        assert named.done_quantity == Decimal('0')
        assert unnamed.done_quantity == Decimal('0')

    def test_the_flag_covers_the_lines_the_body_leaves_out(self) -> None:
        named = _make_line(expected_quantity=Decimal('3'), done_quantity=Decimal('0'))
        unnamed = _make_line(expected_quantity=Decimal('4'), done_quantity=Decimal('0'))
        doc = _make_doc(lines=[named, unnamed])
        execution = DocumentComplete(
            lines=[DocumentLineExecution(line_id=named.id, done_quantity=Decimal('3'))],
            complete_as_planned=True,
        )

        _apply_execution_quantities(doc, execution)

        assert named.done_quantity == Decimal('3')
        assert unnamed.done_quantity == Decimal('4')

    def test_an_unnamed_line_keeps_the_answer_it_already_has(self) -> None:
        """A session's earlier short answer survives a body that does not repeat it."""
        named = _make_line(expected_quantity=Decimal('3'), done_quantity=Decimal('0'))
        short = _make_line(
            expected_quantity=Decimal('4'),
            done_quantity=Decimal('2'),
            discrepancy_code='SHORTAGE',
            discrepancy_reason='Only 2 arrived',
        )
        doc = _make_doc(lines=[named, short])
        execution = DocumentComplete(
            lines=[DocumentLineExecution(line_id=named.id, done_quantity=Decimal('3'))]
        )

        _apply_execution_quantities(doc, execution)

        assert named.done_quantity == Decimal('3')
        assert short.done_quantity == Decimal('2')
        assert short.discrepancy_code == 'SHORTAGE'
        assert short.discrepancy_reason == 'Only 2 arrived'

    def test_correction_needs_no_answer_per_line(self) -> None:
        line = _make_line(expected_quantity=Decimal('-3'), done_quantity=None)
        doc = _make_doc(doc_type='CORRECTION', lines=[line])
        _apply_execution_quantities(doc, None)
        assert line.done_quantity == Decimal('-3')

    def test_preserves_wms_done_quantity_when_no_execution_data(self) -> None:
        """WMS-recorded done_quantity must not be overwritten."""
        line = _make_line(
            expected_quantity=Decimal('10'),
            done_quantity=Decimal('7'),
            discrepancy_code='OTHER',
        )
        doc = _make_doc(lines=[line])
        _apply_execution_quantities(doc, None)
        assert line.done_quantity == Decimal('7')

    def test_refuses_a_part_picked_line_with_no_reason_when_no_execution_data(
        self,
    ) -> None:
        """A shortfall nobody gave a reason for is not booked as it stands."""
        line = _make_line(expected_quantity=Decimal('10'), done_quantity=Decimal('7'))
        doc = _make_doc(lines=[line])
        with pytest.raises(ServiceRejectionError):
            _apply_execution_quantities(doc, None)
        assert line.done_quantity == Decimal('7')

    def test_preserves_discrepancy_for_partial_pick_when_no_execution_data(
        self,
    ) -> None:
        """Discrepancy set by WMS must survive completion without execution_data."""
        line = _make_line(
            expected_quantity=Decimal('10'),
            done_quantity=Decimal('7'),
            discrepancy_code='SHORTAGE',
            discrepancy_reason='Only 7 found in bin',
        )
        doc = _make_doc(lines=[line])
        _apply_execution_quantities(doc, None)
        assert line.done_quantity == Decimal('7')
        assert line.discrepancy_code == 'SHORTAGE'
        assert line.discrepancy_reason == 'Only 7 found in bin'

    def test_clears_discrepancy_for_full_pick_when_no_execution_data(self) -> None:
        """Lines fully executed (done == expected) have discrepancy cleared."""
        line = _make_line(
            expected_quantity=Decimal('10'),
            done_quantity=Decimal('10'),
            discrepancy_code='SHORTAGE',
            discrepancy_reason='was short then fixed',
        )
        doc = _make_doc(lines=[line])
        _apply_execution_quantities(doc, None)
        assert line.done_quantity == Decimal('10')
        assert line.discrepancy_code is None
        assert line.discrepancy_reason is None

    def test_partial_execution_with_discrepancy(self) -> None:
        line = _make_line(expected_quantity=Decimal('10'), done_quantity=Decimal('0'))
        doc = _make_doc(lines=[line])
        exec_line = MagicMock()
        exec_line.line_id = line.id
        exec_line.held_quantity = Decimal('0')
        exec_line.done_quantity = Decimal('7')
        exec_line.discrepancy_code = 'SHORTAGE'
        exec_line.discrepancy_reason = 'Only 7 delivered'
        exec_data = MagicMock()
        exec_data.lines = [exec_line]
        _apply_execution_quantities(doc, exec_data)
        assert line.done_quantity == Decimal('7')
        assert line.discrepancy_code == 'SHORTAGE'
        assert line.discrepancy_reason == 'Only 7 delivered'

    def test_a_surplus_is_kept_and_named(self) -> None:
        """Over-receipt is the gate's question, not this coercion's.

        The tolerance gate in ``complete_document`` decides whether the
        surplus may be written; here the line only has to carry the code.
        The code is the name — every screen reads its label in the reader's
        language — so a wide line with no note stays without one.
        """
        line = _make_line(expected_quantity=Decimal('10'), done_quantity=Decimal('0'))
        doc = _make_doc(lines=[line])
        exec_line = MagicMock()
        exec_line.line_id = line.id
        exec_line.held_quantity = Decimal('0')
        exec_line.done_quantity = Decimal('15')
        exec_line.discrepancy_code = None
        exec_line.discrepancy_reason = None
        exec_data = MagicMock()
        exec_data.lines = [exec_line]
        _apply_execution_quantities(doc, exec_data)
        assert line.done_quantity == Decimal('15')
        assert line.discrepancy_code == 'SURPLUS'
        assert line.discrepancy_reason is None

    def test_raises_when_partial_without_discrepancy(self) -> None:
        line = _make_line(expected_quantity=Decimal('10'), done_quantity=Decimal('0'))
        doc = _make_doc(lines=[line])
        exec_line = MagicMock()
        exec_line.line_id = line.id
        exec_line.held_quantity = Decimal('0')
        exec_line.done_quantity = Decimal('7')
        exec_line.discrepancy_code = None
        exec_line.discrepancy_reason = None
        exec_data = MagicMock()
        exec_data.lines = [exec_line]
        with pytest.raises(ValueError, match='needs a discrepancy code'):
            _apply_execution_quantities(doc, exec_data)

    def test_raises_on_foreign_line_id(self) -> None:
        line = _make_line(expected_quantity=Decimal('10'))
        doc = _make_doc(lines=[line])
        exec_line = MagicMock()
        exec_line.line_id = uuid4()
        exec_line.done_quantity = Decimal('5')
        exec_line.discrepancy_code = None
        exec_line.discrepancy_reason = None
        exec_data = MagicMock()
        exec_data.lines = [exec_line]
        with pytest.raises(ValueError, match='does not belong'):
            _apply_execution_quantities(doc, exec_data)

    def test_raises_on_duplicate_line_id(self) -> None:
        line = _make_line(expected_quantity=Decimal('10'))
        doc = _make_doc(lines=[line])
        exec_line = MagicMock()
        exec_line.line_id = line.id
        exec_line.held_quantity = Decimal('0')
        exec_line.done_quantity = Decimal('5')
        exec_line.discrepancy_code = None
        exec_line.discrepancy_reason = None
        exec_data = MagicMock()
        exec_data.lines = [exec_line, exec_line]
        with pytest.raises(ValueError, match='executed only once'):
            _apply_execution_quantities(doc, exec_data)

    def test_correction_within_bounds_passes(self) -> None:
        """Corrections within abs(done)<=abs(expected) are allowed."""
        line = _make_line(expected_quantity=Decimal('10'), done_quantity=Decimal('0'))
        doc = _make_doc(doc_type='CORRECTION', lines=[line])
        exec_line = MagicMock()
        exec_line.line_id = line.id
        exec_line.held_quantity = Decimal('0')
        exec_line.done_quantity = Decimal('5')
        exec_line.discrepancy_code = None
        exec_line.discrepancy_reason = None
        exec_data = MagicMock()
        exec_data.lines = [exec_line]
        _apply_execution_quantities(doc, exec_data)
        assert line.done_quantity == Decimal('5')

    def test_correction_exceeding_bounds_raises(self) -> None:
        """Correction done>expected in absolute terms raises."""
        line = _make_line(expected_quantity=Decimal('10'), done_quantity=Decimal('0'))
        doc = _make_doc(doc_type='CORRECTION', lines=[line])
        exec_line = MagicMock()
        exec_line.line_id = line.id
        exec_line.held_quantity = Decimal('0')
        exec_line.done_quantity = Decimal('15')
        exec_line.discrepancy_code = None
        exec_line.discrepancy_reason = None
        exec_data = MagicMock()
        exec_data.lines = [exec_line]
        with pytest.raises(ValueError, match='exceeds the expected quantity'):
            _apply_execution_quantities(doc, exec_data)

    def test_correction_negative_exceeding_bounds_raises(self) -> None:
        """Negative correction delta bounded by abs(expected)."""
        line = _make_line(expected_quantity=Decimal('-5'), done_quantity=Decimal('0'))
        doc = _make_doc(doc_type='CORRECTION', lines=[line])
        exec_line = MagicMock()
        exec_line.line_id = line.id
        exec_line.held_quantity = Decimal('0')
        exec_line.done_quantity = Decimal('-10')
        exec_line.discrepancy_code = None
        exec_line.discrepancy_reason = None
        exec_data = MagicMock()
        exec_data.lines = [exec_line]
        with pytest.raises(ValueError, match='exceeds the expected quantity'):
            _apply_execution_quantities(doc, exec_data)


@pytest.mark.unit
class TestDeleteDocument:
    @pytest.mark.asyncio
    async def test_deletes_draft_document(self) -> None:
        db = MagicMock()
        db.delete = AsyncMock()
        db.flush = AsyncMock()
        doc = _make_doc(status=DocumentStatus.DRAFT.value)
        # The deletion now journals itself (the record leaves no copy behind),
        # so the log is a mock here like in the cancel test above.
        mock_core = MagicMock()
        mock_core.audit_log.log_action_async = AsyncMock()
        with (
            patch(
                'app.modules.warehouse.document_query_service.get_document',
                new_callable=AsyncMock,
                return_value=doc,
            ),
            patch(
                'app.modules.warehouse._document_workflow_crud.core_api',
                mock_core,
            ),
            patch(
                'app.modules.warehouse._document_workflow_crud.notify_withdrawn_async',
                new_callable=AsyncMock,
            ),
        ):
            await delete_document(db, doc.organization_id, doc.id)
        db.delete.assert_awaited_once_with(doc)
        mock_core.audit_log.log_action_async.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_raises_when_not_draft(self) -> None:
        db = MagicMock()
        doc = _make_doc(status=DocumentStatus.CONFIRMED.value)
        with patch(
            'app.modules.warehouse.document_query_service.get_document',
            new_callable=AsyncMock,
            return_value=doc,
        ):
            with pytest.raises(ValueError, match='Only DRAFT'):
                await delete_document(db, doc.organization_id, doc.id)


@pytest.mark.unit
class TestCancelDocument:
    @pytest.mark.asyncio
    async def test_cancels_draft(self) -> None:
        db = MagicMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        org_id = uuid4()
        user_id = uuid4()
        doc = _make_doc(status=DocumentStatus.DRAFT.value)
        # Cancelling reaches the organization log like every transition;
        # the unit test isolates the state machine, so the log call is a
        # mock and the integration tests hold its contents.
        mock_core = MagicMock()
        mock_core.audit_log.log_action_async = AsyncMock()
        with (
            patch(
                'app.modules.warehouse._document_workflow_transitions.core_api',
                mock_core,
            ),
            patch(
                'app.modules.warehouse._document_workflow_transitions._get_doc_for_update',
                new_callable=AsyncMock,
                return_value=doc,
            ),
            patch(
                'app.modules.warehouse._document_workflow_transitions._check_document_period_open',
                new_callable=AsyncMock,
            ),
            patch(
                'app.modules.warehouse._document_workflow_transitions._check_no_active_wms_sessions',
                new_callable=AsyncMock,
            ),
            patch(
                'app.modules.warehouse._document_workflow_transitions._release_quants_for_doc',
                new_callable=AsyncMock,
            ),
            patch(
                'app.modules.warehouse._document_workflow_transitions.notify_withdrawn_async',
                new_callable=AsyncMock,
            ),
        ):
            result = await cancel_document(db, org_id, doc.id, user_id)
        assert result.status == DocumentStatus.CANCELLED.value
        assert result.cancelled_by == user_id
        assert result.cancelled_at is not None
        mock_core.audit_log.log_action_async.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_raises_when_completed(self) -> None:
        db = MagicMock()
        org_id = uuid4()
        user_id = uuid4()
        doc = _make_doc(status=DocumentStatus.COMPLETED.value)
        with (
            patch(
                'app.modules.warehouse._document_workflow_transitions._get_doc_for_update',
                new_callable=AsyncMock,
                return_value=doc,
            ),
            patch(
                'app.modules.warehouse._document_workflow_transitions._check_document_period_open',
                new_callable=AsyncMock,
            ),
            patch(
                'app.modules.warehouse._document_workflow_transitions._check_no_active_wms_sessions',
                new_callable=AsyncMock,
            ),
        ):
            with pytest.raises(
                ValueError, match='Only DRAFT, PENDING_APPROVAL or CONFIRMED'
            ):
                await cancel_document(db, org_id, doc.id, user_id)


@pytest.mark.unit
class TestNonPositiveLinesAtConfirmation:
    """Which types may hold a line of zero or less is the type's business.

    A correction's lines are deltas and a delta of -2 is the whole document;
    everywhere else a line is an amount that "Plan" and "received X of Y"
    add up, so one negative row makes an incomplete receipt report a
    complete one.
    """

    def _doc(self, doc_type: str, *quantities: str) -> Any:
        return _make_doc(
            doc_type=doc_type,
            lines=[
                MagicMock(line_number=i, expected_quantity=Decimal(q))
                for i, q in enumerate(quantities, start=1)
            ],
        )

    def test_receipt_with_a_negative_line_is_refused(self) -> None:
        with pytest.raises(ValueError) as exc:
            _require_positive_quantities(self._doc('IN', '5', '2', '-5'))
        assert '3' in str(exc.value)

    def test_receipt_with_a_zero_line_is_refused(self) -> None:
        with pytest.raises(ValueError):
            _require_positive_quantities(self._doc('IN', '0'))

    def test_receipt_whose_lines_are_all_positive_passes(self) -> None:
        _require_positive_quantities(self._doc('IN', '5', '2'))

    def test_correction_may_carry_a_negative_delta(self) -> None:
        _require_positive_quantities(self._doc('CORRECTION', '-2'))


@pytest.mark.unit
class TestConfirmAfterApproval:
    @pytest.mark.asyncio
    async def test_the_status_change_reaches_the_log(self) -> None:
        """The approval's request and decision are journaled by the approvals
        module; the rung this door adds — PENDING_APPROVAL to CONFIRMED — is
        the document's own act, so it writes its own entry here."""
        db = MagicMock()
        db.refresh = AsyncMock()
        org_id = uuid4()
        approver_id = uuid4()
        doc = _make_doc(status=DocumentStatus.PENDING_APPROVAL.value)
        mock_core = MagicMock()
        mock_core.audit_log.log_action_async = AsyncMock()
        with (
            patch(
                'app.modules.warehouse._document_workflow_transitions.core_api',
                mock_core,
            ),
            patch(
                'app.modules.warehouse._document_workflow_transitions.get_or_raise',
                new_callable=AsyncMock,
                return_value=doc,
            ),
            patch(
                'app.modules.warehouse._document_workflow_transitions._emit_document_confirmed',
                new_callable=AsyncMock,
            ),
        ):
            result = await confirm_after_approval(
                db, org_id, doc.id, 'approvals', user_id=approver_id
            )
        assert result.status == DocumentStatus.CONFIRMED.value
        mock_core.audit_log.log_action_async.assert_awaited_once()
        call = mock_core.audit_log.log_action_async.await_args
        assert call.kwargs['user_id'] == approver_id
        assert call.kwargs['action'] == AuditAction.UPDATE
        assert (
            call.kwargs['snapshot']['old_status']
            == DocumentStatus.PENDING_APPROVAL.value
        )
        assert call.kwargs['snapshot']['new_status'] == DocumentStatus.CONFIRMED.value
