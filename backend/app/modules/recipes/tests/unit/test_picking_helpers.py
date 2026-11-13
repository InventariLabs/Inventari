"""Unit tests for picking service helper functions.

Covers pure functions extracted from the picking service:
- _should_auto_skip: spice/auto-skip heuristic
- select_best_item: FEFO selection
- check_opened_suggestion: the open pack offered instead of a sealed one
- needs_disambiguation: multi-location detection
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

from app.core.contracts import ProductTemplateDTO, UomDTO
from app.modules.recipes._picking_fefo import open_pack_meets_earlier_sealed
from app.modules.recipes._picking_helpers import check_opened_suggestion
from app.modules.recipes._picking_session_helpers import _match_ingredient
from app.modules.recipes.picking_service import (
    _should_auto_skip,
    needs_disambiguation,
    select_best_item,
)

if TYPE_CHECKING:
    from app.models.item import Item


def _mock_ingredient(
    uom_symbol: str | None = 'g', picking_skip: Any = None, is_optional: bool = False
) -> MagicMock:
    ing = MagicMock()
    ing.picking_skip = picking_skip
    ing.is_optional = is_optional
    if uom_symbol:
        ing.uom = MagicMock()
        ing.uom.symbol = uom_symbol
    else:
        ing.uom = None
    return ing


def _mock_item(
    quantity: Any = 500,
    expiry_date: Any = None,
    storage_location_id: Any = None,
    template_id: Any = None,
    uom_id: Any = None,
    opened: bool = False,
) -> MagicMock:
    item = MagicMock()
    item.quantity = Decimal(str(quantity))
    item.expiry_date = expiry_date
    item.location_id = storage_location_id or uuid4()
    item.template_id = template_id
    item.uom_id = uom_id
    item.meta_data = {'opened': {'at': '2026-10-01T09:00:00+00:00'}} if opened else None
    item.id = uuid4()
    return item


# ---------------------------------------------------------------------------
# _should_auto_skip
# ---------------------------------------------------------------------------


class TestShouldAutoSkip:
    def test_explicit_skip_true(self) -> None:
        assert _should_auto_skip(_mock_ingredient(picking_skip=True), 5.0) is True

    def test_explicit_skip_false(self) -> None:
        assert _should_auto_skip(_mock_ingredient(picking_skip=False), 5.0) is False

    def test_optional_always_skipped(self) -> None:
        assert _should_auto_skip(_mock_ingredient(is_optional=True), 100.0) is True

    def test_spice_below_threshold(self) -> None:
        assert _should_auto_skip(_mock_ingredient(uom_symbol='g'), 5.0) is True

    def test_spice_above_threshold(self) -> None:
        assert _should_auto_skip(_mock_ingredient(uom_symbol='g'), 15.0) is False

    def test_ml_below_threshold(self) -> None:
        assert _should_auto_skip(_mock_ingredient(uom_symbol='ml'), 10.0) is True

    def test_mg_below_threshold(self) -> None:
        assert _should_auto_skip(_mock_ingredient(uom_symbol='mg'), 3.0) is True

    def test_one_piece_is_not_folded_away(self) -> None:
        """One egg or one onion is a main ingredient, not a seasoning."""
        assert _should_auto_skip(_mock_ingredient(uom_symbol='pcs'), 1.0) is False

    def test_piece_above_threshold(self) -> None:
        assert _should_auto_skip(_mock_ingredient(uom_symbol='pcs'), 2.0) is False

    def test_kg_never_skipped(self) -> None:
        assert _should_auto_skip(_mock_ingredient(uom_symbol='kg'), 1.0) is False

    def test_no_uom_not_skipped(self) -> None:
        assert _should_auto_skip(_mock_ingredient(uom_symbol=None), 5.0) is False

    def test_no_piece_symbol_is_folded_away_by_amount(self) -> None:
        assert _should_auto_skip(_mock_ingredient(uom_symbol='szt'), 1.0) is False
        assert _should_auto_skip(_mock_ingredient(uom_symbol='pc'), 1.0) is False
        assert _should_auto_skip(_mock_ingredient(uom_symbol='piece'), 1.0) is False
        assert _should_auto_skip(_mock_ingredient(uom_symbol='pieces'), 1.0) is False
        assert _should_auto_skip(_mock_ingredient(uom_symbol='pcs'), 0.5) is False

    def test_explicit_false_overrides_optional(self) -> None:
        ing = _mock_ingredient(picking_skip=False, is_optional=True)
        assert _should_auto_skip(ing, 5.0) is False


# ---------------------------------------------------------------------------
# select_best_item (FEFO)
# ---------------------------------------------------------------------------


class TestSelectBestItem:
    def test_single_item(self) -> None:
        item = _mock_item(expiry_date=date.today() + timedelta(days=10))
        best, days = select_best_item([item], today=date.today())
        assert best is item
        assert days is None

    def test_earliest_expiry_first(self) -> None:
        early = _mock_item(expiry_date=date.today() + timedelta(days=5))
        late = _mock_item(expiry_date=date.today() + timedelta(days=30))
        best, _ = select_best_item([late, early], today=date.today())
        assert best is early

    def test_no_expiry_goes_last(self) -> None:
        with_exp = _mock_item(expiry_date=date.today() + timedelta(days=5))
        no_exp = _mock_item(expiry_date=None)
        best, _ = select_best_item([no_exp, with_exp], today=date.today())
        assert best is with_exp

    def test_urgency_flag_when_close(self) -> None:
        expiring = _mock_item(expiry_date=date.today() + timedelta(days=3))
        safe = _mock_item(expiry_date=date.today() + timedelta(days=60))
        _, days = select_best_item([expiring, safe], today=date.today())
        assert days is not None
        assert days == 3

    def test_no_urgency_when_far(self) -> None:
        far1 = _mock_item(expiry_date=date.today() + timedelta(days=100))
        far2 = _mock_item(expiry_date=date.today() + timedelta(days=120))
        _, days = select_best_item([far1, far2], today=date.today())
        assert days is None

    def test_stock_past_its_date_goes_after_a_fresh_one(self) -> None:
        """The earliest date of all is the one already gone: never first."""
        went_off = _mock_item(expiry_date=date.today() - timedelta(days=2))
        fresh = _mock_item(expiry_date=date.today() + timedelta(days=10))
        undated = _mock_item(expiry_date=None)
        best, _ = select_best_item([went_off, undated, fresh], today=date.today())
        assert best is fresh

    def test_a_pick_past_its_date_has_no_shelf_life_left_to_warn_about(
        self,
    ) -> None:
        older = _mock_item(expiry_date=date.today() - timedelta(days=3))
        newer = _mock_item(expiry_date=date.today() - timedelta(days=2))
        best, days = select_best_item([newer, older], today=date.today())
        assert best is older
        assert days is None

    def test_the_date_itself_is_still_good(self) -> None:
        """The core's rule: an item is past its date the day after it."""
        today_s = _mock_item(expiry_date=date.today())
        later = _mock_item(expiry_date=date.today() + timedelta(days=5))
        best, days = select_best_item([later, today_s], today=date.today())
        assert best is today_s
        assert days == 0

    def test_empty_list_raises(self) -> None:
        with pytest.raises(RuntimeError, match='No items'):
            select_best_item([], today=date.today())


