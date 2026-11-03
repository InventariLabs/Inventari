"""Direct integration tests for ``document_return_service``.

The existing ``test_return.py`` drives these functions through the FastAPI
``TestClient``, which runs the async app in a separate blocking-portal
thread. Coverage's tracer does not reliably record the statements after the
first ``await`` inside that worker thread, so those endpoint tests leave most
of this module around 24%. These tests call the service functions directly on
a real ``AsyncSession`` so the lines are attributed correctly.

Stock is not touched by this service: it only creates the DRAFT return
document and the ``returns`` relation. The actual stock/value effects are
applied later when the returned document is completed.
"""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.testing import ModuleTestHelper
from app.i18n import Language
from app.i18n.service import set_current_lang
from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.uom import Uom, UomCategory
from app.models.user import User
from app.modules.warehouse.document_pdf_service import build_pdf_context
from app.modules.warehouse.document_query_service import get_document
from app.modules.warehouse.document_return_service import create_return
from app.modules.warehouse.models import (
    Document,
    DocumentLine,
    DocumentRelation,
    DocumentStatus,
)

LineSpec = dict[str, Decimal | str]


@pytest.fixture
async def ret_org(real_async_db_session: AsyncSession) -> Organization:
    org = Organization(name='Return Ops Org', enabled_modules=['core', 'warehouse'])
    real_async_db_session.add(org)
    await real_async_db_session.flush()
    return org


@pytest.fixture
async def ret_user(real_async_db_session: AsyncSession, ret_org: Organization) -> User:
    return await ModuleTestHelper.create_user_async(
        real_async_db_session,
        ret_org,
        email='return-ops@example.com',
        role='admin',
    )


@pytest.fixture
async def ret_storage_type(real_async_db_session: AsyncSession) -> StorageType:
    st = StorageType(name='Warehouse', type_code='WAREHOUSE', behavior_mode='STOCK')
    real_async_db_session.add(st)
    await real_async_db_session.flush()
    return st


@pytest.fixture
async def ret_source_location(
    real_async_db_session: AsyncSession,
    ret_org: Organization,
    ret_user: User,
    ret_storage_type: StorageType,
) -> StorageLocation:
    loc = StorageLocation(
        name='Source Warehouse',
        organization_id=ret_org.id,
        storage_type_id=ret_storage_type.id,
        created_by=ret_user.id,
    )
    real_async_db_session.add(loc)
    await real_async_db_session.flush()
    return loc


@pytest.fixture
async def ret_target_location(
    real_async_db_session: AsyncSession,
    ret_org: Organization,
    ret_user: User,
    ret_storage_type: StorageType,
) -> StorageLocation:
    loc = StorageLocation(
        name='Target Warehouse',
        organization_id=ret_org.id,
        storage_type_id=ret_storage_type.id,
        created_by=ret_user.id,
    )
    real_async_db_session.add(loc)
    await real_async_db_session.flush()
    return loc


async def _create_completed_document(
    db: AsyncSession,
    org: Organization,
    user: User,
    *,
    doc_type: str,
    line_specs: list[LineSpec],
    source_location_id: uuid.UUID | None = None,
    target_location_id: uuid.UUID | None = None,
    status: str = DocumentStatus.COMPLETED.value,
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
                # Read in the order the document numbers its lines; a bare
                # select leaves that to the database, and the assertions below
                # index into the result.
                .order_by(DocumentLine.line_number)
            )
        ).all()
    )


