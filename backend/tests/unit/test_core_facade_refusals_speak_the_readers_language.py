"""The public_api facade refuses in the reader's language, or not at all.

An organization that is gone is told to the reader through the catalogue;
a caller that broke the facade's contract gets a developer-facing error
that the 400 envelope never shows to anyone.
"""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.core.contracts import OrganizationDTO, UserContextDTO
from app.core.exceptions import (
    ContractViolationError,
    ServiceRejectionError,
    is_reader_facing_value_error,
)
from app.core.public_api.ai_connections import _persist_org_settings
from app.core.public_api.organizations import CoreOrganizationsAPI
from app.core.public_api.settings import CoreSettingsAPI
from app.i18n.service import set_current_lang


@pytest.fixture(autouse=True)
def _polish_reader():
    set_current_lang('pl')
    yield
    set_current_lang('en')


def _db_without_org() -> AsyncMock:
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=None)
    return db


async def test_saving_settings_for_a_missing_organization_speaks_polish() -> None:
    with pytest.raises(ServiceRejectionError) as exc:
        await CoreSettingsAPI().set_bulk_async(
            _db_without_org(), uuid4(), 'my_module', {'k': 'v'}
        )

    assert exc.value.key == 'organization_not_found'
    assert str(exc.value) == 'Nie znaleziono organizacji'


async def test_persisting_ai_settings_for_a_missing_organization_speaks_polish() -> (
    None
):
    with pytest.raises(ServiceRejectionError) as exc:
        await _persist_org_settings(_db_without_org(), uuid4(), {})

    assert str(exc.value) == 'Nie znaleziono organizacji'


async def test_toggling_a_module_of_a_missing_organization_speaks_polish() -> None:
    org = OrganizationDTO.model_construct(id=uuid4())
    user = UserContextDTO.model_construct(id=uuid4())

    with pytest.raises(ServiceRejectionError) as exc:
        await CoreOrganizationsAPI().toggle_module_async(
            _db_without_org(), org, 'approvals', True, user
        )

    assert str(exc.value) == 'Nie znaleziono organizacji'


async def test_asking_for_a_secret_without_naming_it_is_not_for_the_reader() -> None:
    with pytest.raises(ContractViolationError) as exc:
        await CoreSettingsAPI().get_decrypted_async(
            AsyncMock(), uuid4(), 'my_module', None
        )

    assert not isinstance(exc.value, ValueError)
    assert 'needs a key' in str(exc.value)


def test_a_contract_violation_is_never_a_reader_facing_value_error() -> None:
    assert not issubclass(ContractViolationError, ValueError)
    assert is_reader_facing_value_error(ServiceRejectionError('organization_not_found'))


async def test_onboarding_a_missing_organization_speaks_polish() -> None:
    org = OrganizationDTO.model_construct(id=uuid4())

    with pytest.raises(ServiceRejectionError) as exc:
        await CoreOrganizationsAPI().apply_onboarding_profile_async(
            _db_without_org(), org, 'home'
        )

    assert str(exc.value) == 'Nie znaleziono organizacji'


async def test_an_organization_that_vanishes_after_onboarding_is_not_for_the_reader() -> (
    None
):
    from unittest.mock import patch

    org = OrganizationDTO.model_construct(id=uuid4())
    api = CoreOrganizationsAPI()

    with (
        patch(
            'app.services._org_reads.get_by_id_async', AsyncMock(return_value=object())
        ),
        patch(
            'app.services.onboarding_service.apply_onboarding_profile_async',
            AsyncMock(),
        ),
        patch.object(api, 'get_async', AsyncMock(return_value=None)),
        pytest.raises(ContractViolationError, match='disappeared after onboarding'),
    ):
        await api.apply_onboarding_profile_async(AsyncMock(), org, 'home')


async def test_a_profile_whose_module_schema_is_unreadable_is_skipped() -> None:
    from types import SimpleNamespace
    from unittest.mock import MagicMock, patch

    from app.services.profile_module_config_service import (
        apply_profile_module_config_async,
    )

    broken = SimpleNamespace(get_settings_schema=lambda: {'type': 'array'})
    with patch(
        'app.services.profile_module_config_service.module_registry.get',
        MagicMock(return_value=broken),
    ):
        changed = await apply_profile_module_config_async(
            AsyncMock(),
            MagicMock(),
            {'demo': {'a': 1}},
            default_modules=['demo'],
            profile_id='home',
            user_id=None,
        )

    assert changed == []