# ---------------------------------------------------------------------------
# open pack first
# ---------------------------------------------------------------------------


class TestOpenPackFirst:
    def test_on_the_same_date_the_open_pack_beats_a_larger_sealed_one(self) -> None:
        day = date.today() + timedelta(days=20)
        sealed = _mock_item(quantity=3, expiry_date=day)
        opened = _mock_item(quantity=0.75, expiry_date=day, opened=True)
        best, _ = select_best_item([sealed, opened], today=date.today())
        assert best is opened

    def test_an_earlier_sealed_date_still_comes_first(self) -> None:
        sealed = _mock_item(expiry_date=date.today() + timedelta(days=10))
        opened = _mock_item(expiry_date=date.today() + timedelta(days=20), opened=True)
        best, _ = select_best_item([opened, sealed], today=date.today())
        assert best is sealed

    def test_a_sealed_pack_with_an_earlier_date_competes_with_the_open_one(
        self,
    ) -> None:
        today = date.today()
        sealed = _mock_item(expiry_date=today + timedelta(days=10))
        opened = _mock_item(expiry_date=today + timedelta(days=20), opened=True)
        assert open_pack_meets_earlier_sealed([sealed, opened], today) is True

    def test_an_open_pack_with_no_date_competes_with_a_dated_sealed_one(self) -> None:
        today = date.today()
        sealed = _mock_item(expiry_date=today + timedelta(days=10))
        opened = _mock_item(expiry_date=None, opened=True)
        assert open_pack_meets_earlier_sealed([sealed, opened], today) is True

    def test_the_same_date_is_no_competition(self) -> None:
        today = date.today()
        day = today + timedelta(days=10)
        sealed = _mock_item(expiry_date=day)
        opened = _mock_item(expiry_date=day, opened=True)
        assert open_pack_meets_earlier_sealed([sealed, opened], today) is False

    def test_a_sealed_pack_past_its_date_is_no_competition(self) -> None:
        today = date.today()
        sealed = _mock_item(expiry_date=today - timedelta(days=2))
        opened = _mock_item(expiry_date=today + timedelta(days=5), opened=True)
        assert open_pack_meets_earlier_sealed([sealed, opened], today) is False

    def test_without_an_open_pack_there_is_nothing_to_choose(self) -> None:
        today = date.today()
        packs = [
            _mock_item(expiry_date=today + timedelta(days=5)),
            _mock_item(expiry_date=today + timedelta(days=9)),
        ]
        assert open_pack_meets_earlier_sealed(packs, today) is False


