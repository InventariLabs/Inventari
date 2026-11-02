"""HTTP endpoint tests for ``GET /api/v1/audit-log``.

Uses async fixtures consistent with the rest of the async integration
suite (real_async_client + real_async_db_session + explicit _auth
helper). All write paths funnel through ``log_action_async`` so the
Phase B instrumentation can be tested by reading existing entries.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from app.models.audit_log import AuditAction
from app.services.audit_service import log_action_async
from app.services.token_service import create_access_token

pytestmark = pytest.mark.integration


def _auth(user) -> dict:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


@pytest.mark.asyncio
class TestAuditLogRouter:
    """GET /api/v1/audit-log — list audit entries for the current org."""

    async def test_returns_committed_entries(
        self,
        real_async_client,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        await log_action_async(
            real_async_db_session,
            organization_id=async_test_household.id,
            user_id=async_test_user.id,
            action=AuditAction.CREATE,
            target_type='item',
            target_id=uuid4(),
            snapshot={'name': 'Test Widget'},
        )
        await real_async_db_session.commit()

        response = await real_async_client.get(
            '/api/v1/audit-log', headers=_auth(async_test_user)
        )
        assert response.status_code == 200
        body = response.json()['items']
        assert isinstance(body, list)
        matching = [e for e in body if e['action'] == AuditAction.CREATE.value]
        assert matching
        assert matching[0]['target_type'] == 'item'
        assert matching[0]['snapshot'] == {'name': 'Test Widget'}
        assert matching[0]['user_email'] == async_test_user.email

    async def test_user_email_is_none_when_user_id_is_null(
        self,
        real_async_client,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        """System-originated entries (user_id=NULL) must not crash the LEFT JOIN."""
        await log_action_async(
            real_async_db_session,
            organization_id=async_test_household.id,
            user_id=None,
            action=AuditAction.CREATE,
            target_type='item',
            target_id=uuid4(),
        )
        await real_async_db_session.commit()

        response = await real_async_client.get(
            '/api/v1/audit-log', headers=_auth(async_test_user)
        )
        assert response.status_code == 200
        body = response.json()['items']
        matching = [
            e for e in body if e.get('user_id') is None and e['action'] == 'CREATE'
        ]
        assert matching
        assert matching[0]['user_email'] is None

    async def test_filter_by_target_type(
        self,
        real_async_client,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        item_target = uuid4()
        await log_action_async(
            real_async_db_session,
            organization_id=async_test_household.id,
            user_id=async_test_user.id,
            action=AuditAction.CREATE,
            target_type='item',
            target_id=item_target,
        )
        await log_action_async(
            real_async_db_session,
            organization_id=async_test_household.id,
            user_id=async_test_user.id,
            action=AuditAction.CREATE,
            target_type='document',
            target_id=uuid4(),
        )
        await real_async_db_session.commit()

        response = await real_async_client.get(
            '/api/v1/audit-log',
            params={'target_type': 'item'},
            headers=_auth(async_test_user),
        )
        assert response.status_code == 200
        body = response.json()['items']
        assert all(entry['target_type'] == 'item' for entry in body)
        assert any(entry['target_id'] == str(item_target) for entry in body)

    async def test_filter_by_target_id(
        self,
        real_async_client,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        target_a = uuid4()
        target_b = uuid4()
        await log_action_async(
            real_async_db_session,
            organization_id=async_test_household.id,
            user_id=async_test_user.id,
            action=AuditAction.UPDATE,
            target_type='item',
            target_id=target_a,
        )
        await log_action_async(
            real_async_db_session,
            organization_id=async_test_household.id,
            user_id=async_test_user.id,
            action=AuditAction.UPDATE,
            target_type='item',
            target_id=target_b,
        )
        await real_async_db_session.commit()

        response = await real_async_client.get(
            '/api/v1/audit-log',
            params={'target_id': str(target_a)},
            headers=_auth(async_test_user),
        )
        assert response.status_code == 200
        body = response.json()['items']
        assert all(entry['target_id'] == str(target_a) for entry in body)
        assert len(body) == 1

    async def test_limit_caps_result_size(
        self,
        real_async_client,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        for _ in range(5):
            await log_action_async(
                real_async_db_session,
                organization_id=async_test_household.id,
                user_id=async_test_user.id,
                action=AuditAction.CREATE,
                target_type='item',
                target_id=uuid4(),
            )
        await real_async_db_session.commit()

        response = await real_async_client.get(
            '/api/v1/audit-log',
            params={'limit': 2},
            headers=_auth(async_test_user),
        )
        assert response.status_code == 200
        body = response.json()
        assert len(body['items']) == 2
        assert body['total'] == 5
        assert body['has_more'] is True

    async def test_offset_paginates_across_pages(
        self,
        real_async_client,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        for _ in range(5):
            await log_action_async(
                real_async_db_session,
                organization_id=async_test_household.id,
                user_id=async_test_user.id,
                action=AuditAction.CREATE,
                target_type='item',
                target_id=uuid4(),
            )
        await real_async_db_session.commit()

        page1 = (
            await real_async_client.get(
                '/api/v1/audit-log',
                params={'limit': 2, 'offset': 0},
                headers=_auth(async_test_user),
            )
        ).json()
        page2 = (
            await real_async_client.get(
                '/api/v1/audit-log',
                params={'limit': 2, 'offset': 2},
                headers=_auth(async_test_user),
            )
        ).json()

        ids1 = {e['id'] for e in page1['items']}
        ids2 = {e['id'] for e in page2['items']}
        assert page1['total'] == 5
        assert page1['has_more'] is True
        assert page2['has_more'] is True
        assert len(ids1) == 2
        assert len(ids2) == 2
        assert ids1.isdisjoint(ids2)

    async def test_endpoint_cap_declared_in_openapi_schema(self):
        """Query(le=500) is enforced via Pydantic — verify via OpenAPI schema.

        Checking it via a live request is brittle because validation order
        depends on the FastAPI dependency graph (auth runs before/after
        query validation depending on test fixture wiring). The contract
        is documented in the OpenAPI schema, which is the source of truth
        for client generators and the front-end type generator.
        """
        from app.main import app

        schema = app.openapi()
        op = schema['paths']['/api/v1/audit-log']['get']
        limit_param = next(p for p in op['parameters'] if p['name'] == 'limit')
        schema_max = limit_param['schema'].get('maximum')
        assert schema_max == 500, (
            f'expected limit le=500 in OpenAPI schema, got {schema_max}'
        )

    async def test_does_not_leak_other_org_entries(
        self,
        real_async_client,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        from app.models.organization import Organization

        other_org = Organization(name='Other Org Audit Test', enabled_modules=[])
        real_async_db_session.add(other_org)
        await real_async_db_session.flush()
        await real_async_db_session.refresh(other_org)

        await log_action_async(
            real_async_db_session,
            organization_id=other_org.id,
            user_id=None,
            action=AuditAction.CREATE,
            target_type='item',
            target_id=uuid4(),
            snapshot={'name': 'other-org-secret'},
        )
        await real_async_db_session.commit()

        response = await real_async_client.get(
            '/api/v1/audit-log', headers=_auth(async_test_user)
        )
        assert response.status_code == 200
        body = response.json()['items']
        for entry in body:
            assert entry['organization_id'] != str(other_org.id)

    async def test_unauthenticated_request_gets_401(
        self,
        real_async_client,
    ):
        response = await real_async_client.get('/api/v1/audit-log')
        assert response.status_code == 401

    async def test_non_admin_member_gets_403(
        self,
        real_async_client,
        real_async_db_session,
        async_test_household,
    ):
        """Audit log read is admin-only — the log contains
        activity metadata of all org members."""
        import uuid as _uuid

        from app.models.user import User
        from app.services.token_service import get_password_hash

        member = User(
            email=f'audit_member_{_uuid.uuid4().hex[:8]}@example.com',
            hashed_password=get_password_hash('memberpass'),
            full_name='Org Member',
            organization_id=async_test_household.id,
            role='user',
            is_active=True,
        )
        real_async_db_session.add(member)
        await real_async_db_session.commit()
        await real_async_db_session.refresh(member)

        response = await real_async_client.get(
            '/api/v1/audit-log', headers=_auth(member)
        )
        assert response.status_code == 403


# ---------------------------------------------------------------------------
# Instrument item mutation services with audit logs.
#
# create_item / update_item / delete_item now write audit entries via
# log_action_async. These tests fail (RED) until the instrumentation
# lands. Once green, the audit-log endpoint will surface real entries.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestItemAuditInstrumentation:
    """Item mutation paths must write AuditLog rows."""

    async def test_create_item_writes_create_entry(
        self,
        real_async_client,
        real_async_db_session,
        async_test_user,
        async_test_storage_location,
    ):
        from app.schemas.item import ItemCreate
        from app.services.items import create_item

        item_in = ItemCreate(
            location_id=async_test_storage_location.id,
            name='Audited Widget',
            brand='Test Brand',
            quantity=2,
        )
        item = await create_item(real_async_db_session, item_in, async_test_user)
        await real_async_db_session.commit()

        response = await real_async_client.get(
            '/api/v1/audit-log',
            params={'target_id': str(item.id)},
            headers=_auth(async_test_user),
        )
        assert response.status_code == 200
        body = response.json()['items']
        assert any(
            e['action'] == AuditAction.CREATE.value and e['target_id'] == str(item.id)
            for e in body
        ), body

    async def test_update_item_writes_update_entry(
        self,
        real_async_client,
        real_async_db_session,
        async_test_item,
        async_test_user,
    ):
        from app.schemas.item import ItemUpdate
        from app.services.items import update_item

        item_in = ItemUpdate(brand='Updated Brand')
        await update_item(
            real_async_db_session, async_test_item, item_in, async_test_user
        )
        await real_async_db_session.commit()

        response = await real_async_client.get(
            '/api/v1/audit-log',
            params={'target_id': str(async_test_item.id)},
            headers=_auth(async_test_user),
        )
        assert response.status_code == 200
        body = response.json()['items']
        update_entries = [e for e in body if e['action'] == AuditAction.UPDATE.value]
        assert update_entries, 'expected UPDATE entry not found'
        snap = update_entries[0]['snapshot']
        assert 'before' in snap and 'after' in snap
        assert snap['after']['brand'] == 'Updated Brand'
        # Only the field that moved. The form posts its whole state, and a log
        # that repeats the payload says a dozen fields changed on every save.
        assert snap['fields'] == ['brand']

    async def test_update_repeating_current_values_writes_no_entry(
        self,
        real_async_client,
        real_async_db_session,
        async_test_item,
        async_test_user,
    ):
        """A save that changed nothing leaves no entry.

        The values are restated the way the form sends them back — the
        quantity as a plain number, the location as text — so the test would
        fail again the moment either side of the comparison went through
        ``str()``.
        """
        from app.schemas.item import ItemUpdate
        from app.services.items import update_item

        item_in = ItemUpdate(
            name=async_test_item.name,
            brand=async_test_item.brand,
            quantity=int(async_test_item.quantity),
            location_id=str(async_test_item.storage_location_id),
            category_id=str(async_test_item.category_id),
            expiry_date=async_test_item.expiry_date,
            shelf_location=async_test_item.shelf_location,
        )
        await update_item(
            real_async_db_session, async_test_item, item_in, async_test_user
        )
        await real_async_db_session.commit()

        response = await real_async_client.get(
            '/api/v1/audit-log',
            params={'target_id': str(async_test_item.id)},
            headers=_auth(async_test_user),
        )
        assert response.status_code == 200
        body = response.json()['items']
        assert not [e for e in body if e['action'] == AuditAction.UPDATE.value], (
            'a PATCH that changed nothing must not be recorded as a change'
        )

    async def test_update_snapshot_keeps_values_comparable(
        self,
        real_async_client,
        real_async_db_session,
        async_test_item,
        async_test_user,
    ):
        """The snapshot holds values, not their Python repr.

        The column is JSON, so a nested field has to arrive as something the
        screen can walk rather than a printed dict. A quantity arrives as its
        exact digits in a string: the journal is the account of what the
        numbers were, and a float is a less precise copy of the data it
        describes. `formatAuditValue` prints a string as it stands, so
        `2.000 -> 5` reads on the screen exactly as it is stored.

        This test used to require the opposite -- a number, explicitly not
        `'5.000'`. The quantity-change path had already moved to strings by
        then, so the same field read one way on one row and the other way on
        the next; the rule in `docs/subsystems/AUDIT.md` settles it.
        """
        from app.schemas.item import ItemUpdate
        from app.services.items import update_item

        item_in = ItemUpdate(quantity=5, shelf_location='Shelf 2')
        await update_item(
            real_async_db_session, async_test_item, item_in, async_test_user
        )
        await real_async_db_session.commit()

        response = await real_async_client.get(
            '/api/v1/audit-log',
            params={'target_id': str(async_test_item.id)},
            headers=_auth(async_test_user),
        )
        entries = [
            e
            for e in response.json()['items']
            if e['action'] == AuditAction.UPDATE.value
        ]
        assert entries, 'expected UPDATE entry not found'
        snap = entries[0]['snapshot']
        assert sorted(snap['fields']) == ['quantity', 'shelf_location']
        assert Decimal(snap['before']['quantity']) == 2
        assert Decimal(snap['after']['quantity']) == 5
        assert isinstance(snap['after']['quantity'], str)
        assert snap['after']['shelf_location'] == 'Shelf 2'

    async def test_delete_item_writes_soft_delete_entry(
        self,
        real_async_client,
        real_async_db_session,
        async_test_item,
        async_test_user,
    ):
        from app.services.items import delete_item

        await delete_item(
            real_async_db_session,
            async_test_item,
            async_test_user,
            reason='reported_damaged',
        )
        await real_async_db_session.commit()

        response = await real_async_client.get(
            '/api/v1/audit-log',
            params={'target_id': str(async_test_item.id)},
            headers=_auth(async_test_user),
        )
        assert response.status_code == 200
        body = response.json()['items']
        soft_entries = [e for e in body if e['action'] == AuditAction.SOFT_DELETE.value]
        assert soft_entries, 'expected SOFT_DELETE entry not found'
        assert soft_entries[0]['reason'] == 'reported_damaged'


# ---------------------------------------------------------------------------
# Instrument document + purchase-order mutations.
#
# These tests cover the cross-module flow: documents/purchase_orders live
# under app/modules/<m>/, so they must use core_api.audit_log (the public
# API surface) rather than the service-layer helper directly -- per the
# Golden Path rule that modules never import app.services / app.models.
#
# The document create entry is asserted where a document can actually be
# built — warehouse/tests/integration/test_executing_a_document_reaches_the_log.py.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestPurchaseOrderAuditInstrumentation:
    """PO create + confirm emit audit entries via CoreAPI."""

    async def test_create_purchase_order_writes_create_entry(
        self,
        real_async_client,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        from app.modules.purchase_orders._service_crud import create_purchase_order
        from app.modules.purchase_orders.schemas import (
            PurchaseOrderCreate,
            PurchaseOrderLineCreate,
        )

        po = await create_purchase_order(
            real_async_db_session,
            async_test_household.id,
            PurchaseOrderCreate(
                partner_id=None,
                lines=[PurchaseOrderLineCreate(name='Widget A', quantity_ordered=1)],
                currency='USD',
            ),
            async_test_user.id,
        )
        await real_async_db_session.commit()

        response = await real_async_client.get(
            '/api/v1/audit-log',
            params={'target_id': str(po.id)},
            headers=_auth(async_test_user),
        )
        assert response.status_code == 200
        body = response.json()['items']
        create_entries = [
            e
            for e in body
            if e['action'] == AuditAction.CREATE.value
            and e['target_type'] == 'purchase_order'
        ]
        assert create_entries, 'expected CREATE entry for purchase_order'
        assert create_entries[0]['snapshot']['number'] == po.number
