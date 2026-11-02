"""Base class for PDF generation services.

Consolidates shared boilerplate: Jinja2 environment setup, label dictionaries
with i18n-lite resolution, DB template lookup, filesystem template rendering,
and PDF conversion.  Subclasses compose these building blocks in their own
``generate_*()`` function.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

from jinja2 import ChoiceLoader, Environment, FileSystemLoader, select_autoescape
from sqlalchemy.ext.asyncio import AsyncSession
from weasyprint import HTML

from app.core.logging import get_logger
from app.core.pdf_url_fetcher import data_only_fetcher
from app.core.print_identity import PRINT_TEMPLATES_DIR
from app.core.utils import pick_by_lang
from app.services.pdf_utils import register_pdf_filters
from app.services.template_engine import TemplateEngine

logger = get_logger(__name__)


def print_template_loader(templates_dir: Path | None) -> ChoiceLoader:
    """Templates of one print family, then the partials every family shares.

    The family's own directory is searched first, so a family can override a
    shared partial; what it cannot do is quietly grow a fourth copy of the
    header.
    """
    loaders = []
    if templates_dir is not None:
        loaders.append(FileSystemLoader(str(templates_dir)))
    loaders.append(FileSystemLoader(str(PRINT_TEMPLATES_DIR)))
    return ChoiceLoader(loaders)


class PdfServiceBase:
    """Subclass and set class attributes, then compose ``generate_*()``."""

    templates_dir: Path
    labels_en: dict[str, str]
    labels_pl: dict[str, str] = {}
    labels_de: dict[str, str] = {}
    labels_fr: dict[str, str] = {}
    labels_es: dict[str, str] = {}
    module_name: str

    def __init__(self) -> None:
        self._jinja_env = self._create_jinja_env()

    def _create_jinja_env(self) -> Environment:
        env = Environment(
            loader=print_template_loader(self.templates_dir),
            autoescape=select_autoescape(['html']),
        )
        register_pdf_filters(env)
        return env

    def get_labels(self, lang: str) -> dict[str, str]:
        """Resolve labels for *lang* (i18n-lite), falling back to English."""
        return dict(
            pick_by_lang(
                lang,
                self.labels_en,
                pl=self.labels_pl,
                de=self.labels_de,
                fr=self.labels_fr,
                es=self.labels_es,
            )
        )

    async def try_db_template(
        self,
        db: AsyncSession,
        org_id: UUID,
        context: dict[str, Any],
        *,
        template_id: UUID | None = None,
        document_type: str | None = None,
    ) -> str | None:
        """Render an organization's own template, or None to fall back to disk.

               Async because its only caller already had an AsyncSession and reached
               this sync code through ``db.run_sync``, which parks a greenlet for the
               duration — connection budget spent to call a sync twin of a query that
        already existed in async form.
        """
        from app.services import template_crud

        tpl = None
        if template_id:
            tpl = await template_crud.get_template_async(
                db, org_id, template_id, module=self.module_name
            )
        elif document_type:
            tpl = await template_crud.get_default_template_async(
                db, org_id, module=self.module_name, document_type=document_type
            )
        if tpl is None:
            return None

        engine = TemplateEngine(templates_dir=self.templates_dir)
        logger.debug('Using DB template %s for %s', tpl.id, self.module_name)
        return engine.render(tpl.body_html, context)

    def render_filesystem_template(
        self, template_name: str, context: dict[str, Any]
    ) -> str:
        template = self._jinja_env.get_template(template_name)
        return template.render(**context)

    @staticmethod
    def render_to_pdf(html_content: str) -> bytes:
        pdf: bytes = HTML(
            string=html_content, url_fetcher=data_only_fetcher()
        ).write_pdf()
        return pdf

    @staticmethod
    def render_merged_pdf(html_contents: list[str]) -> bytes:
        """Render each HTML on its own, then join the pages into one PDF."""
        rendered = [
            HTML(string=html, url_fetcher=data_only_fetcher()).render()
            for html in html_contents
        ]
        pages = [page for doc in rendered for page in doc.pages]
        merged: bytes = rendered[0].copy(pages).write_pdf()
        return merged
