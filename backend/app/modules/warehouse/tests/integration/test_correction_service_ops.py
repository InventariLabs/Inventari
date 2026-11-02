"""Direct integration tests for ``document_correction_service``.

The existing ``test_correction_documents.py`` drives these functions through
the FastAPI ``TestClient``, which runs the async app in a separate
blocking-portal thread. Coverage's tracer does not reliably record the
statements after the first ``await`` inside that worker thread, so those
endpoint tests leave most of this module around 26%. These tests call the
service functions directly on a real ``AsyncSession`` so the lines are
attributed correctly.

Stock is not touched by this service: it only creates the DRAFT
``CORRECTION`` document and the ``corrects`` relation. The actual stock/value
effects are applied later by ``execute_correction`` during document
completion, which lives in a separate module.
"""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.user import User
from app.modules.warehouse.document_correction_service import (
    create_correction,
    get_corrections_for_document,
)
from app.modules.warehouse.models import (
    Document,
    DocumentLine,
    DocumentRelation,
    DocumentStatus,
)

LineSpec = dict[str, Decimal | str]


@pytest.fixture
async def corr_org(real_async_db_session: AsyncSession) -> Organization:
    org = Organization(name='Correction Ops Org', enabled_modules=['core', 'warehouse'])
    real_async_db_session.add(org)
    await real_async_db_session.flush()
    return org


@pytest.fixture
async def corr_user(
    real_async_db_session: AsyncSession, corr_org: Organization
) -> User:
    return await ModuleTestHelper.create_user_async(
        real_async_db_session,
        corr_org,
        email='correction-ops@example.com',
        role='admin',
    )


async def _create_completed_document(
    db: AsyncSession,
    org: Organization,
    user: User,
    *,
    doc_type: str,
    line_specs: list[LineSpec],
    status: str = DocumentStatus.COMPLETED.value,
    source_location_id: uuid.UUID | None = None,
    target_location_id: uuid.UUID | None = None,
) -> Document:
    """Create a document with the given completed lines in the async session."""
    doc = Document(
        organization_id=org.id,
        type=doc_type,
        number=f'{doc_type}-{uuid.uuid4().hex[:8]}',
        status=status,
        source_location_id=source_location_id,
        target_location_id=target_location_id,
        created_by=user.id,
    )
    for i, spec in enumerate(line_specs, start=1):
        doc.lines.append(
            DocumentLine(
                quantity=Decimal(str(spec['quantity'])),
                expected_quantity=Decimal(str(spec['quantity'])),
                done_quantity=Decimal(str(spec['done_quantity'])),
                line_number=i,
            )
        )
    db.add(doc)
    await db.flush()
    return doc


async def _get_lines(db: AsyncSession, doc_id: uuid.UUID) -> list[DocumentLine]:
    return list(
        (
            await db.scalars(
                select(DocumentLine)
                .where(DocumentLine.document_id == doc_id)
                # The document's own lines come back in the order the
                # correction numbered them; a bare select has none, which made
                # an assertion on lines[0] true only by luck.
                .order_by(DocumentLine.line_number)
            )
        ).all()
    )


