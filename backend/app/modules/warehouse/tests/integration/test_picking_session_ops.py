"""Direct integration tests for ``_picking_session_ops``.

The existing ``test_wms_picking.py`` drives these functions through the
FastAPI ``TestClient``, which runs the async app in a separate blocking-portal
thread. Coverage's tracer does not reliably record the statements after the
first ``await`` inside that worker thread, so those endpoint tests leave most
of this module at ~22%. These tests call the service functions directly on a
real ``AsyncSession`` so the lines are attributed correctly.
"""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.user import User
from app.modules.warehouse._picking_session_ops import (
    cancel_pick_session_async,
    complete_pick_session_async,
    confirm_short_pick_async,
    skip_pick_line_async,
    undo_pick_async,
)
from app.modules.warehouse.models import (
    Document,
    DocumentLine,
    DocumentStatus,
    WmsPickLine,
    WmsPickSession,
)


@pytest.fixture
async def pick_org(real_async_db_session: AsyncSession) -> Organization:
    org = Organization(name='Pick Ops Org', enabled_modules=['core', 'warehouse'])
    real_async_db_session.add(org)
    await real_async_db_session.flush()
    return org


@pytest.fixture
async def pick_user(
    real_async_db_session: AsyncSession, pick_org: Organization
) -> User:
    return await ModuleTestHelper.create_user_async(
        real_async_db_session,
        pick_org,
        email='pick-ops@example.com',
        role='admin',
    )


async def _create_pick_session(
    db: AsyncSession,
    org: Organization,
    user: User,
    *,
    line_specs: list[dict[str, Decimal | str]],
    session_status: str = 'active',
) -> tuple[WmsPickSession, list[WmsPickLine], list[DocumentLine]]:
    """Create a CONFIRMED OUT document with a pick session and its lines."""
    doc = Document(
        organization_id=org.id,
        type='OUT',
        number=f'OUT-{uuid.uuid4().hex[:8]}',
        status=DocumentStatus.CONFIRMED.value,
        created_by=user.id,
    )
    db.add(doc)
    await db.flush()

    session = WmsPickSession(
        organization_id=org.id,
        document_id=doc.id,
        assigned_to=user.id,
        status=session_status,
    )
    db.add(session)
    await db.flush()

    pick_lines: list[WmsPickLine] = []
    doc_lines: list[DocumentLine] = []
    for i, spec in enumerate(line_specs):
        doc_line = DocumentLine(
            document_id=doc.id,
            quantity=spec['expected'],
            expected_quantity=spec['expected'],
            done_quantity=spec.get('done', Decimal('0')),
            line_number=i + 1,
            discrepancy_code=spec.get('discrepancy_code'),
            discrepancy_reason=spec.get('discrepancy_reason'),
        )
        db.add(doc_line)
        await db.flush()

        pick_line = WmsPickLine(
            session_id=session.id,
            document_line_id=doc_line.id,
            pick_order=i,
            status=spec.get('status', 'pending'),
            picked_quantity=spec.get('picked', Decimal('0')),
            expected_quantity=spec['expected'],
        )
        db.add(pick_line)
        pick_lines.append(pick_line)
        doc_lines.append(doc_line)

    await db.flush()
    return session, pick_lines, doc_lines


