"""The doors that write organization settings leave an entry in the journal.

The organization PUT and the module-settings PUT already did. Four others
wrote the same kind of setting — the SKU naming schema, a module's namespace
through ``core_api.settings.set_bulk_async``, the AI purpose bindings and the
AI connections themselves — and left nothing: which provider and key receives
an organization's data was decided with no record of who decided it.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.public_api import core_api
from app.models.audit_log import AuditLog
from app.services.token_service import create_access_token

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures('stub_dns')]


def _auth(user) -> dict:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


async def _entries(db, org, **where):
    rows = await db.scalars(
        select(AuditLog)
        .where(AuditLog.organization_id == org.id)
        .where(*(getattr(AuditLog, k) == v for k, v in where.items()))
        .order_by(AuditLog.created_at)
    )
    return list(rows)


def _connection_body(name: str = 'Pool A') -> dict:
    return {
        'name': name,
        'provider': 'openrouter',
        'api_key': 'sk-or-plaintext-NEVER-JOURNALLED',
        'api_base_url': 'https://openrouter.ai/api/v1',
        'model_name': 'gemini-2.0-flash',
        'capabilities': ['vision', 'text'],
    }


@pytest.mark.asyncio
class TestSettingsWritesReachTheJournal:
    async def test_the_sku_schema_names_what_it_changed(
        self,
        real_async_client,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        await real_async_db_session.commit()
        schema = {
            'prefix': 'WH',
            'separator': '-',
            'next_number': 1,
            'pad_length': 5,
            'enabled': True,
        }
        response = await real_async_client.put(
            '/api/v1/items/product-templates/sku-schema',
            json=schema,
            headers=_auth(async_test_user),
        )
        assert response.status_code == 200

        (entry,) = await _entries(
            real_async_db_session, async_test_household, target_type='organization'
        )
        assert entry.user_id == async_test_user.id
        assert entry.target_id == async_test_household.id
        assert entry.snapshot['after']['sku_schema']['prefix'] == 'WH'
        assert entry.snapshot['name'] == async_test_household.name

        # The same schema again changes nothing, and the journal records
        # changes, not keystrokes.
        again = await real_async_client.put(
            '/api/v1/items/product-templates/sku-schema',
            json=schema,
            headers=_auth(async_test_user),
        )
        assert again.status_code == 200
        assert (
            len(
                await _entries(
                    real_async_db_session,
                    async_test_household,
                    target_type='organization',
                )
            )
            == 1
        )

    async def test_a_module_writing_its_settings_leaves_an_entry(
        self, real_async_db_session, async_test_household
    ):
        await core_api.settings.set_bulk_async(
            real_async_db_session,
            async_test_household.id,
            'webhooks',
            {'delivery_timeout_seconds': 7},
        )

        (entry,) = await _entries(
            real_async_db_session, async_test_household, target_type='module'
        )
        assert entry.snapshot['name'] == 'webhooks'
        assert entry.snapshot['after']['delivery_timeout_seconds'] == 7
        # No account travels with the call: the entry says the system acted.
        assert entry.meta_data == {'actor': {'type': 'system'}}

    async def test_binding_a_purpose_names_the_connection_and_the_user(
        self,
        real_async_client,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        await real_async_db_session.commit()
        created = await real_async_client.post(
            '/api/v1/ai-connections',
            json=_connection_body(),
            headers=_auth(async_test_user),
        )
        assert created.status_code == 200
        conn_id = created.json()['id']

        bound = await real_async_client.put(
            '/api/v1/ai-connections/bindings',
            json={'purpose_key': 'vision.extract', 'connection_id': conn_id},
            headers=_auth(async_test_user),
        )
        assert bound.status_code == 200

        (entry,) = await _entries(
            real_async_db_session, async_test_household, target_type='organization'
        )
        assert entry.user_id == async_test_user.id
        assert entry.snapshot['purpose'] == 'vision.extract'
        assert entry.snapshot['purpose_label_key'] == 'vision:ai.purposeLabel'
        assert entry.snapshot['name'] == async_test_household.name
        assert entry.snapshot['before'] == {
            'connection_id': None,
            'connection_name': None,
        }
        assert entry.snapshot['after'] == {
            'connection_id': conn_id,
            'connection_name': 'Pool A',
        }

    async def test_a_connection_is_journalled_without_its_key(
        self,
        real_async_client,
        real_async_db_session,
        async_test_household,
        async_test_user,
    ):
        await real_async_db_session.commit()
        headers = _auth(async_test_user)
        created = await real_async_client.post(
            '/api/v1/ai-connections', json=_connection_body(), headers=headers
        )
        conn_id = created.json()['id']
        renamed = await real_async_client.put(
            f'/api/v1/ai-connections/{conn_id}',
            json={'name': 'Pool B', 'api_key': 'sk-or-another-NEVER-JOURNALLED'},
            headers=headers,
        )
        assert renamed.status_code == 200
        deleted = await real_async_client.delete(
            f'/api/v1/ai-connections/{conn_id}', headers=headers
        )
        assert deleted.status_code == 200

        rows = await _entries(
            real_async_db_session, async_test_household, target_type='ai_connection'
        )
        assert [r.action for r in rows] == ['CREATE', 'UPDATE', 'HARD_DELETE']
        assert {str(r.target_id) for r in rows} == {conn_id}
        assert rows[1].snapshot['before'] == {'name': 'Pool A'}
        assert rows[1].snapshot['after'] == {
            'name': 'Pool B',
            'api_key': 'ROTATED_VALUE',
        }
        assert rows[2].snapshot['name'] == 'Pool B'
        assert 'NEVER-JOURNALLED' not in ''.join(str(r.snapshot) for r in rows)