@pytest.mark.integration
class TestCreateCorrection:
    @pytest.mark.asyncio
    async def test_create_correction_success(
        self,
        real_async_db_session: AsyncSession,
        corr_org: Organization,
        corr_user: User,
    ) -> None:
        original = await _create_completed_document(
            real_async_db_session,
            corr_org,
            corr_user,
            doc_type='IN',
            line_specs=[{'quantity': Decimal('10'), 'done_quantity': Decimal('10')}],
        )

        correction = await create_correction(
            real_async_db_session,
            original.id,
            [
                {
                    'original_line_number': 1,
                    'quantity_delta': Decimal('-2'),
                    'notes': 'Damaged in transit',
                }
            ],
            corr_org.id,
            corr_user.id,
            notes='Quality control',
        )

        assert correction.type == 'CORRECTION'
        assert correction.status == DocumentStatus.DRAFT.value
        # A draft carries an identifier; the COR/ number arrives when the
        # correction is confirmed.
        assert correction.number.startswith('DRAFT-')
        assert correction.corrects_document_id == original.id
        assert correction.external_reference == original.number
        assert correction.notes == 'Quality control'

        lines = await _get_lines(real_async_db_session, correction.id)
        assert len(lines) == 1
        assert lines[0].quantity == Decimal('-2')
        assert lines[0].expected_quantity == Decimal('-2')
        assert lines[0].done_quantity == Decimal('0')
        assert lines[0].notes == 'Damaged in transit'

        relations = (
            await real_async_db_session.scalars(
                select(DocumentRelation).where(
                    DocumentRelation.source_document_id == correction.id,
                    DocumentRelation.target_document_id == original.id,
                )
            )
        ).all()
        assert len(relations) == 1
        assert relations[0].relation_type == 'corrects'

    @pytest.mark.asyncio
    async def test_create_correction_accepts_line_number_key(
        self,
        real_async_db_session: AsyncSession,
        corr_org: Organization,
        corr_user: User,
    ) -> None:
        original = await _create_completed_document(
            real_async_db_session,
            corr_org,
            corr_user,
            doc_type='IN',
            line_specs=[{'quantity': Decimal('5'), 'done_quantity': Decimal('5')}],
        )

        correction = await create_correction(
            real_async_db_session,
            original.id,
            [{'line_number': 1, 'quantity_delta': Decimal('3')}],
            corr_org.id,
            corr_user.id,
            # A surplus correction; the caller holds the over-receipt
            # permission the ramp would ask of a person.
            may_exceed_over_receipt=True,
        )

        lines = await _get_lines(real_async_db_session, correction.id)
        assert len(lines) == 1
        assert lines[0].quantity == Decimal('3')

    @pytest.mark.asyncio
    async def test_create_correction_original_not_found_raises(
        self,
        real_async_db_session: AsyncSession,
        corr_org: Organization,
        corr_user: User,
    ) -> None:
        with pytest.raises(ValueError, match='Document not found'):
            await create_correction(
                real_async_db_session,
                uuid.uuid4(),
                [{'original_line_number': 1, 'quantity_delta': Decimal('-1')}],
                corr_org.id,
                corr_user.id,
            )

    @pytest.mark.asyncio
    async def test_create_correction_requires_completed_original(
        self,
        real_async_db_session: AsyncSession,
        corr_org: Organization,
        corr_user: User,
    ) -> None:
        original = await _create_completed_document(
            real_async_db_session,
            corr_org,
            corr_user,
            doc_type='IN',
            line_specs=[{'quantity': Decimal('5'), 'done_quantity': Decimal('0')}],
            status=DocumentStatus.DRAFT.value,
        )

        with pytest.raises(ValueError, match='Only a completed document'):
            await create_correction(
                real_async_db_session,
                original.id,
                [{'original_line_number': 1, 'quantity_delta': Decimal('-1')}],
                corr_org.id,
                corr_user.id,
            )

    @pytest.mark.asyncio
    async def test_create_correction_empty_lines_raises(
        self,
        real_async_db_session: AsyncSession,
        corr_org: Organization,
        corr_user: User,
    ) -> None:
        original = await _create_completed_document(
            real_async_db_session,
            corr_org,
            corr_user,
            doc_type='IN',
            line_specs=[{'quantity': Decimal('5'), 'done_quantity': Decimal('5')}],
        )

        with pytest.raises(ValueError, match='at least one line'):
            await create_correction(
                real_async_db_session,
                original.id,
                [],
                corr_org.id,
                corr_user.id,
            )

    @pytest.mark.asyncio
    async def test_create_correction_unknown_line_number_raises(
        self,
        real_async_db_session: AsyncSession,
        corr_org: Organization,
        corr_user: User,
    ) -> None:
        original = await _create_completed_document(
            real_async_db_session,
            corr_org,
            corr_user,
            doc_type='IN',
            line_specs=[{'quantity': Decimal('5'), 'done_quantity': Decimal('5')}],
        )

        with pytest.raises(ValueError, match='does not exist'):
            await create_correction(
                real_async_db_session,
                original.id,
                [{'original_line_number': 999, 'quantity_delta': Decimal('-1')}],
                corr_org.id,
                corr_user.id,
            )

    @pytest.mark.asyncio
    async def test_create_correction_below_zero_delta_raises(
        self,
        real_async_db_session: AsyncSession,
        corr_org: Organization,
        corr_user: User,
    ) -> None:
        original = await _create_completed_document(
            real_async_db_session,
            corr_org,
            corr_user,
            doc_type='IN',
            line_specs=[{'quantity': Decimal('10'), 'done_quantity': Decimal('10')}],
        )

        with pytest.raises(ValueError, match='below zero'):
            await create_correction(
                real_async_db_session,
                original.id,
                [{'original_line_number': 1, 'quantity_delta': Decimal('-15')}],
                corr_org.id,
                corr_user.id,
            )

    @pytest.mark.asyncio
    async def test_create_correction_exact_reversal_is_accepted(
        self,
        real_async_db_session: AsyncSession,
        corr_org: Organization,
        corr_user: User,
    ) -> None:
        original = await _create_completed_document(
            real_async_db_session,
            corr_org,
            corr_user,
            doc_type='IN',
            line_specs=[{'quantity': Decimal('5'), 'done_quantity': Decimal('5')}],
        )

        correction = await create_correction(
            real_async_db_session,
            original.id,
            [{'original_line_number': 1, 'quantity_delta': Decimal('-5')}],
            corr_org.id,
            corr_user.id,
        )

        lines = await _get_lines(real_async_db_session, correction.id)
        assert lines[0].quantity == Decimal('-5')

    @pytest.mark.asyncio
    async def test_create_correction_zero_delta_is_accepted(
        self,
        real_async_db_session: AsyncSession,
        corr_org: Organization,
        corr_user: User,
    ) -> None:
        original = await _create_completed_document(
            real_async_db_session,
            corr_org,
            corr_user,
            doc_type='IN',
            line_specs=[{'quantity': Decimal('10'), 'done_quantity': Decimal('10')}],
        )

        correction = await create_correction(
            real_async_db_session,
            original.id,
            [{'original_line_number': 1, 'quantity_delta': Decimal('0')}],
            corr_org.id,
            corr_user.id,
        )

        lines = await _get_lines(real_async_db_session, correction.id)
        assert len(lines) == 1
        assert lines[0].quantity == Decimal('0')

    @pytest.mark.asyncio
    async def test_create_correction_multiple_lines(
        self,
        real_async_db_session: AsyncSession,
        corr_org: Organization,
        corr_user: User,
    ) -> None:
        original = await _create_completed_document(
            real_async_db_session,
            corr_org,
            corr_user,
            doc_type='IN',
            line_specs=[
                {'quantity': Decimal('10'), 'done_quantity': Decimal('10')},
                {'quantity': Decimal('20'), 'done_quantity': Decimal('20')},
            ],
        )

        correction = await create_correction(
            real_async_db_session,
            original.id,
            [
                {'original_line_number': 1, 'quantity_delta': Decimal('-2')},
                {'original_line_number': 2, 'quantity_delta': Decimal('3')},
            ],
            corr_org.id,
            corr_user.id,
            # The second line is a surplus correction — the permission that
            # lets a person write one, held by the caller here.
            may_exceed_over_receipt=True,
        )

        lines = await _get_lines(real_async_db_session, correction.id)
        assert len(lines) == 2
        assert lines[0].line_number == 1
        assert lines[0].quantity == Decimal('-2')
        assert lines[1].line_number == 2
        assert lines[1].quantity == Decimal('3')


