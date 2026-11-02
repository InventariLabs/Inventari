from uuid import uuid4

import pytest
from fastapi import APIRouter, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.modules import BaseModule, CategoryDeclaration, ModuleMetadata
from app.models.category import Category
from app.models.organization import Organization
from app.models.user import User
from app.services.auth_service import get_password_hash
from app.services.token_service import create_access_token


def _auth(user: User) -> dict:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


@pytest.fixture
async def mod_org(real_async_db_session: AsyncSession) -> Organization:
    org = Organization(
        name='Mod API Test Org',
        enabled_modules=[
            'core',
            'items',
            'locations',
            'categories',
            'stats',
            'shopping_lists',
            'vision',
            'stock_takes',
        ],
    )
    real_async_db_session.add(org)
    await real_async_db_session.commit()
    await real_async_db_session.refresh(org)
    return org


@pytest.fixture
async def mod_user(real_async_db_session: AsyncSession, mod_org: Organization) -> User:
    user = User(
        email=f'modapi_{uuid4().hex[:8]}@test.com',
        hashed_password=get_password_hash('pass'),
        full_name='Mod API User',
        organization_id=mod_org.id,
        role='admin',
        is_active=True,
    )
    real_async_db_session.add(user)
    await real_async_db_session.commit()
    await real_async_db_session.refresh(user)
    return user


