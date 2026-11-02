"""What a product label prints beside its QR code.

The caption on the screenshots that started this — "minced beef 8.2026" —
was typed by hand into a description field, while both halves of it were
already on the record it was about. So a label with nothing typed for it
composes one from the product it is assigned to.
"""

from dataclasses import dataclass
from datetime import date

from app.services.label_service import label_caption


@dataclass
class _Label:
    description: str | None = None
    assigned_item_name: str | None = None
    assigned_item_expiry: date | None = None


class TestLabelCaption:
    def test_a_caption_typed_for_this_label_wins(self):
        label = _Label(
            description='Grandma’s jam',
            assigned_item_name='Strawberry jam',
        )
        assert label_caption(label) == 'Grandma’s jam'

    def test_the_product_supplies_one_when_nothing_was_typed(self):
        label = _Label(assigned_item_name='Minced beef')
        assert label_caption(label) == 'Minced beef'

    def test_an_expiry_joins_the_name_as_month_and_year(self):
        label = _Label(
            assigned_item_name='Minced beef',
            assigned_item_expiry=date(2026, 8, 14),
        )
        assert label_caption(label) == 'Minced beef 8.2026'

    def test_an_unassigned_label_has_nothing_to_say(self):
        assert label_caption(_Label()) is None
