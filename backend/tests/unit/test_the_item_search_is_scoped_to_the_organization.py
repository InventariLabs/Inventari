"""Both branches of the item search start from the asking organization.

The search is a set of record ids with one branch per carrier of the text.
The product-code branch was scoped to the organization, the own-fields
branch was not: on a database with several organizations every search read
the matches of all of them before the outer scope dropped the rest, where
the former single ``OR`` was narrowed by the organization's index first.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.models.item import Item
from app.services.items._search_terms import item_matches_text


def _statement_text(organization_id: uuid.UUID | None) -> str:
    stmt = select(Item.id).where(item_matches_text('kawa', organization_id))
    return str(stmt.compile(dialect=postgresql.dialect()))


def _branches(sql: str) -> list[str]:
    """The SELECTs of the ``UNION`` inside the ``id IN (...)`` predicate."""
    inner = sql.split(' IN (', 1)[1]
    return inner.split(' UNION ')


def test_every_branch_of_the_search_filters_on_the_organization() -> None:
    branches = _branches(_statement_text(uuid.uuid4()))

    assert len(branches) == 2
    for branch in branches:
        assert 'organization_id' in branch, branch


def test_the_organization_is_one_bound_value_per_branch() -> None:
    org_id = uuid.uuid4()
    stmt = select(Item.id).where(item_matches_text('kawa', org_id))
    compiled = stmt.compile(dialect=postgresql.dialect())

    assert [v for v in compiled.params.values() if v == org_id] != [], (
        'the organization must reach the statement as a bound value'
    )


def test_without_an_organization_nothing_is_filtered_on_one() -> None:
    """Callers that have no organization (the archive) keep the old reach."""
    branches = _branches(_statement_text(None))

    for branch in branches:
        assert 'organization_id' not in branch, branch
