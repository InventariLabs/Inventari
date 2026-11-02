"""The paper a printout goes on.

Paper size is a property of the printer standing in the office, not of the
document type: a warehouse receipt, an order and an equipment protocol all
leave through the same tray. So the organization answers, not a document
profile — the country says which paper a country's offices usually hold
(the US, Canada and Mexico print Letter; everyone else A4), and an
organization whose printer disagrees with its country says so explicitly
in ``print_page_size``.

The decision is applied to the rendered HTML, after the body exists and
before WeasyPrint sees it. A ``@page`` rule that comes last wins the
cascade, so a layout saved in the database back when templates baked
``size: A4`` into their body follows the organization too, without anyone
having to edit saved templates by hand.

Reading the decision has two doors. The async one selects exactly the two
columns it needs — ``print_page_size`` is deferred on the model, and
touching it on an instance the caller did not load it on fires a lazy load
no async caller survives. The sync one is for objects already carrying the
answer: the ``OrganizationDTO`` the organization API refreshes its
deferred columns into, or an ORM instance the caller refreshed by hand.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

#: What an organization may say explicitly. Stored lowercase on the
#: ``print_page_size`` column; NULL is "no opinion — the country answers".
PAGE_SIZES: frozenset[str] = frozenset({'a4', 'letter'})

#: Countries whose offices print Letter by default.
LETTER_COUNTRIES: frozenset[str] = frozenset({'US', 'CA', 'MX'})

#: The CSS keyword WeasyPrint reads, per stored value.
_CSS_NAMES: dict[str, str] = {'a4': 'A4', 'letter': 'Letter'}


def decide_page_size(override: object, country: object) -> str:
    """The decision on the two columns that carry it, whatever loaded them."""
    if isinstance(override, str) and override.strip().lower() in PAGE_SIZES:
        return override.strip().lower()
    if isinstance(country, str) and country.strip().upper() in LETTER_COUNTRIES:
        return 'letter'
    return 'a4'


def page_size_of(organization: Any) -> str:
    """The paper an already-loaded organization object carries.

    For the ``OrganizationDTO`` the organization API builds (its deferred
    columns are refreshed there) or an ORM instance the caller loaded the
    page-size column on. Not a DB read — the render paths that only have
    a session use :func:`resolve_page_size_async`. An organization-less
    render is an A4 render, as it always was.
    """
    if organization is None:
        return 'a4'
    return decide_page_size(
        getattr(organization, 'print_page_size', None),
        getattr(organization, 'country', None),
    )


async def resolve_page_size_async(db: AsyncSession, org_id: UUID) -> str:
    """Which paper the organization behind *org_id* prints on.

    Reads only the two columns the decision needs, so it never trips over
    the deferred ``print_page_size`` mapping on a half-loaded instance.
    """
    from sqlalchemy import select

    from app.models.organization import Organization

    result = await db.execute(
        select(Organization.print_page_size, Organization.country).where(
            Organization.id == org_id
        )
    )
    row = result.first()
    if row is None:
        return 'a4'
    return decide_page_size(row.print_page_size, row.country)


def apply_page_size(html: str, page_size: str) -> str:
    """State the page size after everything the body already said.

    The rule lands at the end of the document, so an earlier ``size`` —
    a built-in's leftover or a saved copy from before this module existed —
    loses the cascade to the organization's answer.
    """
    css_name = _CSS_NAMES.get(page_size, 'A4')
    rule = f'\n<style>@page {{ size: {css_name}; }}</style>\n'
    head, sep, tail = html.rpartition('</body>')
    if sep:
        return head + rule + sep + tail
    return html + rule
