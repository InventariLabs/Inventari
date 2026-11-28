"""Module-safe PDF/template rendering helpers.

Replaces direct ``app.services.pdf_utils`` / ``app.services.template_engine``
imports in module code, which the architecture lint refuses.
All methods are synchronous, stateless utilities — no DB access.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.public_api._access import reads
from app.core.utils import pick_by_lang

if TYPE_CHECKING:
    from app.core.print_identity import IssuerContext


class CorePdfAPI:
    """Public Core API for PDF generation and template rendering."""

    @reads
    def sanitize_html(self, body_html: str) -> str:
        """Strip dangerous tags/attributes from user-authored HTML (nh3)."""
        from app.services.template_engine import sanitize_html

        return sanitize_html(body_html)

    @reads
    def render_html(
        self,
        template_html: str | None,
        context: dict[str, Any],
        *,
        templates_dir: Path | None = None,
    ) -> str:
        """Render a template string with the sandboxed Jinja2 engine.

        When ``templates_dir`` is given, ``{% include %}`` directives resolve
        from the filesystem; otherwise the template must be flat HTML.
        """
        from app.services.template_engine import TemplateEngine

        return TemplateEngine(templates_dir=templates_dir).render(
            template_html, context
        )

    @reads
    def render_pdf(self, html: str) -> bytes:
        """Convert rendered HTML to PDF bytes (WeasyPrint)."""
        from app.core.pdf_base_service import PdfServiceBase

        return PdfServiceBase.render_to_pdf(html)

    @reads
    async def render_document_pdf_async(
        self, db: AsyncSession, organization_id: UUID, html: str
    ) -> bytes:
        """Render a document on the organization's paper, off the event loop.

        WeasyPrint is CPU-bound, so a module printing a PDF must not call it
        inline. The page size is the organization's own statement, applied
        after the body so a saved layout cannot decide the paper.
        """
        from app.core.async_utils import run_sync_in_thread
        from app.core.pdf_base_service import PdfServiceBase
        from app.core.print_page_size import apply_page_size, resolve_page_size_async

        page_size = await resolve_page_size_async(db, organization_id)
        sized = apply_page_size(html, page_size)
        return await run_sync_in_thread(lambda: PdfServiceBase.render_to_pdf(sized))

    @reads
    async def issuer_async(
        self, db: AsyncSession, organization_id: UUID, lang: str = 'en'
    ) -> IssuerContext:
        """The organization's identity block for a printed document."""
        from app.core.print_identity import build_issuer_context
        from app.core.public_api import core_api

        organization = await core_api.organizations.get_async(db, organization_id)
        return await build_issuer_context(organization, lang)

    @reads
    def generate_code128_base64(self, value: str) -> str:
        """Code128 barcode as a data-URI image at the standard print geometry."""
        from app.services.pdf_utils import generate_code128_base64

        return generate_code128_base64(value)

    @reads
    def generate_qr_base64(self, value: str) -> str:
        """QR code as a data-URI PNG at the standard print geometry."""
        from app.services.pdf_utils import generate_qr_base64

        return generate_qr_base64(value)

    @reads
    def printed_codes(self, number: str) -> dict[str, Any]:
        """The code images a printout carries, and the size to print them at.

        One helper for every print family: the geometry that decides
        whether a scanner can read the paper is not something a template gets
        to re-decide, and three copies of it had already drifted apart. The
        Code128 carries the bare number — that is what a 1D laser gun in a
        warehouse can read — while the QR carries the installation address of
        the record, so a phone camera opens it instead of showing a string.
        Without a usable installation address the QR falls back to
        the number.
        """
        from app.core.scan_links import printable_scan_url
        from app.services.pdf_utils import generate_code128, generate_qr

        code128 = generate_code128(number)
        qr = generate_qr(printable_scan_url(number) or number)
        return {
            'code128_img': code128.data_uri,
            'code128_width_mm': code128.width_mm,
            'code128_height_mm': code128.height_mm,
            'qr_img': qr.data_uri,
            'qr_size_mm': qr.width_mm,
        }

    @reads
    def format_partner_address(
        self, address: dict[str, Any] | None, lang: str = 'en'
    ) -> str | None:
        """Format a partner address dict as a single-line string.

        ``country`` is localised via:func:`country_name`; codes
               outside the curated list print as-is.
        """
        from app.services.pdf_utils import format_partner_address

        return format_partner_address(address, lang)

    @reads
    def get_doc_status_map(self, lang: str) -> dict[str, str]:
        """Document status code -> localized label map."""
        from app.services.pdf_utils import get_doc_status_map

        return get_doc_status_map(lang)

    @reads
    def common_labels(self, lang: str) -> dict[str, str]:
        """Shared PDF labels (i18n-lite): every shipped language, English fallback."""
        from app.services import pdf_utils

        return dict(
            pick_by_lang(
                lang,
                pdf_utils.COMMON_PDF_LABELS_EN,
                pl=pdf_utils.COMMON_PDF_LABELS_PL,
                de=pdf_utils.COMMON_PDF_LABELS_DE,
                fr=pdf_utils.COMMON_PDF_LABELS_FR,
                es=pdf_utils.COMMON_PDF_LABELS_ES,
                pt=pdf_utils.COMMON_PDF_LABELS_PT,
            )
        )

    @reads
    def register_pdf_filters(self, env: Any) -> None:
        """Register standard Jinja2 filters (format_date, format_qty, etc.)."""
        from app.services.pdf_utils import register_pdf_filters

        register_pdf_filters(env)
