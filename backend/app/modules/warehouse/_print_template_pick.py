"""Which HTML a printout renders: the type's own template, else the profile's.

The template's ``document_type`` column used to be decorative at print
time: the PDF endpoint read the profile's single ``default_template_id``
and printed every document through it — a receipt wearing a scrap layout,
because that happened to be the template the profile named. The data
model already kept one default per (organization, module, document_type);
this is the reading that honours it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.public_api import core_api


async def pick_print_template_html(
    db: AsyncSession,
    org_id: UUID,
    profile: Any,
    document_type: str,
) -> str | None:
    """The user template HTML this document prints through, or ``None``.

    The organization's default template for the document's own type wins —
    a per-type promise is more specific than the profile's
    one-layout-for-everything choice, which stays the fallback for types
    without their own template (and covers the layout families copied from
    the built-ins, which name no document type at all). ``None`` lets the
    built-in family render, exactly as before either of the two exists.
    """
    typed = await core_api.templates.get_default_async(
        db, org_id, 'warehouse', document_type
    )
    if typed:
        return typed.body_html
    if profile.default_template_id:
        tpl = await core_api.templates.get_async(
            db, org_id, profile.default_template_id, module='warehouse'
        )
        if tpl:
            return tpl.body_html
    return None


#: The template type a packing slip prints through.
PACKING_SLIP = 'PACKING_SLIP'

#: The template type a pick list prints through.
PICK_LIST = 'PICK_LIST'

_TEMPLATES_DIR = Path(__file__).parent / 'templates'


async def _pick_own_type_html(
    db: AsyncSession, org_id: UUID, template_type: str, built_in: str
) -> str:
    """The organization's default template of *template_type*, else the built-in file.

    No profile fallback here: the profile's layout lays out a document, and a
    packing slip or a pick list printed through it would be the dispatch note
    again.
    """
    typed = await core_api.templates.get_default_async(
        db, org_id, 'warehouse', template_type
    )
    if typed:
        return typed.body_html
    return (_TEMPLATES_DIR / built_in).read_text(encoding='utf-8')


async def pick_packing_slip_html(db: AsyncSession, org_id: UUID) -> str:
    """The organization's default packing slip, else the built-in one."""
    return await _pick_own_type_html(db, org_id, PACKING_SLIP, 'packing_slip.html')


async def pick_pick_list_html(db: AsyncSession, org_id: UUID) -> str:
    """The organization's default pick list, else the built-in one."""
    return await _pick_own_type_html(db, org_id, PICK_LIST, 'pick_list.html')
