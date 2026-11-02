"""Unit tests for UoM conversion (``uom_service.convert_quantity``)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID, uuid4

from app.services.uom_service import convert_quantity


@dataclass
class _FakeUom:
    """Minimal UoM stand-in — only id, category_id, factor are read."""

    id: UUID
    category_id: UUID
    factor: Decimal


_WEIGHT = uuid4()
_VOL = uuid4()


def _uom(cat: UUID, factor: float | str) -> _FakeUom:
    # The factor is an exact number now — a definition, not a
    # measurement — so the fake carries one too.
    return _FakeUom(id=uuid4(), category_id=cat, factor=Decimal(str(factor)))


class TestConvertQuantity:
    """``convert_quantity`` factor-ratio conversion within one category."""

    def test_same_uom_returns_unchanged(self) -> None:
        uom = _uom(_WEIGHT, 1.0)
        result, ok = convert_quantity(Decimal('100'), uom, uom)
        assert result == Decimal('100')
        assert ok is True

    def test_kg_to_g(self) -> None:
        kg = _uom(_WEIGHT, 1000.0)  # 1 kg = 1000 g (reference)
        g = _uom(_WEIGHT, 1.0)
        result, ok = convert_quantity(Decimal('2.5'), kg, g)
        assert ok is True
        assert result == Decimal('2500')

    def test_g_to_kg(self) -> None:
        kg = _uom(_WEIGHT, 1000.0)
        g = _uom(_WEIGHT, 1.0)
        result, ok = convert_quantity(Decimal('500'), g, kg)
        assert ok is True
        assert result == Decimal('0.5')

    def test_l_to_ml(self) -> None:
        liter = _uom(_VOL, 1000.0)
        ml = _uom(_VOL, 1.0)
        result, ok = convert_quantity(Decimal('1.5'), liter, ml)
        assert ok is True
        assert result == Decimal('1500')

    def test_cross_category_not_convertible(self) -> None:
        kg = _uom(_WEIGHT, 1000.0)
        liter = _uom(_VOL, 1000.0)
        result, ok = convert_quantity(Decimal('2'), kg, liter)
        assert ok is False
        assert result == Decimal('2')

    def test_none_uom_not_convertible(self) -> None:
        uom = _uom(_WEIGHT, 1.0)
        result, ok = convert_quantity(Decimal('5'), uom, None)
        assert ok is False
        assert result == Decimal('5')

        result, ok = convert_quantity(Decimal('5'), None, uom)
        assert ok is False
        assert result == Decimal('5')

    def test_zero_target_factor_not_convertible(self) -> None:
        good = _uom(_WEIGHT, 1.0)
        bad = _uom(_WEIGHT, 0.0)
        result, ok = convert_quantity(Decimal('10'), good, bad)
        assert ok is False
        assert result == Decimal('10')
