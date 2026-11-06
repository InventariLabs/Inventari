"""Shared PDF generation utilities.

Consolidates Jinja2 filters, barcode generation, and partner address
formatting used by both ``document_pdf_service`` and ``po_pdf_service``.
"""

from __future__ import annotations

import base64
import io
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, cast

import barcode as barcode_lib
import qrcode
from babel import Locale
from jinja2 import Environment, pass_context
from jinja2.runtime import Context

from app.core.datetimes import format_date_for
from app.core.utils import pick_by_lang
from app.i18n._types import SUPPORTED_LANGUAGES, Language
from app.i18n.service import get_unit_label, writes_decimal_comma


def filter_format_date(value: datetime | str | None, lang: str = 'en') -> str:
    if value is None:
        return '—'
    if isinstance(value, str):
        return value[:10]
    try:
        return format_date_for(lang, value)
    except (TypeError, ValueError, AttributeError):
        return str(value)


def _localize_decimal(text: str, lang: str) -> str:
    """Swap the dot of an already formatted number for the language's separator."""
    return text.replace('.', ',') if writes_decimal_comma(lang) else text


def filter_format_qty(value: Decimal | float | str | None, lang: str = 'en') -> str:
    if value is None:
        return '—'
    try:
        d = Decimal(str(value))
        normalized = d.normalize()
        return _localize_decimal(f'{normalized:f}', lang)
    except (InvalidOperation, ValueError):
        return str(value)


def filter_format_decimal(value: Decimal | float | str | None, lang: str = 'en') -> str:
    if value is None:
        return '—'
    try:
        return _localize_decimal(f'{Decimal(str(value)):.2f}', lang)
    except (InvalidOperation, ValueError):
        return str(value)


def filter_format_pct(value: Decimal | float | str | None, lang: str = 'en') -> str:
    if value is None:
        return '—'
    try:
        d = Decimal(str(value))
        if d == d.to_integral_value():
            return f'{int(d)}%'
        return _localize_decimal(f'{d:.2f}%', lang)
    except (InvalidOperation, ValueError):
        return f'{value}%'


# ---------------------------------------------------------------------------
# Printed code geometry
# ---------------------------------------------------------------------------
#
# Two numbers decide whether a printed Code128 can be scanned: the module (the
# width of the narrowest bar) and the bar height. They are set here, in
# millimetres, and the image carries them as its intrinsic size — templates do
# not scale it. They used to: the image was generated at 0.25 mm/module and
# stretched to a CSS ``height``, which moved both numbers at once, so the
# earlier fix ("raise the height") worked by accident and any later attempt to
# lower the bar to a sane height would have narrowed the modules back.
#
# ISO/IEC 15417 asks for a bar height of at least 6.35 mm or 15% of the symbol
# length; 11 mm clears both for every number this app prints, at a third of
# the ink the old 21 mm bar used.
CODE128_MODULE_WIDTH_MM = 0.40
CODE128_BAR_HEIGHT_MM = 11.0
# The header column the codes live in. A number long enough to overflow it
# narrows the module rather than running off the page — down to the floor,
# never past it: a symbol that fits but cannot be read is worse than one that
# overflows, so the floor is where fitting stops being the goal.
CODE128_MAX_WIDTH_MM = 85.0
CODE128_MIN_MODULE_WIDTH_MM = 0.25
# Quiet zone, in modules, on each side (ISO/IEC 15417: at least 10).
_CODE128_QUIET_MODULES = 10

# A QR is read by a phone camera at arm's length; 0.6 mm per module is
# comfortable for that, and the code grows with its payload instead of
# packing more modules into a fixed square.
QR_MODULE_SIZE_MM = 0.6
QR_MIN_SIZE_MM = 16.0
QR_MAX_SIZE_MM = 20.0


@dataclass(frozen=True)
class PrintedCode:
    """A code image together with the size it has to be printed at.

    ``data_uri`` is embeddable as-is; ``width_mm``/``height_mm`` are the
    intrinsic size of the image, so a template that sets no CSS size prints it
    correctly and one that sets an explicit size can state these numbers.
    """

    data_uri: str
    width_mm: float
    height_mm: float
    module_width_mm: float


_SVG_CANVAS_RE = re.compile(
    r'<svg[^>]*\swidth="([\d.]+)mm"[^>]*\sheight="([\d.]+)mm"', re.IGNORECASE
)


