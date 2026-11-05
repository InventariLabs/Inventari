"""The facade's "organization not found" reaches a Polish reader as a Polish 400.

``test_core_facade_refusals_speak_the_readers_language`` pins the sentence at
the call; this file pins the road home. A narrow app mounts the real
``LanguageMiddleware`` and the real ``ValueError`` handler of ``app.main`` and
exposes one route per facade branch that refuses a missing organization.
A request with ``Accept-Language: pl`` must come back as the 400 envelope with
the catalogue's Polish sentence and the machine code — an English literal
behind the same exception type answers 400 too, and only the sentence and the
code tell the builds apart.

Events and storage types raise developer-facing errors on purpose; they are
not reader-facing and have no route here.
"""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app._middleware import LanguageMiddleware
from app.core.contracts import OrganizationDTO, UserContextDTO
from app.core.public_api.ai_connections import _persist_org_settings
from app.core.public_api.organizations import CoreOrganizationsAPI
from app.core.public_api.settings import CoreSettingsAPI
from app.main import value_error_handler

pytestmark = pytest.mark.integration


def _db_without_org() -> AsyncMock:
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=None)
    return db


@pytest.fixture
def harness() -> TestClient:
    app = FastAPI()
    app.add_middleware(LanguageMiddleware)
    app.add_exception_handler(ValueError, value_error_handler)

    @app.post('/settings')
    async def save_settings() -> None:
        await CoreSettingsAPI().set_bulk_async(
            _db_without_org(), uuid4(), 'my_module', {'k': 'v'}
        )

    @app.post('/ai-settings')
    async def persist_ai_settings() -> None:
        await _persist_org_settings(_db_without_org(), uuid4(), {})

    @app.post('/toggle-module')
    async def toggle_module() -> None:
        org = OrganizationDTO.model_construct(id=uuid4())
        user = UserContextDTO.model_construct(id=uuid4())
        await CoreOrganizationsAPI().toggle_module_async(
            _db_without_org(), org, 'approvals', True, user
        )

    @app.post('/onboarding')
    async def onboard() -> None:
        org = OrganizationDTO.model_construct(id=uuid4())
        await CoreOrganizationsAPI().apply_onboarding_profile_async(
            _db_without_org(), org, 'home'
        )

    return TestClient(app)


@pytest.mark.parametrize(
    'path', ['/settings', '/ai-settings', '/toggle-module', '/onboarding']
)
@pytest.mark.parametrize(
    ('lang', 'sentence'),
    [('pl', 'Nie znaleziono organizacji'), ('en', 'Organization not found')],
)
def test_a_missing_organization_answers_in_the_requests_language(
    harness: TestClient, path: str, lang: str, sentence: str
) -> None:
    response = harness.post(path, headers={'Accept-Language': lang})

    assert response.status_code == 400
    assert response.json()['detail'] == {
        'code': 'ORGANIZATION_NOT_FOUND',
        'message': sentence,
        'lang': lang,
    }