@pytest.mark.integration
class TestCreateReturn:
    @pytest.mark.asyncio
    async def test_return_of_in_creates_out_and_swaps_locations(
        self,
        real_async_db_session: AsyncSession,
        ret_org: Organization,
        ret_user: User,
        ret_source_location: StorageLocation,
        ret_target_location: StorageLocation,
    ) -> None:
        original = await _create_completed_document(
            real_async_db_session,
            ret_org,
            ret_user,
            doc_type='IN',
            line_specs=[{'quantity': Decimal('5'), 'done_quantity': Decimal('5')}],
            source_location_id=ret_source_location.id,
            target_location_id=ret_target_location.id,
        )

        returned = await create_return(
            real_async_db_session,
            original.id,
            [
                {
                    'original_line_number': 1,
                    'return_quantity': Decimal('3'),
                    'reason': 'Customer rejected 3 units',
                }
            ],
            ret_org.id,
            ret_user.id,
            notes='Customer return',
        )

        assert returned.type == 'OUT'
        assert returned.status == DocumentStatus.DRAFT.value
        assert returned.source_location_id == ret_target_location.id
        assert returned.target_location_id == ret_source_location.id
        assert returned.notes == 'Customer return'

        lines = await _get_lines(real_async_db_session, returned.id)
        assert len(lines) == 1
        assert lines[0].quantity == Decimal('3')
        assert lines[0].expected_quantity == Decimal('3')
        assert lines[0].done_quantity == Decimal('0')
        assert lines[0].notes == 'Customer rejected 3 units'

        relations = (
            await real_async_db_session.scalars(
                select(DocumentRelation).where(
                    DocumentRelation.source_document_id == original.id,
                    DocumentRelation.target_document_id == returned.id,
                )
            )
        ).all()
        assert len(relations) == 1
        assert relations[0].relation_type == 'returns'

    @pytest.mark.asyncio
    async def test_return_of_int_creates_int_and_swaps_locations(
        self,
        real_async_db_session: AsyncSession,
        ret_org: Organization,
        ret_user: User,
        ret_source_location: StorageLocation,
        ret_target_location: StorageLocation,
    ) -> None:
        original = await _create_completed_document(
            real_async_db_session,
            ret_org,
            ret_user,
            doc_type='INT',
            line_specs=[{'quantity': Decimal('5'), 'done_quantity': Decimal('5')}],
            source_location_id=ret_source_location.id,
            target_location_id=ret_target_location.id,
        )

        returned = await create_return(
            real_async_db_session,
            original.id,
            [{'original_line_number': 1, 'return_quantity': Decimal('2')}],
            ret_org.id,
            ret_user.id,
        )

        assert returned.type == 'INT'
        assert returned.source_location_id == ret_target_location.id
        assert returned.target_location_id == ret_source_location.id

    @pytest.mark.asyncio
    async def test_return_of_out_creates_in_coming_back_where_it_left(
        self,
        real_async_db_session: AsyncSession,
        ret_org: Organization,
        ret_user: User,
        ret_source_location: StorageLocation,
        ret_target_location: StorageLocation,
    ) -> None:
        original = await _create_completed_document(
            real_async_db_session,
            ret_org,
            ret_user,
            doc_type='OUT',
            line_specs=[{'quantity': Decimal('5'), 'done_quantity': Decimal('5')}],
            source_location_id=ret_source_location.id,
            target_location_id=ret_target_location.id,
        )

        returned = await create_return(
            real_async_db_session,
            original.id,
            [{'original_line_number': 1, 'return_quantity': Decimal('2')}],
            ret_org.id,
            ret_user.id,
        )

        # The goods go back the way they came: the receipt comes in to the
        # place the delivery took them from.
        assert returned.type == 'IN'
        assert returned.source_location_id == ret_target_location.id
        assert returned.target_location_id == ret_source_location.id

    @pytest.mark.asyncio
    async def test_return_original_not_found_raises(
        self,
        real_async_db_session: AsyncSession,
        ret_org: Organization,
        ret_user: User,
    ) -> None:
        with pytest.raises(ValueError, match='Document not found'):
            await create_return(
                real_async_db_session,
                uuid.uuid4(),
                [{'original_line_number': 1, 'return_quantity': Decimal('1')}],
                ret_org.id,
                ret_user.id,
            )

    @pytest.mark.asyncio
    async def test_return_requires_completed_original(
        self,
        real_async_db_session: AsyncSession,
        ret_org: Organization,
        ret_user: User,
        ret_target_location: StorageLocation,
    ) -> None:
        original = await _create_completed_document(
            real_async_db_session,
            ret_org,
            ret_user,
            doc_type='IN',
            line_specs=[{'quantity': Decimal('5'), 'done_quantity': Decimal('0')}],
            target_location_id=ret_target_location.id,
            status=DocumentStatus.DRAFT.value,
        )

        with pytest.raises(
            ValueError, match='only be made against a completed document'
        ):
            await create_return(
                real_async_db_session,
                original.id,
                [{'original_line_number': 1, 'return_quantity': Decimal('1')}],
                ret_org.id,
                ret_user.id,
            )

    @pytest.mark.asyncio
    async def test_return_non_eligible_type_raises(
        self,
        real_async_db_session: AsyncSession,
        ret_org: Organization,
        ret_user: User,
        ret_target_location: StorageLocation,
    ) -> None:
        original = await _create_completed_document(
            real_async_db_session,
            ret_org,
            ret_user,
            doc_type='INTERNAL_IN',
            line_specs=[{'quantity': Decimal('5'), 'done_quantity': Decimal('5')}],
            target_location_id=ret_target_location.id,
        )

        with pytest.raises(ValueError, match='Returns can only be made against'):
            await create_return(
                real_async_db_session,
                original.id,
                [{'original_line_number': 1, 'return_quantity': Decimal('1')}],
                ret_org.id,
                ret_user.id,
            )

    @pytest.mark.asyncio
    async def test_return_empty_lines_raises(
        self,
        real_async_db_session: AsyncSession,
        ret_org: Organization,
        ret_user: User,
        ret_target_location: StorageLocation,
    ) -> None:
        original = await _create_completed_document(
            real_async_db_session,
            ret_org,
            ret_user,
            doc_type='IN',
            line_specs=[{'quantity': Decimal('5'), 'done_quantity': Decimal('5')}],
            target_location_id=ret_target_location.id,
        )

        with pytest.raises(ValueError, match='at least one line'):
            await create_return(
                real_async_db_session,
                original.id,
                [],
                ret_org.id,
                ret_user.id,
            )

    @pytest.mark.asyncio
    async def test_return_unknown_line_number_raises(
        self,
        real_async_db_session: AsyncSession,
        ret_org: Organization,
        ret_user: User,
        ret_target_location: StorageLocation,
    ) -> None:
        original = await _create_completed_document(
            real_async_db_session,
            ret_org,
            ret_user,
            doc_type='IN',
            line_specs=[{'quantity': Decimal('5'), 'done_quantity': Decimal('5')}],
            target_location_id=ret_target_location.id,
        )

        with pytest.raises(ValueError, match='does not exist in document'):
            await create_return(
                real_async_db_session,
                original.id,
                [{'original_line_number': 999, 'return_quantity': Decimal('1')}],
                ret_org.id,
                ret_user.id,
            )

    @pytest.mark.asyncio
    async def test_return_nonpositive_quantity_raises(
        self,
        real_async_db_session: AsyncSession,
        ret_org: Organization,
        ret_user: User,
        ret_target_location: StorageLocation,
    ) -> None:
        original = await _create_completed_document(
            real_async_db_session,
            ret_org,
            ret_user,
            doc_type='IN',
            line_specs=[{'quantity': Decimal('5'), 'done_quantity': Decimal('5')}],
            target_location_id=ret_target_location.id,
        )

        with pytest.raises(ValueError, match='must be greater than zero'):
            await create_return(
                real_async_db_session,
                original.id,
                [{'original_line_number': 1, 'return_quantity': Decimal('0')}],
                ret_org.id,
                ret_user.id,
            )

        with pytest.raises(ValueError, match='must be greater than zero'):
            await create_return(
                real_async_db_session,
                original.id,
                [{'original_line_number': 1, 'return_quantity': Decimal('-1')}],
                ret_org.id,
                ret_user.id,
            )

    @pytest.mark.asyncio
    async def test_return_quantity_exceeding_done_raises(
        self,
        real_async_db_session: AsyncSession,
        ret_org: Organization,
        ret_user: User,
        ret_target_location: StorageLocation,
    ) -> None:
        original = await _create_completed_document(
            real_async_db_session,
            ret_org,
            ret_user,
            doc_type='IN',
            line_specs=[{'quantity': Decimal('5'), 'done_quantity': Decimal('5')}],
            target_location_id=ret_target_location.id,
        )

        # The bound is what the line has left, which for a line nobody has
        # touched is everything it executed.
        with pytest.raises(ValueError, match='is more than what is left of line'):
            await create_return(
                real_async_db_session,
                original.id,
                [{'original_line_number': 1, 'return_quantity': Decimal('99')}],
                ret_org.id,
                ret_user.id,
            )

    @pytest.mark.asyncio
    async def test_the_refusal_states_its_quantities_with_the_lines_unit(
        self,
        real_async_db_session: AsyncSession,
        ret_org: Organization,
        ret_user: User,
        ret_target_location: StorageLocation,
    ) -> None:
        category = UomCategory(name='Mass', organization_id=ret_org.id)
        real_async_db_session.add(category)
        await real_async_db_session.flush()
        kilo = Uom(
            organization_id=ret_org.id,
            category_id=category.id,
            name='Kilogram',
            symbol='kg',
            rounding=Decimal('0.001'),
        )
        real_async_db_session.add(kilo)
        await real_async_db_session.flush()
        original = await _create_completed_document(
            real_async_db_session,
            ret_org,
            ret_user,
            doc_type='IN',
            line_specs=[{'quantity': Decimal('10'), 'done_quantity': Decimal('10')}],
            target_location_id=ret_target_location.id,
        )
        original.lines[0].uom_id = kilo.id
        await real_async_db_session.flush()

        # The store keeps three decimals ("10.000"); a reader never typed
        # them and the line is counted in kilograms.
        with pytest.raises(
            ValueError,
            match=r'A return of 99 kg is more than what is left of line 1 '
            r'\(10 kg of 10 kg\)',
        ):
            await create_return(
                real_async_db_session,
                original.id,
                [{'original_line_number': 1, 'return_quantity': Decimal('99')}],
                ret_org.id,
                ret_user.id,
            )

    @pytest.mark.asyncio
    async def test_return_exact_done_quantity_is_accepted(
        self,
        real_async_db_session: AsyncSession,
        ret_org: Organization,
        ret_user: User,
        ret_target_location: StorageLocation,
    ) -> None:
        original = await _create_completed_document(
            real_async_db_session,
            ret_org,
            ret_user,
            doc_type='IN',
            line_specs=[{'quantity': Decimal('5'), 'done_quantity': Decimal('5')}],
            target_location_id=ret_target_location.id,
        )

        returned = await create_return(
            real_async_db_session,
            original.id,
            [{'original_line_number': 1, 'return_quantity': Decimal('5')}],
            ret_org.id,
            ret_user.id,
        )

        lines = await _get_lines(real_async_db_session, returned.id)
        assert lines[0].quantity == Decimal('5')

    @pytest.mark.asyncio
    @pytest.mark.parametrize('lang', ['en', 'pl', 'de', 'fr', 'es'])
    async def test_return_without_a_note_stores_no_note(
        self,
        lang: Language,
        real_async_db_session: AsyncSession,
        ret_org: Organization,
        ret_user: User,
        ret_target_location: StorageLocation,
    ) -> None:
        """An empty note stays empty whichever language asked for the return.

        The server used to write a sentence here: first English for every
        reader, then the creator's request language — and a return created
        from an English session still read "Return for IN/…" on a Polish
        screen and printout. The pointer to the original is the stored
        ``returns`` relation, rendered at read time, so no sentence is
        written at all.
        """
        original = await _create_completed_document(
            real_async_db_session,
            ret_org,
            ret_user,
            doc_type='IN',
            line_specs=[{'quantity': Decimal('5'), 'done_quantity': Decimal('5')}],
            target_location_id=ret_target_location.id,
        )

        set_current_lang(lang)
        try:
            returned = await create_return(
                real_async_db_session,
                original.id,
                [{'original_line_number': 1, 'return_quantity': Decimal('1')}],
                ret_org.id,
                ret_user.id,
            )
        finally:
            set_current_lang('en')

        assert returned.notes is None

    @pytest.mark.asyncio
    async def test_read_document_carries_the_return_pointer(
        self,
        real_async_db_session: AsyncSession,
        ret_org: Organization,
        ret_user: User,
        ret_target_location: StorageLocation,
    ) -> None:
        """A reader gets the document a return reverses, and its number.

        That pointer is what the screen and the printout name the original
        from, in the reader's own language — the return itself stores no
        note saying what it is. Both are also what the print context
        renders, so the paper and the screen agree.
        """
        original = await _create_completed_document(
            real_async_db_session,
            ret_org,
            ret_user,
            doc_type='IN',
            line_specs=[{'quantity': Decimal('5'), 'done_quantity': Decimal('5')}],
            target_location_id=ret_target_location.id,
        )
        returned = await create_return(
            real_async_db_session,
            original.id,
            [{'original_line_number': 1, 'return_quantity': Decimal('1')}],
            ret_org.id,
            ret_user.id,
        )

        loaded = await get_document(real_async_db_session, ret_org.id, returned.id)
        assert loaded is not None
        assert loaded.return_of_id == original.id  # type: ignore[attr-defined]
        assert loaded.return_of_number == original.number  # type: ignore[attr-defined]

        context = build_pdf_context(loaded, None, lang='pl')
        assert context['return_of_number'] == original.number
        assert context['labels']['return_of'] == 'Zwrot do'

        plain = await _create_completed_document(
            real_async_db_session,
            ret_org,
            ret_user,
            doc_type='IN',
            line_specs=[{'quantity': Decimal('5'), 'done_quantity': Decimal('5')}],
            target_location_id=ret_target_location.id,
        )
        loaded_plain = await get_document(real_async_db_session, ret_org.id, plain.id)
        assert loaded_plain is not None
        assert getattr(loaded_plain, 'return_of_id', None) is None
        assert getattr(loaded_plain, 'return_of_number', None) is None

    @pytest.mark.asyncio
    async def test_return_multiple_lines(
        self,
        real_async_db_session: AsyncSession,
        ret_org: Organization,
        ret_user: User,
        ret_target_location: StorageLocation,
    ) -> None:
        original = await _create_completed_document(
            real_async_db_session,
            ret_org,
            ret_user,
            doc_type='IN',
            line_specs=[
                {'quantity': Decimal('5'), 'done_quantity': Decimal('5')},
                {'quantity': Decimal('10'), 'done_quantity': Decimal('10')},
            ],
            target_location_id=ret_target_location.id,
        )

        returned = await create_return(
            real_async_db_session,
            original.id,
            [
                {'original_line_number': 1, 'return_quantity': Decimal('2')},
                {'original_line_number': 2, 'return_quantity': Decimal('3')},
            ],
            ret_org.id,
            ret_user.id,
        )

        lines = await _get_lines(real_async_db_session, returned.id)
        assert len(lines) == 2
        assert lines[0].line_number == 1
        assert lines[0].quantity == Decimal('2')
        assert lines[1].line_number == 2
        assert lines[1].quantity == Decimal('3')
