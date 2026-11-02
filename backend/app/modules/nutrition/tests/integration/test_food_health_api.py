"""Integration tests for nutrition module via scan endpoint.

The nutrition module has no direct routes — it contributes an OFFScanProvider
to the scan registry.  These tests verify the scan endpoint at
GET /api/v1/labels/scan/{code} responds correctly when the OFF provider is involved.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import status
from starlette.testclient import TestClient


@pytest.mark.integration
class TestOFFScanIntegration:
    """Integration tests for OFF barcode scanning via the labels scan endpoint."""

    def test_scan_numeric_barcode_module_disabled_returns_fallback(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """When module is disabled, the scan returns a non-OFF response (not 500)."""
        with patch('app.modules.nutrition.scan_provider.core_api') as mock_core_api:
            mock_core_api.organizations.is_module_enabled_async = AsyncMock(
                return_value=False
            )
            mock_core_api.items.has_active_barcode_async = AsyncMock(return_value=False)

            response = client.get(
                '/api/v1/labels/scan/5901234123457', headers=auth_headers
            )

        # A numeric code always finds a handler: the core BarcodeScanProvider
        # takes it and answers 200 with an 'unassigned' status when nothing in
        # the organization matches. Turning this module off removes the OFF
        # lookup, not the answer.
        assert response.status_code == status.HTTP_200_OK

    def test_scan_non_numeric_code_not_handled_by_off(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """A label code (STM-XXXX) is not handled by OFFScanProvider."""
        response = client.get('/api/v1/labels/scan/STM-FAKE', headers=auth_headers)

        # STM-FAKE matches the label-code pattern, so the scan is routed to the
        # label lookup rather than to OFF — and no such label exists, which is
        # a 404. Not "either way": this code has one owner.
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_scan_unauthorized_returns_401(self, client: TestClient) -> None:
        """Unauthenticated scan returns 401."""
        response = client.get('/api/v1/labels/scan/5901234123457')
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_scan_known_barcode_with_off_data_returns_quick_add(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """When OFF has data, scan returns action='show_quick_add' with template."""
        off_data = {
            'name': 'Integration Test Product',
            'brand': 'TestBrand',
            'image_url': None,
            'nutriscore': 'c',
            'energy_kcal': 400,
            'proteins': 5.0,
            'carbohydrates': 60.0,
            'fat': 10.0,
            'sugars': None,
            'salt': None,
            'fiber': None,
            'saturated_fat': None,
            'nova_group': None,
            'nutrient_levels': None,
            'ingredients': None,
            'categories': None,
            'source': 'local_off_db',
        }

        mock_session = MagicMock()
        mock_session.close = MagicMock()
        mock_session.query = MagicMock()

        with (
            patch('app.modules.nutrition.scan_provider.core_api') as mock_core_api,
            patch('app.modules.nutrition.scan_provider.off_service') as mock_off,
            patch('app.core.db_facade.ProductsSessionLocal', return_value=mock_session),
        ):
            mock_core_api.organizations.is_module_enabled_async = AsyncMock(
                return_value=True
            )
            mock_core_api.items.has_active_barcode_async = AsyncMock(return_value=False)
            mock_core_api.product_templates.lookup_by_barcode_async = AsyncMock(
                return_value=None
            )
            mock_off.fetch_product = MagicMock(return_value=off_data)

            response = client.get(
                '/api/v1/labels/scan/5901234123457', headers=auth_headers
            )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['action'] == 'show_quick_add'
        assert data['label_code'] == '5901234123457'
        template = data['stock_summary']['template']
        assert template['name'] == 'Integration Test Product'
        assert template['metadata']['nutriscore'] == 'c'
