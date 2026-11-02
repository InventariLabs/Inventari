"""Zero-boilerplate tests using @pytest.mark.module() plugin fixtures.

Demonstrates how ``@pytest.mark.module('example_widgets')`` replaces
~60 lines of manual org/user/auth fixtures with 4 auto-injected fixtures:
``module_org``, ``module_user``, ``module_auth_headers``, ``module_client``.
"""

import pytest
from fastapi.testclient import TestClient

from app.models.organization import Organization


@pytest.mark.integration
@pytest.mark.module('example_widgets')
class TestWidgetsPlugin:
    """Widget tests with zero boilerplate — plugin handles org, user, auth."""

    def test_create_widget(
        self,
        module_client: TestClient,
        module_auth_headers: dict[str, str],
    ) -> None:
        resp = module_client.post(
            '/api/v1/example-widgets',
            json={'name': 'Plugin Widget', 'color': 'green', 'quantity': 3},
            headers=module_auth_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data['name'] == 'Plugin Widget'
        assert data['color'] == 'green'
        assert data['quantity'] == 3
        assert data['is_active'] is True

    def test_list_widgets_empty(
        self,
        module_client: TestClient,
        module_auth_headers: dict[str, str],
    ) -> None:
        resp = module_client.get(
            '/api/v1/example-widgets',
            headers=module_auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()['items'] == []

    def test_org_has_module_enabled(self, module_org: Organization) -> None:
        assert 'example_widgets' in module_org.enabled_modules
        assert 'core' in module_org.enabled_modules
