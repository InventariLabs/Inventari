import pytest

from app.modules.vision.schemas import VisionExtractResult


@pytest.mark.unit
class TestVisionSchemas:
    """Tests for vision schemas."""

    def test_vision_extract_result_schema(self) -> None:
        """Verifies that vision extract result schema works."""
        data: dict[str, str] = {
            'name': 'Milk',
            'weight': '1L',
            'expiry_date': '2024-12-31',
            'brand': 'Mlekovita',
            'category': 'Dairy',
        }
        result = VisionExtractResult(**data)

        assert result.name == 'Milk'
        assert result.weight == '1L'
        assert result.expiry_date == '2024-12-31'
        assert result.brand == 'Mlekovita'
        assert result.category == 'Dairy'
