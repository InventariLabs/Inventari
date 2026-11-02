"""Direct integration tests for ``_receiving_session_ops``.

Same rationale as ``test_picking_session_ops.py``: the existing
``test_wms_receiving.py`` drives these functions through the FastAPI
``TestClient`` (blocking portal thread), where coverage cannot reliably record
the statements after the first ``await``. These tests call the service
functions directly on a real ``AsyncSession``.
"""

import uuid
from decimal import Decimal
from typing import cast

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.user import User
from app.modules.warehouse._receiving_session_ops import (
    cancel_receive_session_async,
    close_session_if_complete_async,
    complete_receive_session_async,
    confirm_short_receive_async,
    skip_receive_line_async,
    undo_receive_async,
)
from app.modules.warehouse.models import (
    Document,
    DocumentLine,
    DocumentStatus,
    WmsPickLine,
    WmsPickSession,
)


@pytest.fixture
async def receive_org(real_async_db_session: AsyncSession) -> Organization:
    org = Organization(name='Receive Ops Org', enabled_modules=['core', 'warehouse'])
    real_async_db_session.add(org)
    await real_async_db_session.flush()
    return org


@pytest.fixture
async def receive_user(
    real_async_db_session: AsyncSession, receive_org: Organization
) -> User:
    return await ModuleTestHelper.create_user_async(
        real_async_db_session,
        receive_org,
        email='receive-ops@example.com',
        role='admin',
    )


async def _create_receive_session(
    db: AsyncSession,
    org: Organization,
    user: User,
    *,
    line_specs: list[dict[str, Decimal | str]],
    session_status: str = 'active',
) -> tuple[WmsPickSession, list[WmsPickLine], list[DocumentLine]]:
    """Create a CONFIRMED IN document with a receiving session and its lines."""
    doc = Document(
        organization_id=org.id,
        type='IN',
        number=f'IN-{uuid.uuid4().hex[:8]}',
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
        meta_data={'direction': 'inbound'},
    )
    db.add(session)
    await db.flush()

    receive_lines: list[WmsPickLine] = []
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

        receive_line = WmsPickLine(
            session_id=session.id,
            document_line_id=doc_line.id,
            pick_order=i,
            status=spec.get('status', 'pending'),
            picked_quantity=spec.get('picked', Decimal('0')),
            expected_quantity=spec['expected'],
        )
        db.add(receive_line)
        receive_lines.append(receive_line)
        doc_lines.append(doc_line)

    await db.flush()
    return session, receive_lines, doc_lines


async def _load_session(
    db: AsyncSession, session_id: uuid.UUID
) -> WmsPickSession | None:
    return cast(
        WmsPickSession | None,
        await db.scalar(select(WmsPickSession).where(WmsPickSession.id == session_id)),
    )


@pytest.mark.integration
class TestCloseSessionIfComplete:
    @pytest.mark.asyncio
    async def test_no_lines_is_noop(
        self,
        real_async_db_session: AsyncSession,
        receive_org: Organization,
        receive_user: User,
    ) -> None:
        session, _, _ = await _create_receive_session(
            real_async_db_session,
            receive_org,
            receive_user,
            line_specs=[],
        )

        await close_session_if_complete_async(real_async_db_session, session)

        refreshed = await _load_session(real_async_db_session, session.id)
        assert refreshed is not None
        assert refreshed.status == 'active'
        assert refreshed.completed_at is None

    @pytest.mark.asyncio
    async def test_pending_line_is_noop(
        self,
        real_async_db_session: AsyncSession,
        receive_org: Organization,
        receive_user: User,
    ) -> None:
        session, _, _ = await _create_receive_session(
            real_async_db_session,
            receive_org,
            receive_user,
            line_specs=[{'expected': Decimal('10')}],
        )

        await close_session_if_complete_async(real_async_db_session, session)

        refreshed = await _load_session(real_async_db_session, session.id)
        assert refreshed is not None
        assert refreshed.status == 'active'
        assert refreshed.completed_at is None

    @pytest.mark.asyncio
    async def test_all_picked_closes_completed(
        self,
        real_async_db_session: AsyncSession,
        receive_org: Organization,
        receive_user: User,
    ) -> None:
        session, _, _ = await _create_receive_session(
            real_async_db_session,
            receive_org,
            receive_user,
            line_specs=[
                {
                    'expected': Decimal('10'),
                    'status': 'picked',
                    'picked': Decimal('10'),
                }
            ],
        )

        await close_session_if_complete_async(real_async_db_session, session)

        refreshed = await _load_session(real_async_db_session, session.id)
        assert refreshed is not None
        assert refreshed.status == 'completed'
        assert refreshed.completed_at is not None

    @pytest.mark.asyncio
    async def test_short_line_closes_short_receive(
        self,
        real_async_db_session: AsyncSession,
        receive_org: Organization,
        receive_user: User,
    ) -> None:
        session, _, _ = await _create_receive_session(
            real_async_db_session,
            receive_org,
            receive_user,
            line_specs=[
                {
                    'expected': Decimal('10'),
                    'status': 'short',
                    'picked': Decimal('3'),
                }
            ],
        )

        await close_session_if_complete_async(real_async_db_session, session)

        refreshed = await _load_session(real_async_db_session, session.id)
        assert refreshed is not None
        assert refreshed.status == 'short_receive'
        assert refreshed.completed_at is not None


