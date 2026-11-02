"""Integration tests for example_widgets module."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration


class TestWidgetsAPI:
    def test_list_empty(self, client: TestClient, widget_auth: dict[str, str]) -> None:
        resp = client.get('/api/v1/example-widgets', headers=widget_auth)
        assert resp.status_code == 200
        assert resp.json() == {
            'items': [],
            'total': 0,
            'limit': 100,
            'offset': 0,
            'has_more': False,
            'total_capped': False,
        }

    def test_create(self, client: TestClient, widget_auth: dict[str, str]) -> None:
        resp = client.post(
            '/api/v1/example-widgets',
            json={'name': 'Test Widget', 'color': 'red', 'quantity': 5},
            headers=widget_auth,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data['name'] == 'Test Widget'
        assert data['color'] == 'red'
        assert data['quantity'] == 5
        assert data['is_active'] is True
        assert 'id' in data

    def test_create_rejects_a_colour_outside_the_set(
        self, client: TestClient, widget_auth: dict[str, str]
    ) -> None:
        resp = client.post(
            '/api/v1/example-widgets',
            json={'name': 'Test Widget', 'color': 'grass green'},
            headers=widget_auth,
        )
        assert resp.status_code == 422

    def test_create_default_quantity(
        self, client: TestClient, widget_auth: dict[str, str]
    ) -> None:
        resp = client.post(
            '/api/v1/example-widgets',
            json={'name': 'Default Qty'},
            headers=widget_auth,
        )
        assert resp.status_code == 201
        assert resp.json()['quantity'] == 0

    def test_get_nonexistent_returns_404(
        self, client: TestClient, widget_auth: dict[str, str]
    ) -> None:
        resp = client.get(f'/api/v1/example-widgets/{uuid4()}', headers=widget_auth)
        assert resp.status_code == 404

    def test_update_nonexistent_returns_404(
        self, client: TestClient, widget_auth: dict[str, str]
    ) -> None:
        resp = client.patch(
            f'/api/v1/example-widgets/{uuid4()}',
            json={'name': 'Nope'},
            headers=widget_auth,
        )
        assert resp.status_code == 404

    def test_delete_nonexistent_returns_404(
        self, client: TestClient, widget_auth: dict[str, str]
    ) -> None:
        resp = client.delete(f'/api/v1/example-widgets/{uuid4()}', headers=widget_auth)
        assert resp.status_code == 404

    def test_org_b_sees_empty_list(
        self,
        client: TestClient,
        widget_auth: dict[str, str],
        widget_auth_b: dict[str, str],
    ) -> None:
        """Multi-tenancy: org B sees no widgets from org A."""
        client.post(
            '/api/v1/example-widgets',
            json={'name': 'Org A Widget'},
            headers=widget_auth,
        )
        resp = client.get('/api/v1/example-widgets', headers=widget_auth_b)
        assert resp.status_code == 200
        assert resp.json()['items'] == []
        assert resp.json()['total'] == 0
