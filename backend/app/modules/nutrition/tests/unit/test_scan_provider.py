"""Tests for OFFScanProvider — barcode scan handling and OFF data integration."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.nutrition.scan_provider import OFFScanProvider


@pytest.fixture
def provider() -> OFFScanProvider:
    return OFFScanProvider()


@pytest.fixture
def mock_user() -> MagicMock:
    user = MagicMock()
    user.organization_id = 'test-org-id'
    return user


@pytest.fixture
def mock_db() -> AsyncMock:
    db = AsyncMock()
    db.run_sync = AsyncMock(side_effect=lambda fn: fn(db))
    return db


class TestOFFScanProviderCanHandle:
    """Tests for barcode format validation."""

    @pytest.mark.asyncio
    async def test_accepts_ean13_barcode(self, provider: OFFScanProvider) -> None:
        assert await provider.can_handle('5901234123457') is True

    @pytest.mark.asyncio
    async def test_accepts_ean8_barcode(self, provider: OFFScanProvider) -> None:
        assert await provider.can_handle('12345678') is True

    @pytest.mark.asyncio
    async def test_rejects_short_barcode(self, provider: OFFScanProvider) -> None:
        assert await provider.can_handle('123') is False

    @pytest.mark.asyncio
    async def test_rejects_non_numeric_code(self, provider: OFFScanProvider) -> None:
        assert await provider.can_handle('STM-1234') is False

    @pytest.mark.asyncio
    async def test_rejects_empty_string(self, provider: OFFScanProvider) -> None:
        assert await provider.can_handle('') is False


class TestOFFScanProviderHandle:
    """Tests for OFFScanProvider.handle logic."""

    @pytest.mark.asyncio
    async def test_returns_none_when_no_organization(
        self, provider: OFFScanProvider, mock_db: AsyncMock
    ) -> None:
        user = MagicMock()
        user.organization_id = None

        result = await provider.handle('5901234123457', user, mock_db)

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_module_disabled(
        self, provider: OFFScanProvider, mock_user: MagicMock, mock_db: AsyncMock
    ) -> None:
        with patch('app.modules.nutrition.scan_provider.core_api') as mock_core_api:
            mock_core_api.organizations.is_module_enabled.return_value = False
            mock_core_api.organizations.is_module_enabled_async = AsyncMock(
                return_value=False
            )
            mock_core_api.items.has_active_barcode.return_value = False
            mock_core_api.items.has_active_barcode_async = AsyncMock(return_value=False)

            result = await provider.handle('5901234123457', mock_user, mock_db)

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_active_barcode_in_inventory(
        self, provider: OFFScanProvider, mock_user: MagicMock, mock_db: AsyncMock
    ) -> None:
        """If barcode exists in local inventory, provider defers."""
        with patch('app.modules.nutrition.scan_provider.core_api') as mock_core_api:
            mock_core_api.organizations.is_module_enabled.return_value = True
            mock_core_api.organizations.is_module_enabled_async = AsyncMock(
                return_value=True
            )
            mock_core_api.items.has_active_barcode.return_value = True
            mock_core_api.items.has_active_barcode_async = AsyncMock(return_value=True)

            result = await provider.handle('5901234123457', mock_user, mock_db)

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_product_not_in_off(
        self, provider: OFFScanProvider, mock_user: MagicMock, mock_db: AsyncMock
    ) -> None:
        """Returns None when OFF DB has no data for barcode."""
        mock_session = MagicMock()
        mock_session.close = MagicMock()

        with (
            patch('app.modules.nutrition.scan_provider.core_api') as mock_core_api,
            patch('app.modules.nutrition.scan_provider.off_service') as mock_off,
            patch('app.core.db_facade.ProductsSessionLocal', None),
            patch('app.core.db_facade.SessionLocal', return_value=mock_session),
        ):
            mock_core_api.organizations.is_module_enabled.return_value = True
            mock_core_api.organizations.is_module_enabled_async = AsyncMock(
                return_value=True
            )
            mock_core_api.items.has_active_barcode.return_value = False
            mock_core_api.items.has_active_barcode_async = AsyncMock(return_value=False)
            mock_core_api.product_templates.lookup_by_barcode_async = AsyncMock(
                return_value=None
            )
            mock_off.fetch_product = MagicMock(return_value=None)

            result = await provider.handle('0000000000000', mock_user, mock_db)

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_label_scan_response_for_known_product(
        self, provider: OFFScanProvider, mock_user: MagicMock, mock_db: AsyncMock
    ) -> None:
        """Returns LabelScanResponse with product template when OFF finds data."""
        off_data: dict[str, object] = {
            'name': 'Test Cereal',
            'brand': 'TestBrand',
            'image_url': 'http://example.com/img.jpg',
            'nutriscore': 'b',
            'energy_kcal': 350,
            'proteins': 8.0,
            'carbohydrates': 70.0,
            'fat': 3.0,
            'ingredients': 'Oats, Sugar',
            'categories': 'Breakfast',
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
            mock_core_api.organizations.is_module_enabled.return_value = True
            mock_core_api.organizations.is_module_enabled_async = AsyncMock(
                return_value=True
            )
            mock_core_api.items.has_active_barcode.return_value = False
            mock_core_api.items.has_active_barcode_async = AsyncMock(return_value=False)
            mock_core_api.product_templates.lookup_by_barcode_async = AsyncMock(
                return_value=None
            )
            mock_off.fetch_product = MagicMock(return_value=off_data)

            result = await provider.handle('5901234123457', mock_user, mock_db)

        assert result is not None
        assert result.status == 'unassigned'
        assert result.action == 'show_quick_add'
        assert result.label_code == '5901234123457'
        assert result.stock_summary is not None
        # The product's name is a value now, not a sentence the server built:
        # the line under the status is resolved from the reader's catalogue.
        assert result.message_params == {'product': 'Test Cereal'}
        template = result.stock_summary['template']
        assert template['name'] == 'Test Cereal'
        assert template['metadata']['nutriscore'] == 'b'
