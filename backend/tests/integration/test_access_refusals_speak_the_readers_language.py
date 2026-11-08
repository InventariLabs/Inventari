"""The refusals of members, roles, sign-up, onboarding and module switching
answer in the reader's language.

Each of these used to be an English sentence raised in the service or the
router, so a Polish reader got English under a language stamp. They are
catalogue keys now: the sentence is looked up in the request language, and the
machine code a client branches on stays what it was.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from fastapi import status

from app.core.exceptions import ConflictException
from app.core.testing import ModuleTestHelper
from app.i18n import service as i18n_service
from app.models.organization import Organization
from app.models.user import User
from app.services.token_service import create_access_token

pytestmark = pytest.mark.integration

PL = {'Accept-Language': 'pl'}


def _auth(user: User, extra: dict[str, str] | None = None) -> dict[str, str]:
    token = create_access_token(data={'sub': str(user.id)})
    return {'Authorization': f'Bearer {token}', **(extra or {})}


@pytest.fixture
def polish():
    """Run the code under test as a Polish request, then forget the language."""
    i18n_service.set_current_lang('pl')
    yield
    i18n_service._current_lang.set(None)


async def _admin(session, *, enabled_modules=None, **org_fields) -> User:
    org = Organization(
        name=f'Refusals {uuid.uuid4().hex[:8]}',
        enabled_modules=enabled_modules or ['core'],
        **org_fields,
    )
    session.add(org)
    await session.flush()
    user = User(
        email=f'refusals_{uuid.uuid4().hex[:8]}@example.com',
        hashed_password='x',
        full_name='Refusals Admin',
        organization_id=org.id,
        role='admin',
        is_active=True,
    )
    session.add(user)
    await session.commit()
    return user


async def _custom_administrator(session, org) -> User:
    """A member who administers through a custom role, not the ``admin`` level."""
    from app.models.role import Role, UserRole

    user = await ModuleTestHelper.create_user_async(
        session, org, email=f'custom-{uuid.uuid4().hex[:8]}@example.com', role='user'
    )
    role = Role(
        name=f'custom_{uuid.uuid4().hex[:6]}',
        permissions=['admin:access'],
        is_system=False,
        organization_id=org.id,
    )
    session.add(role)
    await session.flush()
    session.add(UserRole(user_id=user.id, role_id=role.id))
    await session.commit()
    return user


@pytest.mark.asyncio
class TestSoleAdministratorOverHttp:
    async def test_demoting_the_last_administrator_is_refused_in_polish(
        self, real_async_client, real_async_db_session
    ):
        sole = await _admin(real_async_db_session)
        org = await real_async_db_session.get(Organization, sole.organization_id)
        actor = await _custom_administrator(real_async_db_session, org)

        response = await real_async_client.patch(
            f'/api/v1/organizations/my/members/{sole.id}/role',
            json={'role': 'user'},
            headers=_auth(actor, PL),
        )

        assert response.status_code == status.HTTP_409_CONFLICT, response.text
        detail = response.json()['detail']
        assert detail['code'] == 'SOLE_ADMINISTRATOR'
        assert detail['message'] == (
            'Nie można zmienić roli jedynego administratora. '
            'Najpierw awansuj innego członka.'
        )

    async def test_the_founder_leaving_alone_is_refused_in_polish(
        self, real_async_client, real_async_db_session
    ):
        founder = await _admin(real_async_db_session)
        org = await real_async_db_session.get(Organization, founder.organization_id)
        org.created_by = founder.id
        await real_async_db_session.commit()

        response = await real_async_client.post(
            '/api/v1/organizations/my/leave', headers=_auth(founder, PL)
        )

        assert response.status_code == status.HTTP_409_CONFLICT, response.text
        detail = response.json()['detail']
        assert detail['code'] == 'SOLE_ADMINISTRATOR'
        assert detail['message'] == (
            'Nie możesz opuścić organizacji jako jedyny administrator. '
            'Najpierw wyznacz innego administratora.'
        )


@pytest.mark.asyncio
class TestSoleAdministrator:
    async def test_the_last_administrator_cannot_be_demoted_in_polish(
        self, real_async_db_session, polish
    ):
        from app.services._org_membership import change_member_role

        org = Organization(name='Solo Admin Org')
        real_async_db_session.add(org)
        await real_async_db_session.flush()
        admin = await ModuleTestHelper.create_user_async(
            real_async_db_session, org, email='solo-pl@example.com', role='admin'
        )

        with pytest.raises(ConflictException) as refused:
            await change_member_role(real_async_db_session, admin, 'user', org.id)

        assert refused.value.detail['code'] == 'SOLE_ADMINISTRATOR'
        assert refused.value.detail['message'] == (
            'Nie można zmienić roli jedynego administratora. '
            'Najpierw awansuj innego członka.'
        )

    async def test_the_founder_cannot_leave_as_the_only_administrator_in_polish(
        self, real_async_db_session, polish
    ):
        from app.services._org_membership import leave_organization

        org = Organization(name='Founder Org')
        real_async_db_session.add(org)
        await real_async_db_session.flush()
        admin = await ModuleTestHelper.create_user_async(
            real_async_db_session, org, email='founder-pl@example.com', role='admin'
        )
        org.created_by = admin.id
        await real_async_db_session.flush()

        with pytest.raises(ConflictException) as refused:
            await leave_organization(real_async_db_session, admin.id, org.id)

        assert refused.value.detail['code'] == 'SOLE_ADMINISTRATOR'
        assert refused.value.detail['message'] == (
            'Nie możesz opuścić organizacji jako jedyny administrator. '
            'Najpierw wyznacz innego administratora.'
        )


@pytest.mark.asyncio
class TestOrganizationMemberLimit:
    async def test_a_full_organization_refuses_an_invitation_in_polish(
        self, real_async_client, real_async_db_session, monkeypatch
    ):
        from app.core.contributions import contribution_registry

        admin = await _admin(real_async_db_session)
        monkeypatch.setattr(
            contribution_registry, 'check_quota', AsyncMock(return_value=False)
        )

        response = await real_async_client.post(
            '/api/v1/organizations/my/invitation-code',
            json={'role': 'user', 'email': 'anna@example.com'},
            headers=_auth(admin, PL),
        )

        assert response.status_code == status.HTTP_409_CONFLICT, response.text
        detail = response.json()['detail']
        assert detail['code'] == 'ORG_MEMBER_LIMIT'
        assert detail['message'] == (
            'Osiągnięto limit członków organizacji. '
            'Przejdź na Inventari Cloud, aby mieć więcej miejsc.'
        )


@pytest.mark.asyncio
class TestSuperuserOnlyDoor:
    async def test_an_ordinary_admin_is_refused_in_polish(
        self, real_async_client, real_async_db_session
    ):
        admin = await _admin(real_async_db_session)

        response = await real_async_client.get(
            '/api/v1/users', headers=_auth(admin, PL)
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.text
        assert response.json()['detail']['message'] == (
            'Ta czynność wymaga uprawnień superużytkownika'
        )


@pytest.mark.asyncio
class TestRegistration:
    async def test_a_taken_address_refuses_in_the_language_of_the_form(
        self, real_async_client, real_async_db_session, monkeypatch
    ):
        from app.services.auth_service import AuthService

        taken = await _admin(real_async_db_session)
        monkeypatch.setattr(
            AuthService,
            'find_usable_invitation_async',
            AsyncMock(return_value=object()),
        )

        response = await real_async_client.post(
            '/api/v1/auth/register',
            json={
                'email': taken.email,
                'password': 'Str0ng-Passw0rd!x',
                'full_name': 'Someone',
                'invite_code': 'whatever',
                'preferred_language': 'pl',
            },
            headers=PL,
        )

        assert response.status_code == status.HTTP_409_CONFLICT, response.text
        detail = response.json()['detail']
        assert detail['code'] == 'REGISTRATION_FAILED'
        assert detail['message'] == (
            'Nie udało się dokończyć rejestracji. '
            'Spróbuj ponownie lub skontaktuj się z pomocą.'
        )


@pytest.mark.asyncio
class TestOnboarding:
    async def test_a_second_setup_is_refused_in_polish(
        self, real_async_client, real_async_db_session
    ):
        admin = await _admin(real_async_db_session, onboarding_completed=True)

        response = await real_async_client.post(
            '/api/v1/onboarding/setup',
            json={'profile_id': 'clean_core'},
            headers=_auth(admin, PL),
        )

        assert response.status_code == status.HTTP_409_CONFLICT, response.text
        detail = response.json()['detail']
        assert detail['code'] == 'ONBOARDING_ALREADY_COMPLETED'
        assert detail['message'] == (
            'Wdrożenie jest już ukończone — użyj /switch-profile'
        )


@pytest.mark.asyncio
class TestFocusMode:
    async def _focus(self, client, admin, module: str):
        return await client.post(
            '/api/v1/modules/focus',
            json={'module_name': module},
            headers=_auth(admin, PL),
        )

    async def test_an_always_on_module_cannot_be_the_focus_in_polish(
        self, real_async_client, real_async_db_session
    ):
        admin = await _admin(real_async_db_session)

        response = await self._focus(real_async_client, admin, 'core')

        assert response.status_code == status.HTTP_409_CONFLICT, response.text
        detail = response.json()['detail']
        assert detail['code'] == 'focus_module_always_on'
        assert detail['message'] == (
            'Moduł „core” jest zawsze włączony i nie może być jedynym skupieniem.'
        )

    async def test_an_unknown_module_is_refused_in_polish(
        self, real_async_client, real_async_db_session
    ):
        admin = await _admin(real_async_db_session)

        response = await self._focus(real_async_client, admin, 'no_such_module')

        assert response.status_code == status.HTTP_409_CONFLICT, response.text
        detail = response.json()['detail']
        assert detail['code'] == 'unknown_module'
        assert detail['message'] == 'Moduł „no_such_module” nie jest zarejestrowany.'

    async def test_leaving_without_focus_is_refused_in_polish(
        self, real_async_client, real_async_db_session
    ):
        admin = await _admin(real_async_db_session)

        response = await real_async_client.delete(
            '/api/v1/modules/focus', headers=_auth(admin, PL)
        )

        assert response.status_code == status.HTTP_409_CONFLICT, response.text
        detail = response.json()['detail']
        assert detail['code'] == 'not_in_focus'
        assert detail['message'] == (
            'Organizacja nie jest w trybie skupienia na jednym module.'
        )

    async def test_a_second_focus_is_refused_in_polish(
        self, real_async_client, real_async_db_session
    ):
        admin = await _admin(
            real_async_db_session, enabled_modules=['core', 'items', 'recipes']
        )
        first = await real_async_client.post(
            '/api/v1/modules/focus',
            json={'module_name': 'recipes'},
            headers=_auth(admin),
        )
        assert first.status_code == status.HTTP_200_OK, first.text

        response = await self._focus(real_async_client, admin, 'items')

        assert response.status_code == status.HTTP_409_CONFLICT, response.text
        detail = response.json()['detail']
        assert detail['code'] == 'already_in_focus'
        assert detail['message'] == (
            'Organizacja jest już skupiona na module „recipes”.'
        )


class TestProfileSwitchPlanner:
    """The planner's refusals carry the sentence and the structured context."""

    def test_an_unknown_module_names_the_modules_in_polish(self, polish):
        from app.services.profile_switch_planner import (
            ProfileSwitchError,
            _validate_profile_modules,
        )

        with pytest.raises(ProfileSwitchError) as refused:
            _validate_profile_modules(
                target={'ghost', 'phantom'},
                registered=set(),
                always_on=set(),
                allowed_modules=None,
            )

        assert refused.value.code == 'unknown_module'
        assert refused.value.context == {'unknown_modules': ['ghost', 'phantom']}
        assert str(refused.value) == (
            'Profil odwołuje się do niezarejestrowanych modułów: ghost, phantom'
        )

    def test_a_module_the_organization_may_not_use_is_refused_in_polish(self, polish):
        from app.services.profile_switch_planner import (
            ProfileSwitchError,
            _validate_profile_modules,
        )

        with pytest.raises(ProfileSwitchError) as refused:
            _validate_profile_modules(
                target={'items', 'wms'},
                registered={'items', 'wms'},
                always_on=set(),
                allowed_modules=['items'],
            )

        assert refused.value.code == 'module_not_allowed'
        assert str(refused.value) == 'Moduły niedozwolone dla tej organizacji: wms'

    def test_a_cycle_is_refused_in_polish(self, polish):
        from app.services.profile_switch_planner import (
            ProfileSwitchError,
            _topological_order,
        )

        with pytest.raises(ProfileSwitchError) as refused:
            _topological_order({'a', 'b'}, {'a': ['b'], 'b': ['a']})

        assert refused.value.code == 'dependency_cycle'
        assert str(refused.value) == (
            'Wykryto zależność cykliczną między modułami: a, b'
        )

    def test_a_requirement_nobody_registered_is_refused_in_polish(self, polish):
        from app.services.profile_switch_planner import (
            ProfileSwitchError,
            _dependency_closure,
        )

        with pytest.raises(ProfileSwitchError) as refused:
            _dependency_closure({'a'}, {'a': ['ghost']})

        assert refused.value.code == 'dependency_closure'
        assert str(refused.value) == (
            'Moduł „a” wymaga modułu „ghost”, który nie jest zarejestrowany.'
        )


