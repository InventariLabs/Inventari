"""Integration tests for single-module focus mode.

Covered:
- Organization.focus_module with a migration; NULL keeps today's behaviour.
- The enabled set is computed from the choice + its requires by the same
  planner a profile switch uses.
- A focus choice the organization cannot stand behind is rejected with a code.
- Leaving restores the state from before the choice, not the profile defaults.
"""

import pytest
from fastapi import status
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.organization import Organization
from app.models.user import User
from app.services.token_service import create_access_token, get_password_hash

# The Food & Home profile's defaults — focusing on a module that needs none of
# these is what switches them off.
FOOD_HOME_DEFAULTS = [
    'core',
    'items',
    'locations',
    'categories',
    'shopping_lists',
    'recipes',
    'stock_takes',
    'nutrition',
    'vision',
    'stats',
]


def _auth(user: User) -> dict[str, str]:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


@pytest.fixture
def food_home_org(db_session: Session) -> Organization:
    org = Organization(
        name='Focus Org',
        enabled_modules=list(FOOD_HOME_DEFAULTS),
        active_profile_id='food_home',
    )
    db_session.add(org)
    db_session.commit()
    db_session.refresh(org)
    return org


@pytest.fixture
def admin_headers(db_session: Session, food_home_org: Organization) -> dict[str, str]:
    user = User(
        email='focus_admin@example.com',
        hashed_password=get_password_hash('adminpass'),
        full_name='Focus Admin',
        organization_id=food_home_org.id,
        role='admin',
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return _auth(user)


@pytest.mark.integration
class TestFocusPreview:
    def test_preview_reports_the_diff_without_writing(
        self,
        client: TestClient,
        admin_headers: dict[str, str],
        db_session: Session,
        food_home_org: Organization,
    ) -> None:
        response = client.post(
            '/api/v1/modules/focus/preview',
            json={'module_name': 'equipment'},
            headers=admin_headers,
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['applied'] is False
        diff = data['diff']
        # Equipment needs nothing beyond the always-on floor, so the food
        # modules the profile brought are what switch off.
        assert 'equipment' in diff['final_enabled_modules']
        assert 'recipes' in diff['disable_all']
        assert 'shopping_lists' in diff['disable_all']
        # The always-on floor survives the narrowing.
        assert 'items' in diff['final_enabled_modules']
        assert 'stats' in diff['final_enabled_modules']

        db_session.refresh(food_home_org)
        assert food_home_org.focus_module is None
        assert sorted(food_home_org.enabled_modules) == sorted(FOOD_HOME_DEFAULTS)


@pytest.mark.integration
class TestEnterFocusMode:
    def test_entering_narrows_to_the_focus_and_its_floor(
        self,
        client: TestClient,
        admin_headers: dict[str, str],
        db_session: Session,
        food_home_org: Organization,
    ) -> None:
        response = client.post(
            '/api/v1/modules/focus',
            json={'module_name': 'equipment'},
            headers=admin_headers,
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['applied'] is True
        assert data['focus_module'] == 'equipment'

        db_session.refresh(food_home_org)
        assert food_home_org.focus_module == 'equipment'
        # The snapshot carries the state from before the choice.
        assert sorted(food_home_org.pre_focus_enabled_modules) == sorted(
            FOOD_HOME_DEFAULTS
        )
        # The profile's modules are off; the floor and the focus stay.
        assert 'recipes' not in food_home_org.enabled_modules
        assert 'shopping_lists' not in food_home_org.enabled_modules
        assert 'equipment' in food_home_org.enabled_modules
        assert 'items' in food_home_org.enabled_modules
        # The profile itself is untouched.
        assert food_home_org.active_profile_id == 'food_home'

    def test_reject_an_always_on_focus(
        self, client: TestClient, admin_headers: dict[str, str]
    ) -> None:
        response = client.post(
            '/api/v1/modules/focus',
            json={'module_name': 'items'},
            headers=admin_headers,
        )
        assert response.status_code == status.HTTP_409_CONFLICT
        assert response.json()['detail']['code'] == 'focus_module_always_on'

    def test_reject_an_unknown_focus(
        self, client: TestClient, admin_headers: dict[str, str]
    ) -> None:
        response = client.post(
            '/api/v1/modules/focus',
            json={'module_name': 'definitely_not_a_module'},
            headers=admin_headers,
        )
        assert response.status_code == status.HTTP_409_CONFLICT
        assert response.json()['detail']['code'] == 'unknown_module'

    def test_reject_focus_twice(
        self, client: TestClient, admin_headers: dict[str, str]
    ) -> None:
        first = client.post(
            '/api/v1/modules/focus',
            json={'module_name': 'equipment'},
            headers=admin_headers,
        )
        assert first.status_code == status.HTTP_200_OK
        second = client.post(
            '/api/v1/modules/focus',
            json={'module_name': 'maker'},
            headers=admin_headers,
        )
        assert second.status_code == status.HTTP_409_CONFLICT
        assert second.json()['detail']['code'] == 'already_in_focus'


@pytest.mark.integration
class TestExitFocusMode:
    def test_leaving_restores_the_state_before_the_choice_and_keeps_the_choice(
        self,
        client: TestClient,
        admin_headers: dict[str, str],
        db_session: Session,
        food_home_org: Organization,
    ) -> None:
        entered = client.post(
            '/api/v1/modules/focus',
            json={'module_name': 'equipment'},
            headers=admin_headers,
        )
        assert entered.status_code == status.HTTP_200_OK

        left = client.delete('/api/v1/modules/focus', headers=admin_headers)
        assert left.status_code == status.HTTP_200_OK
        assert left.json()['focus_module'] is None

        db_session.refresh(food_home_org)
        assert food_home_org.focus_module is None
        assert food_home_org.pre_focus_enabled_modules is None
        # The pre-choice set comes back, and the module that was chosen stays.
        assert sorted(food_home_org.enabled_modules) == sorted(
            {*FOOD_HOME_DEFAULTS, 'equipment'}
        )
        assert food_home_org.active_profile_id == 'food_home'

    def test_leaving_without_focus_is_refused(
        self, client: TestClient, admin_headers: dict[str, str]
    ) -> None:
        response = client.delete('/api/v1/modules/focus', headers=admin_headers)
        assert response.status_code == status.HTTP_409_CONFLICT
        assert response.json()['detail']['code'] == 'not_in_focus'


@pytest.mark.integration
class TestFocusState:
    def test_no_focus_reads_applied_false(
        self, client: TestClient, admin_headers: dict[str, str]
    ) -> None:
        response = client.get('/api/v1/modules/focus', headers=admin_headers)
        assert response.status_code == status.HTTP_200_OK
        assert response.json()['applied'] is False
        assert response.json()['focus_module'] is None

    def test_focus_state_reflects_the_choice(
        self, client: TestClient, admin_headers: dict[str, str]
    ) -> None:
        entered = client.post(
            '/api/v1/modules/focus',
            json={'module_name': 'equipment'},
            headers=admin_headers,
        )
        assert entered.status_code == status.HTTP_200_OK

        response = client.get('/api/v1/modules/focus', headers=admin_headers)
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['applied'] is True
        assert data['focus_module'] == 'equipment'
        assert 'equipment' in data['enabled_modules']


@pytest.mark.integration
class TestRecipeBackgroundModules:
    def test_recipe_focus_keeps_shopping_through_the_exit(
        self,
        client: TestClient,
        admin_headers: dict[str, str],
        db_session: Session,
        food_home_org: Organization,
    ) -> None:
        previous = [name for name in FOOD_HOME_DEFAULTS if name != 'shopping_lists']
        food_home_org.enabled_modules = previous
        db_session.commit()
        preview = client.post(
            '/api/v1/modules/focus/preview',
            json={'module_name': 'recipes'},
            headers=admin_headers,
        )
        assert preview.status_code == 200
        assert 'shopping_lists' in preview.json()['diff']['final_enabled_modules']
        entered = client.post(
            '/api/v1/modules/focus',
            json={'module_name': 'recipes'},
            headers=admin_headers,
        )
        assert entered.status_code == 200
        db_session.refresh(food_home_org)
        assert 'shopping_lists' in food_home_org.enabled_modules
        left = client.delete('/api/v1/modules/focus', headers=admin_headers)
        assert left.status_code == 200
        db_session.refresh(food_home_org)
        # The chosen module's background provider stays with it.
        assert sorted(food_home_org.enabled_modules) == sorted(
            {*previous, 'shopping_lists'}
        )
