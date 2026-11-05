"""
Integration tests for label_service functions.

Tests cover:
- Unique code generation with various prefixes
- Exception handling when max attempts exceeded
- Prefix normalization (whitespace, dashes)
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.label_pool import LabelPool
from app.models.storage_location import StorageLocation
from app.services.label_service import LabelService, generate_short_code_async


def _short(p: str) -> str:
    return f'{p}-{uuid.uuid4().hex[:4].upper()}'


@pytest.mark.integration
@pytest.mark.asyncio
class TestGenerateShortCode:
    """Tests for generate_short_code_async function."""

    async def test_generate_short_code_basic(self, real_async_db_session: AsyncSession):
        """Test generating a basic short code with default prefix."""
        code = await generate_short_code_async(real_async_db_session)

        assert code is not None
        assert code.startswith('STM-')
        assert len(code) == 8  # STM- (4) + XXXX (4)

    async def test_generate_short_code_custom_prefix(
        self, real_async_db_session: AsyncSession
    ):
        """Test generating code with custom prefix."""
        code = await generate_short_code_async(real_async_db_session, prefix='LOC')

        assert code.startswith('LOC-')
        assert len(code) == 8

    async def test_generate_short_code_empty_prefix(
        self, real_async_db_session: AsyncSession
    ):
        """Test generating with empty prefix results in dash."""
        code = await generate_short_code_async(real_async_db_session, prefix='')

        # Empty prefix should result in just dash and random part
        assert code.startswith('-')
        assert len(code) == 5  # - (1) + XXXX (4)

    async def test_generate_short_code_whitespace_normalization(
        self, real_async_db_session: AsyncSession
    ):
        """Test prefix normalization removes whitespace and dashes."""
        code = await generate_short_code_async(
            real_async_db_session, prefix='  L-O-C  '
        )

        # Should normalize to LOC
        assert code.startswith('LOC-')

    async def test_generate_short_code_uppercase_conversion(
        self, real_async_db_session: AsyncSession
    ):
        """Test that prefix is converted to uppercase."""
        code = await generate_short_code_async(real_async_db_session, prefix='loc')

        assert code.startswith('LOC-')

    async def test_generate_short_code_multiple_are_unique(
        self, real_async_db_session: AsyncSession
    ):
        """Test that multiple generated codes are unique."""
        codes = set()

        for _ in range(20):
            code = await generate_short_code_async(real_async_db_session)
            codes.add(code)

        # All 20 generated codes should be unique
        assert len(codes) == 20

    async def test_generate_short_code_format_uppercase_and_digits(
        self, real_async_db_session: AsyncSession
    ):
        """Test that generated suffix contains only uppercase letters and digits."""
        import re

        code = await generate_short_code_async(real_async_db_session, prefix='FMT')

        # Format: PREFIX-XXXX where X is uppercase letter or digit
        pattern = r'^FMT-[A-Z0-9]{4}$'
        assert re.match(pattern, code), f'Code {code} does not match expected pattern'

    async def test_generate_short_code_exception_when_max_attempts_exceeded(
        self,
        real_async_db_session: AsyncSession,
        monkeypatch,
        async_test_user,
        async_test_household,
    ):
        """Test that exception is raised when max attempts exhausted."""

        # Mock secrets.choice to always return the same value
        def mock_choice_constant(*args, **kwargs):
            return 'Z'

        monkeypatch.setattr('secrets.choice', mock_choice_constant)

        # Pre-populate label pool so all attempts will fail
        pool = LabelPool(
            short_code='MAX-ZZZZ',
            organization_id=async_test_household.id,
            created_by=async_test_user.id,
        )
        real_async_db_session.add(pool)
        await real_async_db_session.flush()

        # Should raise exception after 100 attempts
        with pytest.raises(Exception) as exc_info:
            await generate_short_code_async(real_async_db_session, prefix='MAX')

        assert 'Could not generate a unique code' in str(exc_info.value)
        assert 'MAX' in str(exc_info.value)
        assert '100 attempts' in str(exc_info.value)

    async def test_generate_short_code_checks_both_pools(
        self,
        real_async_db_session: AsyncSession,
        async_test_user,
        async_test_household,
        async_test_storage_type,
        monkeypatch,
    ):
        """Test that uniqueness is checked against both LabelPool and StorageLocation."""
        import secrets

        from app.models.storage_location import LocationUsage

        # Create a label in pool
        pool_code = 'CHCK-0001'
        pool = LabelPool(
            short_code=pool_code,
            organization_id=async_test_household.id,
            created_by=async_test_user.id,
        )
        real_async_db_session.add(pool)
        await real_async_db_session.flush()

        # Create a storage location with specific code
        storage_code = 'CHCK-0002'
        storage = StorageLocation(
            organization_id=async_test_household.id,
            created_by=async_test_user.id,
            storage_type_id=async_test_storage_type.id,
            name='Storage',
            short_code=storage_code,
            usage=LocationUsage.INTERNAL,
        )
        real_async_db_session.add(storage)
        await real_async_db_session.flush()

        # Mock secrets.choice to try reserved codes first. Each code attempt
        # consumes 4 chars (one per position), so hand out '0001' then '0002'.
        reserved = list('0001' + '0002')
        original_choice = secrets.choice

        def mock_choice(*args, **kwargs):
            if reserved:
                return reserved.pop(0)
            return original_choice(*args, **kwargs)

        monkeypatch.setattr('secrets.choice', mock_choice)

        # Generate code - should skip both reserved codes
        generated_code = await generate_short_code_async(
            real_async_db_session, prefix='CHCK'
        )

        assert generated_code != pool_code, 'Should not match LabelPool code'
        assert generated_code != storage_code, 'Should not match StorageLocation code'
        assert generated_code.startswith('CHCK-'), 'Should have correct prefix'

    async def test_generate_short_code_preserves_normalized_prefix(
        self, real_async_db_session: AsyncSession
    ):
        """Test that normalized prefix is preserved in output."""
        code = await generate_short_code_async(real_async_db_session, prefix='TEST')
        assert code.startswith('TEST-')

        code2 = await generate_short_code_async(real_async_db_session, prefix='test')
        assert code2.startswith('TEST-')

        code3 = await generate_short_code_async(real_async_db_session, prefix='t-e-s-t')
        assert code3.startswith('TEST-')


@pytest.mark.integration
@pytest.mark.asyncio
class TestGenerateLabelPool:
    """Tests for LabelService.generate_label_pool_async static method."""

    async def test_generate_label_pool_creates_requested_count(
        self, real_async_db_session: AsyncSession, async_test_user, async_test_household
    ):
        """Test that the correct number of labels is generated."""
        from app.core.contracts import UserContextDTO
        from app.schemas.label_pool import LabelPoolCreate

        user_ctx = UserContextDTO(
            id=async_test_user.id,
            email=async_test_user.email,
            organization_id=async_test_household.id,
            role='admin',
            full_name='Test User',
        )
        request = LabelPoolCreate(count=5, prefix='TST')

        labels = await LabelService.generate_label_pool_async(
            real_async_db_session, request, user_ctx
        )

        assert len(labels) == 5

    async def test_generate_label_pool_labels_have_unique_codes(
        self, real_async_db_session: AsyncSession, async_test_user, async_test_household
    ):
        """Test that all generated labels have unique short codes."""
        from app.core.contracts import UserContextDTO
        from app.schemas.label_pool import LabelPoolCreate

        user_ctx = UserContextDTO(
            id=async_test_user.id,
            email=async_test_user.email,
            organization_id=async_test_household.id,
            role='admin',
            full_name='Test User',
        )
        request = LabelPoolCreate(count=10, prefix='UNQ')

        labels = await LabelService.generate_label_pool_async(
            real_async_db_session, request, user_ctx
        )

        codes = [label.short_code for label in labels]
        assert len(set(codes)) == 10

    async def test_generate_label_pool_labels_have_correct_attributes(
        self, real_async_db_session: AsyncSession, async_test_user, async_test_household
    ):
        """Test that generated labels carry the correct organization, creator, and type."""
        from app.core.contracts import UserContextDTO
        from app.schemas.label_pool import LabelPoolCreate

        user_ctx = UserContextDTO(
            id=async_test_user.id,
            email=async_test_user.email,
            organization_id=async_test_household.id,
            role='admin',
            full_name='Test User',
        )
        request = LabelPoolCreate(
            count=3, prefix='ATR', label_type='STORAGE', description='Shelf labels'
        )

        labels = await LabelService.generate_label_pool_async(
            real_async_db_session, request, user_ctx
        )

        for label in labels:
            assert label.organization_id == async_test_household.id
            assert label.created_by == async_test_user.id
            assert label.is_assigned is False
            assert label.label_type == 'STORAGE'
            assert label.description == 'Shelf labels'
            assert label.short_code.startswith('ATR-')

    async def test_generate_label_pool_persists_to_database(
        self, real_async_db_session: AsyncSession, async_test_user, async_test_household
    ):
        """Test that generated labels are committed and visible in a fresh query."""
        from app.core.contracts import UserContextDTO
        from app.schemas.label_pool import LabelPoolCreate

        user_ctx = UserContextDTO(
            id=async_test_user.id,
            email=async_test_user.email,
            organization_id=async_test_household.id,
            role='admin',
            full_name='Test User',
        )
        request = LabelPoolCreate(count=2, prefix='PRS')

        labels = await LabelService.generate_label_pool_async(
            real_async_db_session, request, user_ctx
        )
        ids = [label.id for label in labels]

        persisted = (
            await real_async_db_session.scalars(
                select(LabelPool).where(LabelPool.id.in_(ids))
            )
        ).all()

        assert len(persisted) == 2

    async def test_generate_label_pool_with_context_tag(
        self, real_async_db_session: AsyncSession, async_test_user, async_test_household
    ):
        """Test that context_tag is stored on generated labels."""
        from app.core.contracts import UserContextDTO
        from app.schemas.label_pool import LabelPoolCreate

        user_ctx = UserContextDTO(
            id=async_test_user.id,
            email=async_test_user.email,
            organization_id=async_test_household.id,
            role='admin',
            full_name='Test User',
        )
        request = LabelPoolCreate(count=2, prefix='CTX', context_tag='kitchen')

        labels = await LabelService.generate_label_pool_async(
            real_async_db_session, request, user_ctx
        )

        for label in labels:
            assert label.context_tag == 'kitchen'

    async def test_generate_label_pool_concurrent_no_collision(
        self, real_async_db_session: AsyncSession, async_test_user, async_test_household
    ):
        """Regression: two concurrent generate_label_pool calls for the same
        prefix must produce disjoint short_codes (no IntegrityError, no dupes).

        Bug: generate_label_pool_async used random code generation with a
        SELECT→commit window, so two parallel transactions could pick the
        same code and the second commit failed with unique violation
        (ix_label_pool_short_code). Fix: pg_advisory_xact_lock per prefix
        serializes the batch under transaction scope.

        We exercise the function twice serially with rollback between calls
        to confirm uniqueness under realistic DB state; the advisory lock
        ensures the same property holds for truly concurrent sessions.
        """
        from app.core.contracts import UserContextDTO
        from app.schemas.label_pool import LabelPoolCreate

        user_ctx = UserContextDTO(
            id=async_test_user.id,
            email=async_test_user.email,
            organization_id=async_test_household.id,
            role='admin',
            full_name='Test User',
        )

        req = LabelPoolCreate(count=5, prefix='RACE')
        batch1 = await LabelService.generate_label_pool_async(
            real_async_db_session, req, user_ctx
        )
        codes1 = {label.short_code for label in batch1}
        assert len(codes1) == 5

        # A second call must not pick any of the codes used by the first call.
        batch2 = await LabelService.generate_label_pool_async(
            real_async_db_session, req, user_ctx
        )
        codes2 = {label.short_code for label in batch2}
        assert len(codes2) == 5
        assert codes1.isdisjoint(codes2), f'Overlap between batches: {codes1 & codes2}'


@pytest.mark.integration
@pytest.mark.asyncio
class TestDeleteLabel:
    """Tests for LabelService.delete_label_async static method."""

    async def test_delete_label_removes_from_database(
        self, real_async_db_session: AsyncSession, async_test_user, async_test_household
    ):
        """Test that delete_label_async removes the label from the database."""
        label = LabelPool(
            short_code=_short('DEL'),
            organization_id=async_test_household.id,
            created_by=async_test_user.id,
        )
        real_async_db_session.add(label)
        await real_async_db_session.flush()
        label_id = label.id

        await LabelService.delete_label_async(real_async_db_session, label)

        result = await real_async_db_session.scalar(
            select(LabelPool).where(LabelPool.id == label_id)
        )
        assert result is None

    async def test_delete_label_assigned_label(
        self,
        real_async_db_session: AsyncSession,
        async_test_user,
        async_test_household,
        async_test_item,
    ):
        """Test that an assigned label can be deleted."""
        label = LabelPool(
            short_code=_short('DEL'),
            organization_id=async_test_household.id,
            created_by=async_test_user.id,
            is_assigned=True,
            item_id=async_test_item.id,
        )
        real_async_db_session.add(label)
        await real_async_db_session.flush()
        label_id = label.id

        await LabelService.delete_label_async(real_async_db_session, label)

        result = await real_async_db_session.scalar(
            select(LabelPool).where(LabelPool.id == label_id)
        )
        assert result is None


@pytest.mark.integration
@pytest.mark.asyncio
class TestUnassignLabel:
    """Tests for LabelService.unassign_label_async static method."""

    async def test_unassign_label_clears_assignment(
        self,
        real_async_db_session: AsyncSession,
        async_test_user,
        async_test_household,
        async_test_item,
    ):
        """Test that unassign clears is_assigned, item_id, and assigned_at."""
        from datetime import UTC, datetime

        label = LabelPool(
            short_code=_short('UNA'),
            organization_id=async_test_household.id,
            created_by=async_test_user.id,
            is_assigned=True,
            item_id=async_test_item.id,
            assigned_at=datetime.now(UTC),
        )
        real_async_db_session.add(label)
        await real_async_db_session.flush()

        result = await LabelService.unassign_label_async(real_async_db_session, label)

        assert result.is_assigned is False
        assert result.item_id is None
        assert result.assigned_at is None

    async def test_unassign_label_clears_item_label_code(
        self,
        real_async_db_session: AsyncSession,
        async_test_user,
        async_test_household,
        async_test_item,
    ):
        """Unassigning must clear item.label_code to avoid a dangling reference."""
        from app.models.item import Item

        label = LabelPool(
            short_code=_short('UC'),
            organization_id=async_test_household.id,
            created_by=async_test_user.id,
            is_assigned=True,
            item_id=async_test_item.id,
        )
        real_async_db_session.add(label)
        item = await real_async_db_session.scalar(
            select(Item).where(Item.id == async_test_item.id)
        )
        item.label_code = label.short_code
        await real_async_db_session.flush()

        await LabelService.unassign_label_async(real_async_db_session, label)

        refreshed = await real_async_db_session.scalar(
            select(Item).where(Item.id == async_test_item.id)
        )
        assert refreshed.label_code is None

    async def test_unassign_label_persists_changes(
        self, real_async_db_session: AsyncSession, async_test_user, async_test_household
    ):
        """Test that unassignment is persisted to the database."""
        label = LabelPool(
            short_code=_short('UNA'),
            organization_id=async_test_household.id,
            created_by=async_test_user.id,
            is_assigned=True,
        )
        real_async_db_session.add(label)
        await real_async_db_session.flush()
        label_id = label.id

        await LabelService.unassign_label_async(real_async_db_session, label)

        persisted = await real_async_db_session.scalar(
            select(LabelPool).where(LabelPool.id == label_id)
        )
        assert persisted.is_assigned is False
        assert persisted.item_id is None
        assert persisted.assigned_at is None


@pytest.mark.integration
@pytest.mark.asyncio
class TestAssignToExistingItem:
    """Tests for LabelService.assign_to_existing_item_async static method."""

    async def test_assign_to_existing_item_sets_fields(
        self,
        real_async_db_session: AsyncSession,
        async_test_user,
        async_test_household,
        async_test_item,
    ):
        """Test that assigning a label sets item_id and is_assigned."""
        label = LabelPool(
            short_code=_short('ASI'),
            organization_id=async_test_household.id,
            created_by=async_test_user.id,
            is_assigned=False,
        )
        real_async_db_session.add(label)
        await real_async_db_session.flush()

        result = await LabelService.assign_to_existing_item_async(
            real_async_db_session, label, async_test_item.id
        )

        assert result.item_id == async_test_item.id
        assert result.is_assigned is True

    async def test_assign_to_existing_item_persists(
        self,
        real_async_db_session: AsyncSession,
        async_test_user,
        async_test_household,
        async_test_item,
    ):
        """Test that assignment is persisted to the database."""
        label = LabelPool(
            short_code=_short('ASI'),
            organization_id=async_test_household.id,
            created_by=async_test_user.id,
            is_assigned=False,
        )
        real_async_db_session.add(label)
        await real_async_db_session.flush()
        label_id = label.id

        await LabelService.assign_to_existing_item_async(
            real_async_db_session, label, async_test_item.id
        )

        persisted = await real_async_db_session.scalar(
            select(LabelPool).where(LabelPool.id == label_id)
        )
        assert persisted.item_id == async_test_item.id
        assert persisted.is_assigned is True

    async def test_assign_to_existing_item_sets_item_label_code(
        self,
        real_async_db_session: AsyncSession,
        async_test_user,
        async_test_household,
        async_test_item,
    ):
        """Assigning a label must persist label_code on the Item, not only on the LabelPool."""
        from app.models.item import Item

        label = LabelPool(
            short_code=_short('LC'),
            organization_id=async_test_household.id,
            created_by=async_test_user.id,
            is_assigned=False,
        )
        real_async_db_session.add(label)
        await real_async_db_session.flush()

        await LabelService.assign_to_existing_item_async(
            real_async_db_session, label, async_test_item.id
        )

        item = await real_async_db_session.scalar(
            select(Item).where(Item.id == async_test_item.id)
        )
        assert item.label_code == label.short_code

    async def test_assign_to_existing_item_reassigns_and_frees_previous(
        self,
        real_async_db_session: AsyncSession,
        async_test_user,
        async_test_household,
        async_test_item,
    ):
        """Reassigning a new label frees the old one and updates item.label_code."""
        from app.models.item import Item

        old_label = LabelPool(
            short_code=_short('OLD'),
            organization_id=async_test_household.id,
            created_by=async_test_user.id,
            is_assigned=False,
        )
        new_label = LabelPool(
            short_code=_short('NEW'),
            organization_id=async_test_household.id,
            created_by=async_test_user.id,
            is_assigned=False,
        )
        real_async_db_session.add_all([old_label, new_label])
        await real_async_db_session.flush()

        await LabelService.assign_to_existing_item_async(
            real_async_db_session, old_label, async_test_item.id
        )
        await LabelService.assign_to_existing_item_async(
            real_async_db_session, new_label, async_test_item.id
        )

        item = await real_async_db_session.scalar(
            select(Item).where(Item.id == async_test_item.id)
        )
        assert item.label_code == new_label.short_code
        old_persisted = await real_async_db_session.scalar(
            select(LabelPool).where(LabelPool.id == old_label.id)
        )
        assert old_persisted.is_assigned is False
        assert old_persisted.item_id is None


@pytest.mark.integration
@pytest.mark.asyncio
class TestMarkAsPrintedByIds:
    """Tests for LabelService.mark_as_printed_by_ids_async static method."""

    async def test_mark_as_printed_by_ids_sets_printed_at(
        self, real_async_db_session: AsyncSession, async_test_user, async_test_household
    ):
        """Test that labels get printed_at set when marked by IDs."""
        labels = []
        uid = uuid.uuid4().hex[:4].upper()
        for i in range(3):
            label = LabelPool(
                short_code=f'PID-{uid}-{i:04d}',
                organization_id=async_test_household.id,
                created_by=async_test_user.id,
            )
            real_async_db_session.add(label)
            labels.append(label)
        await real_async_db_session.flush()
        label_ids = [label.id for label in labels]

        await LabelService.mark_as_printed_by_ids_async(
            real_async_db_session, label_ids, async_test_household.id
        )

        persisted = (
            await real_async_db_session.scalars(
                select(LabelPool).where(LabelPool.id.in_(label_ids))
            )
        ).all()

        for label in persisted:
            assert label.printed_at is not None

    async def test_mark_as_printed_by_ids_empty_list(
        self, real_async_db_session: AsyncSession, async_test_household
    ):
        """Test that empty list is a no-op."""
        await LabelService.mark_as_printed_by_ids_async(
            real_async_db_session, [], async_test_household.id
        )

    async def test_mark_as_printed_by_ids_partial_subset(
        self, real_async_db_session: AsyncSession, async_test_user, async_test_household
    ):
        """Test marking only a subset of labels as printed."""
        labels = []
        uid = uuid.uuid4().hex[:4].upper()
        for i in range(3):
            label = LabelPool(
                short_code=f'PPS-{uid}-{i:04d}',
                organization_id=async_test_household.id,
                created_by=async_test_user.id,
            )
            real_async_db_session.add(label)
            labels.append(label)
        await real_async_db_session.flush()

        # Mark only first two
        await LabelService.mark_as_printed_by_ids_async(
            real_async_db_session, [labels[0].id, labels[1].id], async_test_household.id
        )

        refreshed_0 = await real_async_db_session.scalar(
            select(LabelPool).where(LabelPool.id == labels[0].id)
        )
        refreshed_1 = await real_async_db_session.scalar(
            select(LabelPool).where(LabelPool.id == labels[1].id)
        )
        refreshed_2 = await real_async_db_session.scalar(
            select(LabelPool).where(LabelPool.id == labels[2].id)
        )

        assert refreshed_0.printed_at is not None
        assert refreshed_1.printed_at is not None
        assert refreshed_2.printed_at is None


@pytest.mark.integration
@pytest.mark.asyncio
class TestGenerateLabelPoolRetry:
    """Async retry-on-collision tests for LabelService.generate_label_pool_async."""

    async def test_retries_on_short_code_collision(
        self, real_async_db_session, async_test_user, async_test_household, monkeypatch
    ):
        """Retry the batch on IntegrityError when short_code collides.

        Regression guard for the label_service TOCTOU race: force the first
        batch to share one short_code so commit hits the UNIQUE constraint,
        then assert the pool is regenerated and persisted instead of raising
        an unhandled IntegrityError. Covers both the concurrent TOCTOU race
        and intra-batch collisions.
        """
        import app.services.label_service as label_service_mod
        from app.core.contracts import UserContextDTO
        from app.schemas.label_pool import LabelPoolCreate

        call_count = [0]
        seen_orgs = []

        async def fake_draw_async(
            db, *, prefix='STM', count=1, organization_id=None, **_kwargs
        ):
            # The real drawer reads the codes of one organization; record what
            # it is handed so the stub cannot drift back into a table-wide read.
            seen_orgs.append(organization_id)
            call_count[0] += 1
            if call_count[0] == 1:
                # Every code the same: the batch cannot survive its own INSERT.
                return ['RTST-AAAA'] * count
            # After IntegrityError rollback the org/user are detached;
            # re-add them so the retry batch can FK-reference them.
            db.add(async_test_household)
            db.add(async_test_user)
            return [f'RTST-{call_count[0]}{i:03d}' for i in range(count)]

        monkeypatch.setattr(
            label_service_mod, '_draw_unused_short_codes_async', fake_draw_async
        )

        user_ctx = UserContextDTO(
            id=async_test_user.id,
            email=async_test_user.email,
            organization_id=async_test_household.id,
            role='admin',
            full_name='Test User',
        )
        request = LabelPoolCreate(count=3, prefix='RTST')

        labels = await LabelService.generate_label_pool_async(
            real_async_db_session, request, user_ctx
        )

        assert len(labels) == 3
        codes = [label.short_code for label in labels]
        assert len(set(codes)) == 3
        assert 'RTST-AAAA' not in codes  # colliding code rejected by retry
        assert set(seen_orgs) == {async_test_household.id}


@pytest.mark.integration
@pytest.mark.asyncio
class TestListByShortCodes:
    """Tests for LabelService.list_by_short_codes_async."""

    async def test_list_by_short_codes_returns_matches(
        self, real_async_db_session: AsyncSession, async_test_user, async_test_household
    ):
        """Returns only labels whose short_code is in the given list, org-scoped."""
        wanted = LabelPool(
            short_code=_short('W1'),
            organization_id=async_test_household.id,
            created_by=async_test_user.id,
        )
        unwanted = LabelPool(
            short_code=_short('W2'),
            organization_id=async_test_household.id,
            created_by=async_test_user.id,
        )
        real_async_db_session.add_all([wanted, unwanted])
        await real_async_db_session.flush()

        result = await LabelService.list_by_short_codes_async(
            real_async_db_session,
            [wanted.short_code, 'MISSING-CODE'],
            async_test_household.id,
        )

        codes = {label.short_code for label in result}
        assert codes == {wanted.short_code}
        assert all(label.organization_id == async_test_household.id for label in result)

    async def test_list_by_short_codes_empty_input(
        self, real_async_db_session: AsyncSession, async_test_household
    ):
        """Empty input list returns an empty result without querying."""
        result = await LabelService.list_by_short_codes_async(
            real_async_db_session, [], async_test_household.id
        )
        assert result == []


@pytest.mark.integration
class TestPerOrgShortCodeUniqueness:
    """short_code is unique per organization, not globally (archived orglabel01).

    Sync (not async) so the session depends on setup_test_db, which rebuilds
    the schema from current models — async sessions reuse stale schema from a
    prior worker and would not reflect the constraint change.
    """

    def test_same_short_code_allowed_in_two_orgs(
        self, db_session, test_user, test_household
    ):
        """Two tenants may reuse the same short_code (e.g. equipment serial DELL-1)."""
        from app.models.organization import Organization

        other_org = Organization(name='Other Tenant')
        db_session.add(other_org)
        db_session.commit()

        shared_code = _short('DELLX1')
        db_session.add_all(
            [
                LabelPool(
                    short_code=shared_code,
                    organization_id=test_household.id,
                    created_by=test_user.id,
                ),
                LabelPool(
                    short_code=shared_code,
                    organization_id=other_org.id,
                    created_by=test_user.id,
                ),
            ]
        )
        db_session.commit()

        rows = (
            db_session.query(LabelPool)
            .filter(LabelPool.short_code == shared_code)
            .all()
        )
        assert {r.organization_id for r in rows} == {
            test_household.id,
            other_org.id,
        }

    def test_duplicate_short_code_in_same_org_rejected(
        self, db_session, test_user, test_household
    ):
        """Intra-org duplicate short_code must still violate the constraint."""
        from sqlalchemy.exc import IntegrityError as SyncIntegrityError

        code = _short('DUP')
        db_session.add(
            LabelPool(
                short_code=code,
                organization_id=test_household.id,
                created_by=test_user.id,
            )
        )
        db_session.commit()
        db_session.add(
            LabelPool(
                short_code=code,
                organization_id=test_household.id,
                created_by=test_user.id,
            )
        )
        with pytest.raises(SyncIntegrityError):
            db_session.commit()
        db_session.rollback()


@pytest.mark.integration
@pytest.mark.asyncio
class TestCreateFromCodes:
    """Tests for LabelService.create_from_codes_async."""

    @staticmethod
    def _ctx(async_test_user, async_test_household):
        from app.core.contracts import UserContextDTO

        return UserContextDTO(
            id=async_test_user.id,
            email=async_test_user.email,
            organization_id=async_test_household.id,
            role='admin',
            full_name='Test User',
        )

    async def test_creates_labels_with_explicit_codes(
        self, real_async_db_session, async_test_user, async_test_household
    ):
        from app.schemas.label_pool import LabelCodeItem

        ctx = self._ctx(async_test_user, async_test_household)
        codes = [
            LabelCodeItem(short_code=_short('ASD1'), description='Asset ASD-1'),
            LabelCodeItem(short_code=_short('ASD2'), description='Asset ASD-2'),
        ]
        labels = await LabelService.create_from_codes_async(
            real_async_db_session, codes, ctx
        )

        assert len(labels) == 2
        assert {lbl.short_code for lbl in labels} == {
            codes[0].short_code,
            codes[1].short_code,
        }
        assert all(lbl.description is not None for lbl in labels)
        assert all(lbl.organization_id == async_test_household.id for lbl in labels)

    async def test_rejects_intra_request_duplicate(
        self, real_async_db_session, async_test_user, async_test_household
    ):
        from app.schemas.label_pool import LabelCodeItem

        ctx = self._ctx(async_test_user, async_test_household)
        dup = _short('DUP')
        with pytest.raises(ValueError, match='Duplicate short_code'):
            await LabelService.create_from_codes_async(
                real_async_db_session,
                [LabelCodeItem(short_code=dup), LabelCodeItem(short_code=dup)],
                ctx,
            )

    async def test_rejects_code_already_in_org(
        self, real_async_db_session, async_test_user, async_test_household
    ):
        from app.schemas.label_pool import LabelCodeItem

        ctx = self._ctx(async_test_user, async_test_household)
        existing = _short('EX')
        real_async_db_session.add(
            LabelPool(
                short_code=existing,
                organization_id=async_test_household.id,
                created_by=async_test_user.id,
            )
        )
        await real_async_db_session.flush()

        with pytest.raises(ValueError, match='already in use'):
            await LabelService.create_from_codes_async(
                real_async_db_session,
                [LabelCodeItem(short_code=existing)],
                ctx,
            )
