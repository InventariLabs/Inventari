"""A partial settings write must not reset the keys it omits.

The PUT /modules/{name}/settings door used to let ``_validate_and_clean``
fill schema defaults for every key absent from the body, and the storage
``update`` then overwrote the saved values with those defaults: writing one
setting silently reset the rest of the module's configuration. The
resolution recorded on the task: the write is a PARTIAL update — the body
merges over the saved settings at the top level, a key absent from the body
keeps its saved value, and a key that was never written gets the schema
default (storage stays complete, because readers read the raw namespace).
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization
from app.services.module_service import ModuleService


@pytest.mark.integration
def test_writing_one_setting_leaves_the_others_as_saved(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """Measured on the live endpoint: two writes, each naming one key —
    the first write's value must survive the second."""
    first = client.put(
        '/api/v1/modules/recipes/settings',
        json={'register_production_as_document': True},
        headers=auth_headers,
    )
    assert first.status_code == 200, first.text

    second = client.put(
        '/api/v1/modules/recipes/settings',
        json={'enable_cost_calculation': False},
        headers=auth_headers,
    )
    assert second.status_code == 200, second.text

    settings = client.get(
        '/api/v1/modules/recipes/settings', headers=auth_headers
    ).json()['settings']
    assert settings['register_production_as_document'] is True
    assert settings['enable_cost_calculation'] is False


@pytest.mark.integration
def test_a_first_write_of_one_key_still_carries_schema_defaults(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """Guard of the other half of the contract — this passed before the fix
    too: a key that was NEVER written gets the schema default, because the
    readers read the raw namespace and count on storage being complete."""
    response = client.put(
        '/api/v1/modules/recipes/settings',
        json={'enable_cost_calculation': False},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text

    settings = client.get(
        '/api/v1/modules/recipes/settings', headers=auth_headers
    ).json()['settings']
    assert settings['enable_cost_calculation'] is False
    assert settings['register_production_as_document'] is False


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_change_report_names_only_the_key_that_moved(
    real_async_db_session: AsyncSession,
) -> None:
    """The journal snapshot reports what moved. A write of one key used to
    also report the omitted keys resetting to their defaults — a reset the
    client never asked for is not a change it made."""
    org = Organization(
        name=f'Mig {uuid4().hex[:6]}', enabled_modules=['core', 'items', 'recipes']
    )
    org.settings = {
        'module:recipes': {
            'enable_cost_calculation': True,
            'register_production_as_document': True,
        }
    }
    real_async_db_session.add(org)
    await real_async_db_session.flush()

    change = await ModuleService.update_module_settings_async(
        real_async_db_session, org.id, 'recipes', {'enable_cost_calculation': False}
    )

    assert change is not None
    moved = set(change['before']) | set(change['after'])
    assert moved == {'enable_cost_calculation'}