@pytest.mark.asyncio
class TestProfileSwitchOverHttp:
    async def _preview(self, client, admin, profile, monkeypatch):
        from app.api import onboarding as onboarding_api

        monkeypatch.setattr(onboarding_api, 'get_profile', lambda _id: profile)
        return await client.post(
            '/api/v1/onboarding/switch-profile',
            json={'profile_id': profile.id},
            headers=_auth(admin, PL),
        )

    @staticmethod
    def _profile(modules):
        from app.core.product_profiles import ProductProfile

        return ProductProfile(
            id='refusals_probe',
            name='Probe',
            description='Probe',
            default_modules=modules,
            seed_profile='clean_core',
        )

    async def test_an_unregistered_module_is_refused_in_polish(
        self, real_async_client, real_async_db_session, monkeypatch
    ):
        admin = await _admin(real_async_db_session)

        response = await self._preview(
            real_async_client, admin, self._profile(['ghost']), monkeypatch
        )

        assert response.status_code == status.HTTP_409_CONFLICT, response.text
        detail = response.json()['detail']
        assert detail['code'] == 'unknown_module'
        assert detail['message'] == (
            'Profil odwołuje się do niezarejestrowanych modułów: ghost'
        )


class TestModuleDependencyCycle:
    def test_a_cycle_in_the_requirements_is_refused_in_polish(
        self, polish, monkeypatch
    ):
        from app.api import modules as modules_api
        from app.core.exceptions import ServiceRejectionError

        class _Meta:
            requires = ['b']

        class _Module:
            metadata = _Meta()

        monkeypatch.setattr(modules_api.module_registry, 'get', lambda name: _Module())
        monkeypatch.setattr(modules_api, 'is_always_on', lambda name: False)

        with pytest.raises(ServiceRejectionError) as refused:
            modules_api._check_module_dependencies('a', ['b'])

        assert refused.value.code == 'MODULE_DEPENDENCY_CYCLE'
        assert str(refused.value) == (
            'Wykryto zależność cykliczną z udziałem modułu „b”'
        )


