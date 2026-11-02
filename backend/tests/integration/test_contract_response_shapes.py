"""Response shape contract tests.

Validates that key endpoints return the field names the frontend expects.
These tests catch field-name mismatches at CI time — the root cause of
"undefined" values in the UI.

Add new assertions here when the frontend adds new fields it depends on.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.user import User
from app.modules.webhooks.models import WebhookDeliveryLog, WebhookEndpoint

pytestmark = [pytest.mark.integration]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _assert_fields(data: dict, required: list[str], label: str) -> None:
    """Assert that all required fields are present in the response dict."""
    missing = [k for k in required if k not in data]
    assert not missing, f'{label}: missing fields {missing}'


def _assert_list_items(data: list[dict], required: list[str], label: str) -> None:
    """Assert each item in a list has the required fields."""
    for i, item in enumerate(data[:3]):  # check first 3
        missing = [k for k in required if k not in item]
        assert not missing, f'{label}[{i}]: missing fields {missing}'


# ---------------------------------------------------------------------------
# Stats module
# ---------------------------------------------------------------------------


class TestStatsContract:
    """Verify stats endpoint response shapes match FE expectations."""

    def test_overview_shape(self, client: TestClient, auth_headers: dict):
        resp = client.get('/api/v1/stats/overview', headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        _assert_fields(
            data,
            [
                'total_items',
                'total_locations',
                'expiring_soon',
                'expired',
                'low_stock',
            ],
            'stats/overview',
        )

    def test_rotation_shape(self, client: TestClient, auth_headers: dict):
        resp = client.get('/api/v1/stats/rotation-analysis', headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        # RotationAnalysisResponse wraps CategoryRotation in rotation_by_category
        _assert_fields(
            data,
            [
                'average_stock_age_days',
                'rotation_by_category',
            ],
            'stats/rotation',
        )
        if data.get('rotation_by_category'):
            _assert_fields(
                data['rotation_by_category'][0],
                [
                    'category_name',
                    'average_days',
                    'item_count',
                ],
                'stats/rotation.rotation_by_category[0]',
            )

    def test_expense_forecast_shape(self, client: TestClient, auth_headers: dict):
        resp = client.get('/api/v1/stats/expense-forecast', headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        _assert_fields(
            data,
            [
                'predicted_spending',
                'waste_reduction_potential',
                'confidence',
                'top_cost_drivers',
            ],
            'stats/expense-forecast',
        )

    def test_seasonal_shape(self, client: TestClient, auth_headers: dict):
        resp = client.get('/api/v1/stats/purchase-patterns', headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        _assert_fields(
            data,
            [
                'top_recurring_products',
                'seasonal_products',
                'bulk_opportunities',
            ],
            'stats/purchase-patterns',
        )
        if data.get('seasonal_products'):
            _assert_fields(
                data['seasonal_products'][0],
                [
                    'name',
                ],
                'stats/purchase-patterns.seasonal_products[0]',
            )

    def test_alerts_shape(self, client: TestClient, auth_headers: dict):
        resp = client.get('/api/v1/stats/smart-alerts', headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        _assert_fields(data, ['alerts', 'total_alerts'], 'stats/alerts')

    def test_cost_analysis_shape(self, client: TestClient, auth_headers: dict):
        resp = client.get('/api/v1/stats/cost-analysis', headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        _assert_fields(
            data,
            [
                'total_spent',
                'total_wasted',
                'waste_value_percentage',
            ],
            'stats/cost-analysis',
        )


# ---------------------------------------------------------------------------
# Webhooks module
# ---------------------------------------------------------------------------


@pytest.fixture
def planted_delivery(db_session: Session, test_user: User) -> WebhookDeliveryLog:
    """One endpoint with one delivery, written as rows.

    Both shape tests used to read whatever the org happened to have, and a
    fresh org has no endpoints — so the list check never looked at an element
    and the deliveries check skipped in every run. Rows, not the API: the
    create route resolves the URL against SSRF rules, which is not the subject.
    """
    endpoint = WebhookEndpoint(
        organization_id=test_user.organization_id,
        name='Shape probe',
        url='https://hooks.example.com/shape',
        event_types=['item.created'],
    )
    db_session.add(endpoint)
    db_session.flush()
    delivery = WebhookDeliveryLog(
        webhook_endpoint_id=endpoint.id,
        organization_id=test_user.organization_id,
        event_type='item.created',
        payload_json={'probe': True},
        status_code=200,
        delivery_status='success',
    )
    db_session.add(delivery)
    db_session.commit()
    return delivery


class TestWebhooksContract:
    """Verify webhook endpoint response shapes match FE expectations."""

    def test_endpoints_list_shape(
        self, client: TestClient, auth_headers: dict, planted_delivery
    ):
        resp = client.get('/api/v1/webhooks/endpoints', headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()['items']
        assert isinstance(data, list)
        assert data, 'the planted endpoint is missing from the list'
        _assert_fields(
            data[0],
            [
                'id',
                'name',
                'url',
                'has_secret',
                'http_method',
                'event_types',
                'max_retries',
                'retry_backoff_seconds',
                'timeout_seconds',
                'is_active',
                'consecutive_failures',
                'created_at',
                'updated_at',
            ],
            'webhooks/endpoints[0]',
        )

    def test_deliveries_shape(
        self, client: TestClient, auth_headers: dict, planted_delivery
    ):
        resp = client.get(
            f'/api/v1/webhooks/endpoints/{planted_delivery.webhook_endpoint_id}/deliveries',
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        _assert_fields(
            data, ['items', 'next_cursor', 'has_more'], 'webhooks/deliveries'
        )
        assert data['items'], 'the planted delivery is missing from the page'
        _assert_fields(
            data['items'][0],
            [
                'id',
                'event_type',
                'delivery_status',
                'attempt_number',
                'created_at',
            ],
            'webhooks/deliveries.items[0]',
        )


# ---------------------------------------------------------------------------
# Documents module
# ---------------------------------------------------------------------------


class TestDocumentsContract:
    """Verify document endpoint response shapes match FE expectations."""

    def test_document_list_shape(self, client: TestClient, auth_headers: dict):
        resp = client.get('/api/v1/warehouse/documents', headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        _assert_fields(
            data, ['items', 'total', 'limit', 'offset', 'has_more'], 'documents'
        )
        assert 'documents' not in data, (
            'the list answers the canonical envelope only; the pre-release '
            'documents alias did not survive the first release'
        )
        assert isinstance(data['items'], list)
        if data['items']:
            _assert_fields(
                data['items'][0],
                [
                    'id',
                    'type',
                    'number',
                    'status',
                    'created_at',
                ],
                'documents.items[0]',
            )

    def test_profile_shape(self, client: TestClient, auth_headers: dict):
        resp = client.get('/api/v1/warehouse/profile', headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        _assert_fields(
            data,
            [
                'id',
                'organization_id',
            ],
            'documents/profile',
        )


# ---------------------------------------------------------------------------
# Approvals module
# ---------------------------------------------------------------------------


class TestApprovalsContract:
    """Verify approval endpoint response shapes match FE expectations."""

    def test_workflows_list_shape(self, client: TestClient, auth_headers: dict):
        resp = client.get('/api/v1/approvals/workflows', headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()['items']
        assert isinstance(data, list)
        if data:
            _assert_fields(
                data[0],
                [
                    'id',
                    'organization_id',
                    'target_type',
                    'name',
                    'stages',
                    'is_active',
                    'created_at',
                ],
                'approvals/workflows[0]',
            )

    def test_requests_list_shape(self, client: TestClient, auth_headers: dict):
        resp = client.get('/api/v1/approvals/requests', headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)
        assert 'items' in data and 'total' in data
        assert isinstance(data['items'], list)
        if data['items']:
            _assert_fields(
                data['items'][0],
                [
                    'id',
                    'status',
                    'current_stage',
                    'total_stages',
                    'created_at',
                ],
                'approvals/requests[0]',
            )
