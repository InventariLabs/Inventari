"""The numbers and requirements a country gives an organization's documents.

A document profile carries two axes at once: how an organization works
(numbering, type labels, visible line fields, print template) and the law
where it sits (the tax rate its documents apply, whether the partner must
carry a tax id). The first belongs to a preset, the second to the
organization's country — the division the organization currency already
follows: the preset's entry is an override and the organization is the
source of truth.

The table starts with the three countries the presets used to name — the
law their presets pinned moved here, so ``PL Magazyn`` still means 23% for
a Polish organization, and now means it on every work profile — and France
and Spain, whose presets name their own paperwork. The Polish tax-id
requirement is a product default for B2B practice rather than a statute;
only a row grounded in the country's law says ``True`` by right. Adding a
country is a row in ``COUNTRY_RULES``; it changes no preset and no
frontend list. A country with no row degrades to the profile as it stands
(no rate, no requirement), never to an exception.
"""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class CountryTaxRule:
    """The numbers and requirements one country's documents follow."""

    #: Standard VAT rate the country applies when the profile names none.
    default_tax_rate: Decimal
    #: Whether a document naming a partner must see that partner's tax id
    #: before it can be confirmed.
    require_partner_tax_id: bool
    #: The reduced rates the country's law knows besides the standard one —
    #: food, books, medicine. Offered to an organization as a starting rate
    #: table; which goods a rate applies to is the organization's to say.
    reduced_tax_rates: tuple[Decimal, ...] = ()
    #: What the country calls the tax, for the names of the rates it offers.
    tax_name: str = 'VAT'
    #: The preset that carries the country's paperwork (document names,
    #: numbering, print layout), offered at onboarding. ``None``: no preset
    #: of its own, only the rate and the requirement above apply.
    document_preset: str | None = None


COUNTRY_RULES: dict[str, CountryTaxRule] = {
    'PL': CountryTaxRule(
        default_tax_rate=Decimal('23.00'),
        require_partner_tax_id=True,
        reduced_tax_rates=(Decimal('8.00'), Decimal('5.00')),
        document_preset='PL Magazyn',
    ),
    # §14(4) UStG names only the supplier's own number as an invoice field;
    # the recipient's USt-IdNr. matters for intra-EU supplies and reverse
    # charge, and a delivery note has no tax-id field at all. An organization
    # that wants the check turns it on in its document profile.
    'DE': CountryTaxRule(
        default_tax_rate=Decimal('19.00'),
        require_partner_tax_id=False,
        reduced_tax_rates=(Decimal('7.00'),),
        tax_name='USt.',
        document_preset='DE Lager',
    ),
    'GB': CountryTaxRule(
        default_tax_rate=Decimal('20.00'),
        require_partner_tax_id=False,
        # Zero-rated is a rate of its own, not "untaxed": the line still
        # belongs on the return, in the zero-rate box.
        reduced_tax_rates=(Decimal('5.00'), Decimal('0.00')),
        document_preset='UK Warehouse',
    ),
    # Standard rate: Code général des impôts, art. 278. A B2B invoice names
    # the customer's SIREN, and its VAT number for intra-EU supplies (CGI
    # annexe IV, art. 242 nonies A; art. 289) — the requirement a consumer
    # is exempt from (``Partner.is_consumer``).
    'FR': CountryTaxRule(
        default_tax_rate=Decimal('20.00'),
        require_partner_tax_id=True,
        # CGI art. 279 (10 %), 278-0 bis (5.5 %, most food), 281 quater (2.1 %).
        reduced_tax_rates=(Decimal('10.00'), Decimal('5.50'), Decimal('2.10')),
        tax_name='TVA',
        document_preset='FR Entrepôt',
    ),
    # Standard rate: Ley 37/1992 del IVA, art. 90. An invoice to a business
    # carries the recipient's NIF (Real Decreto 1619/2012, art. 6.1.d).
    'ES': CountryTaxRule(
        default_tax_rate=Decimal('21.00'),
        require_partner_tax_id=True,
        # Ley 37/1992, art. 91: 10 % and, for basic food, 4 %.
        reduced_tax_rates=(Decimal('10.00'), Decimal('4.00')),
        tax_name='IVA',
        document_preset='ES Almacén',
    ),
}


def get_country_rule(country: str | None) -> CountryTaxRule | None:
    """The rule for a country, or None when the country has no row.

    ISO-2 codes reach us in the case the caller stored them; ``PL`` and
    ``pl`` are the same country. An unknown or absent country returns None,
    which the resolvers read as "the profile stands" — never as an error.
    """
    if not country:
        return None
    return COUNTRY_RULES.get(country.upper())


def country_requires_partner_tax_id(country: str | None) -> bool:
    """Whether the country's documents demand a partner's tax id.

    The one place that default is read: the offer the settings screen shows
    and the check at confirmation both ask here, so they cannot drift apart.
    A country with no row, or no country at all, requires nothing.
    """
    rule = get_country_rule(country)
    return rule.require_partner_tax_id if rule else False