@pytest.mark.integration
class TestConfirmShortPick:
    @pytest.mark.asyncio
    async def test_short_pick_sets_short_and_discrepancy(
        self,
        real_async_db_session: AsyncSession,
        pick_org: Organization,
        pick_user: User,
    ) -> None:
        session, lines, doc_lines = await _create_pick_session(
            real_async_db_session,
            pick_org,
            pick_user,
            line_specs=[{'expected': Decimal('10')}],
        )

        result = await confirm_short_pick_async(
            real_async_db_session,
            session.id,
            pick_org.id,
            lines[0].id,
            Decimal('3'),
            'SHORTAGE',
            'Only 3 found on shelf',
        )

        assert result.status == 'short'
        assert result.picked_quantity == Decimal('3')
        await real_async_db_session.refresh(doc_lines[0])
        assert doc_lines[0].done_quantity == Decimal('3')
        assert doc_lines[0].discrepancy_code == 'SHORTAGE'
        assert doc_lines[0].discrepancy_reason == 'Only 3 found on shelf'

    @pytest.mark.asyncio
    async def test_short_pick_without_a_reason_stores_none(
        self,
        real_async_db_session: AsyncSession,
        pick_org: Organization,
        pick_user: User,
    ) -> None:
        """A short line names the shortage by code, not by a stored sentence.

        The default reason this used to write was an English sentence
        ("Short picking") shown as is to every reader, in every language.
        The code the person chose is the name and the screens translate it.
        """
        session, lines, doc_lines = await _create_pick_session(
            real_async_db_session,
            pick_org,
            pick_user,
            line_specs=[{'expected': Decimal('10')}],
        )

        result = await confirm_short_pick_async(
            real_async_db_session,
            session.id,
            pick_org.id,
            lines[0].id,
            Decimal('3'),
            'SHORTAGE',
        )

        assert result.status == 'short'
        await real_async_db_session.refresh(doc_lines[0])
        assert doc_lines[0].discrepancy_code == 'SHORTAGE'
        assert doc_lines[0].discrepancy_reason is None

    @pytest.mark.asyncio
    async def test_exact_pick_sets_picked_without_discrepancy(
        self,
        real_async_db_session: AsyncSession,
        pick_org: Organization,
        pick_user: User,
    ) -> None:
        session, lines, doc_lines = await _create_pick_session(
            real_async_db_session,
            pick_org,
            pick_user,
            line_specs=[{'expected': Decimal('10')}],
        )

        result = await confirm_short_pick_async(
            real_async_db_session,
            session.id,
            pick_org.id,
            lines[0].id,
            Decimal('10'),
            'SHORTAGE',
            'should not be recorded',
        )

        assert result.status == 'picked'
        assert result.picked_quantity == Decimal('10')
        await real_async_db_session.refresh(doc_lines[0])
        assert doc_lines[0].done_quantity == Decimal('10')
        assert doc_lines[0].discrepancy_code is None
        assert doc_lines[0].discrepancy_reason is None

    @pytest.mark.asyncio
    async def test_a_count_below_the_scanned_quantity_is_refused(
        self,
        real_async_db_session: AsyncSession,
        pick_org: Organization,
        pick_user: User,
    ) -> None:
        """The typed number is the line's total, so it cannot undo a scan.

        A worker who scanned 7 of 10 and types 5 has either counted less
        than the goods they handled or tapped the wrong line. The record
        keeps the 7 until the caller says the count supersedes the scans.
        """
        session, lines, _ = await _create_pick_session(
            real_async_db_session,
            pick_org,
            pick_user,
            line_specs=[{'expected': Decimal('10'), 'picked': Decimal('7')}],
        )

        with pytest.raises(ValueError, match='below the scanned quantity'):
            await confirm_short_pick_async(
                real_async_db_session,
                session.id,
                pick_org.id,
                lines[0].id,
                Decimal('5'),
            )

    @pytest.mark.asyncio
    async def test_a_count_below_the_scans_replaces_them_when_it_says_so(
        self,
        real_async_db_session: AsyncSession,
        pick_org: Organization,
        pick_user: User,
    ) -> None:
        session, lines, doc_lines = await _create_pick_session(
            real_async_db_session,
            pick_org,
            pick_user,
            line_specs=[{'expected': Decimal('10'), 'picked': Decimal('7')}],
        )

        result = await confirm_short_pick_async(
            real_async_db_session,
            session.id,
            pick_org.id,
            lines[0].id,
            Decimal('5'),
            'DAMAGE',
            'two cartons crushed',
            replace_scans=True,
        )

        assert result.status == 'short'
        assert result.picked_quantity == Decimal('5')
        await real_async_db_session.refresh(doc_lines[0])
        assert doc_lines[0].done_quantity == Decimal('5')

    @pytest.mark.asyncio
    async def test_a_count_between_the_scans_and_the_expected_needs_no_flag(
        self,
        real_async_db_session: AsyncSession,
        pick_org: Organization,
        pick_user: User,
    ) -> None:
        session, lines, _ = await _create_pick_session(
            real_async_db_session,
            pick_org,
            pick_user,
            line_specs=[{'expected': Decimal('10'), 'picked': Decimal('7')}],
        )

        result = await confirm_short_pick_async(
            real_async_db_session,
            session.id,
            pick_org.id,
            lines[0].id,
            Decimal('9'),
            'OTHER',
        )

        assert result.status == 'short'
        assert result.picked_quantity == Decimal('9')

    @pytest.mark.asyncio
    async def test_quantity_exceeding_expected_raises(
        self,
        real_async_db_session: AsyncSession,
        pick_org: Organization,
        pick_user: User,
    ) -> None:
        session, lines, _ = await _create_pick_session(
            real_async_db_session,
            pick_org,
            pick_user,
            line_specs=[{'expected': Decimal('10')}],
        )

        with pytest.raises(ValueError, match='cannot exceed the expected quantity'):
            await confirm_short_pick_async(
                real_async_db_session,
                session.id,
                pick_org.id,
                lines[0].id,
                Decimal('11'),
            )

    @pytest.mark.asyncio
    async def test_negative_quantity_raises(
        self,
        real_async_db_session: AsyncSession,
        pick_org: Organization,
        pick_user: User,
    ) -> None:
        session, lines, _ = await _create_pick_session(
            real_async_db_session,
            pick_org,
            pick_user,
            line_specs=[{'expected': Decimal('10')}],
        )

        with pytest.raises(ValueError, match='cannot be negative'):
            await confirm_short_pick_async(
                real_async_db_session,
                session.id,
                pick_org.id,
                lines[0].id,
                Decimal('-1'),
            )

    @pytest.mark.asyncio
    async def test_unknown_line_raises(
        self,
        real_async_db_session: AsyncSession,
        pick_org: Organization,
        pick_user: User,
    ) -> None:
        session, _, _ = await _create_pick_session(
            real_async_db_session,
            pick_org,
            pick_user,
            line_specs=[{'expected': Decimal('10')}],
        )

        with pytest.raises(ValueError, match='session line was not found'):
            await confirm_short_pick_async(
                real_async_db_session,
                session.id,
                pick_org.id,
                uuid.uuid4(),
                Decimal('5'),
            )

    @pytest.mark.asyncio
    async def test_line_from_other_session_raises(
        self,
        real_async_db_session: AsyncSession,
        pick_org: Organization,
        pick_user: User,
    ) -> None:
        session_a, _, _ = await _create_pick_session(
            real_async_db_session,
            pick_org,
            pick_user,
            line_specs=[{'expected': Decimal('10')}],
        )
        _, lines_b, _ = await _create_pick_session(
            real_async_db_session,
            pick_org,
            pick_user,
            line_specs=[{'expected': Decimal('10')}],
        )

        with pytest.raises(ValueError, match='session line was not found'):
            await confirm_short_pick_async(
                real_async_db_session,
                session_a.id,
                pick_org.id,
                lines_b[0].id,
                Decimal('5'),
            )