@pytest.mark.integration
class TestConfirmShortReceive:
    @pytest.mark.asyncio
    async def test_short_receive_sets_short_and_discrepancy(
        self,
        real_async_db_session: AsyncSession,
        receive_org: Organization,
        receive_user: User,
    ) -> None:
        session, lines, doc_lines = await _create_receive_session(
            real_async_db_session,
            receive_org,
            receive_user,
            line_specs=[{'expected': Decimal('10')}],
        )

        result = await confirm_short_receive_async(
            real_async_db_session,
            session.id,
            receive_org.id,
            lines[0].id,
            Decimal('7'),
            'DAMAGE',
            '3 units damaged in transit',
        )

        assert result.status == 'short'
        assert result.picked_quantity == Decimal('7')
        await real_async_db_session.refresh(doc_lines[0])
        assert doc_lines[0].done_quantity == Decimal('7')
        assert doc_lines[0].discrepancy_code == 'DAMAGE'
        assert doc_lines[0].discrepancy_reason == '3 units damaged in transit'

        refreshed = await _load_session(real_async_db_session, session.id)
        assert refreshed is not None
        assert refreshed.status == 'short_receive'
        assert refreshed.completed_at is not None

    @pytest.mark.asyncio
    async def test_short_receive_without_a_reason_stores_none(
        self,
        real_async_db_session: AsyncSession,
        receive_org: Organization,
        receive_user: User,
    ) -> None:
        """A short line names the shortage by code, not by a stored sentence.

        The default reason this used to write was an English sentence
        ("Short receiving") shown as is to every reader, in every language.
        The code SHORTAGE is the name now and the screens translate it.
        """
        session, lines, doc_lines = await _create_receive_session(
            real_async_db_session,
            receive_org,
            receive_user,
            line_specs=[{'expected': Decimal('10')}],
        )

        result = await confirm_short_receive_async(
            real_async_db_session,
            session.id,
            receive_org.id,
            lines[0].id,
            Decimal('7'),
        )

        assert result.status == 'short'
        await real_async_db_session.refresh(doc_lines[0])
        assert doc_lines[0].discrepancy_code == 'SHORTAGE'
        assert doc_lines[0].discrepancy_reason is None

    @pytest.mark.asyncio
    async def test_a_count_below_the_scanned_quantity_is_refused(
        self,
        real_async_db_session: AsyncSession,
        receive_org: Organization,
        receive_user: User,
    ) -> None:
        session, lines, _ = await _create_receive_session(
            real_async_db_session,
            receive_org,
            receive_user,
            line_specs=[{'expected': Decimal('10'), 'picked': Decimal('7')}],
        )

        with pytest.raises(ValueError, match='below the scanned quantity'):
            await confirm_short_receive_async(
                real_async_db_session,
                session.id,
                receive_org.id,
                lines[0].id,
                Decimal('5'),
            )

    @pytest.mark.asyncio
    async def test_a_count_below_the_scans_replaces_them_when_it_says_so(
        self,
        real_async_db_session: AsyncSession,
        receive_org: Organization,
        receive_user: User,
    ) -> None:
        session, lines, doc_lines = await _create_receive_session(
            real_async_db_session,
            receive_org,
            receive_user,
            line_specs=[{'expected': Decimal('10'), 'picked': Decimal('7')}],
        )

        result = await confirm_short_receive_async(
            real_async_db_session,
            session.id,
            receive_org.id,
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
    async def test_exact_receive_sets_picked_and_closes_completed(
        self,
        real_async_db_session: AsyncSession,
        receive_org: Organization,
        receive_user: User,
    ) -> None:
        session, lines, doc_lines = await _create_receive_session(
            real_async_db_session,
            receive_org,
            receive_user,
            line_specs=[{'expected': Decimal('10')}],
        )

        result = await confirm_short_receive_async(
            real_async_db_session,
            session.id,
            receive_org.id,
            lines[0].id,
            Decimal('10'),
        )

        assert result.status == 'picked'
        await real_async_db_session.refresh(doc_lines[0])
        assert doc_lines[0].done_quantity == Decimal('10')

        refreshed = await _load_session(real_async_db_session, session.id)
        assert refreshed is not None
        assert refreshed.status == 'completed'

    @pytest.mark.asyncio
    async def test_quantity_exceeding_expected_raises(
        self,
        real_async_db_session: AsyncSession,
        receive_org: Organization,
        receive_user: User,
    ) -> None:
        session, lines, _ = await _create_receive_session(
            real_async_db_session,
            receive_org,
            receive_user,
            line_specs=[{'expected': Decimal('10')}],
        )

        # Receiving's default is the over-receipt policy with no permission:
        # past the (zero) tolerance the refusal names whose hand is needed.
        with pytest.raises(ValueError, match='over-receipt tolerance'):
            await confirm_short_receive_async(
                real_async_db_session,
                session.id,
                receive_org.id,
                lines[0].id,
                Decimal('11'),
            )

    @pytest.mark.asyncio
    async def test_negative_quantity_raises(
        self,
        real_async_db_session: AsyncSession,
        receive_org: Organization,
        receive_user: User,
    ) -> None:
        session, lines, _ = await _create_receive_session(
            real_async_db_session,
            receive_org,
            receive_user,
            line_specs=[{'expected': Decimal('10')}],
        )

        with pytest.raises(ValueError, match='cannot be negative'):
            await confirm_short_receive_async(
                real_async_db_session,
                session.id,
                receive_org.id,
                lines[0].id,
                Decimal('-1'),
            )

    @pytest.mark.asyncio
    async def test_zero_short_receive_records_that_nothing_arrived(
        self,
        real_async_db_session: AsyncSession,
        receive_org: Organization,
        receive_user: User,
    ) -> None:
        """Nothing arrived on this line is an answer, not an omission.

        The dialog at the other end refused zero with "Enter how much
        actually arrived", and the schema and this guard refused it next —
        so a delivery that turned up empty for one line had no way to be
        recorded as checked and empty, only as skipped.
        """
        session, lines, doc_lines = await _create_receive_session(
            real_async_db_session,
            receive_org,
            receive_user,
            line_specs=[{'expected': Decimal('10')}],
        )

        result = await confirm_short_receive_async(
            real_async_db_session,
            session.id,
            receive_org.id,
            lines[0].id,
            Decimal('0'),
        )

        assert result.status == 'short'
        assert result.picked_quantity == Decimal('0')
        await real_async_db_session.refresh(doc_lines[0])
        assert doc_lines[0].done_quantity == Decimal('0')
        assert doc_lines[0].discrepancy_code == 'SHORTAGE'

        refreshed = await _load_session(real_async_db_session, session.id)
        assert refreshed is not None
        assert refreshed.status == 'short_receive'
        assert refreshed.completed_at is not None

    @pytest.mark.asyncio
    async def test_unknown_line_raises(
        self,
        real_async_db_session: AsyncSession,
        receive_org: Organization,
        receive_user: User,
    ) -> None:
        session, _, _ = await _create_receive_session(
            real_async_db_session,
            receive_org,
            receive_user,
            line_specs=[{'expected': Decimal('10')}],
        )

        with pytest.raises(ValueError, match='session line was not found'):
            await confirm_short_receive_async(
                real_async_db_session,
                session.id,
                receive_org.id,
                uuid.uuid4(),
                Decimal('5'),
            )

    @pytest.mark.asyncio
    async def test_line_from_other_session_raises(
        self,
        real_async_db_session: AsyncSession,
        receive_org: Organization,
        receive_user: User,
    ) -> None:
        session_a, _, _ = await _create_receive_session(
            real_async_db_session,
            receive_org,
            receive_user,
            line_specs=[{'expected': Decimal('10')}],
        )
        _, lines_b, _ = await _create_receive_session(
            real_async_db_session,
            receive_org,
            receive_user,
            line_specs=[{'expected': Decimal('10')}],
        )

        with pytest.raises(ValueError, match='session line was not found'):
            await confirm_short_receive_async(
                real_async_db_session,
                session_a.id,
                receive_org.id,
                lines_b[0].id,
                Decimal('5'),
            )


@pytest.mark.integration
class TestCompleteReceiveSession:
    @pytest.mark.asyncio
    async def test_complete_all_received_sets_completed(
        self,
        real_async_db_session: AsyncSession,
        receive_org: Organization,
        receive_user: User,
    ) -> None:
        session, _, doc_lines = await _create_receive_session(
            real_async_db_session,
            receive_org,
            receive_user,
            line_specs=[
                {
                    'expected': Decimal('10'),
                    'status': 'picked',
                    'picked': Decimal('10'),
                }
            ],
        )

        result = await complete_receive_session_async(
            real_async_db_session, session.id, receive_org.id
        )

        assert result.status == 'completed'
        assert result.completed_at is not None
        await real_async_db_session.refresh(doc_lines[0])
        assert doc_lines[0].done_quantity == Decimal('10')

    @pytest.mark.asyncio
    async def test_complete_with_short_sets_short_receive(
        self,
        real_async_db_session: AsyncSession,
        receive_org: Organization,
        receive_user: User,
    ) -> None:
        session, _, doc_lines = await _create_receive_session(
            real_async_db_session,
            receive_org,
            receive_user,
            line_specs=[
                {
                    'expected': Decimal('10'),
                    'status': 'short',
                    'picked': Decimal('3'),
                }
            ],
        )

        result = await complete_receive_session_async(
            real_async_db_session, session.id, receive_org.id
        )

        assert result.status == 'short_receive'
        await real_async_db_session.refresh(doc_lines[0])
        assert doc_lines[0].done_quantity == Decimal('3')

    @pytest.mark.asyncio
    async def test_complete_with_pending_lines_raises(
        self,
        real_async_db_session: AsyncSession,
        receive_org: Organization,
        receive_user: User,
    ) -> None:
        session, _, _ = await _create_receive_session(
            real_async_db_session,
            receive_org,
            receive_user,
            line_specs=[{'expected': Decimal('10')}],
        )

        with pytest.raises(ValueError, match='cannot be completed'):
            await complete_receive_session_async(
                real_async_db_session, session.id, receive_org.id
            )

    @pytest.mark.asyncio
    async def test_complete_empty_session_raises(
        self,
        real_async_db_session: AsyncSession,
        receive_org: Organization,
        receive_user: User,
    ) -> None:
        """An empty session must not report completion.

        ``all([])`` is True, so without the guard complete answered success
        over a document whose lines were all still pending.
        """
        session, _, _ = await _create_receive_session(
            real_async_db_session,
            receive_org,
            receive_user,
            line_specs=[],
        )

        with pytest.raises(ValueError, match='no lines'):
            await complete_receive_session_async(
                real_async_db_session, session.id, receive_org.id
            )

    @pytest.mark.asyncio
    async def test_complete_is_idempotent_for_completed(
        self,
        real_async_db_session: AsyncSession,
        receive_org: Organization,
        receive_user: User,
    ) -> None:
        session, _, _ = await _create_receive_session(
            real_async_db_session,
            receive_org,
            receive_user,
            line_specs=[
                {
                    'expected': Decimal('10'),
                    'status': 'picked',
                    'picked': Decimal('10'),
                }
            ],
            session_status='completed',
        )

        result = await complete_receive_session_async(
            real_async_db_session, session.id, receive_org.id
        )

        assert result.status == 'completed'

    @pytest.mark.asyncio
    async def test_complete_is_idempotent_for_short_receive(
        self,
        real_async_db_session: AsyncSession,
        receive_org: Organization,
        receive_user: User,
    ) -> None:
        session, _, _ = await _create_receive_session(
            real_async_db_session,
            receive_org,
            receive_user,
            line_specs=[
                {
                    'expected': Decimal('10'),
                    'status': 'short',
                    'picked': Decimal('3'),
                }
            ],
            session_status='short_receive',
        )

        result = await complete_receive_session_async(
            real_async_db_session, session.id, receive_org.id
        )

        assert result.status == 'short_receive'

    @pytest.mark.asyncio
    async def test_complete_cancelled_session_raises(
        self,
        real_async_db_session: AsyncSession,
        receive_org: Organization,
        receive_user: User,
    ) -> None:
        session, _, _ = await _create_receive_session(
            real_async_db_session,
            receive_org,
            receive_user,
            line_specs=[{'expected': Decimal('10')}],
            session_status='cancelled',
        )

        with pytest.raises(ValueError, match='active session was not found'):
            await complete_receive_session_async(
                real_async_db_session, session.id, receive_org.id
            )

    @pytest.mark.asyncio
    async def test_complete_unknown_session_raises(
        self,
        real_async_db_session: AsyncSession,
        receive_org: Organization,
        receive_user: User,
    ) -> None:
        await _create_receive_session(
            real_async_db_session,
            receive_org,
            receive_user,
            line_specs=[{'expected': Decimal('10')}],
        )

        with pytest.raises(ValueError, match='active session was not found'):
            await complete_receive_session_async(
                real_async_db_session, uuid.uuid4(), receive_org.id
            )


@pytest.mark.integration
class TestUndoReceive:
    @pytest.mark.asyncio
    async def test_undo_received_line_resets(
        self,
        real_async_db_session: AsyncSession,
        receive_org: Organization,
        receive_user: User,
    ) -> None:
        session, lines, doc_lines = await _create_receive_session(
            real_async_db_session,
            receive_org,
            receive_user,
            line_specs=[
                {
                    'expected': Decimal('10'),
                    'status': 'picked',
                    'picked': Decimal('5'),
                    'done': Decimal('5'),
                }
            ],
        )

        result = await undo_receive_async(
            real_async_db_session, session.id, receive_org.id, lines[0].id
        )

        assert result.status == 'pending'
        assert result.picked_quantity == Decimal('0')
        await real_async_db_session.refresh(doc_lines[0])
        assert doc_lines[0].done_quantity == Decimal('0')
        assert doc_lines[0].discrepancy_code is None

    @pytest.mark.asyncio
    async def test_undo_line_without_received_quantity_raises(
        self,
        real_async_db_session: AsyncSession,
        receive_org: Organization,
        receive_user: User,
    ) -> None:
        session, lines, _ = await _create_receive_session(
            real_async_db_session,
            receive_org,
            receive_user,
            line_specs=[{'expected': Decimal('10')}],
        )

        with pytest.raises(ValueError, match='nothing recorded to undo'):
            await undo_receive_async(
                real_async_db_session, session.id, receive_org.id, lines[0].id
            )

    @pytest.mark.asyncio
    async def test_undo_a_line_that_received_nothing_resets(
        self,
        real_async_db_session: AsyncSession,
        receive_org: Organization,
        receive_user: User,
    ) -> None:
        """A short receive of zero is recorded, so its row can take it back.

        The filter read the quantity alone, and zero is exactly the quantity
        this answer carries: the row offered Undo beside the line and the
        session refused it with "nothing recorded to undo".
        """
        session, lines, doc_lines = await _create_receive_session(
            real_async_db_session,
            receive_org,
            receive_user,
            line_specs=[
                {'expected': Decimal('10')},
                {'expected': Decimal('4')},
            ],
        )

        await confirm_short_receive_async(
            real_async_db_session,
            session.id,
            receive_org.id,
            lines[0].id,
            Decimal('0'),
        )

        result = await undo_receive_async(
            real_async_db_session, session.id, receive_org.id, lines[0].id
        )

        assert result.status == 'pending'
        assert result.picked_quantity == Decimal('0')
        await real_async_db_session.refresh(doc_lines[0])
        assert doc_lines[0].done_quantity == Decimal('0')
        assert doc_lines[0].discrepancy_code is None


@pytest.mark.integration
class TestSkipReceiveLine:
    @pytest.mark.asyncio
    async def test_skip_pending_line(
        self,
        real_async_db_session: AsyncSession,
        receive_org: Organization,
        receive_user: User,
    ) -> None:
        session, lines, doc_lines = await _create_receive_session(
            real_async_db_session,
            receive_org,
            receive_user,
            line_specs=[{'expected': Decimal('10')}],
        )

        result = await skip_receive_line_async(
            real_async_db_session, session.id, receive_org.id, lines[0].id
        )

        assert result.status == 'skipped'
        assert result.picked_quantity == Decimal('0')
        await real_async_db_session.refresh(doc_lines[0])
        assert doc_lines[0].done_quantity == Decimal('0')
        # A skip puts the line off: the summary asks what it becomes, so
        # nothing is written on the document line until somebody answers.
        assert doc_lines[0].discrepancy_code is None
        assert doc_lines[0].discrepancy_reason is None

        refreshed = await _load_session(real_async_db_session, session.id)
        assert refreshed is not None
        assert refreshed.status == 'completed'

    @pytest.mark.asyncio
    async def test_skip_last_pending_line_closes_session(
        self,
        real_async_db_session: AsyncSession,
        receive_org: Organization,
        receive_user: User,
    ) -> None:
        session, lines, _ = await _create_receive_session(
            real_async_db_session,
            receive_org,
            receive_user,
            line_specs=[
                {
                    'expected': Decimal('10'),
                    'status': 'picked',
                    'picked': Decimal('10'),
                },
                {'expected': Decimal('5')},
            ],
        )

        await skip_receive_line_async(
            real_async_db_session, session.id, receive_org.id, lines[1].id
        )

        refreshed = await _load_session(real_async_db_session, session.id)
        assert refreshed is not None
        assert refreshed.status == 'completed'
        assert refreshed.completed_at is not None

    @pytest.mark.asyncio
    async def test_skip_does_not_close_when_lines_remain_pending(
        self,
        real_async_db_session: AsyncSession,
        receive_org: Organization,
        receive_user: User,
    ) -> None:
        session, lines, _ = await _create_receive_session(
            real_async_db_session,
            receive_org,
            receive_user,
            line_specs=[
                {'expected': Decimal('10')},
                {'expected': Decimal('5')},
            ],
        )

        await skip_receive_line_async(
            real_async_db_session, session.id, receive_org.id, lines[0].id
        )

        refreshed = await _load_session(real_async_db_session, session.id)
        assert refreshed is not None
        assert refreshed.status == 'active'
        assert refreshed.completed_at is None

    @pytest.mark.asyncio
    async def test_skip_nonpending_line_raises(
        self,
        real_async_db_session: AsyncSession,
        receive_org: Organization,
        receive_user: User,
    ) -> None:
        session, lines, _ = await _create_receive_session(
            real_async_db_session,
            receive_org,
            receive_user,
            line_specs=[
                {
                    'expected': Decimal('10'),
                    'status': 'picked',
                    'picked': Decimal('10'),
                }
            ],
        )

        with pytest.raises(ValueError, match='no longer pending'):
            await skip_receive_line_async(
                real_async_db_session, session.id, receive_org.id, lines[0].id
            )


@pytest.mark.integration
class TestCancelReceiveSession:
    @pytest.mark.asyncio
    async def test_cancel_resets_received_lines(
        self,
        real_async_db_session: AsyncSession,
        receive_org: Organization,
        receive_user: User,
    ) -> None:
        session, lines, doc_lines = await _create_receive_session(
            real_async_db_session,
            receive_org,
            receive_user,
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
                    'discrepancy_code': 'DAMAGE',
                    'discrepancy_reason': 'damaged',
                },
            ],
        )

        await cancel_receive_session_async(
            real_async_db_session, session.id, receive_org.id
        )

        refreshed = await _load_session(real_async_db_session, session.id)
        assert refreshed is not None
        assert refreshed.status == 'cancelled'

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
        receive_org: Organization,
        receive_user: User,
    ) -> None:
        session, lines, _ = await _create_receive_session(
            real_async_db_session,
            receive_org,
            receive_user,
            line_specs=[{'expected': Decimal('10')}],
        )

        await cancel_receive_session_async(
            real_async_db_session, session.id, receive_org.id
        )

        refreshed = await _load_session(real_async_db_session, session.id)
        assert refreshed is not None
        assert refreshed.status == 'cancelled'
        await real_async_db_session.refresh(lines[0])
        assert lines[0].status == 'pending'
