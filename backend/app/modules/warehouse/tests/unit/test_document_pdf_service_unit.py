from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from jinja2 import Environment

from app.modules.warehouse.document_pdf_service import (
    _get_labels,
    _get_line_status_map,
    _PartnerContext,
    _resolve_doc_title,
)
from app.services.pdf_utils import (
    filter_format_date,
    filter_format_decimal,
    filter_format_pct,
    filter_format_qty,
    format_partner_address,
    register_pdf_filters,
)


@pytest.mark.unit
class TestFilterFormatDate:
    async def test_none_returns_dash(self) -> None:
        assert filter_format_date(None) == '—'

    async def test_datetime_is_written_the_way_the_language_writes_it(self) -> None:
        dt = datetime(2025, 3, 15, 10, 30)
        assert filter_format_date(dt, 'pl') == '15.03.2025'
        assert filter_format_date(dt, 'fr') == '15/03/2025'
        assert filter_format_date(dt, 'en') == 'Mar 15, 2025'
        assert filter_format_date(dt) == 'Mar 15, 2025'

    async def test_template_filter_takes_the_language_of_the_document(self) -> None:
        env = Environment(autoescape=True)
        register_pdf_filters(env)
        template = env.from_string('{{ d | format_date }}')
        d = datetime(2025, 3, 15)
        assert template.render(d=d, lang='pl') == '15.03.2025'
        assert template.render(d=d, lang='en') == 'Mar 15, 2025'

    async def test_iso_string_returns_first_10_chars(self) -> None:
        assert filter_format_date('2025-06-15T10:30:00') == '2025-06-15'

    async def test_plain_string_passthrough(self) -> None:
        assert filter_format_date('15.03.2025') == '15.03.2025'

    async def test_non_date_object_str_representation(self) -> None:
        assert filter_format_date('123') == '123'


@pytest.mark.unit
class TestFilterFormatQty:
    async def test_none_returns_dash(self) -> None:
        assert filter_format_qty(None) == '—'

    async def test_strips_trailing_zeros(self) -> None:
        assert filter_format_qty(Decimal('10.50')) == '10.5'

    async def test_integer_value(self) -> None:
        assert filter_format_qty(Decimal('100')) == '100'

    async def test_zero(self) -> None:
        assert filter_format_qty(Decimal('0')) == '0'

    async def test_float_input(self) -> None:
        assert filter_format_qty(3.14) == '3.14'

    async def test_string_input(self) -> None:
        assert filter_format_qty('42.00') == '42'

    async def test_invalid_returns_raw_string(self) -> None:
        assert filter_format_qty('not_a_number') == 'not_a_number'


@pytest.mark.unit
class TestFilterFormatDecimal:
    async def test_none_returns_dash(self) -> None:
        assert filter_format_decimal(None) == '—'

    async def test_two_decimal_places(self) -> None:
        assert filter_format_decimal(Decimal('10.5')) == '10.50'

    async def test_integer_gets_two_decimals(self) -> None:
        assert filter_format_decimal(Decimal('100')) == '100.00'

    async def test_zero(self) -> None:
        assert filter_format_decimal(Decimal('0')) == '0.00'

    async def test_large_number(self) -> None:
        assert filter_format_decimal(Decimal('123456.789')) == '123456.79'

    async def test_invalid_returns_raw_string(self) -> None:
        assert filter_format_decimal('abc') == 'abc'


@pytest.mark.unit
class TestFilterFormatPct:
    async def test_none_returns_dash(self) -> None:
        assert filter_format_pct(None) == '—'

    async def test_integer_percentage(self) -> None:
        assert filter_format_pct(Decimal('23')) == '23%'

    async def test_fractional_percentage(self) -> None:
        assert filter_format_pct(Decimal('8.5')) == '8.50%'

    async def test_zero_percentage(self) -> None:
        assert filter_format_pct(Decimal('0')) == '0%'

    async def test_invalid_returns_raw_with_percent(self) -> None:
        assert filter_format_pct('abc') == 'abc%'


