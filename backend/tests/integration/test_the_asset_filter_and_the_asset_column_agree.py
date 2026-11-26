"""The journal's object filter and its Target column name an asset alike.

An asset is a product card with an equipment block, so its create and edit
entries are written as ``item``, while its status changes are
``equipment_asset``. The column calls all of them an asset; the filter lists
all of them under that word.
"""

from __future__ import annotations

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


async def _write(db, org, user, target_type, snapshot):
    target = uuid4()
    await log_action_async(
        db,
        organization_id=org.id,
        user_id=user.id,
        action=AuditAction.UPDATE,
        target_type=target_type,
        target_id=target,
        snapshot=snapshot,
    )
    return str(target)


@pytest.mark.asyncio
async def test_the_asset_filter_lists_every_entry_the_column_calls_an_asset(
    real_async_client,
    real_async_db_session,
    async_test_household,
    async_test_user,
):
    db, org, user = real_async_db_session, async_test_household, async_test_user
    created = await _write(
        db, org, user, 'item', {'name': 'Laptop', 'module_name': 'equipment'}
    )
    edited = await _write(
        db,
        org,
        user,
        'item',
        {
            'name': 'Laptop',
            'before': {'meta_data': {'equipment': {'tag': 'A'}}},
            'after': {'meta_data': {'equipment': {'tag': 'B'}}},
        },
    )
    status = await _write(db, org, user, 'equipment_asset', {'name': 'Laptop'})
    product = await _write(db, org, user, 'item', {'name': 'Flour'})
    await db.commit()

    async def ids(kind: str) -> set[str]:
        response = await real_async_client.get(
            '/api/v1/audit-log',
            params={'target_type': kind},
            headers=_auth(user),
        )
        assert response.status_code == 200, response.text
        return {entry['target_id'] for entry in response.json()['items']}

    assert {created, edited, status} <= await ids('equipment_asset')
    assert product not in await ids('equipment_asset')

    assert product in await ids('item')


@pytest.mark.asyncio
async def test_the_filter_offers_asset_when_only_product_entries_are_assets(
    real_async_client,
    real_async_db_session,
    async_test_household,
    async_test_user,
):
    """An asset that was never handed out or retired has only ``item``
    entries; the filter still offers the word its column prints."""
    db, org, user = real_async_db_session, async_test_household, async_test_user
    await _write(db, org, user, 'item', {'name': 'Flour'})
    await db.commit()

    async def offered() -> list[str]:
        response = await real_async_client.get(
            '/api/v1/audit-log/target-types', headers=_auth(user)
        )
        assert response.status_code == 200, response.text
        return response.json()

    assert 'equipment_asset' not in await offered()

    await _write(db, org, user, 'item', {'name': 'Laptop', 'module_name': 'equipment'})
    await db.commit()

    assert await offered() == ['equipment_asset', 'item']
