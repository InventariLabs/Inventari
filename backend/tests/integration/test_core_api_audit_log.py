"""Tests for core_api.audit_log namespace.

The AuditLog table is populated by DB triggers + service calls
(log_purge_async) and made immutable by a DB trigger. This CoreAPI
exposes read-only access for SOX/GDPR compliance reporting.

Contract:
    - list_for_org_async returns entries for one organization, newest
      first, optionally filtered by target_type / target_id / user_id /
      since. Org-scoped (entries from other orgs never returned).
    - list_for_target_async returns entries for a specific
      (target_type, target_id) pair, useful for "show me the audit
      trail for this item".
    - No write surface — entries are produced by services/triggers,
      not user-facing APIs. The trigger makes UPDATE/DELETE impossible
      at the DB level.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.core.contracts import AuditLogDTO
from app.core.public_api import core_api
from app.models.audit_log import AuditAction, AuditLog
from app.services.audit_service import log_purge_async

from ._core_api_helpers import make_other_org

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
class TestCoreAuditLogAPI:
    """Read-only audit-log access via CoreAPI."""

    async def test_list_for_target_async_returns_entries_for_specific_target(
        self,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        """Write 2 purge entries for item A, 1 for item B → list_for_target_async
        for item A returns exactly 2 entries, newest first."""
        db = real_async_db_session
        item_a = uuid4()
        item_b = uuid4()

        await log_purge_async(
            db,
            organization_id=async_test_household.id,
            user_id=async_test_user.id,
            target_type='item',
            target_id=item_a,
            reason='first purge',
        )
        await log_purge_async(
            db,
            organization_id=async_test_household.id,
            user_id=async_test_user.id,
            target_type='item',
            target_id=item_a,
            reason='second purge',
        )
        await log_purge_async(
            db,
            organization_id=async_test_household.id,
            user_id=async_test_user.id,
            target_type='item',
            target_id=item_b,
            reason='unrelated',
        )
        await db.commit()

        result = await core_api.audit_log.list_for_target_async(
            db,
            async_test_household.id,
            'item',
            item_a,
        )

        assert len(result) == 2
        assert all(isinstance(r, AuditLogDTO) for r in result)
        assert all(r.target_type == 'item' for r in result)
        assert all(r.target_id == item_a for r in result)
        # Newest first
        assert result[0].created_at >= result[1].created_at

    async def test_list_for_org_async_filters_by_organization(
        self,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        """Entries from another org are never returned."""
        db = real_async_db_session
        other_org = await db.run_sync(make_other_org)

        item = uuid4()
        await log_purge_async(
            db,
            organization_id=async_test_household.id,
            user_id=async_test_user.id,
            target_type='item',
            target_id=item,
            reason='ours',
        )
        await log_purge_async(
            db,
            organization_id=other_org.id,
            user_id=async_test_user.id,
            target_type='item',
            target_id=item,
            reason='theirs',
        )
        await db.commit()

        ours, total = await core_api.audit_log.list_for_org_async(
            db, async_test_household.id
        )
        assert total == 1
        assert len(ours) == 1
        assert ours[0].reason == 'ours'

    async def test_list_for_org_async_filters_by_target_type(
        self,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        """target_type filter narrows results."""
        db = real_async_db_session
        item_id = uuid4()
        partner_id = uuid4()

        await log_purge_async(
            db,
            organization_id=async_test_household.id,
            user_id=async_test_user.id,
            target_type='item',
            target_id=item_id,
        )
        await log_purge_async(
            db,
            organization_id=async_test_household.id,
            user_id=async_test_user.id,
            target_type='partner',
            target_id=partner_id,
        )
        await db.commit()

        items, _ = await core_api.audit_log.list_for_org_async(
            db, async_test_household.id, target_type='item'
        )
        assert len(items) == 1
        assert items[0].target_type == 'item'
        assert items[0].target_id == item_id

    async def test_list_for_org_async_filters_by_since(
        self,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        """since=now+1h returns 0 (entries are all older)."""
        db = real_async_db_session
        item_id = uuid4()
        await log_purge_async(
            db,
            organization_id=async_test_household.id,
            user_id=async_test_user.id,
            target_type='item',
            target_id=item_id,
        )
        await db.commit()

        future = datetime.now(UTC) + timedelta(hours=1)
        result, total = await core_api.audit_log.list_for_org_async(
            db, async_test_household.id, since=future
        )
        assert result == []
        assert total == 0

    async def test_list_for_org_async_respects_limit(
        self,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        """limit caps result size."""
        db = real_async_db_session
        for _ in range(5):
            await log_purge_async(
                db,
                organization_id=async_test_household.id,
                user_id=async_test_user.id,
                target_type='item',
                target_id=uuid4(),
            )
        await db.commit()

        result, _ = await core_api.audit_log.list_for_org_async(
            db, async_test_household.id, limit=2
        )
        assert len(result) == 2

    async def test_action_is_preserved_in_dto(
        self,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        """Action enum value surfaces as string in DTO."""
        db = real_async_db_session
        entry = await log_purge_async(
            db,
            organization_id=async_test_household.id,
            user_id=async_test_user.id,
            target_type='item',
            target_id=uuid4(),
            reason='compliance review',
            snapshot={'before': {'name': 'Old'}},
        )
        await db.commit()

        result = await core_api.audit_log.list_for_target_async(
            db,
            async_test_household.id,
            'item',
            entry.target_id,
        )
        assert len(result) == 1
        assert result[0].action == AuditAction.PURGE.value
        assert result[0].reason == 'compliance review'
        assert result[0].snapshot == {'before': {'name': 'Old'}}

    async def test_snapshot_and_meta_data_are_optional(
        self,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        """Snapshot/meta_data default to None when not provided."""
        db = real_async_db_session
        item_id = uuid4()
        await log_purge_async(
            db,
            organization_id=async_test_household.id,
            user_id=async_test_user.id,
            target_type='item',
            target_id=item_id,
        )
        await db.commit()

        result = await core_api.audit_log.list_for_target_async(
            db,
            async_test_household.id,
            'item',
            item_id,
        )
        assert len(result) == 1
        assert result[0].snapshot is None
        assert result[0].meta_data is None

    async def test_direct_model_query_audit_consistency(
        self,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        """Sanity: AuditLog table is populated, CoreAPI count matches
        direct SQL count (catches accidental service-layer filtering)."""
        db = real_async_db_session
        for _ in range(3):
            await log_purge_async(
                db,
                organization_id=async_test_household.id,
                user_id=async_test_user.id,
                target_type='item',
                target_id=uuid4(),
            )
        await db.commit()

        from sqlalchemy import func, select

        direct_count = await db.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.organization_id == async_test_household.id)
        )

        api_result, api_total = await core_api.audit_log.list_for_org_async(
            db, async_test_household.id
        )
        assert direct_count == len(api_result) == api_total == 3


# ---------------------------------------------------------------------------
# Extended AuditAction enum + log_action_async writer
#
# AuditAction was historically just PURGE / HARD_DELETE. New actions
# (CREATE / UPDATE / SOFT_DELETE) let us instrument the hot-path mutation
# services (item/document/PO) without each one inventing its own writer.
# The legacy ``log_purge_async`` is now a thin wrapper over the generic
# ``log_action_async`` so the contract for existing callers stays stable.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestAuditActionEnumExtension:
    """New AuditAction values needed by Phase B instrumentation."""

    def test_create_action_value(self):
        assert AuditAction.CREATE.value == 'CREATE'

    def test_update_action_value(self):
        assert AuditAction.UPDATE.value == 'UPDATE'

    def test_soft_delete_action_value(self):
        assert AuditAction.SOFT_DELETE.value == 'SOFT_DELETE'

    def test_legacy_actions_still_present(self):
        """Backward compat: existing PURGE / HARD_DELETE values must remain."""
        assert AuditAction.PURGE.value == 'PURGE'
        assert AuditAction.HARD_DELETE.value == 'HARD_DELETE'


@pytest.mark.asyncio
class TestLogActionAsync:
    """Generic audit-log writer used by item/document/PO instrumentation."""

    async def test_logs_create_entry(
        self,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        from app.services.audit_service import log_action_async

        db = real_async_db_session
        target_id = uuid4()

        entry = await log_action_async(
            db,
            organization_id=async_test_household.id,
            user_id=async_test_user.id,
            action=AuditAction.CREATE,
            target_type='item',
            target_id=target_id,
            snapshot={'name': 'New Widget'},
        )
        await db.commit()

        assert entry.action == AuditAction.CREATE.value
        assert entry.target_type == 'item'
        assert entry.target_id == target_id
        assert entry.snapshot == {'name': 'New Widget'}

    async def test_logs_update_entry_with_before_after_snapshot(
        self,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        from app.services.audit_service import log_action_async

        db = real_async_db_session
        target_id = uuid4()

        entry = await log_action_async(
            db,
            organization_id=async_test_household.id,
            user_id=async_test_user.id,
            action=AuditAction.UPDATE,
            target_type='item',
            target_id=target_id,
            snapshot={
                'before': {'quantity': 5},
                'after': {'quantity': 3},
            },
        )
        await db.commit()

        assert entry.action == AuditAction.UPDATE.value
        assert entry.snapshot['before']['quantity'] == 5
        assert entry.snapshot['after']['quantity'] == 3

    async def test_logs_soft_delete_with_reason(
        self,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        from app.services.audit_service import log_action_async

        db = real_async_db_session
        target_id = uuid4()

        entry = await log_action_async(
            db,
            organization_id=async_test_household.id,
            user_id=async_test_user.id,
            action=AuditAction.SOFT_DELETE,
            target_type='item',
            target_id=target_id,
            reason='reported_damaged_by_user',
        )
        await db.commit()

        assert entry.action == AuditAction.SOFT_DELETE.value
        assert entry.reason == 'reported_damaged_by_user'

    async def test_log_purge_async_still_writes_purge_entry(
        self,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        """Backward-compat: log_purge_async must keep working unchanged."""
        db = real_async_db_session
        target_id = uuid4()

        entry = await log_purge_async(
            db,
            organization_id=async_test_household.id,
            user_id=async_test_user.id,
            target_type='item',
            target_id=target_id,
            reason='old purge path still works',
        )
        await db.commit()

        assert entry.action == AuditAction.PURGE.value
        assert entry.reason == 'old purge path still works'

    async def test_meta_data_defaults_to_none(
        self,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        """meta_data omitted -> row stays NULL (matches legacy behaviour)."""
        from app.services.audit_service import log_action_async

        db = real_async_db_session
        entry = await log_action_async(
            db,
            organization_id=async_test_household.id,
            user_id=async_test_user.id,
            action=AuditAction.CREATE,
            target_type='item',
            target_id=uuid4(),
        )
        await db.commit()

        assert entry.meta_data is None