@pytest.mark.unit
class TestGetLabels:
    async def test_english_labels(self) -> None:
        labels = _get_labels('en')
        assert labels['document_details'] == 'Document Details'

    async def test_polish_labels(self) -> None:
        labels = _get_labels('pl')
        assert labels['document_details'] == 'Dane dokumentu'

    async def test_german_labels(self) -> None:
        labels = _get_labels('de')
        assert labels['document_details'] == 'Dokumentdetails'

    async def test_french_labels(self) -> None:
        labels = _get_labels('fr')
        assert labels['document_details'] == 'Détails du document'

    async def test_spanish_labels(self) -> None:
        labels = _get_labels('es')
        assert labels['document_details'] == 'Detalles del documento'

    async def test_unknown_lang_defaults_to_english(self) -> None:
        labels = _get_labels('it')
        assert labels['document_details'] == 'Document Details'


@pytest.mark.unit
class TestGetLineStatusMap:
    async def test_english(self) -> None:
        m = _get_line_status_map('en')
        assert m['DONE'] == 'Done'

    async def test_polish(self) -> None:
        m = _get_line_status_map('pl')
        assert m['DONE'] == 'Wykonano'

    async def test_german(self) -> None:
        m = _get_line_status_map('de')
        assert m['DONE'] == 'Erledigt'

    async def test_french(self) -> None:
        m = _get_line_status_map('fr')
        assert m['DONE'] == 'Terminé'

    async def test_spanish(self) -> None:
        m = _get_line_status_map('es')
        assert m['DONE'] == 'Completado'


@pytest.mark.unit
class TestResolveDocTitle:
    async def test_profile_type_labels_take_priority(self) -> None:
        profile = MagicMock()
        profile.type_labels = {'IN': 'Custom Receipt'}
        assert _resolve_doc_title('IN', profile, 'en') == 'Custom Receipt'

    async def test_falls_back_to_english_default(self) -> None:
        assert _resolve_doc_title('IN', None, 'en') == 'Goods Receipt Note'

    async def test_falls_back_to_polish_default(self) -> None:
        assert _resolve_doc_title('IN', None, 'pl') == 'Przyjęcie Zewnętrzne'

    async def test_falls_back_to_german_default(self) -> None:
        assert _resolve_doc_title('IN', None, 'de') == 'Wareneingang'

    async def test_falls_back_to_french_default(self) -> None:
        assert _resolve_doc_title('IN', None, 'fr') == 'Bon de réception'

    async def test_falls_back_to_spanish_default(self) -> None:
        assert _resolve_doc_title('IN', None, 'es') == 'Nota de recepción'

    async def test_unknown_type_returns_raw_code(self) -> None:
        assert _resolve_doc_title('UNKNOWN', None, 'en') == 'UNKNOWN'

    async def test_profile_without_type_labels(self) -> None:
        profile = MagicMock()
        profile.type_labels = None
        assert _resolve_doc_title('OUT', profile, 'en') == 'Goods Dispatch Note'

    async def test_profile_empty_type_labels(self) -> None:
        profile = MagicMock()
        profile.type_labels = {}
        assert _resolve_doc_title('INT', profile, 'en') == 'Internal Transfer'


@pytest.mark.unit
class TestFormatPartnerAddress:
    async def test_none_returns_none(self) -> None:
        assert format_partner_address(None) is None

    async def test_empty_dict_returns_none(self) -> None:
        assert format_partner_address({}) is None

    async def test_full_address(self) -> None:
        addr = {
            'street': 'Main St 1',
            'city': 'Warsaw',
            'postal_code': '00-001',
            'country': 'PL',
        }
        # the country prints as a name (English default), not the code.
        result = format_partner_address(addr)
        assert result == 'Main St 1, Warsaw, 00-001, Poland'

    async def test_full_address_localized_country(self) -> None:
        addr = {
            'street': 'Main St 1',
            'city': 'Warsaw',
            'postal_code': '00-001',
            'country': 'PL',
        }
        assert format_partner_address(addr, lang='de') == (
            'Main St 1, Warsaw, 00-001, Polen'
        )
        assert format_partner_address(addr, lang='fr') == (
            'Main St 1, Warsaw, 00-001, Pologne'
        )
        assert format_partner_address(addr, lang='es') == (
            'Main St 1, Warsaw, 00-001, Polonia'
        )

    async def test_partial_address(self) -> None:
        addr = {'city': 'Berlin'}
        assert format_partner_address(addr) == 'Berlin'

    async def test_skips_none_values(self) -> None:
        addr = {
            'street': 'Main St',
            'city': None,
            'postal_code': '12345',
            'country': None,
        }
        assert format_partner_address(addr) == 'Main St, 12345'