# ---------------------------------------------------------------------------
# check_opened_suggestion (regression: ProductTemplateDTO must carry weight_uom)
# ---------------------------------------------------------------------------


class TestCheckOpenedSuggestion:
    def test_suggestion_carries_uom_symbol_from_dto(self) -> None:
        """Opened-pack suggestion must read the UOM symbol from a
        ProductTemplateDTO (CoreAPI shape), not just the ORM row.

        Regression: ``ProductTemplateDTO`` lacked ``weight_uom``, so
        ``_template_uom_symbol`` returned ``None`` and
        ``OpenedSuggestion.opened_uom`` was always ``None``.
        """
        weight_uom = UomDTO(id=uuid4(), category_id=uuid4(), name='gram', symbol='g')
        template = ProductTemplateDTO(
            id=uuid4(),
            organization_id=uuid4(),
            name='Flour 1kg',
            weight_value=1000.0,
            weight_uom=weight_uom,
        )
        sealed = _mock_item(quantity=1000)  # full pack — sealed
        opened = _mock_item(
            quantity=200, expiry_date=date.today() + timedelta(days=5), opened=True
        )
        opened.location_name = 'Shelf A'

        suggestion = check_opened_suggestion(sealed, [sealed, opened], template)
        assert suggestion is not None
        assert suggestion.opened_uom == 'g'
        assert suggestion.opened_quantity == 200.0

    def test_sealed_with_no_open_pack_returns_none(self) -> None:
        weight_uom = UomDTO(id=uuid4(), category_id=uuid4(), name='gram', symbol='g')
        template = ProductTemplateDTO(
            id=uuid4(),
            organization_id=uuid4(),
            name='Flour 1kg',
            weight_value=1000.0,
            weight_uom=weight_uom,
        )
        sealed = _mock_item(quantity=1000)
        assert check_opened_suggestion(sealed, [sealed], template) is None

    def test_a_smaller_sealed_pack_is_not_taken_for_an_open_one(self) -> None:
        """Only the mark opening writes makes a pack open.

        A sealed pack lighter than the card's full weight — a 400 g bag on a
        card that says 1 kg — was guessed open, so the scan offered it as the
        open pack to cook from, and a scan of that bag offered no open pack at
        all because it was taken for one itself.
        """
        weight_uom = UomDTO(id=uuid4(), category_id=uuid4(), name='gram', symbol='g')
        template = ProductTemplateDTO(
            id=uuid4(),
            organization_id=uuid4(),
            name='Flour 1kg',
            weight_value=1000.0,
            weight_uom=weight_uom,
        )
        full = _mock_item(quantity=1000)
        smaller = _mock_item(quantity=400)
        smaller.location_name = 'Shelf B'
        assert check_opened_suggestion(full, [full, smaller], template) is None

        opened = _mock_item(quantity=300, opened=True)
        opened.location_name = 'Shelf A'
        suggestion = check_opened_suggestion(smaller, [smaller, opened], template)
        assert suggestion is not None
        assert suggestion.opened_item_id == opened.id

    def test_no_weight_uom_returns_none(self) -> None:
        template = ProductTemplateDTO(
            id=uuid4(),
            organization_id=uuid4(),
            name='Generic item',
            weight_value=1000.0,
        )
        sealed = _mock_item(quantity=1000)
        assert check_opened_suggestion(sealed, [sealed], template) is None


