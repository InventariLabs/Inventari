"""Who a printout is issued by, and the header every family shares.

The identity block used to live in the warehouse module, so purchase orders
printed a bare organization name where warehouse documents printed a
letterhead — the same fact, told twice, differently. It is neutral by nature:
an organization has a name, a tax id, an address and a logo whatever it keeps
in stock, so it belongs here rather than in whichever module needed it
first.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from app.core.datetimes import format_date_for
from app.core.logging import get_logger

logger = get_logger(__name__)

# The partials shared by every print family. A module's own templates
# directory is searched first, so a family can still override one.
PRINT_TEMPLATES_DIR = Path(__file__).parent / 'print_templates'

_LOGO_EXT_TO_MIME = {
    'jpg': 'image/jpeg',
    'jpeg': 'image/jpeg',
    'png': 'image/png',
    'gif': 'image/gif',
    'webp': 'image/webp',
}


@dataclass
class IssuerContext:
    """Issuer identity passed to the template.

    Built from the ``Organization`` — the same identity labels, order PDFs,
    equipment protocols and e-mails need — never from a per-module profile,
    which would force every print family to keep its own copy of the company
    address. Missing data renders an empty block, not a crash.
    """

    name: str | None = None
    tax_id: str | None = None
    address: str | None = None
    logo: str | None = None  # data URI, read server-side from org storage

    @classmethod
    def from_organization(cls, organization: Any, lang: str = 'en') -> IssuerContext:
        if organization is None:
            return cls()
        return cls.from_snapshot(issuer_snapshot(organization), lang)

    @classmethod
    def from_snapshot(
        cls, snapshot: dict[str, Any] | None, lang: str = 'en'
    ) -> IssuerContext:
        """The block as ``issuer_snapshot`` froze it, worded in ``lang``.

        The logo is not part of the snapshot: an image changed later is
        presentation, not a statement of the transaction, so it stays the
        one the organization has now.
        """
        from app.services.pdf_utils import format_partner_address

        if not snapshot:
            return cls()
        return cls(
            name=snapshot.get('name'),
            tax_id=snapshot.get('tax_id'),
            address=format_partner_address(snapshot.get('address') or None, lang),
        )


def issuer_snapshot(organization: Any) -> dict[str, Any]:
    """The organization's own identity as a document states it on the day.

    Stored raw (the address as its parts, the country as its ISO code) so the
    block can still be worded in whichever language the document is printed
    in later. The country lives in the organization's ISO column, not inside
    the address JSONB — it is folded in so the printed address ends with the
    localised country name.
    """
    address = dict(getattr(organization, 'address', None) or {})
    country = getattr(organization, 'country', None)
    if country:
        address['country'] = country
    return {
        'name': getattr(organization, 'name', None),
        'tax_id': getattr(organization, 'tax_id', None),
        'address': address or None,
    }


async def build_issuer_context(organization: Any, lang: str = 'en') -> IssuerContext:
    """Issuer context with the logo embedded as a data URI.

    WeasyPrint renders with a data-only URL fetcher, so an external or
    proxied logo URL would never load — the bytes are read server-side and
    embedded. A missing or unreadable logo degrades to None, never to a
    failed PDF.
    """
    from app.core.file_storage.service import FileStorageService

    ctx = IssuerContext.from_organization(organization, lang)
    logo_path = getattr(organization, 'logo_url', None) if organization else None
    if logo_path:
        try:
            # The column carries the absolute storage path, so the bytes are
            # read through the storage service directly — the facade is the
            # module-facing surface that adds the org prefix, and there is
            # nothing left to prefix here.
            content = (await FileStorageService().get(logo_path)).read()
            ext = logo_path.rsplit('.', 1)[-1].lower() if '.' in logo_path else ''
            mime = _LOGO_EXT_TO_MIME.get(ext, 'image/png')
            ctx.logo = f'data:{mime};base64,' + base64.b64encode(content).decode(
                'ascii'
            )
        except Exception as exc:  # noqa: BLE001 — a broken logo must not kill the PDF
            logger.warning('Could not read organization logo %s: %s', logo_path, exc)
    return ctx


def _printed_date(
    lang: str, value: datetime | date | str, country: str | None = None
) -> str:
    """A stamp as the document's own language writes it.

    The header used to print ``%d.%m.%Y`` whatever the document's language
    was: an English screen showed ``26.09.2026`` beside interface dates it
    spelled ``Sep 26, 2026`` — one day in two spellings. The stamp is part of
    the document a person reads, so it follows the language that document is
    printed in (``format_date_for``). A bare string is passed through: it is
    already the writer's text and there is no date here to re-spell.
    """
    if isinstance(value, str):
        return value[:10]
    return format_date_for(lang, value, country=country)


def print_date_rows(
    entries: list[tuple[str, datetime | date | str | None]],
    lang: str = 'en',
    country: str | None = None,
) -> list[dict[str, str]]:
    """Date rows worth printing, in order.

    A document confirmed and completed on the day it was issued printed the
    same date three times, one under the other, in the smallest type on the
    page — noise exactly where the header should carry information. A stamp
    survives only when it says something the one above it did not.
    """
    rows: list[dict[str, str]] = []
    for label, value in entries:
        if value is None or value == '':
            continue
        formatted = _printed_date(lang, value, country)
        if rows and rows[-1]['value'] == formatted:
            continue
        rows.append({'label': label, 'value': formatted})
    return rows