@pytest.mark.integration
class TestCompletePickSession:
    @pytest.mark.asyncio
    async def test_complete_all_picked_sets_completed(
        self,
        real_async_db_session: AsyncSession,
        pick_org: Organization,
        pick_user: User,
    ) -> None:
        session, _, doc_lines = await _create_pick_session(
            real_async_db_session,
            pick_org,
            pick_user,
            line_specs=[
                {
                    'expected': Decimal('10'),
                    'status': 'picked',
                    'picked': Decimal('10'),
                }
            ],
        )

        result = await complete_pick_session_async(
            real_async_db_session, session.id, pick_org.id
        )

        assert result.status == 'completed'
        assert result.completed_at is not None
        await real_async_db_session.refresh(doc_lines[0])
        assert doc_lines[0].done_quantity == Decimal('10')

    @pytest.mark.asyncio
    async def test_complete_with_short_sets_short_pick(
        self,
        real_async_db_session: AsyncSession,
        pick_org: Organization,
        pick_user: User,
    ) -> None:
        session, _, doc_lines = await _create_pick_session(
            real_async_db_session,
            pick_org,
            pick_user,
            line_specs=[
                {
                    'expected': Decimal('10'),
                    'status': 'short',
                    'picked': Decimal('3'),
                }
            ],
        )

        result = await complete_pick_session_async(
            real_async_db_session, session.id, pick_org.id
        )

        assert result.status == 'short_pick'
        assert result.completed_at is not None
        await real_async_db_session.refresh(doc_lines[0])
        assert doc_lines[0].done_quantity == Decimal('3')

    @pytest.mark.asyncio
    async def test_complete_with_pending_lines_raises(
        self,
        real_async_db_session: AsyncSession,
        pick_org: Organization,
        pick_user: User,
    ) -> None:
        session, _, _ = await _create_pick_session(
            real_async_db_session,
            pick_org,
            pick_user,
            line_specs=[{'expected': Decimal('10')}],
        )

        with pytest.raises(ValueError, match='cannot be completed'):
            await complete_pick_session_async(
                real_async_db_session, session.id, pick_org.id
            )

    @pytest.mark.asyncio
    async def test_complete_empty_session_raises(
        self,
        real_async_db_session: AsyncSession,
        pick_org: Organization,
        pick_user: User,
    ) -> None:
        session, _, _ = await _create_pick_session(
            real_async_db_session,
            pick_org,
            pick_user,
            line_specs=[],
        )

        with pytest.raises(ValueError, match='no lines'):
            await complete_pick_session_async(
                real_async_db_session, session.id, pick_org.id
            )

    @pytest.mark.asyncio
    async def test_complete_zero_quantity_line_does_not_sync(
        self,
        real_async_db_session: AsyncSession,
        pick_org: Organization,
        pick_user: User,
    ) -> None:
        session, _, doc_lines = await _create_pick_session(
            real_async_db_session,
            pick_org,
            pick_user,
            line_specs=[
                {
                    'expected': Decimal('10'),
                    'status': 'picked',
                    'picked': Decimal('0'),
                }
            ],
        )

        result = await complete_pick_session_async(
            real_async_db_session, session.id, pick_org.id
        )

        assert result.status == 'completed'
        await real_async_db_session.refresh(doc_lines[0])
        assert doc_lines[0].done_quantity == Decimal('0')

    @pytest.mark.asyncio
    async def test_complete_mixed_picked_and_skipped(
        self,
        real_async_db_session: AsyncSession,
        pick_org: Organization,
        pick_user: User,
    ) -> None:
        session, _, doc_lines = await _create_pick_session(
            real_async_db_session,
            pick_org,
            pick_user,
            line_specs=[
                {
                    'expected': Decimal('10'),
                    'status': 'picked',
                    'picked': Decimal('10'),
                },
                {
                    'expected': Decimal('5'),
                    'status': 'skipped',
                    'picked': Decimal('0'),
                },
            ],
        )

        result = await complete_pick_session_async(
            real_async_db_session, session.id, pick_org.id
        )

        assert result.status == 'completed'
        await real_async_db_session.refresh(doc_lines[0])
        await real_async_db_session.refresh(doc_lines[1])
        assert doc_lines[0].done_quantity == Decimal('10')
        assert doc_lines[1].done_quantity == Decimal('0')


