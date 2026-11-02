"""Each country with a rule offers its standard rate and its reduced ones.

The rate table an organization starts from: the standard rate first, then
the reduced rates its law knows, named the way the country names the tax.
A country without a rule offers nothing.
"""

from decimal import Decimal

import pytest

from app.modules.warehouse.tax_rate_assignment_service import country_rate_offer

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ('country', 'offer'),
    [
        ('PL', [('VAT 23%', '23'), ('VAT 8%', '8'), ('VAT 5%', '5')]),
        ('de', [('USt. 19%', '19'), ('USt. 7%', '7')]),
        ('GB', [('VAT 20%', '20'), ('VAT 5%', '5'), ('VAT 0%', '0')]),
        (
            'FR',
            [
                ('TVA 20%', '20'),
                ('TVA 10%', '10'),
                ('TVA 5.5%', '5.5'),
                ('TVA 2.1%', '2.1'),
            ],
        ),
        ('ES', [('IVA 21%', '21'), ('IVA 10%', '10'), ('IVA 4%', '4')]),
    ],
)
def test_a_country_offers_its_standard_and_reduced_rates(
    country: str, offer: list[tuple[str, str]]
) -> None:
    offered = country_rate_offer(country)
    assert [(name, rate) for name, rate, _ in offered] == [
        (name, Decimal(rate)) for name, rate in offer
    ]
    assert [standard for _, _, standard in offered] == [True] + [False] * (
        len(offer) - 1
    )


@pytest.mark.parametrize('country', ['BR', '', None])
def test_a_country_without_a_rule_offers_nothing(country: str | None) -> None:
    assert country_rate_offer(country) == []
