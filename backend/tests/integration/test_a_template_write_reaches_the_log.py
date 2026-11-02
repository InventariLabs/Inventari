"""Templates are catalogue: the definitions everything printed is written
against, and until now nothing recorded a change to one.

The rule in ``AuditTargetType`` names templates among the definitions the
organization log holds, and a handover protocol is exactly that -- change
it and every asset handed over from then on is signed on different terms.

The entry is written by the core rather than by the modules, because
equipment, documents and purchase orders all write the same table through
the same functions. Kept per module, the log would say a protocol was
edited when equipment did it and nothing when documents did: the log
depending on which screen was open, which is the thing it must never do.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models.audit_log import AuditLog
from app.services.template_crud import (
    create_template_async,
    delete_template_async,
    update_template_async,
)


async def _entries(db, org_id: uuid.UUID) -> list[AuditLog]:
    rows = await db.scalars(
        select(AuditLog)
        .where(
            AuditLog.organization_id == org_id,
            AuditLog.target_type == 'document_template',
        )
        .order_by(AuditLog.created_at.asc())
    )
    return list(rows.all())


@pytest.mark.integration
class TestATemplateWriteReachesTheLog:
    async def test_creating_one_names_it_and_the_module_that_owns_it(
        self, real_async_db_session, async_test_user, async_test_household
    ):
        tpl = await create_template_async(
            db=real_async_db_session,
            org_id=async_test_household.id,
            module='equipment',
            user_id=async_test_user.id,
            name='Handover protocol',
            body_html='<h1>Handover</h1>',
            is_default=True,
        )

        (entry,) = await _entries(real_async_db_session, async_test_household.id)
        assert entry.action == 'CREATE'
        assert entry.target_id == tpl.id
        assert entry.user_id == async_test_user.id
        assert entry.snapshot is not None
        assert entry.snapshot['name'] == 'Handover protocol'
        assert entry.snapshot['module'] == 'equipment'
        assert entry.snapshot['is_default'] is True

    async def test_an_edit_says_the_body_changed_without_printing_it(
        self, real_async_db_session, async_test_user, async_test_household
    ):
        """A protocol is pages of HTML; a snapshot that size buries the screen."""
        tpl = await create_template_async(
            db=real_async_db_session,
            org_id=async_test_household.id,
            module='warehouse',
            user_id=async_test_user.id,
            name='Invoice',
            body_html='<h1>Invoice</h1>',
        )

        await update_template_async(
            db=real_async_db_session,
            org_id=async_test_household.id,
            template_id=tpl.id,
            module='warehouse',
            name='Invoice v2',
            body_html='<h1>Invoice</h1><p>' + 'x' * 5000 + '</p>',
            user_id=async_test_user.id,
        )

        _created, edited = await _entries(
            real_async_db_session, async_test_household.id
        )
        assert edited.action == 'UPDATE'
        assert edited.snapshot is not None
        assert edited.snapshot['after']['name'] == 'Invoice v2'
        assert edited.snapshot['after']['body_html'] == 'changed'
        assert 'xxxx' not in str(edited.snapshot)

    async def test_an_edit_that_changes_nothing_writes_nothing(
        self, real_async_db_session, async_test_user, async_test_household
    ):
        tpl = await create_template_async(
            db=real_async_db_session,
            org_id=async_test_household.id,
            module='warehouse',
            user_id=async_test_user.id,
            name='Invoice',
            body_html='<h1>Invoice</h1>',
        )

        await update_template_async(
            db=real_async_db_session,
            org_id=async_test_household.id,
            template_id=tpl.id,
            module='warehouse',
            name='Invoice',
            user_id=async_test_user.id,
        )

        assert len(await _entries(real_async_db_session, async_test_household.id)) == 1

    async def test_deleting_one_keeps_what_it_was(
        self, real_async_db_session, async_test_user, async_test_household
    ):
        tpl = await create_template_async(
            db=real_async_db_session,
            org_id=async_test_household.id,
            module='purchase_orders',
            user_id=async_test_user.id,
            name='Order form',
            body_html='<h1>Order</h1>',
        )

        await delete_template_async(
            real_async_db_session,
            async_test_household.id,
            tpl.id,
            'purchase_orders',
            user_id=async_test_user.id,
        )

        _created, removed = await _entries(
            real_async_db_session, async_test_household.id
        )
        assert removed.action == 'HARD_DELETE'
        assert removed.snapshot is not None
        assert removed.snapshot['name'] == 'Order form'
        assert removed.snapshot['module'] == 'purchase_orders'