@pytest.mark.unit
class TestPartnerContext:
    async def test_from_partner(self) -> None:
        partner = MagicMock()
        partner.name = 'Acme Corp'
        partner.code = 'ACM'
        partner.tax_id = '1234567890'
        partner.address = {'city': 'Warsaw'}
        ctx = _PartnerContext(partner)
        assert ctx.name == 'Acme Corp'
        assert ctx.code == 'ACM'
        assert ctx.tax_id == '1234567890'
        assert ctx.address == 'Warsaw'

    async def test_from_none_partner(self) -> None:
        ctx = _PartnerContext(None)
        assert ctx.name is None
        assert ctx.code is None

    async def test_from_snapshot(self) -> None:
        snapshot = {
            'name': 'Old Corp',
            'code': 'OLD',
            'tax_id': '999',
            'address': {'street': 'Old St', 'city': 'Krakow'},
        }
        ctx = _PartnerContext.from_snapshot(snapshot)
        assert ctx.name == 'Old Corp'
        assert ctx.code == 'OLD'
        assert ctx.address == 'Old St, Krakow'

    async def test_from_empty_snapshot(self) -> None:
        ctx = _PartnerContext.from_snapshot({})
        assert ctx.name is None
        assert ctx.address is None


@pytest.mark.unit
class TestSharedPdfRendering:
    def test_generate_pdf_uses_base_converter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Fails on the separate document WeasyPrint call."""
        from app.core.pdf_base_service import PdfServiceBase
        from app.modules.warehouse import document_pdf_service as service

        rendered: list[str] = []

        def convert(html: str) -> bytes:
            rendered.append(html)
            return b'shared-pdf'

        monkeypatch.setattr(
            service, 'build_pdf_context', lambda *args, **kwargs: {'quantity': 12.5}
        )
        monkeypatch.setattr(
            PdfServiceBase,
            'render_to_pdf',
            staticmethod(convert),
        )
        result = service.generate_pdf(
            MagicMock(),
            None,
            user_template_html='<p>{{ quantity | format_decimal }}</p>',
            page_size='letter',
        )
        assert result == b'shared-pdf'
        assert '<p>12.50</p>' in rendered[0]
        assert 'Letter' in rendered[0]


@pytest.mark.unit
class TestBuiltInLayout:
    """A profile that names no layout follows the organization's country."""

    @pytest.mark.parametrize(
        ('country', 'expected'),
        [('PL', 'pl_pz'), ('pl', 'pl_pz'), ('DE', 'standard'), (None, 'standard')],
    )
    def test_auto_follows_the_country(self, country: str | None, expected: str) -> None:
        from app.modules.warehouse.document_pdf_service import built_in_layout

        profile = MagicMock(print_template='auto')
        assert built_in_layout(profile, country) == expected

    def test_a_named_layout_is_kept_whatever_the_country(self) -> None:
        from app.modules.warehouse.document_pdf_service import built_in_layout

        assert built_in_layout(MagicMock(print_template='standard'), 'PL') == (
            'standard'
        )
        assert built_in_layout(MagicMock(print_template='pl_pz'), 'DE') == 'pl_pz'

    def test_a_polish_organization_prints_polish_without_asking(self) -> None:
        from app.modules.warehouse.document_pdf_service import (
            _resolve_template_and_lang,
        )

        name, lang = _resolve_template_and_lang(
            MagicMock(print_template='auto'), 'en', 'PL'
        )
        assert (name, lang) == ('pl_pz', 'pl')