def _render_code128_svg(
    value: str, module_width_mm: float, bar_height_mm: float
) -> tuple[bytes, float, float]:
    """Render the symbol and report the canvas size the renderer produced."""
    code128 = barcode_lib.get('code128', value, writer=barcode_lib.writer.SVGWriter())
    buf = io.BytesIO()
    code128.write(
        buf,
        options={
            'write_text': False,
            'module_width': module_width_mm,
            'module_height': bar_height_mm,
            'quiet_zone': _CODE128_QUIET_MODULES * module_width_mm,
        },
    )
    buf.seek(0)
    svg = buf.read()
    match = _SVG_CANVAS_RE.search(svg.decode('utf-8', errors='replace'))
    if match is None:  # pragma: no cover — the writer always emits both
        raise RuntimeError('Code128 SVG carries no canvas size')
    return svg, float(match.group(1)), float(match.group(2))


def generate_code128(
    value: str,
    *,
    module_width_mm: float = CODE128_MODULE_WIDTH_MM,
    bar_height_mm: float = CODE128_BAR_HEIGHT_MM,
    max_width_mm: float = CODE128_MAX_WIDTH_MM,
    min_module_width_mm: float = CODE128_MIN_MODULE_WIDTH_MM,
) -> PrintedCode:
    """Code128 as a vector image sized in millimetres.

    SVG rather than PNG: the bars land on device pixels at whatever resolution
    the printer works in, and the file is a tenth of the size.

    The size is read back off the rendered canvas rather than predicted — the
    quiet zone and the vertical margin are the renderer's business, and a
    predicted number that drifts from the real one is how the geometry got
    away from the templates in the first place.
    """
    svg, width_mm, height_mm = _render_code128_svg(
        value, module_width_mm, bar_height_mm
    )
    if width_mm > max_width_mm:
        module_width_mm = max(
            min_module_width_mm, module_width_mm * max_width_mm / width_mm
        )
        svg, width_mm, height_mm = _render_code128_svg(
            value, module_width_mm, bar_height_mm
        )
    return PrintedCode(
        data_uri='data:image/svg+xml;base64,' + base64.b64encode(svg).decode('ascii'),
        width_mm=width_mm,
        height_mm=height_mm,
        module_width_mm=module_width_mm,
    )


def generate_qr(
    value: str,
    *,
    module_size_mm: float = QR_MODULE_SIZE_MM,
    min_size_mm: float = QR_MIN_SIZE_MM,
    max_size_mm: float = QR_MAX_SIZE_MM,
) -> PrintedCode:
    """QR as a data-URI PNG together with the size it prints at."""
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=3,
    )
    qr.add_data(value)
    qr.make(fit=True)
    img = qr.make_image(fill_color='black', back_color='white').convert('L')
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    # ``modules_count`` excludes the border, which prints as the quiet zone.
    side_modules = qr.modules_count + 2 * qr.border
    size_mm = min(max_size_mm, max(min_size_mm, side_modules * module_size_mm))
    return PrintedCode(
        data_uri='data:image/png;base64,'
        + base64.b64encode(buf.read()).decode('ascii'),
        width_mm=round(size_mm, 3),
        height_mm=round(size_mm, 3),
        module_width_mm=round(size_mm / side_modules, 3),
    )


def generate_code128_base64(value: str) -> str:
    """Code128 data URI at the standard print geometry."""
    return generate_code128(value).data_uri


def generate_qr_base64(value: str) -> str:
    """QR data URI at the standard print geometry."""
    return generate_qr(value).data_uri


def country_name(code: str, lang: str = 'en') -> str:
    """Localised name for an ISO 3166-1 alpha-2 code, falling back to the code.

    Resolved through Babel's CLDR territory tables ( follow-up): the
       API accepts all 249 ISO codes, so the printed name must exist for every
       one of them, in every supported language — a hand-maintained map of 40
       codes printed a bare code (AE) for the other 209. ``lang`` falls back to
       English like the label dictionaries. A value that is not a real code
       (legacy free text) still prints as-is.
    """
    locale = _BABEL_LOCALES.get(lang, _BABEL_LOCALES['en'])
    return locale.territories.get(code) or code


_BABEL_LOCALES: dict[str, Any] = {lang: Locale(lang) for lang in SUPPORTED_LANGUAGES}


def format_partner_address(address: dict | None, lang: str = 'en') -> str | None:
    if not address:
        return None
    parts = []
    for field in ('street', 'city', 'postal_code'):
        val = address.get(field)
        if val:
            parts.append(val)
    country = address.get('country')
    if country:
        parts.append(country_name(str(country), lang))
    return ', '.join(parts) if parts else None


def _in_document_language(func: Any) -> Any:
    """Bind a number/unit formatter to the ``lang`` the template renders in."""

    @pass_context
    def bound(ctx: Context, value: Any) -> str:
        return str(func(value, ctx.get('lang') or 'en'))

    return bound


def filter_unit_label(symbol: str | None, lang: str = 'en') -> str:
    """The unit as the document's language writes it ("szt." for ``pcs``)."""
    if not symbol:
        return '—'
    return get_unit_label(symbol, cast(Language, lang[:2]))