@pytest.mark.integration
@pytest.mark.asyncio
class TestModularAPI:
    async def test_available_modules_endpoint(self, real_async_client, mod_user):
        """Tests that the available modules endpoint returns registered modules."""
        response = await real_async_client.get(
            '/api/v1/modules/available', headers=_auth(mod_user)
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()['items']

        module_names = [m['name'] for m in data]
        assert 'stats' in module_names
        assert 'shopping_lists' in module_names
        assert 'vision' in module_names
        assert 'stock_takes' in module_names

    async def test_dynamic_routes_registration(self, real_async_client):
        """Tests that dynamically registered routes are actually reachable."""
        response = await real_async_client.get('/api/v1/stats/overview')
        # 401 means route exists but needs auth; 404 means NOT registered
        assert response.status_code != status.HTTP_404_NOT_FOUND

    async def test_always_on_modules_always_returned(self, real_async_client, mod_user):
        """Ensure frontend-only always-on modules are returned even when the org
        has an explicit enabled_modules list that pre-dates them being added."""
        response = await real_async_client.get(
            '/api/v1/modules/my', headers=_auth(mod_user)
        )
        assert response.status_code == status.HTTP_200_OK
        modules = response.json()

        for required in (
            'core',
            'inventory',
            'spaces',
            'dashboard',
            'admin',
            'settings',
        ):
            assert required in modules, (
                f"'{required}' missing from /modules/my response"
            )

    async def test_printing_is_always_on(self, real_async_client, mod_user):
        """Printed QR stickers point at ``/labels/scan/:code``, and the frontend
        registers a route only for enabled modules. No product profile listed
        ``printing``, so every fresh organisation shipped stickers that lead to
        a 404 — labelling is not an optional capability, it is part of the box.
        """
        response = await real_async_client.get(
            '/api/v1/modules/my', headers=_auth(mod_user)
        )
        assert response.status_code == status.HTTP_200_OK
        assert 'printing' in response.json()

        response = await real_async_client.post(
            '/api/v1/modules/toggle',
            headers=_auth(mod_user),
            json={'module_name': 'printing', 'enabled': False},
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

        response = await real_async_client.get(
            '/api/v1/modules/my', headers=_auth(mod_user)
        )
        assert 'printing' in response.json()

    async def test_announcements_is_always_on(self, real_async_client, mod_user):
        """The notification tray and the announcement banner are shell furniture,
        not a capability an organisation opts into. The frontend gates both on
        ``announcements`` being in this list, and no product profile could ever
        put it there — the name is not a registered backend module, so the
        sanitiser dropped it and the bell was missing from every organisation
        while notifications piled up unread.
        """
        response = await real_async_client.get(
            '/api/v1/modules/my', headers=_auth(mod_user)
        )
        assert response.status_code == status.HTTP_200_OK
        assert 'announcements' in response.json()

        response = await real_async_client.post(
            '/api/v1/modules/toggle',
            headers=_auth(mod_user),
            json={'module_name': 'announcements', 'enabled': False},
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

        response = await real_async_client.get(
            '/api/v1/modules/my', headers=_auth(mod_user)
        )
        assert 'announcements' in response.json()

    async def test_module_toggle_persists(self, real_async_client, mod_user):
        """Tests enabling/disabling a module for a organization."""
        response = await real_async_client.get(
            '/api/v1/modules/my', headers=_auth(mod_user)
        )
        initial_modules = response.json()

        test_module = 'vision'
        is_enabled = test_module in initial_modules

        response = await real_async_client.post(
            '/api/v1/modules/toggle',
            headers=_auth(mod_user),
            json={'module_name': test_module, 'enabled': not is_enabled},
        )
        assert response.status_code == status.HTTP_200_OK

        response = await real_async_client.get(
            '/api/v1/modules/my', headers=_auth(mod_user)
        )
        updated_modules = response.json()
        if not is_enabled:
            assert test_module in updated_modules
        else:
            assert test_module not in updated_modules

    async def test_toggle_with_stale_snapshot_does_not_lose_modules(
        self, real_async_db_session, async_engine_fixture, mod_org, mod_user
    ):
        """An interleaved toggle must not drop a concurrently enabled module.

        Session A holds an org snapshot taken before session B's toggle
        commits. Without the FOR UPDATE re-read in toggle_module, A's commit
        writes its stale enabled_modules over B's, silently dropping B's
        module — observed in E2E as "Module 'shopping_lists' is not enabled"
        right after enableAllModules.
        """
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from app.core.contracts import UserContextDTO
        from app.services._org_reads import get_by_id_async
        from app.services.module_service import ModuleService

        user_ctx = UserContextDTO(
            id=mod_user.id,
            organization_id=mod_org.id,
            role=mod_user.role,
            email=mod_user.email,
        )

        # A takes its snapshot BEFORE B's toggle commits.
        stale_org = await get_by_id_async(real_async_db_session, mod_org.id)
        assert stale_org is not None

        session_factory = async_sessionmaker(
            async_engine_fixture, class_=AsyncSession, expire_on_commit=False
        )
        async with session_factory() as session_b:
            org_b = await get_by_id_async(session_b, mod_org.id)
            assert org_b is not None
            await ModuleService.toggle_module(
                session_b, org_b, 'api_keys', True, user_ctx
            )
            await session_b.commit()

        # A toggles a different module with its now-stale snapshot.
        result = await ModuleService.toggle_module(
            real_async_db_session, stale_org, 'webhooks', True, user_ctx
        )

        assert 'webhooks' in result
        assert 'api_keys' in result, (
            'B toggle was lost: A committed its stale enabled_modules snapshot'
        )

    async def test_disable_blocked_when_dependent_enabled(
        self, real_async_client, real_async_db_session, mod_org
    ):
        """Disabling a module that other enabled modules depend on must 403."""
        from app.models.user import User
        from app.services.auth_service import get_password_hash
        from app.services.token_service import create_access_token

        # Enable both documents and purchase_orders (which requires documents)
        mod_org.enabled_modules = [
            'core',
            'items',
            'locations',
            'categories',
            'stats',
            'warehouse',
            'purchase_orders',
        ]
        real_async_db_session.add(mod_org)
        await real_async_db_session.commit()

        user = User(
            email=f'dep_{uuid4().hex[:8]}@test.com',
            hashed_password=get_password_hash('pass'),
            full_name='Dep Test User',
            organization_id=mod_org.id,
            role='admin',
            is_active=True,
        )
        real_async_db_session.add(user)
        await real_async_db_session.commit()
        await real_async_db_session.refresh(user)

        headers = {
            'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
        }

        # Attempt to disable documents while purchase_orders is still enabled
        response = await real_async_client.post(
            '/api/v1/modules/toggle',
            headers=headers,
            json={'module_name': 'warehouse', 'enabled': False},
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
        message = response.json()['detail']['message']
        assert 'depends on' in message
        # Named as the store card names them, not by their slugs.
        assert "'Purchase Orders' depends on 'Warehouse'" in message, message

    async def test_enable_refusal_names_the_required_module_as_the_store_does(
        self, real_async_client, mod_org, mod_user
    ):
        """Purchase orders without the Warehouse: the refusal said "Module
        'warehouse' must be enabled first." — the slug, where the store card
        the administrator just pressed names the module "Warehouse"."""
        response = await real_async_client.post(
            '/api/v1/modules/toggle',
            headers=_auth(mod_user),
            json={'module_name': 'purchase_orders', 'enabled': True},
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        message = response.json()['detail']['message']
        assert "'Warehouse'" in message, message
        assert "'warehouse'" not in message, message

    async def test_system_on_enable_merges_fields_per_organization(
        self, real_async_db_session: AsyncSession, mod_org: Organization
    ):
        """Declared categories seed per organization and merge field definitions.

        The startup ``sync_categories`` used to write one installation-wide
        row (``organization_id IS NULL``) per declared category; the merge
        behaviour now lives in ``BaseModule.system_on_enable``, scoped to the
        enabling organization.
        """

        class MockModule(BaseModule):
            def __init__(self, categories_decl):
                self._categories = categories_decl

            @property
            def metadata(self) -> ModuleMetadata:
                return ModuleMetadata(
                    name='test_module',
                    version='1.0.0',
                    display_name='Test Module',
                    description='Test',
                    icon='test',
                    categories=self._categories,
                )

            def register_routes(self) -> APIRouter:
                return APIRouter()

        initial_fields = [{'key': 'sys_field', 'label': 'System Field', 'type': 'text'}]
        cat_decl = CategoryDeclaration(
            code='TEST_CAT', name='Test Category', field_definitions=initial_fields
        )

        module = MockModule([cat_decl])
        await module.system_on_enable(mod_org.id, real_async_db_session)
        await real_async_db_session.commit()

        result = await real_async_db_session.execute(
            select(Category).where(Category.code == 'TEST_CAT')
        )
        cats = result.scalars().all()
        assert len(cats) == 1
        cat = cats[0]
        assert cat.organization_id == mod_org.id
        assert len(cat.field_definitions) == 1
        assert cat.field_definitions[0]['key'] == 'sys_field'
        assert cat.field_definitions[0].get('is_system') is True

        user_field = {
            'key': 'user_field',
            'label': 'User Field',
            'type': 'number',
            'is_system': False,
        }
        cat.field_definitions = cat.field_definitions + [user_field]
        await real_async_db_session.commit()

        updated_fields = [
            {
                'key': 'sys_field',
                'label': 'System Field Updated',
                'type': 'text',
            },
            {
                'key': 'new_sys_field',
                'label': 'New System Field',
                'type': 'text',
            },
        ]
        updated_cat_decl = CategoryDeclaration(
            code='TEST_CAT',
            name='Test Category',
            field_definitions=updated_fields,
        )

        module_updated = MockModule([updated_cat_decl])
        await module_updated.system_on_enable(mod_org.id, real_async_db_session)
        await real_async_db_session.commit()

        await real_async_db_session.refresh(cat)
        keys = [f['key'] for f in cat.field_definitions]
        assert 'sys_field' in keys
        assert 'user_field' in keys
        assert 'new_sys_field' in keys

        sys_f = next(f for f in cat.field_definitions if f['key'] == 'sys_field')
        assert sys_f['label'] == 'System Field Updated'
        assert sys_f.get('is_system') is True

        # A second organization gets its own copy; nothing is shared.
        other_org = Organization(name='Other Org', enabled_modules=['core'])
        real_async_db_session.add(other_org)
        await real_async_db_session.commit()
        await module_updated.system_on_enable(other_org.id, real_async_db_session)
        await real_async_db_session.commit()

        result = await real_async_db_session.execute(
            select(Category).where(Category.code == 'TEST_CAT')
        )
        cats = result.scalars().all()
        assert len(cats) == 2
        assert {c.organization_id for c in cats} == {mod_org.id, other_org.id}

    async def test_system_on_enable_creates_no_global_categories(
        self, real_async_db_session: AsyncSession, mod_org: Organization
    ):
        """Enabling a module never writes ``organization_id IS NULL`` rows."""
        from app.modules.equipment.module import EquipmentModule

        await EquipmentModule().system_on_enable(mod_org.id, real_async_db_session)
        await real_async_db_session.commit()

        result = await real_async_db_session.execute(
            select(Category).where(
                Category.organization_id.is_(None),
                Category.module_name.is_not(None),
            )
        )
        assert result.scalars().all() == []

        owned = await real_async_db_session.execute(
            select(Category).where(
                Category.organization_id == mod_org.id,
                Category.module_name == 'equipment',
            )
        )
        codes = {c.code for c in owned.scalars()}
        assert {'LAPTOP', 'SERVER', 'OTHER_EQUIPMENT'} <= codes