@pytest.mark.integration
class TestUndoPick:
    @pytest.mark.asyncio
    async def test_undo_picked_line_resets(
        self,
        real_async_db_session: AsyncSession,
        pick_org: Organization,
        pick_user: User,
    ) -> None:
        session, lines, doc_lines = await _create_pick_session(
            real_async_db_session,
            pick_org,
            pick_user,
            line_specs=[
                {
                    'expected': Decimal('10'),
                    'status': 'picked',
                    'picked': Decimal('5'),
                    'done': Decimal('5'),
                }
            ],
        )

        result = await undo_pick_async(
            real_async_db_session, session.id, pick_org.id, lines[0].id
        )

        assert result.status == 'pending'
        assert result.picked_quantity == Decimal('0')
        await real_async_db_session.refresh(doc_lines[0])
        assert doc_lines[0].done_quantity == Decimal('0')
        assert doc_lines[0].discrepancy_code is None

    @pytest.mark.asyncio
    async def test_undo_short_line_clears_discrepancy(
        self,
        real_async_db_session: AsyncSession,
        pick_org: Organization,
        pick_user: User,
    ) -> None:
        session, lines, doc_lines = await _create_pick_session(
            real_async_db_session,
            pick_org,
            pick_user,
            line_specs=[
                {
                    'expected': Decimal('10'),
                    'status': 'short',
                    'picked': Decimal('3'),
                    'done': Decimal('3'),
                    'discrepancy_code': 'SHORTAGE',
                    'discrepancy_reason': 'only 3',
                }
            ],
        )

        result = await undo_pick_async(
            real_async_db_session, session.id, pick_org.id, lines[0].id
        )

        assert result.status == 'pending'
        await real_async_db_session.refresh(doc_lines[0])
        assert doc_lines[0].done_quantity == Decimal('0')
        assert doc_lines[0].discrepancy_code is None
        assert doc_lines[0].discrepancy_reason is None

    @pytest.mark.asyncio
    async def test_undo_pending_line_raises(
        self,
        real_async_db_session: AsyncSession,
        pick_org: Organization,
        pick_user: User,
    ) -> None:
        session, lines, _ = await _create_pick_session(
            real_async_db_session,
            pick_org,
            pick_user,
            line_specs=[{'expected': Decimal('10')}],
        )

        with pytest.raises(ValueError, match='nothing recorded to undo'):
            await undo_pick_async(
                real_async_db_session, session.id, pick_org.id, lines[0].id
            )

    @pytest.mark.asyncio
    async def test_undo_partially_scanned_line_resets(
        self,
        real_async_db_session: AsyncSession,
        pick_org: Organization,
        pick_user: User,
    ) -> None:
        """Undo follows the quantity, not only the resolved status word.

        A partial scan leaves the line ``pending`` with a quantity on it;
        refusing to undo that line was the stale half of the filter — the
        receiving side has always undone anything with a quantity.
        """
        session, lines, doc_lines = await _create_pick_session(
            real_async_db_session,
            pick_org,
            pick_user,
            line_specs=[
                {
                    'expected': Decimal('10'),
                    'status': 'pending',
                    'picked': Decimal('4'),
                    'done': Decimal('4'),
                }
            ],
        )

        result = await undo_pick_async(
            real_async_db_session, session.id, pick_org.id, lines[0].id
        )

        assert result.status == 'pending'
        assert result.picked_quantity == Decimal('0')
        await real_async_db_session.refresh(doc_lines[0])
        assert doc_lines[0].done_quantity == Decimal('0')


