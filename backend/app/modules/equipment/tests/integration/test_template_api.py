"""
Integration tests for equipment document template CRUD endpoints.

Covers:
- POST /equipment/templates — create
- GET /equipment/templates — list
- GET /equipment/templates/{id} — get
- PUT /equipment/templates/{id} — update
- DELETE /equipment/templates/{id} — delete
- GET /equipment/protocol/placeholders
- POST /equipment/templates/seed-defaults
"""

from typing import Any, cast

import pytest
from fastapi import status
from starlette.testclient import TestClient

from app.models.item import Item


@pytest.mark.integration
class TestDocumentTemplateCRUD:
    def test_create_template_success(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        response = client.post(
            '/api/v1/equipment/templates',
            headers=eq_auth_headers,
            json={
                'name': 'Handover Protocol',
                'module': 'equipment',
                'body_html': '<html><body>Test {{item_name}}</body></html>',
                'document_type': 'CHECKOUT',
                'is_default': False,
            },
        )
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data['name'] == 'Handover Protocol'
        assert data['document_type'] == 'CHECKOUT'
        assert data['is_default'] is False
        assert 'id' in data

    def test_a_type_this_module_cannot_print_is_refused(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        """The write schema took any fifty characters, and the screen had no
        label for what came back — so a stray value printed as a raw token."""
        response = client.post(
            '/api/v1/equipment/templates',
            headers=eq_auth_headers,
            json={
                'name': 'Return Protocol',
                'module': 'equipment',
                'body_html': '<html><body>x</body></html>',
                'document_type': 'RETURN',
            },
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_an_unnamed_type_defaults_to_one_this_module_prints(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        """The shared schema defaulted to 'DEFAULT', which this module renders
        for nothing and the templates tab has no label for."""
        response = client.post(
            '/api/v1/equipment/templates',
            headers=eq_auth_headers,
            json={
                'name': 'Nameless',
                'module': 'equipment',
                'body_html': '<html><body>x</body></html>',
            },
        )
        assert response.status_code == status.HTTP_201_CREATED, response.text
        assert response.json()['document_type'] == 'CHECKOUT'

    def test_an_edit_cannot_move_a_template_out_of_the_vocabulary(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        created = client.post(
            '/api/v1/equipment/templates',
            headers=eq_auth_headers,
            json={
                'name': 'Handover',
                'module': 'equipment',
                'body_html': '<html><body>x</body></html>',
                'document_type': 'CHECKOUT',
            },
        )
        template_id = created.json()['id']

        response = client.put(
            f'/api/v1/equipment/templates/{template_id}',
            headers=eq_auth_headers,
            json={'document_type': 'RETURN'},
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_create_default_template_clears_previous_default(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        client.post(
            '/api/v1/equipment/templates',
            headers=eq_auth_headers,
            json={
                'name': 'First Default',
                'module': 'equipment',
                'body_html': '<p>First</p>',
                'document_type': 'CHECKOUT',
                'is_default': True,
            },
        )
        r2 = client.post(
            '/api/v1/equipment/templates',
            headers=eq_auth_headers,
            json={
                'name': 'Second Default',
                'module': 'equipment',
                'body_html': '<p>Second</p>',
                'document_type': 'CHECKOUT',
                'is_default': True,
            },
        )
        assert r2.status_code == status.HTTP_201_CREATED

        list_r = client.get('/api/v1/equipment/templates', headers=eq_auth_headers)
        templates = list_r.json()['items']
        defaults = [t for t in templates if t['is_default']]
        assert len(defaults) == 1
        assert defaults[0]['name'] == 'Second Default'

    def test_list_templates_empty(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        response = client.get('/api/v1/equipment/templates', headers=eq_auth_headers)
        assert response.status_code == status.HTTP_200_OK
        assert isinstance(response.json()['items'], list)

    def test_list_templates_returns_created(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        client.post(
            '/api/v1/equipment/templates',
            headers=eq_auth_headers,
            json={
                'name': 'Template A',
                'module': 'equipment',
                'body_html': '<p>A</p>',
            },
        )
        response = client.get('/api/v1/equipment/templates', headers=eq_auth_headers)
        assert response.status_code == status.HTTP_200_OK
        names = [t['name'] for t in response.json()['items']]
        assert 'Template A' in names

    def test_get_template_by_id(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        create_r = client.post(
            '/api/v1/equipment/templates',
            headers=eq_auth_headers,
            json={
                'name': 'Fetch Me',
                'module': 'equipment',
                'body_html': '<p>Fetch</p>',
            },
        )
        tpl_id = create_r.json()['id']

        response = client.get(
            f'/api/v1/equipment/templates/{tpl_id}',
            headers=eq_auth_headers,
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()['name'] == 'Fetch Me'

    def test_get_nonexistent_template_returns_404(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        from uuid import uuid4

        response = client.get(
            f'/api/v1/equipment/templates/{uuid4()}',
            headers=eq_auth_headers,
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_update_template_name(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        create_r = client.post(
            '/api/v1/equipment/templates',
            headers=eq_auth_headers,
            json={
                'name': 'Old Name',
                'module': 'equipment',
                'body_html': '<p>Old</p>',
            },
        )
        tpl_id = create_r.json()['id']

        response = client.put(
            f'/api/v1/equipment/templates/{tpl_id}',
            headers=eq_auth_headers,
            json={'name': 'New Name'},
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()['name'] == 'New Name'

    def test_update_template_set_default(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        create_r = client.post(
            '/api/v1/equipment/templates',
            headers=eq_auth_headers,
            json={
                'name': 'Future Default',
                'module': 'equipment',
                'body_html': '<p>Default</p>',
                'is_default': False,
            },
        )
        tpl_id = create_r.json()['id']

        response = client.put(
            f'/api/v1/equipment/templates/{tpl_id}',
            headers=eq_auth_headers,
            json={'is_default': True},
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()['is_default'] is True

    def test_update_nonexistent_returns_404(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        from uuid import uuid4

        response = client.put(
            f'/api/v1/equipment/templates/{uuid4()}',
            headers=eq_auth_headers,
            json={'name': 'Ghost'},
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_delete_template(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        create_r = client.post(
            '/api/v1/equipment/templates',
            headers=eq_auth_headers,
            json={
                'name': 'Delete Me',
                'module': 'equipment',
                'body_html': '<p>Bye</p>',
            },
        )
        tpl_id = create_r.json()['id']

        response = client.delete(
            f'/api/v1/equipment/templates/{tpl_id}',
            headers=eq_auth_headers,
        )
        assert response.status_code == status.HTTP_204_NO_CONTENT

        get_r = client.get(
            f'/api/v1/equipment/templates/{tpl_id}',
            headers=eq_auth_headers,
        )
        assert get_r.status_code == status.HTTP_404_NOT_FOUND

    def test_delete_nonexistent_returns_404(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        from uuid import uuid4

        response = client.delete(
            f'/api/v1/equipment/templates/{uuid4()}',
            headers=eq_auth_headers,
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.integration
class TestPlaceholders:
    def test_get_placeholders(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        response = client.get(
            '/api/v1/equipment/protocol/placeholders',
            headers=eq_auth_headers,
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 5
        assert all('key' in p and 'description' in p for p in data)


@pytest.mark.integration
class TestSeedDefaults:
    def test_seed_defaults_creates_templates(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        response = client.post(
            '/api/v1/equipment/templates/seed-defaults',
            headers=eq_auth_headers,
        )
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert len(data) == 2

    def test_seed_defaults_idempotent(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        client.post(
            '/api/v1/equipment/templates/seed-defaults',
            headers=eq_auth_headers,
        )
        response = client.post(
            '/api/v1/equipment/templates/seed-defaults',
            headers=eq_auth_headers,
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert len(response.json()) == 0


@pytest.mark.integration
class TestProtocolHtml:
    def _checkout(
        self, client: TestClient, headers: dict[str, str], item_id: Any
    ) -> str:
        r = client.post(
            '/api/v1/equipment/assignments',
            headers=headers,
            json={'item_id': str(item_id), 'assigned_to_name': 'Alice'},
        )
        r.raise_for_status()
        return cast(str, r.json()['id'])

    def test_get_protocol_html_success(
        self, client: TestClient, eq_auth_headers: dict[str, str], eq_item: Item
    ) -> None:
        assignment_id = self._checkout(client, eq_auth_headers, eq_item.id)

        response = client.get(
            f'/api/v1/equipment/assignments/{assignment_id}/protocol/html',
            headers=eq_auth_headers,
        )
        assert response.status_code == status.HTTP_200_OK
        assert 'text/html' in response.headers.get('content-type', '')
        assert eq_item.name in response.text

    def test_get_protocol_html_nonexistent_assignment(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        from uuid import uuid4

        response = client.get(
            f'/api/v1/equipment/assignments/{uuid4()}/protocol/html',
            headers=eq_auth_headers,
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_get_protocol_html_with_custom_template(
        self, client: TestClient, eq_auth_headers: dict[str, str], eq_item: Item
    ) -> None:
        assignment_id = self._checkout(client, eq_auth_headers, eq_item.id)

        tpl_r = client.post(
            '/api/v1/equipment/templates',
            headers=eq_auth_headers,
            json={
                'name': 'Custom Protocol',
                'module': 'equipment',
                'body_html': '<div>{{item_name}} CUSTOM</div>',
            },
        )
        tpl_id = tpl_r.json()['id']

        response = client.get(
            f'/api/v1/equipment/assignments/{assignment_id}/protocol/html?template_id={tpl_id}',
            headers=eq_auth_headers,
        )
        assert response.status_code == status.HTTP_200_OK
        assert 'CUSTOM' in response.text
