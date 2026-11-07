import uuid
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.datetimes import format_date_for, format_datetime_for
from app.core.db_utils import get_org_owned_or_404_async
from app.core.logging import get_logger
from app.core.print_page_size import resolve_page_size_async
from app.core.public_api import core_api
from app.core.template_schemas import PlaceholderInfo
from app.i18n import Language

from ._protocol_templates import (
    AVAILABLE_PLACEHOLDERS,
)
from ._protocol_templates import (
    DEFAULT_CHECKIN_TEMPLATE as _DEFAULT_CHECKIN_TEMPLATE,
)
from ._protocol_templates import (
    DEFAULT_CHECKOUT_TEMPLATE as _DEFAULT_CHECKOUT_TEMPLATE,
)
from ._protocol_templates import (
    LABELS as _LABELS,
)
from ._serial import serial_of
from .models import EquipmentAssignment

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Context builder
# ---------------------------------------------------------------------------


async def _build_context_async(
    db: AsyncSession,
    assignment: EquipmentAssignment,
    lang: str = 'en',
) -> dict[str, Any]:
    item = await core_api.items.get_any_async(
        db, assignment.organization_id, assignment.item_id
    )
    org_name = await core_api.organizations.get_name_async(
        db, assignment.organization_id
    )
    organization = await core_api.organizations.get_async(
        db, assignment.organization_id
    )
    country = organization.country if organization else None
    issuer = (
        await core_api.users.get_async(
            db, assignment.organization_id, assignment.checked_out_by
        )
        if assignment.checked_out_by
        else None
    )

    meta: dict[str, Any] = {}
    if item and item.meta_data and isinstance(item.meta_data, dict):
        meta = item.meta_data.get('equipment', {})
        if not isinstance(meta, dict):
            meta = {}

    doc_number = f'EQ-{assignment.created_at.strftime("%Y%m%d")}-{str(assignment.id)[:8].upper()}'

    # A protocol is a document a worker signs, so its dates are written the
    # way that worker's language writes them (AGENTS.md §4 is about domains,
    # not readers; see app/core/datetimes.py for the decision). The reference
    # number above stays canonical: it is an identifier, not a date to read.
    manufacturer = str(meta.get('manufacturer', ''))
    model = str(meta.get('model', ''))
    # "— Latitude 5540" reads like a mangled value, not like a manufacturer
    # nobody wrote down: the pair is joined first and the missing marker only
    # stands for what the pair has none of.
    manufacturer_model = ' '.join(part for part in (manufacturer, model) if part)

    # The return day is pinned to the end of its day on the organization's
    # clock. Printing the stored instant as a UTC wall clock moved it a day
    # forward for every organization west of UTC, while the screen showed
    # the day the form picked (review 2026-09-23). The document a person
    # signs prints the day the screen showed them.
    return_day = assignment.expected_return_at
    if return_day is not None:
        if return_day.tzinfo is None:
            return_day = return_day.replace(tzinfo=UTC)
        return_day = return_day.astimezone(
            await core_api.organizations.timezone_async(db, assignment.organization_id)
        )

    return {
        'item_name': item.name if item else '—',
        'item_barcode': item.barcode or '—' if item else '—',
        'category_name': item.category.name if item and item.category else '—',
        'serial_number': (serial_of(item) if item else None) or '—',
        'asset_tag': str(meta.get('asset_tag', '')) or '—',
        'manufacturer': manufacturer or '—',
        'model': model or '—',
        'manufacturer_model': manufacturer_model or '—',
        # Where a placement put the asset; empty for a person checkout,
        # and the template's one condition for the signature count.
        'checkout_location_name': (
            assignment.checkout_location.name if assignment.checkout_location else ''
        ),
        # The category's custom fields, by key, as a plain dict — never the
        # ORM object: the sandboxed template reaches data a category
        # defined, and attribute-shaped reaches at anything else are
        # refused by the engine, not by this list's goodwill.
        'custom': dict(meta),
        'assigned_to_name': assignment.assigned_to_name,
        'assigned_to_email': assignment.assigned_to_email or '',
        'checked_out_at': format_datetime_for(
            lang, assignment.checked_out_at, country=country
        ),
        'checked_in_at': format_datetime_for(
            lang, assignment.checked_in_at, country=country
        ),
        'expected_return_at': format_date_for(lang, return_day, country=country),
        'checkout_notes': assignment.checkout_notes or '',
        'checkin_notes': assignment.checkin_notes or '',
        'checkin_condition': assignment.checkin_condition or '',
        'issued_by_name': issuer.full_name or issuer.email if issuer else '—',
        'issued_by_email': issuer.email if issuer else '',
        'organization_name': org_name or '—',
        'document_date': format_date_for(lang, datetime.now(), country=country),
        'document_number': doc_number,
    }