@pytest.mark.integration
class TestSkipPickLine:
    @pytest.mark.asyncio
    async def test_skip_pending_line(
        self,
        real_async_db_session: AsyncSession,
        pick_org: Organization,
        pick_user: User,
    ) -> None:
        session, lines, doc_lines = await _create_pick_session(
            real_async_db_session,
            pick_org,
            pick_user,
            line_specs=[{'expected': Decimal('10')}],
        )

        result = await skip_pick_line_async(
            real_async_db_session, session.id, pick_org.id, lines[0].id
        )

        assert result.status == 'skipped'
        assert result.picked_quantity == Decimal('0')
        await real_async_db_session.refresh(doc_lines[0])
        assert doc_lines[0].done_quantity == Decimal('0')
        # A skip puts the line off: nothing on the document says why yet,
        # because the summary asks the person what it becomes.
        assert doc_lines[0].discrepancy_code is None
        assert doc_lines[0].discrepancy_reason is None

    @pytest.mark.asyncio
    async def test_skip_nonpending_line_raises(
        self,
        real_async_db_session: AsyncSession,
        pick_org: Organization,
        pick_user: User,
    ) -> None:
        session, lines, _ = await _create_pick_session(
            real_async_db_session,
            pick_org,
            pick_user,
            line_specs=[
                {
                    'expected': Decimal('10'),
                    'status': 'picked',
                    'picked': Decimal('10'),
                }
            ],
        )

        with pytest.raises(ValueError, match='no longer pending'):
            await skip_pick_line_async(
                real_async_db_session, session.id, pick_org.id, lines[0].id
            )


@pytest.mark.integration
class TestCancelPickSession:
    @pytest.mark.asyncio
    async def test_cancel_resets_picked_and_short_lines(
        self,
        real_async_db_session: AsyncSession,
        pick_org: Organization,
        pick_user: User,
    ) -> None:
        session, lines, doc_lines = await _create_pick_session(
            real_async_db_session,
            pick_org,
            pick_user,
            line_specs=[
                {
                    'expected': Decimal('10'),
                    'status': 'picked',
                    'picked': Decimal('10'),
                    'done': Decimal('10'),
                },
                {
                    'expected': Decimal('5'),
                    'status': 'short',
                    'picked': Decimal('2'),
                    'done': Decimal('2'),
                    'discrepancy_code': 'SHORTAGE',
                    'discrepancy_reason': 'only 2',
                },
            ],
        )

        await cancel_pick_session_async(real_async_db_session, session.id, pick_org.id)

        refreshed_session = await real_async_db_session.scalar(
            select(WmsPickSession).where(WmsPickSession.id == session.id)
        )
        assert refreshed_session is not None
        assert refreshed_session.status == 'cancelled'

        for line in lines:
            await real_async_db_session.refresh(line)
            assert line.status == 'pending'
            assert line.picked_quantity == Decimal('0')
        for doc_line in doc_lines:
            await real_async_db_session.refresh(doc_line)
            assert doc_line.done_quantity == Decimal('0')
            assert doc_line.discrepancy_code is None
            assert doc_line.discrepancy_reason is None

    @pytest.mark.asyncio
    async def test_cancel_with_only_pending_line(
        self,
        real_async_db_session: AsyncSession,
        pick_org: Organization,
        pick_user: User,
    ) -> None:
        session, lines, _ = await _create_pick_session(
            real_async_db_session,
            pick_org,
            pick_user,
            line_specs=[{'expected': Decimal('10')}],
        )

        await cancel_pick_session_async(real_async_db_session, session.id, pick_org.id)

        refreshed_session = await real_async_db_session.scalar(
            select(WmsPickSession).where(WmsPickSession.id == session.id)
        )
        assert refreshed_session is not None
        assert refreshed_session.status == 'cancelled'
        await real_async_db_session.refresh(lines[0])
        assert lines[0].status == 'pending'