def register_pdf_filters(env: Environment) -> None:
    env.filters['format_date'] = _in_document_language(filter_format_date)
    env.filters['format_qty'] = _in_document_language(filter_format_qty)
    env.filters['format_decimal'] = _in_document_language(filter_format_decimal)
    env.filters['format_pct'] = _in_document_language(filter_format_pct)
    env.filters['unit_label'] = _in_document_language(filter_unit_label)


COMMON_PDF_LABELS_EN: dict[str, str] = {
    'name': 'Name',
    'tax_id': 'Tax ID',
    'address': 'Address',
    'unit': 'Unit',
    'unit_price': 'Unit Price',
    'total_net': 'Net Total',
    'total_gross': 'Gross Total',
    'notes': 'Notes',
    'sig_prepared': 'Prepared by',
    'sig_approved': 'Approved by',
    'created': 'Created',
    'sig_hint': 'Name, date, signature',
}

COMMON_PDF_LABELS_PL: dict[str, str] = {
    'name': 'Nazwa',
    'tax_id': 'NIP',
    'address': 'Adres',
    'unit': 'J.m.',
    'unit_price': 'Cena jedn.',
    'total_net': 'Wartość netto',
    'total_gross': 'Wartość brutto',
    'notes': 'Uwagi',
    'sig_prepared': 'Sporządził',
    'sig_approved': 'Zatwierdził',
    'created': 'Wystawiono',
    'sig_hint': 'Imię, nazwisko, data, podpis',
}

COMMON_PDF_LABELS_DE: dict[str, str] = {
    'name': 'Name',
    'tax_id': 'Steuer-ID',
    'address': 'Adresse',
    'unit': 'Einheit',
    'unit_price': 'Einzelpreis',
    'total_net': 'Nettosumme',
    'total_gross': 'Bruttosumme',
    'notes': 'Anmerkungen',
    'sig_prepared': 'Erstellt von',
    'sig_approved': 'Genehmigt von',
    'created': 'Erstellt',
    'sig_hint': 'Name, Datum, Unterschrift',
}

COMMON_PDF_LABELS_FR: dict[str, str] = {
    'name': 'Nom',
    'tax_id': 'N° de TVA',
    'address': 'Adresse',
    'unit': 'Unité',
    'unit_price': 'Prix unitaire',
    'total_net': 'Total net',
    'total_gross': 'Total brut',
    'notes': 'Remarques',
    'sig_prepared': 'Établi par',
    'sig_approved': 'Approuvé par',
    'created': 'Créé',
    'sig_hint': 'Nom, date, signature',
}

COMMON_PDF_LABELS_ES: dict[str, str] = {
    'name': 'Nombre',
    'tax_id': 'NIF',
    'address': 'Dirección',
    'unit': 'Unidad',
    'unit_price': 'Precio unitario',
    'total_net': 'Total neto',
    'total_gross': 'Total bruto',
    'notes': 'Notas',
    'sig_prepared': 'Preparado por',
    'sig_approved': 'Aprobado por',
    'created': 'Creado',
    'sig_hint': 'Nombre, fecha, firma',
}

DOC_STATUS_LABELS_EN: dict[str, str] = {
    'DRAFT': 'Draft',
    'CONFIRMED': 'Confirmed',
    'COMPLETED': 'Completed',
    'CANCELLED': 'Cancelled',
}

DOC_STATUS_LABELS_PL: dict[str, str] = {
    'DRAFT': 'Projekt',
    'CONFIRMED': 'Potwierdzone',
    'COMPLETED': 'Zakończone',
    'CANCELLED': 'Anulowane',
}

DOC_STATUS_LABELS_DE: dict[str, str] = {
    'DRAFT': 'Entwurf',
    'CONFIRMED': 'Bestätigt',
    'COMPLETED': 'Abgeschlossen',
    'CANCELLED': 'Storniert',
}

DOC_STATUS_LABELS_FR: dict[str, str] = {
    'DRAFT': 'Brouillon',
    'CONFIRMED': 'Confirmé',
    'COMPLETED': 'Terminé',
    'CANCELLED': 'Annulé',
}

DOC_STATUS_LABELS_ES: dict[str, str] = {
    'DRAFT': 'Borrador',
    'CONFIRMED': 'Confirmado',
    'COMPLETED': 'Completado',
    'CANCELLED': 'Cancelado',
}


def get_doc_status_map(lang: str) -> dict[str, str]:
    return pick_by_lang(
        lang,
        DOC_STATUS_LABELS_EN,
        pl=DOC_STATUS_LABELS_PL,
        de=DOC_STATUS_LABELS_DE,
        fr=DOC_STATUS_LABELS_FR,
        es=DOC_STATUS_LABELS_ES,
    )