# ---------------------------------------------------------------------------
# Placeholder catalogue
# ---------------------------------------------------------------------------


async def protocol_placeholders_async(
    db: AsyncSession, org_id: uuid.UUID
) -> list[PlaceholderInfo]:
    """The static catalogue plus the custom fields this org can actually use.

    A category's own fields — an hour counter, an inspection day — reach
    the document through the ``{{custom.<key>}}`` accessor, so the editor
    hint has to name the keys this organization's categories define.
    System fields are skipped: each already has its named placeholder, and
    a second spelling of it is a copy someone will edit out of sync.
    """
    categories = await core_api.categories.list_async(db, org_id)

    # key -> (label, category names carrying it); the first label a key
    # meets wins, so a shared field is described once, not twice.
    fields: dict[str, tuple[str, list[str]]] = {}
    for category in categories:
        if category.context_tag != 'equipment':
            continue
        for definition in category.field_definitions or []:
            if not isinstance(definition, dict) or definition.get('is_system'):
                continue
            key = definition.get('key')
            if not key:
                continue
            label, sources = fields.setdefault(
                key, (str(definition.get('label') or key), [])
            )
            sources.append(category.name)

    entries = [
        PlaceholderInfo(
            key=f'{{{{custom.{key}}}}}',
            description=f'{label} — custom field of {", ".join(sources)}',
            custom_field_label=label,
            custom_field_categories=sources,
        )
        for key, (label, sources) in fields.items()
    ]
    return [
        *(
            PlaceholderInfo(key=p['key'], description=p['description'])
            for p in AVAILABLE_PLACEHOLDERS
        ),
        *entries,
    ]


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


async def render_protocol_html(
    db: AsyncSession,
    org_id: uuid.UUID,
    assignment_id: uuid.UUID,
    template_id: uuid.UUID | None = None,
    lang: str = 'en',
) -> str:
    assignment = await get_org_owned_or_404_async(
        db,
        EquipmentAssignment,
        assignment_id,
        org_id,
        resource='assignment',
        lang=cast(Language, lang),
    )

    template_html: str | None = None
    if template_id:
        tpl = await core_api.templates.get_async(
            db, org_id, template_id, module='equipment'
        )
        if tpl:
            template_html = tpl.body_html

    if not template_html:
        doc_type = 'CHECKIN' if assignment.checked_in_at else 'CHECKOUT'
        default_tpl = await core_api.templates.get_default_async(
            db, org_id, module='equipment', document_type=doc_type
        )
        if default_tpl:
            template_html = default_tpl.body_html

    if not template_html:
        if assignment.checked_in_at:
            template_html = _DEFAULT_CHECKIN_TEMPLATE
        else:
            template_html = _DEFAULT_CHECKOUT_TEMPLATE

    context = await _build_context_async(db, assignment, lang)
    context['L'] = _LABELS.get(lang, _LABELS['en'])
    # The rendered document, not the author's source, is what a browser
    # executes: the shared engine cleans the output with nh3 on the way
    # out — the same treatment every documents/PO template gets. A
    # sandboxed render alone stops template injection, not markup the
    # template's author wrote on purpose.
    return core_api.pdf.render_html(template_html, context)


async def render_protocol_pdf_async(
    db: AsyncSession,
    org_id: uuid.UUID,
    assignment_id: uuid.UUID,
    template_id: uuid.UUID | None = None,
    lang: str = 'en',
) -> bytes:
    from app.core.async_utils import run_sync_in_thread

    html = await render_protocol_html(db, org_id, assignment_id, template_id, lang=lang)
    # The paper the organization prints on — stated after the body, so
    # whatever a saved template said about page size loses to it.
    page_size = await resolve_page_size_async(db, org_id)
    return await run_sync_in_thread(lambda: _render_pdf_sync(html, page_size))


def _render_pdf_sync(html: str, page_size: str) -> bytes:
    from app.core.print_page_size import apply_page_size

    return core_api.pdf.render_pdf(apply_page_size(html, page_size))
