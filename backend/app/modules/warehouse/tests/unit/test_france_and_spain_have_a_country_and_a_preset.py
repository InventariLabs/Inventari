"""France and Spain have what Poland, Germany and the United Kingdom have.

A country row (the standard VAT rate and whether a partner must carry a tax
id) and a document profile preset (type codes, numbering, print layout) —
the two halves of one organization's paperwork. Without the row a French or
Spanish organization gets no default rate and no requirement; without the
preset it can only choose between a Polish, British or German vocabulary.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.warehouse import document_profile_service
from app.modules.warehouse.country_tax_rules import get_country_rule


@pytest.mark.unit
class TestTheCountryRules:
    @pytest.mark.parametrize(('country', 'rate'), [('FR', '20.00'), ('ES', '21.00')])
    def test_the_country_states_its_standard_rate_and_asks_for_a_tax_id(
        self, country: str, rate: str
    ) -> None:
        rule = get_country_rule(country)
        assert rule is not None
        assert rule.default_tax_rate == Decimal(rate)
        assert rule.require_partner_tax_id is True

    def test_the_code_is_read_in_either_case(self) -> None:
        assert get_country_rule('fr') == get_country_rule('FR')
        assert get_country_rule('es') == get_country_rule('ES')


@pytest.mark.unit
class TestThePresets:
    @pytest.mark.parametrize(
        ('name', 'labels'),
        [
            (
                'FR Entrepôt',
                {
                    'IN': 'BR',
                    'OUT': 'BL',
                    'INT': 'BT',
                    'INTERNAL_IN': 'ERI',
                    'INTERNAL_OUT': 'SCI',
                    'CORRECTION': 'COR',
                },
            ),
            (
                'ES Almacén',
                {
                    'IN': 'AE',
                    'OUT': 'AS',
                    'INT': 'TR',
                    'INTERNAL_IN': 'EI',
                    'INTERNAL_OUT': 'SI',
                    'CORRECTION': 'COR',
                },
            ),
        ],
    )
    def test_the_preset_carries_the_local_type_codes_and_numbers_with_them(
        self, name: str, labels: dict[str, str]
    ) -> None:
        preset = document_profile_service.PRESETS[name]
        assert preset['type_labels'] == labels
        assert preset['numbering_format'] == '{TYPE_LABEL}/{YEAR}/{SEQ:04d}'
        assert preset['number_padding'] == 4
        # Law stays with the country: the preset pins neither a rate nor a
        # requirement (see the sibling presets).
        assert preset['default_tax_rate'] is None
        assert preset['require_partner_tax_id'] is None