@pytest.mark.asyncio
class TestModuleSettingsOrganizationMissing:
    async def test_an_unknown_organization_is_refused_in_polish(
        self, real_async_db_session, polish
    ):
        from app.core.exceptions import ServiceRejectionError
        from app.services.module_service import ModuleService

        with pytest.raises(ServiceRejectionError) as refused:
            await ModuleService.update_module_settings_async(
                real_async_db_session, uuid.uuid4(), 'approvals', {}
            )

        assert str(refused.value) == 'Nie znaleziono organizacji'


@pytest.mark.asyncio
class TestModuleSettingsOverHttp:
    async def test_a_vanished_organization_is_refused_in_polish(
        self, real_async_client, real_async_db_session, monkeypatch
    ):
        from app.services import _org_reads

        admin = await _admin(real_async_db_session)
        monkeypatch.setattr(_org_reads, 'get_by_id_async', AsyncMock(return_value=None))

        response = await real_async_client.put(
            '/api/v1/modules/approvals/settings', json={}, headers=_auth(admin, PL)
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.text
        assert response.json()['detail']['message'] == 'Nie znaleziono organizacji'


class TestSecretsSpeakToOperators:
    """A secret's refusals are for the log: no reader is handed their text."""

    def test_the_unbound_secret_error_is_not_reader_facing(self):
        from app.services.crypto_service import (
            ModuleSecretBindingError,
            UndecryptableSecretError,
        )

        assert ModuleSecretBindingError.reader_facing is False
        assert UndecryptableSecretError.reader_facing is False

    def test_a_decorated_endpoint_does_not_show_a_binding_refusal(self):
        from app.core.exceptions import _map_exception
        from app.services.crypto_service import ModuleSecretBindingError

        assert _map_exception(ModuleSecretBindingError('internal')) is None

    def test_a_plain_permission_error_is_still_a_403(self):
        from app.core.exceptions import _map_exception

        refusal = _map_exception(PermissionError('no'))

        assert refusal is not None
        assert refusal.status_code == status.HTTP_403_FORBIDDEN
