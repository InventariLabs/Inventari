"""Total line weight is quantity times the template's unit weight."""

from decimal import Decimal

from app.models.item import Item
from app.models.product_template import ProductTemplate
from app.models.uom import Uom, UomCategory
from app.services.items.weight import total_weight


class TestTotalWeight:
    def test_reads_a_gram_value_in_kilograms(self):
        # 500 g per piece, 3 pieces → 1.5 kg
        assert total_weight(Decimal('3'), 500.0) == Decimal('1.5')

    def test_applies_the_unit_factor(self):
        # 0.5 kg per piece (factor 1000), 3 pieces → 1.5 kg
        assert total_weight(Decimal('3'), 0.5, 1000.0) == Decimal('1.5')

    def test_handles_a_non_metric_unit(self):
        # 4 oz per piece, 2 pieces → 226.796 g, weighed to the gram.
        assert total_weight(Decimal('2'), 4.0, 28.3495) == Decimal('0.227')

    def test_states_the_weight_to_the_gram_and_no_further(self):
        # Measured on the item card: "NET WEIGHT: 1.6000000000000 kg", and
        # 66 of 66 items with a weight answered the same way. Dividing a
        # Decimal keeps the context's precision, and the tail travelled from
        # the conversion through the serializer onto the screen.
        weight = total_weight(Decimal('4.0000'), 400.000000)

        assert weight == Decimal('1.6')
        assert str(weight) == '1.600'

    def test_rounds_a_product_that_does_not_divide(self):
        # A tenth of a gram per piece over seven pieces: 0.0023333331 kg
        # exactly, which is 2.333 g on any scale anybody owns.
        weight = total_weight(Decimal('7'), 0.333333)

        assert str(weight) == '0.002'

    def test_no_unit_weight_means_no_total(self):
        assert total_weight(Decimal('3'), None) is None
        assert total_weight(Decimal('3'), 0.0) is None

    def test_no_quantity_means_no_total(self):
        assert total_weight(None, 500.0) is None

    def test_zero_quantity_weighs_nothing(self):
        assert total_weight(Decimal('0'), 500.0) == Decimal('0')


class TestQuantityAsWeight:
    def test_a_gram_quantity_is_read_as_kilograms(self):
        from app.services.items.weight import quantity_as_weight

        assert quantity_as_weight(Decimal('500'), 1.0) == Decimal('0.5')

    def test_a_kilogram_quantity_passes_through(self):
        from app.services.items.weight import quantity_as_weight

        assert quantity_as_weight(Decimal('2'), 1000.0) == Decimal('2')

    def test_no_quantity_means_no_weight(self):
        from app.services.items.weight import quantity_as_weight

        assert quantity_as_weight(None, 1.0) is None


def _uom(category: str, name: str, symbol: str, factor: float = 1.0) -> Uom:
    return Uom(
        name=name,
        symbol=symbol,
        factor=factor,
        category=UomCategory(name=category),
    )


class TestTotalWeightUnit:
    """The unit follows whichever unit produced the number.

    Reading it off the quantity's own category works only for continuous
    lines. A line counted in pieces takes its weight from the template, so
    the template's unit is the one that answers — otherwise every bottled
    drink sold by the piece reports litres as kilograms.
    """

    def test_bottles_counted_in_pieces_report_litres(self):
        item = Item(
            quantity=Decimal('6'),
            uom=_uom('Unit', 'piece', 'pcs'),
            template=ProductTemplate(
                weight_value=1500.0,
                weight_uom=_uom('Volume', 'millilitre', 'ml'),
            ),
        )

        assert item.total_weight == Decimal('9')
        assert item.total_weight_unit == 'l'

    def test_packs_counted_in_pieces_report_kilograms(self):
        item = Item(
            quantity=Decimal('6'),
            uom=_uom('Unit', 'piece', 'pcs'),
            template=ProductTemplate(
                weight_value=500.0,
                weight_uom=_uom('Weight', 'gram', 'g'),
            ),
        )

        assert item.total_weight == Decimal('3')
        assert item.total_weight_unit == 'kg'

    def test_a_line_counted_in_litres_keeps_its_own_unit(self):
        item = Item(
            quantity=Decimal('1.5'),
            uom=_uom('Volume', 'litre', 'l', factor=1000.0),
            template=ProductTemplate(weight_value=None, weight_uom=None),
        )

        assert item.total_weight == Decimal('1.5')
        assert item.total_weight_unit == 'l'

    def test_a_line_counted_in_kilograms_keeps_its_own_unit(self):
        item = Item(
            quantity=Decimal('2'),
            uom=_uom('Weight', 'kilogram', 'kg', factor=1000.0),
            template=ProductTemplate(
                weight_value=1500.0,
                weight_uom=_uom('Volume', 'millilitre', 'ml'),
            ),
        )

        assert item.total_weight == Decimal('2')
        assert item.total_weight_unit == 'kg'

    def test_a_product_with_no_weight_unit_falls_back_to_kilograms(self):
        item = Item(
            quantity=Decimal('6'),
            uom=_uom('Unit', 'piece', 'pcs'),
            template=ProductTemplate(weight_value=500.0, weight_uom=None),
        )

        assert item.total_weight == Decimal('3')
        assert item.total_weight_unit == 'kg'

    def test_no_weight_means_no_unit(self):
        item = Item(
            quantity=Decimal('6'),
            uom=_uom('Unit', 'piece', 'pcs'),
            template=ProductTemplate(weight_value=None, weight_uom=None),
        )

        assert item.total_weight is None
        assert item.total_weight_unit is None