# ---------------------------------------------------------------------------
# needs_disambiguation
# ---------------------------------------------------------------------------


class TestNeedsDisambiguation:
    def test_same_location_no_disambiguation(self) -> None:
        loc = uuid4()
        items: list[Item] = [
            _mock_item(storage_location_id=loc),
            _mock_item(storage_location_id=loc),
        ]
        assert needs_disambiguation(items) is False

    def test_different_locations_needs_disambiguation(self) -> None:
        items: list[Item] = [
            _mock_item(storage_location_id=uuid4()),
            _mock_item(storage_location_id=uuid4()),
        ]
        assert needs_disambiguation(items) is True

    def test_single_item_no_disambiguation(self) -> None:
        assert needs_disambiguation([_mock_item()]) is False


# ---------------------------------------------------------------------------
# _match_ingredient — scanning a barcode onto a recipe line
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _ScannedItem:
    name: str
    template_id: UUID | None = None
    id: UUID = field(default_factory=uuid4)


@dataclass(frozen=True)
class _Ingredient:
    name: str
    ingredient_group_name: str | None = None
    template_id: UUID | None = None
    id: UUID = field(default_factory=uuid4)


class TestMatchIngredient:
    """Scanning has to tolerate the same spelling gap availability does."""

    def test_scanned_can_ticks_off_the_differently_worded_line(self) -> None:
        ingredient = _Ingredient(name='Ciecierzyca z puszki')
        scanned = _ScannedItem(name='Ciecierzyca w puszce')
        assert _match_ingredient(scanned, [ingredient]) is ingredient  # type: ignore[arg-type, list-item]

    def test_the_ingredients_own_template_wins(self) -> None:
        template_id = uuid4()
        linked = _Ingredient(name='Coś innego', template_id=template_id)
        by_name = _Ingredient(name='Ciecierzyca z puszki')
        scanned = _ScannedItem(name='Ciecierzyca w puszce', template_id=template_id)
        assert _match_ingredient(scanned, [by_name, linked]) is linked  # type: ignore[arg-type, list-item]

    def test_a_line_named_after_the_item_beats_one_that_mentions_it(self) -> None:
        mention = _Ingredient(name='Spaghetti')
        named = _Ingredient(name='Makaron')
        scanned = _ScannedItem(name='Makaron spaghetti 500g')
        assert _match_ingredient(scanned, [mention, named]) is named  # type: ignore[arg-type, list-item]

    def test_a_qualifier_is_not_the_goods(self) -> None:
        """Scanning tinned tuna must not tick off the oil the recipe wants."""
        ingredient = _Ingredient(name='Olej')
        scanned = _ScannedItem(name='Tunczyk w oleju')
        assert _match_ingredient(scanned, [ingredient]) is None  # type: ignore[arg-type, list-item]

    def test_unrelated_item_matches_nothing(self) -> None:
        ingredient = _Ingredient(name='Ciecierzyca z puszki')
        scanned = _ScannedItem(name='Proszek do pieczenia')
        assert _match_ingredient(scanned, [ingredient]) is None  # type: ignore[arg-type, list-item]