@pytest.mark.integration
class TestGetCorrectionsForDocument:
    @pytest.mark.asyncio
    async def test_no_corrections_returns_empty_list(
        self,
        real_async_db_session: AsyncSession,
        corr_org: Organization,
        corr_user: User,
    ) -> None:
        original = await _create_completed_document(
            real_async_db_session,
            corr_org,
            corr_user,
            doc_type='IN',
            line_specs=[{'quantity': Decimal('5'), 'done_quantity': Decimal('5')}],
        )

        assert (
            await get_corrections_for_document(
                real_async_db_session, original.id, corr_org.id
            )
            == []
        )

    @pytest.mark.asyncio
    async def test_lists_created_corrections(
        self,
        real_async_db_session: AsyncSession,
        corr_org: Organization,
        corr_user: User,
    ) -> None:
        original = await _create_completed_document(
            real_async_db_session,
            corr_org,
            corr_user,
            doc_type='IN',
            line_specs=[{'quantity': Decimal('10'), 'done_quantity': Decimal('10')}],
        )

        first = await create_correction(
            real_async_db_session,
            original.id,
            [{'original_line_number': 1, 'quantity_delta': Decimal('-1')}],
            corr_org.id,
            corr_user.id,
        )
        second = await create_correction(
            real_async_db_session,
            original.id,
            [{'original_line_number': 1, 'quantity_delta': Decimal('-2')}],
            corr_org.id,
            corr_user.id,
        )

        corrections = await get_corrections_for_document(
            real_async_db_session, original.id, corr_org.id
        )
        assert len(corrections) == 2
        assert {corr.number for corr in corrections} == {first.number, second.number}
