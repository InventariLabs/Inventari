"""Tests for OpenFoodFactsService — local DB product lookup and data parsing."""

from unittest.mock import MagicMock

import pytest

from app.modules.nutrition.services import OpenFoodFactsService, strip_html


class TestStripHtml:
    def test_strips_basic_tags(self) -> None:
        assert strip_html('<b>Bold</b>') == 'Bold'

    def test_strips_nested_tags(self) -> None:
        assert strip_html('<p><strong>Hello</strong></p>') == 'Hello'

    def test_returns_none_for_none(self) -> None:
        assert strip_html(None) is None

    def test_returns_empty_string_unchanged(self) -> None:
        # empty string is falsy → returned as-is
        assert strip_html('') == ''

    def test_plain_text_unchanged(self) -> None:
        assert strip_html('No HTML here') == 'No HTML here'


class TestOpenFoodFactsServiceFetchProduct:
    """Unit tests for OpenFoodFactsService.fetch_product."""

    @pytest.fixture
    def service(self) -> OpenFoodFactsService:
        return OpenFoodFactsService()

    @pytest.fixture
    def mock_db(self) -> MagicMock:
        return MagicMock()

    @pytest.mark.asyncio
    def test_fetch_known_product_returns_dict(
        self, service: OpenFoodFactsService, mock_db: MagicMock
    ) -> None:
        """Fetching a known barcode returns expected dict shape."""
        from app.modules.nutrition.models import OFFProductLocal

        mock_product = MagicMock(spec=OFFProductLocal)
        mock_product.barcode = '5901234123457'
        mock_product.name = 'Test Product'
        mock_product.brand = 'TestBrand'
        mock_product.image_url = 'http://example.com/img.jpg'
        mock_product.data = {
            'nutriscore': 'b',
            'energy_kcal': 200,
            'proteins': 10.0,
            'carbohydrates': 30.0,
            'fat': 5.0,
            'sugars': 12.0,
            'salt': 0.5,
            'fiber': 2.0,
            'saturated_fat': 1.0,
            'nova_group': 3,
            'nutrient_levels': {'fat': 'moderate'},
            'categories': 'Snacks',
            'ingredients': 'Water, Sugar',
        }

        mock_scalars = MagicMock()
        mock_scalars.first.return_value = mock_product
        mock_db.scalars.return_value = mock_scalars

        result = service.fetch_product('5901234123457', mock_db)

        assert result is not None
        assert result['name'] == 'Test Product'
        assert result['brand'] == 'TestBrand'
        assert result['nutriscore'] == 'b'
        assert result['energy_kcal'] == 200
        assert result['source'] == 'local_off_db'

    @pytest.mark.asyncio
    def test_fetch_unknown_product_returns_none(
        self, service: OpenFoodFactsService, mock_db: MagicMock
    ) -> None:
        """Fetching an unknown barcode returns None."""
        mock_scalars = MagicMock()
        mock_scalars.first.return_value = None
        mock_db.scalars.return_value = mock_scalars

        result = service.fetch_product('0000000000000', mock_db)

        assert result is None

    @pytest.mark.parametrize(
        'barcode',
        [
            '2000000000213',
            # The scan path pads an EAN-8 to its canonical GTIN-13 form
            # before this service sees it.
            '0000020000004',
            '20000004',
        ],
    )
    def test_fetch_does_not_query_a_restricted_circulation_code(
        self, service: OpenFoodFactsService, mock_db: MagicMock, barcode: str
    ) -> None:
        """A shop may print these; a shared catalogue must not answer for them."""
        result = service.fetch_product(barcode, mock_db)

        assert result is None
        mock_db.scalars.assert_not_called()

    @pytest.mark.asyncio
    def test_fetch_handles_db_error_gracefully(
        self, service: OpenFoodFactsService, mock_db: MagicMock
    ) -> None:
        """A database exception is caught and None is returned instead of raising."""
        from sqlalchemy.exc import OperationalError

        mock_db.scalars.side_effect = OperationalError(
            'SELECT 1', {}, Exception('connection refused')
        )

        result = service.fetch_product('1234567890123', mock_db)

        assert result is None

    @pytest.mark.asyncio
    def test_fetch_product_strips_html_from_ingredients(
        self, service: OpenFoodFactsService, mock_db: MagicMock
    ) -> None:
        """HTML in ingredients field is stripped before returning."""
        from app.modules.nutrition.models import OFFProductLocal

        mock_product = MagicMock(spec=OFFProductLocal)
        mock_product.name = 'Soup'
        mock_product.brand = None
        mock_product.image_url = None
        mock_product.data = {
            'ingredients': '<ul><li>Water</li><li>Salt</li></ul>',
            'categories': None,
        }
        mock_scalars = MagicMock()
        mock_scalars.first.return_value = mock_product
        mock_db.scalars.return_value = mock_scalars

        result = service.fetch_product('1111111111111', mock_db)

        assert result is not None
        assert '<' not in result['ingredients']
        assert 'Water' in result['ingredients']

    @pytest.mark.asyncio
    def test_fetch_product_handles_partial_data(
        self, service: OpenFoodFactsService, mock_db: MagicMock
    ) -> None:
        """Product with minimal data (no nutritional values) is handled gracefully."""
        from app.modules.nutrition.models import OFFProductLocal

        mock_product = MagicMock(spec=OFFProductLocal)
        mock_product.name = 'Minimal Product'
        mock_product.brand = None
        mock_product.image_url = None
        mock_product.data = {}  # no nutritional data at all

        mock_scalars = MagicMock()
        mock_scalars.first.return_value = mock_product
        mock_db.scalars.return_value = mock_scalars

        result = service.fetch_product('9999999999999', mock_db)

        assert result is not None
        assert result['name'] == 'Minimal Product'
        assert result['energy_kcal'] is None
        assert result['nutriscore'] is None
