"""Filters a module adds to the documents list.

The warehouse filters its documents by what it knows — the type, the status,
the partner, a date. A module that keeps its own facts on the lines (a
certificate, a customs code) knows what narrowing by them means, so it
registers a provider here under its own name and a filter name, at its import
time (like a pick order or a pre-post check). The list asks the provider when
a reader turns that filter on and narrows to what it answers, on the server,
where the paging and the count are — not over the page the reader happens to
hold.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import DocumentFilterDTO
from app.core.public_api import core_api

#: ``(db, org_id) -> what the list narrows to``. Asked inside the list's own
#: read; it must not write.
DocumentFilterProvider = Callable[[AsyncSession, UUID], Awaitable[DocumentFilterDTO]]

_FILTERS: dict[tuple[str, str], DocumentFilterProvider] = {}


class UnknownDocumentFilterError(ValueError):
    """The list was asked for a filter no enabled module answers."""


def register_document_filter(
    module: str, name: str, provider: DocumentFilterProvider
) -> None:
    """Claim a filter of the documents list for one module.

    The list names it ``<module>:<name>``. Registering the same pair again
    replaces the earlier provider, which keeps module reloads (and tests) from
    accumulating stale entries.
    """
    _FILTERS[(module, name)] = provider


async def resolve_document_filters_async(
    db: AsyncSession, org_id: UUID, names: list[str]
) -> list[tuple[str, DocumentFilterDTO]]:
    """Ask each named filter's provider, beside the module that owns it.

    A name nothing registered, and one whose module is switched off for the
    organization, is refused rather than skipped: a list that quietly ignores
    the filter it was asked for shows every document under a chip that says
    it shows some.
    """
    answers: list[tuple[str, DocumentFilterDTO]] = []
    for full_name in names:
        module, _, name = full_name.partition(':')
        provider = _FILTERS.get((module, name))
        if provider is None or not await core_api.organizations.is_module_enabled_async(
            db, org_id, module
        ):
            raise UnknownDocumentFilterError(full_name)
        answers.append((module, await provider(db, org_id)))
    return answers
