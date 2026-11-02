"""Unit tests for the UOM conversion helpers — no DB required."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from app.core.contracts import UomDTO
from app.modules.recipes._uom_helpers import convert_qty_for_template
from app.modules.recipes.models import UnitConversion
from app.modules.recipes.services import _convert_qty_to_uom
from app.modules.recipes.unit_conversion_service import render_conversion_table

_weight_cat = uuid4()
_volume_cat = uuid4()
_unit_cat = uuid4()


def _uom(symbol: str, factor: float | str, category_id: Any = _weight_cat) -> UomDTO:
    # A conversion factor is an exact number now — a definition, not a
    # measurement — so the DTO carries one.
    return UomDTO(
        id=uuid4(),
        category_id=category_id,
        name=symbol,
        symbol=symbol,
        factor=Decimal(str(factor)),
        is_reference=False,
        rounding=0.01,
    )


GRAM = _uom('g', 1.0, _weight_cat)
KG = _uom('kg', 1000.0, _weight_cat)
MG = _uom('mg', 0.001, _weight_cat)
ML = _uom('ml', 1.0, _volume_cat)
LITER = _uom('l', 1000.0, _volume_cat)
PCS = _uom('pcs', 1.0, _unit_cat)
_pack_cat = uuid4()
PACK = _uom('pack', 1.0, _pack_cat)


class TestConvertQtyToUom:
    def test_same_uom_returns_unchanged(self) -> None:
        assert _convert_qty_to_uom(Decimal('500'), GRAM, GRAM) == Decimal('500')

    def test_kg_to_gram(self) -> None:
        result = _convert_qty_to_uom(Decimal('0.5'), KG, GRAM)
        assert result == Decimal('500')

    def test_gram_to_kg(self) -> None:
        result = _convert_qty_to_uom(Decimal('1500'), GRAM, KG)
        assert result == Decimal('1.5')

    def test_mg_to_gram(self) -> None:
        result = _convert_qty_to_uom(Decimal('5000'), MG, GRAM)
        assert result == Decimal('5')

    def test_liter_to_ml(self) -> None:
        result = _convert_qty_to_uom(Decimal('2'), LITER, ML)
        assert result == Decimal('2000')

    def test_cross_category_is_refused(self) -> None:
        """An impossible conversion is a refusal — never the same number."""
        assert _convert_qty_to_uom(Decimal('100'), GRAM, ML) is None

    def test_weight_vs_unit_is_refused(self) -> None:
        assert _convert_qty_to_uom(Decimal('180'), GRAM, PCS) is None

    def test_none_source_uom_is_refused(self) -> None:
        assert _convert_qty_to_uom(Decimal('42'), None, GRAM) is None

    def test_none_target_uom_is_refused(self) -> None:
        assert _convert_qty_to_uom(Decimal('42'), GRAM, None) is None

    def test_both_none_is_refused(self) -> None:
        assert _convert_qty_to_uom(Decimal('42'), None, None) is None

    def test_zero_target_factor_is_refused(self) -> None:
        bad_uom = _uom('x', 0.0, _weight_cat)
        assert _convert_qty_to_uom(Decimal('100'), GRAM, bad_uom) is None


@dataclass(frozen=True)
class FakeTemplate:
    """Stands in for a ProductTemplate carrying a pack size."""

    uom_id: UUID | None = None
    weight_value: float | None = None
    weight_uom_id: UUID | None = None
    volume_value: float | None = None
    volume_uom_id: UUID | None = None


UOMS: dict[UUID, UomDTO] = {u.id: u for u in (GRAM, KG, MG, ML, LITER, PCS, PACK)}


class TestConvertQtyForTemplate:
    """The conversion that decides whether the shelf holds enough."""

    def test_same_category_behaves_like_the_plain_ratio(self) -> None:
        assert convert_qty_for_template(Decimal('0.5'), KG, GRAM) == Decimal('500')

    def test_same_uom_passes_through(self) -> None:
        assert convert_qty_for_template(Decimal('42'), GRAM, GRAM) == Decimal('42')

    def test_cans_cover_a_requirement_in_grams(self) -> None:
        """7 cans of 400 g answer a recipe asking for 400 g."""
        chickpeas = FakeTemplate(
            uom_id=PCS.id, weight_value=400.0, weight_uom_id=GRAM.id
        )
        result = convert_qty_for_template(Decimal('7'), PCS, GRAM, chickpeas, UOMS)
        assert result == Decimal('2800')

    def test_grams_answer_a_requirement_in_pieces(self) -> None:
        """The bridge carries in both directions."""
        eggs = FakeTemplate(uom_id=PCS.id, weight_value=60.0, weight_uom_id=GRAM.id)
        result = convert_qty_for_template(Decimal('180'), GRAM, PCS, eggs, UOMS)
        assert result == Decimal('3')

    def test_volume_bridges_the_same_way(self) -> None:
        milk = FakeTemplate(uom_id=PCS.id, volume_value=1.0, volume_uom_id=LITER.id)
        result = convert_qty_for_template(Decimal('2'), PCS, ML, milk, UOMS)
        assert result == Decimal('2000')

    def test_pack_size_crosses_unit_scales(self) -> None:
        """A 400 g can answered in kilograms, not just in grams."""
        chickpeas = FakeTemplate(
            uom_id=PCS.id, weight_value=400.0, weight_uom_id=GRAM.id
        )
        result = convert_qty_for_template(Decimal('5'), PCS, KG, chickpeas, UOMS)
        assert result == Decimal('2')

    def test_no_pack_size_is_not_comparable(self) -> None:
        """Without a bridge the answer is None — never a silent number."""
        assert convert_qty_for_template(Decimal('7'), PCS, GRAM, None, UOMS) is None
        bare = FakeTemplate(uom_id=PCS.id)
        assert convert_qty_for_template(Decimal('7'), PCS, GRAM, bare, UOMS) is None

    def test_weight_bridge_does_not_answer_a_volume_question(self) -> None:
        chickpeas = FakeTemplate(
            uom_id=PCS.id, weight_value=400.0, weight_uom_id=GRAM.id
        )
        assert convert_qty_for_template(Decimal('7'), PCS, ML, chickpeas, UOMS) is None

    def test_one_missing_uom_is_not_comparable(self) -> None:
        assert convert_qty_for_template(Decimal('42'), None, GRAM) is None
        assert convert_qty_for_template(Decimal('42'), GRAM, None) is None

    def test_both_missing_uoms_compare_as_bare_numbers(self) -> None:
        assert convert_qty_for_template(Decimal('42'), None, None) == Decimal('42')

    def test_zero_pack_size_is_not_comparable(self) -> None:
        broken = FakeTemplate(uom_id=PCS.id, weight_value=0.0, weight_uom_id=GRAM.id)
        assert convert_qty_for_template(Decimal('7'), PCS, GRAM, broken, UOMS) is None

    def test_zero_target_factor_is_not_comparable(self) -> None:
        bad = _uom('x', 0.0, _weight_cat)
        assert convert_qty_for_template(Decimal('100'), GRAM, bad) is None

    def test_pack_against_piece_stocked_product_is_refused(self) -> None:
        """An ingredient in packs vs a product stocked in pieces: nothing
        says how many pieces a pack holds, so refuse — the old bridge
        equated one pack with one piece."""
        chickpeas = FakeTemplate(
            uom_id=PCS.id, weight_value=400.0, weight_uom_id=GRAM.id
        )
        assert (
            convert_qty_for_template(Decimal('2'), PACK, GRAM, chickpeas, UOMS) is None
        )

    def test_pack_requirement_answered_in_pieces_is_refused(self) -> None:
        """Same refusal, opposite direction: grams asked about in packs."""
        chickpeas = FakeTemplate(
            uom_id=PCS.id, weight_value=400.0, weight_uom_id=GRAM.id
        )
        assert (
            convert_qty_for_template(Decimal('800'), GRAM, PACK, chickpeas, UOMS)
            is None
        )


def _conv(
    source_unit: str,
    ingredient_name: str,
    metric_quantity: str,
    metric_unit: str,
) -> UnitConversion:
    return UnitConversion(
        ingredient_key=ingredient_name.lower(),
        ingredient_name=ingredient_name,
        source_unit=source_unit,
        metric_quantity=Decimal(metric_quantity),
        metric_unit=metric_unit,
    )


class TestRenderConversionTable:
    def test_empty_returns_none(self) -> None:
        assert render_conversion_table([]) is None

    def test_single_conversion(self) -> None:
        result = render_conversion_table([_conv('cup', 'Flour', '125', 'g')])
        assert result is not None
        assert '1 cup:' in result
        assert 'Flour' in result
        assert '125' in result
        assert ' g' in result

    def test_grouped_by_source_unit(self) -> None:
        result = render_conversion_table(
            [
                _conv('cup', 'Flour', '125', 'g'),
                _conv('cup', 'Sugar', '200', 'g'),
                _conv('tablespoon', 'Butter', '14', 'g'),
            ]
        )
        assert result is not None
        # cup group should contain both Flour and Sugar
        cup_section = result.split('1 tablespoon:')[0]
        assert 'Flour' in cup_section
        assert 'Sugar' in cup_section
        # tablespoon group should contain Butter
        tbsp_section = result.split('1 tablespoon:')[1]
        assert 'Butter' in tbsp_section
