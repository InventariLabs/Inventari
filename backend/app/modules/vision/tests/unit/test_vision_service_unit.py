import io
from typing import Any

import pytest
from PIL import Image

from app.modules.vision.schemas import VisionExtractResult, VisionReceiptItem
from app.modules.vision.service import VisionService


def _make_rgb_image(
    width: int = 100, height: int = 100, color: tuple[int, int, int] = (255, 0, 0)
) -> bytes:
    img = Image.new('RGB', (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format='JPEG')
    return buf.getvalue()


def _make_rgba_image(width: int = 100, height: int = 100) -> bytes:
    img = Image.new('RGBA', (width, height), (255, 0, 0, 128))
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()


@pytest.mark.unit
class TestCompressImage:
    def test_rgb_image_returns_jpeg_bytes(self) -> None:
        image_bytes = _make_rgb_image()
        result: Any = VisionService._compress_image(image_bytes)
        assert isinstance(result, bytes)
        assert len(result) > 0
        img = Image.open(io.BytesIO(result))
        assert img.format == 'JPEG'

    def test_rgba_image_converted_to_rgb(self) -> None:
        image_bytes = _make_rgba_image()
        result: Any = VisionService._compress_image(image_bytes)
        img = Image.open(io.BytesIO(result))
        assert img.mode == 'RGB'

    def test_large_image_is_resized(self) -> None:
        image_bytes = _make_rgb_image(3000, 3000)
        result: Any = VisionService._compress_image(image_bytes, max_size=(800, 800))
        img = Image.open(io.BytesIO(result))
        assert img.width <= 800
        assert img.height <= 800

    def test_small_image_not_resized(self) -> None:
        image_bytes = _make_rgb_image(200, 200)
        result: Any = VisionService._compress_image(image_bytes, max_size=(800, 800))
        img = Image.open(io.BytesIO(result))
        assert img.width == 200
        assert img.height == 200


@pytest.mark.unit
class TestVisionSchemas:
    def test_extract_result_defaults(self) -> None:
        result = VisionExtractResult()
        assert result.name is None
        assert result.weight is None

    def test_extract_result_with_data(self) -> None:
        result = VisionExtractResult(name='Milk', weight='1L', brand='Milko')
        assert result.name == 'Milk'
        assert result.brand == 'Milko'

    def test_the_label_schema_holds_no_nutrition_field(self) -> None:
        """The 3-vertical test, as an assertion.

        A model that can read an equipment nameplate must not carry grams of
        salt. These names left for the nutrition module, which contributes
        them only when a product label is what was photographed.
        """
        fields = set(VisionExtractResult.model_fields)
        assert fields.isdisjoint(
            {'energy_kcal', 'proteins', 'fat', 'salt', 'sugars', 'ingredients'}
        )

    def test_receipt_item_defaults(self) -> None:
        item = VisionReceiptItem(name='Bread')
        assert item.quantity == 1.0
        assert item.unit == 'pcs'
        assert item.brand is None

    def test_receipt_item_with_data(self) -> None:
        item = VisionReceiptItem(
            name='Cheese', quantity=2.5, unit='kg', brand='Lacto', price=12.50
        )
        assert item.quantity == 2.5
        assert item.unit == 'kg'
