"""PDF generation service for warehouse documents.

Uses Jinja2 for HTML templating and WeasyPrint for PDF rendering.
Two built-in templates are available:
  - ``standard``: clean, neutral layout with optional pricing section
  - ``pl_pz``:    Polish PZ format with signature blocks and value summary

The template is selected from ``DocumentProfile.print_template``. If the
profile has ``value_tracking_enabled = True`` the price/value/tax columns are
included in the output.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from datetime import date, datetime
from decimal import Decimal
from functools import partial
from pathlib import Path
from typing import Any

from app.core.async_utils import run_sync_in_thread
from app.core.logging import get_logger
from app.core.money import amounts_by_rate
from app.core.pdf_base_service import PdfServiceBase
from app.core.print_identity import (
    IssuerContext,
    build_issuer_context,
    print_date_rows,
)
from app.core.print_page_size import apply_page_size, page_size_of
from app.core.public_api import core_api
from app.core.utils import pick_by_lang
from app.i18n import SUPPORTED_LANGUAGES

from ._pdf_labels import (  # noqa: F401
    _DEFAULT_TYPE_TITLES_DE,
    _DEFAULT_TYPE_TITLES_EN,
    _DEFAULT_TYPE_TITLES_ES,
    _DEFAULT_TYPE_TITLES_FR,
    _DEFAULT_TYPE_TITLES_PL,
    _LABELS_DE,
    _LABELS_EN,
    _LABELS_ES,
    _LABELS_FR,
    _LABELS_PL,
    _LINE_STATUS_LABELS_EN,
    _LINE_STATUS_LABELS_PL,
    _get_discrepancy_map,
    _get_line_status_map,
    _get_scrap_reason_map,
    _resolve_doc_title,
)
from .document_types import carries_value, is_scrap
from .models import Document, DocumentLine, DocumentProfile

logger = get_logger(__name__)

# Absolute path to the templates directory shipped with this module.
_TEMPLATES_DIR = Path(__file__).parent / 'templates'

# A layout written in one language says so on its root element,
# ``<html lang="pl">``; one that follows the reader writes
# ``<html lang="{{ lang }}">``, which this does not match.
_DECLARED_LANG = re.compile(
    r'<html\b[^>]*?\blang=["\']([a-z]{2})(?:-[a-z]{2})?["\']', re.IGNORECASE
)


class _DocumentPdfService(PdfServiceBase):
    templates_dir = _TEMPLATES_DIR
    labels_en = _LABELS_EN
    labels_pl = _LABELS_PL
    labels_de = _LABELS_DE
    labels_fr = _LABELS_FR
    labels_es = _LABELS_ES
    module_name = 'warehouse'


_svc = _DocumentPdfService()


def _get_labels(lang: str) -> dict[str, str]:
    return _svc.get_labels(lang)


def _labels_for_document(document: Document, lang: str) -> dict[str, str]:
    """The labels a document's printout reads, its date named for what it is.

    "Scheduled" over a document that is done reads as a plan nobody kept; the
    day is the one the register files the document under, so once the
    document is completed it is the document's own date.
    """
    labels = _get_labels(lang)
    if document.status == 'COMPLETED':
        return {**labels, 'scheduled': labels['document_date']}
    return labels


def _own_date_row(
    document: Document, labels: dict[str, str]
) -> tuple[str, date | datetime | None]:
    """The header's first date: the document's own day once it is done.

    The register files a completed document under ``scheduled_date``; a
    header that stamped the day it was typed in disagreed with the body
    beneath it. Confirmation and completion stamps still follow.
    """
    if document.status == 'COMPLETED' and document.scheduled_date:
        return labels['scheduled'], document.scheduled_date
    return labels['created'], document.created_at


class _PartnerContext:
    """Minimal data-transfer object passed to the template."""

    def __init__(self, partner: Any, lang: str = 'en') -> None:
        self.name = partner.name if partner else None
        self.code = getattr(partner, 'code', None)
        self.tax_id = getattr(partner, 'tax_id', None)
        self.address = core_api.pdf.format_partner_address(
            getattr(partner, 'address', None), lang
        )

    @classmethod
    def from_snapshot(
        cls, snapshot: dict[str, Any], lang: str = 'en'
    ) -> _PartnerContext:
        """Build context from a denormalized partner snapshot (historical data)."""
        obj = cls.__new__(cls)
        obj.name = snapshot.get('name')
        obj.code = snapshot.get('code')
        obj.tax_id = snapshot.get('tax_id')
        obj.address = core_api.pdf.format_partner_address(snapshot.get('address'), lang)
        return obj


def print_lang(template_html: str, lang: str) -> str:
    """The language a layout prints in: the one it declares, else ``lang``.

    A layout whose own wording is fixed — PL PZ is a Polish form — still
    includes the shared header, and the header reads its title, status and
    dates from the context. Built for the reader's language, that context
    put "Goods Receipt Note" and "DRAFT" above "DOSTAWCA" on one sheet. The
    language is read from the layout itself, so a built-in, an
    organization's copy of it and the editor's preview all agree with what
    the layout says it is written in.
    """
    match = _DECLARED_LANG.search(template_html)
    declared = match.group(1).lower() if match else None
    return declared if declared in SUPPORTED_LANGUAGES else lang


def built_in_layout(profile: DocumentProfile | None, country: str | None) -> str:
    """The built-in layout family a profile prints through.

    ``auto`` — what a profile starts with — follows the organization's
    country: a Polish organization prints the Polish form (``pl_pz``), every
    other country the standard layout, which writes its words and dates in
    the print language. A profile that names a family keeps it.
    """
    name = (profile.print_template if profile else 'auto') or 'auto'
    if name == 'auto':
        return 'pl_pz' if (country or '').upper() == 'PL' else 'standard'
    if name not in ('standard', 'pl_pz'):
        logger.warning('Unknown print_template %r — falling back to "standard"', name)
        return 'standard'
    return name


def _resolve_template_and_lang(
    profile: DocumentProfile | None, lang: str, country: str | None = None
) -> tuple[str, str]:
    """The built-in template family and the language the document prints in.

    The language must be resolved before the issuer/labels are built —
    otherwise a Polish layout would print English issuer data.
    """
    template_name = built_in_layout(profile, country)
    source = (_TEMPLATES_DIR / f'{template_name}.html').read_text(encoding='utf-8')
    return template_name, print_lang(source, lang)


def _quantity_totals_by_unit(
    lines: Iterable[DocumentLine],
) -> list[dict[str, Any]]:
    """Quantity totals grouped by the unit the lines are in.

    A grand total means something only inside one unit — 123 pieces and 2.5
    kilograms add up to 125.5 of nothing, yet the totals row printed exactly
    that. The groups come back in the order their units first appear, so a
    layout printing them prints them in the order the document carries them.
    """
    groups: dict[str | None, dict[str, Any]] = {}
    for line in lines:
        symbol = line.uom.symbol if line.uom else None
        group = groups.setdefault(
            symbol,
            {'symbol': symbol, 'expected': Decimal('0'), 'done': Decimal('0')},
        )
        group['expected'] += line.expected_quantity or Decimal('0')
        group['done'] += line.done_quantity or Decimal('0')
    return list(groups.values())


def _issuer_and_places(
    document: Document, issuer: IssuerContext | None, lang: str
) -> tuple[IssuerContext | None, str | None, str | None]:
    """The issuer block and the two place names the printout states.

    Frozen at confirmation like the partner (``print_snapshot``); a document
    confirmed before that has none and prints them live. The logo is never
    frozen, so it always comes from the ``issuer`` passed in.
    """
    frozen = document.print_snapshot
    if not frozen:
        return (
            issuer,
            document.source_location.name if document.source_location else None,
            document.target_location.name if document.target_location else None,
        )
    if frozen.get('issuer'):
        frozen_issuer = IssuerContext.from_snapshot(frozen['issuer'], lang)
        frozen_issuer.logo = issuer.logo if issuer else None
        issuer = frozen_issuer
    return issuer, frozen.get('source_location'), frozen.get('target_location')


def build_pdf_context(
    document: Document,
    profile: DocumentProfile | None,
    lang: str = 'en',
    issuer: IssuerContext | None = None,
    packages: list[dict[str, Any]] | None = None,
    country: str | None = None,
) -> dict[str, Any]:
    """Build the Jinja2 render context for a document.

    ``country`` is the organization's ISO code; English dates are written
    day-first unless it is the US, as on the screen.

    Shared between PDF generation and the placeholders catalog, so
       the list of available fields cannot drift from what actually renders.
       The language must already be resolved for the template family (see
       ``_resolve_template_and_lang``).
    """
    # 1. Compute value-column visibility. Price and VAT are printed for the
    # documents that carry them — receipts and issues — and only where the
    # profile tracks value: a transfer, a correction or a scrap is offered no
    # price field, so its printout asks no price question either (the same
    # rule the screens read through `showsDocumentValue`).
    value_tracking = bool(profile and profile.value_tracking_enabled)
    show_value_columns = value_tracking and carries_value(document.type)
    show_tax_column = (
        show_value_columns and profile is not None and profile.tax_handling != 'NONE'
    )

    # 2. Build totals for footer.
    total_expected = sum(
        (line.expected_quantity or Decimal('0')) for line in document.lines
    )
    total_done = sum((line.done_quantity or Decimal('0')) for line in document.lines)
    # The same totals per unit: a layout that prints quantities reads these,
    # so a document in two units gets two totals instead of one sum of
    # pieces and kilograms.
    totals_by_unit = _quantity_totals_by_unit(document.lines)

    # 3. Build partner/location context.
    # Use snapshot for confirmed/completed documents (historical accuracy),
    # fall back to live partner for drafts.
    if document.partner_snapshot:
        partner_ctx = _PartnerContext.from_snapshot(document.partner_snapshot, lang)
    elif document.partner:
        partner_ctx = _PartnerContext(document.partner, lang)
    else:
        partner_ctx = None
    issuer, source_location, target_location = _issuer_and_places(
        document, issuer, lang
    )

    # 4. Resolve labels and document title.
    labels = _labels_for_document(document, lang)
    doc_title = _resolve_doc_title(document.type, profile, lang)
    # Subtitle is the default name of the document type, in the document's
    # language — the same table the title falls back to.
    _subtitle_defaults = pick_by_lang(
        lang,
        _DEFAULT_TYPE_TITLES_EN,
        pl=_DEFAULT_TYPE_TITLES_PL,
        de=_DEFAULT_TYPE_TITLES_DE,
        fr=_DEFAULT_TYPE_TITLES_FR,
        es=_DEFAULT_TYPE_TITLES_ES,
    )
    doc_subtitle = _subtitle_defaults.get(document.type, '')

    corrected_doc_number = (
        document.corrected_document.number if document.corrected_document else None
    )
    # A backorder keeps no note naming the receipt it continues (the English
    # sentence it used to store reached every language), and its link column
    # is what the screens read — so the printout names the original here,
    # the same shape a correction prints its corrected document.
    backorder_of_number = (
        document.backorder_of.number if document.backorder_of else None
    )
    # A return keeps no note sentence naming the document it reverses
    # either; the stored ``returns`` relation is the pointer, exposed as a
    # transient field by the read path, and the printout names the original
    # from it in the reader's language. ``getattr`` because the placeholders
    # catalog builds a context without a database read behind it.
    return_of_number = getattr(document, 'return_of_number', None)

    # 5. Resolve the document variant (drives parties/signatures partials).
    doc_type = document.type
    is_correction = doc_type == 'CORRECTION'
    is_external_in = doc_type in ('IN', 'PZ')
    is_external_out = doc_type in ('OUT', 'WZ')
    is_internal_in = doc_type == 'INTERNAL_IN'
    is_internal_out = doc_type == 'INTERNAL_OUT'
    is_transfer = doc_type in ('INT', 'MM')
    # A write-off prints why it was made, in the reader's words, and what
    # the cost layers it drew were worth — the two things the document page
    # shows and the binder copy used to leave out.
    scrap_reason = (
        _get_scrap_reason_map(lang).get(document.reason_code, document.reason_code)
        if is_scrap(doc_type) and document.reason_code
        else None
    )
    is_external = is_external_in or is_external_out
    is_internal = is_internal_in or is_internal_out or is_transfer
    show_line_status = not is_correction
    show_payment = is_external

    if is_correction:
        doc_variant = 'correction'
    elif is_external_in:
        doc_variant = 'external_in'
    elif is_external_out:
        doc_variant = 'external_out'
    elif is_transfer:
        doc_variant = 'transfer'
    elif is_internal_in:
        doc_variant = 'internal_in'
    elif is_internal_out:
        doc_variant = 'internal_out'
    else:
        doc_variant = 'external_in'

    # 6. The shared header: every print family reads these names, so
    #    the identity, the number, the status, the dates and the codes look
    #    the same wherever they are printed.
    doc_status_map = core_api.pdf.get_doc_status_map(lang)

    return {
        'document': document,
        'profile': profile,
        'partner': partner_ctx,
        'issuer': issuer or IssuerContext(),
        'print_title': doc_title,
        # The subtitle is the default name of the document type. It
        # earns its line only when a profile has renamed the type — next to
        # an unrenamed title it says the same thing twice.
        'print_subtitle': doc_subtitle if doc_subtitle != doc_title else None,
        'print_number': document.number,
        'print_status': doc_status_map.get(document.status, document.status),
        'print_dates': print_date_rows(
            [
                _own_date_row(document, labels),
                (labels['confirmed'], getattr(document, 'confirmed_at', None)),
                (labels['completed'], getattr(document, 'completed_at', None)),
            ],
            lang,
            country,
        ),
        'source_location': source_location,
        'target_location': target_location,
        'show_value_columns': show_value_columns,
        'show_tax_column': show_tax_column,
        'total_expected': total_expected,
        'total_done': total_done,
        'totals_by_unit': totals_by_unit,
        # Goods at a reduced rate and goods at the standard one on one
        # document: the amounts per rate, not only the total.
        'tax_by_rate': amounts_by_rate(
            (line.tax_rate, line.line_value, line.line_tax) for line in document.lines
        )
        if show_tax_column
        else [],
        'labels': labels,
        'doc_title': doc_title,
        'doc_subtitle': doc_subtitle,
        'line_status_map': _get_line_status_map(lang),
        'discrepancy_map': _get_discrepancy_map(lang),
        'doc_status_map': doc_status_map,
        'lang': lang,
        **core_api.pdf.printed_codes(document.number),
        'corrected_doc_number': corrected_doc_number,
        'backorder_of_number': backorder_of_number,
        'return_of_number': return_of_number,
        'doc_type': doc_type,
        'is_correction': is_correction,
        'is_external_in': is_external_in,
        'is_external_out': is_external_out,
        'is_internal_in': is_internal_in,
        'is_internal_out': is_internal_out,
        'is_transfer': is_transfer,
        'is_scrap': is_scrap(doc_type),
        'scrap_reason': scrap_reason,
        'is_external': is_external,
        'is_internal': is_internal,
        'show_line_status': show_line_status,
        'show_payment': show_payment,
        'doc_variant': doc_variant,
        # What the packing slip prints (see ``print_packages``); empty on
        # every other printout.
        'packages': packages or [],
    }


def render_document_html(
    document: Document,
    profile: DocumentProfile | None,
    lang: str = 'en',
    issuer: IssuerContext | None = None,
    user_template_html: str | None = None,
    page_size: str = 'a4',
    country: str | None = None,
) -> str:
    """Render ``document`` to the HTML a PDF is made from.

    Args:
        document: The fully-loaded ``Document`` ORM instance (lines eagerly loaded).
        profile:  The organisation's ``DocumentProfile`` (may be ``None``).
        lang:     ISO language code used for labels and defaults. Defaults to ``"en"``.
        issuer:   Prebuilt issuer context (see ``build_issuer_context``). May be
                  ``None`` — the block then renders empty.
        user_template_html:
                  The organization's own template body (a seeded copy of a
                  built-in, or one written from scratch). When set, it
                  replaces the filesystem family entirely and prints in the
                  language it declares, else in ``lang``.
        page_size:
                  The paper the printout goes on, as ``print_page_size``
                  stores it ('a4' or 'letter'). Applied to the rendered
                  HTML, so a saved body from before the column existed
                  follows the organization too.
        country:  The organization's ISO country, which an ``auto`` layout
                  follows (see ``built_in_layout``).

    Returns:
        The printable HTML — one document's page body.
    """
    # 1. Determine which template to use, and the language it prints in —
    #    a layout that declares its language overrides the UI language.
    if user_template_html:
        template_name = '__user__'
        lang = print_lang(user_template_html, lang)
    else:
        template_name, lang = _resolve_template_and_lang(profile, lang, country)

    # 2-6. Build the Jinja2 context.
    context = build_pdf_context(document, profile, lang, issuer, country=country)

    # 7. Render HTML.
    if user_template_html:
        # The organization's own template: sandboxed engine via the public
        # PDF API (the same path purchase_orders uses), includes resolved
        # from the module's templates directory, output sanitized by the
        # engine itself.
        html_content = core_api.pdf.render_html(
            user_template_html, context, templates_dir=_TEMPLATES_DIR
        )
    else:
        html_content = _svc.render_filesystem_template(f'{template_name}.html', context)

    # 8. The paper the organization prints on — stated after the body, so
    #    whatever a template said about page size loses to it.
    html_content = apply_page_size(html_content, page_size)
    logger.debug(
        'Rendered HTML for document %s using template %r', document.id, template_name
    )
    return html_content


def generate_pdf(
    document: Document,
    profile: DocumentProfile | None,
    lang: str = 'en',
    issuer: IssuerContext | None = None,
    user_template_html: str | None = None,
    page_size: str = 'a4',
    country: str | None = None,
) -> bytes:
    """Render ``document`` to a PDF binary (arguments as ``render_document_html``).

    Returns:
        Raw PDF bytes ready to stream to the HTTP response.
    """
    return _svc.render_to_pdf(
        render_document_html(
            document, profile, lang, issuer, user_template_html, page_size, country
        )
    )


def print_packages(
    document: Document, packages: Sequence[Any], total: int
) -> list[dict[str, Any]]:
    """The packages as the packing slip prints them, each with its barcode.

    The barcode carries the package code — the same code the package label
    prints — so the slip in the box and the label on it can be matched.
    *total* is how many packages the whole dispatch has: a slip printed for
    one package still says "2 of 3".
    """
    from .packing_service import package_code

    by_id = {line.id: line for line in document.lines}
    printed = []
    for package in packages:
        code = package_code(document.number, package.number)
        codes = core_api.pdf.printed_codes(code)
        lines = sorted(
            ((by_id[ln.document_line_id], ln.quantity) for ln in package.lines),
            key=lambda pair: pair[0].line_number,
        )
        printed.append(
            {
                'number': package.number,
                'count': total,
                'code': code,
                'weight_kg': package.weight_kg,
                'code128_img': codes['code128_img'],
                'code128_width_mm': codes['code128_width_mm'],
                'code128_height_mm': codes['code128_height_mm'],
                'lines': [
                    {
                        'line_number': line.line_number,
                        'name': line.name,
                        'sku': (line.product_snapshot or {}).get('sku'),
                        'barcode': line.barcode,
                        'batch_number': line.batch_number,
                        'quantity': quantity,
                        'unit': line.uom.symbol if line.uom else None,
                    }
                    for line, quantity in lines
                ],
            }
        )
    return printed


async def generate_packing_slip_pdf_async(
    document: Document,
    profile: DocumentProfile | None,
    packages: list[dict[str, Any]],
    *,
    template_html: str,
    lang: str = 'en',
    organization: Any = None,
) -> bytes:
    """Render the packing slip — one sheet per package in *packages*.

    The slip is a template like any other printout: the organization's own
    ``PACKING_SLIP`` default, else the built-in ``packing_slip.html``, chosen
    by the caller (``pick_packing_slip_html``) and rendered in the sandbox.
    """
    effective_lang = print_lang(template_html, lang)
    issuer = await build_issuer_context(organization, effective_lang)
    page_size = page_size_of(organization)

    def render() -> bytes:
        context = build_pdf_context(
            document,
            profile,
            effective_lang,
            issuer,
            packages=packages,
            country=getattr(organization, 'country', None),
        )
        html = core_api.pdf.render_html(
            template_html, context, templates_dir=_TEMPLATES_DIR
        )
        return _svc.render_to_pdf(apply_page_size(html, page_size))

    return await run_sync_in_thread(render)


def build_pick_list_context(
    documents: Sequence[Document],
    pick_lines: list[dict[str, Any]],
    lang: str,
    issuer: IssuerContext | None,
) -> dict[str, Any]:
    """The render context of a pick list over one or several dispatches.

    Each document is shown with the Code128 of its number — the code the
    scanner reads off the sheet to find the dispatch — and the lines come
    already in walk order (see ``pick_list_service``). The shared header
    carries no code of its own: a list over several dispatches has no single
    number to encode.
    """
    labels = _get_labels(lang)
    return {
        'issuer': issuer or IssuerContext(),
        'print_title': labels['pick_list'],
        'print_subtitle': None,
        'print_number': ', '.join(doc.number for doc in documents),
        'print_status': None,
        'print_dates': [],
        'code128_img': None,
        'labels': labels,
        'lang': lang,
        'documents': [
            {
                'number': doc.number,
                **{
                    key: value
                    for key, value in core_api.pdf.printed_codes(doc.number).items()
                    if key.startswith('code128')
                },
            }
            for doc in documents
        ],
        'pick_lines': pick_lines,
    }


async def generate_pick_list_pdf_async(
    documents: Sequence[Document],
    pick_lines: list[dict[str, Any]],
    *,
    template_html: str,
    lang: str = 'en',
    organization: Any = None,
) -> bytes:
    """Render the pick list through *template_html* (see ``pick_pick_list_html``)."""
    effective_lang = print_lang(template_html, lang)
    issuer = await build_issuer_context(organization, effective_lang)
    page_size = page_size_of(organization)

    def render() -> bytes:
        html = core_api.pdf.render_html(
            template_html,
            build_pick_list_context(documents, pick_lines, effective_lang, issuer),
            templates_dir=_TEMPLATES_DIR,
        )
        return _svc.render_to_pdf(apply_page_size(html, page_size))

    return await run_sync_in_thread(render)


async def generate_pdf_async(
    document: Document,
    profile: DocumentProfile | None,
    lang: str = 'en',
    organization: Any = None,
    user_template_html: str | None = None,
) -> bytes:
    """Async wrapper: offloads WeasyPrint PDF rendering to a thread pool.

       ``organization`` (ORM or DTO) supplies the issuer identity — its name,
    tax ID, address and logo are printed on the document. The logo
       is embedded server-side as a data URI. ``user_template_html`` replaces
       the filesystem template family with the organization's own template.
       The issuer is built in the language the layout prints in.
    """
    country = getattr(organization, 'country', None)
    if user_template_html:
        effective_lang = print_lang(user_template_html, lang)
    else:
        _, effective_lang = _resolve_template_and_lang(profile, lang, country)
    issuer = await build_issuer_context(organization, effective_lang)
    page_size = page_size_of(organization)
    return await run_sync_in_thread(
        lambda: generate_pdf(
            document,
            profile,
            lang,
            issuer,
            user_template_html=user_template_html,
            page_size=page_size,
            country=country,
        )
    )


async def generate_merged_pdf_async(
    parts: Sequence[tuple[Document, str | None]],
    profile: DocumentProfile | None,
    lang: str = 'en',
    organization: Any = None,
) -> bytes:
    """One PDF holding every document in ``parts``, in the order given.

    Each part is a document and the template body that prints its type (see
    ``pick_print_template_html``) — documents of different types keep their
    own layout and language. Every one starts on a fresh page, since each is
    rendered on its own and only the finished pages are joined.
    """
    page_size = page_size_of(organization)
    country = getattr(organization, 'country', None)
    htmls: list[str] = []
    for document, user_template_html in parts:
        if user_template_html:
            effective_lang = print_lang(user_template_html, lang)
        else:
            _, effective_lang = _resolve_template_and_lang(profile, lang, country)
        issuer = await build_issuer_context(organization, effective_lang)
        htmls.append(
            await run_sync_in_thread(
                partial(
                    render_document_html,
                    document,
                    profile,
                    lang,
                    issuer,
                    user_template_html,
                    page_size,
                    country,
                )
            )
        )
    return await run_sync_in_thread(lambda: _svc.render_merged_pdf(htmls))
