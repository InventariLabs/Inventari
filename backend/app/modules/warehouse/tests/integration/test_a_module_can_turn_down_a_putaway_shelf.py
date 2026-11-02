"""A module turns down shelves the putaway ranking would offer.

The ranking knows the operator's rules and the shelves' capacity; it does not
know that chilled goods need a cold shelf. A cold-chain module does, so it
registers a criterion that answers which of a rule's shelves may not take a
line, and the ranking walks the rest — in the plan a reader sees and in the
booking alike. Turning every shelf down sets the rule aside, the way an
archived list does, and the plan says why.
"""

from __future__ import annotations

from collections.abc import Collection, Iterator
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.contracts import PutawayCandidateDTO
from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.warehouse.warehouse_api import warehouse_api

from .test_putaway_rule_location_list import (
    _categorised_item,
    _confirmed_in,
    _rule_with_locations,
)
from .test_receipt_line_target import _make_category, _make_location

_MODULE = 'cold_chain'


class _Criterion:
    """The criterion: the shelves it turns down, and what it was asked."""

    def __init__(self) -> None:
        self.refuses: set[UUID] = set()
        self.asked: list[PutawayCandidateDTO] = []

    async def __call__(
        self, db: Any, org_id: UUID, candidate: PutawayCandidateDTO
    ) -> Collection[UUID]:
        self.asked.append(candidate)
        return self.refuses


@pytest.fixture
def criterion(db_session: Session, doc_org: Organization) -> Iterator[_Criterion]:
    doc_org.enabled_modules = [*doc_org.enabled_modules, _MODULE]
    db_session.commit()
    answer = _Criterion()
    warehouse_api.register_putaway_criterion(_MODULE, answer)
    yield answer
    # The registry is process-wide; leave the module turning nothing down.
    warehouse_api.register_putaway_criterion(_MODULE, _Criterion())


@pytest.fixture
def setup(
    client: TestClient,
    doc_auth_headers: dict[str, str],
    doc_target_location: StorageLocation,
    db_session: Session,
    doc_org: Organization,
    doc_user: User,
) -> dict[str, Any]:
    """A rule sending a category to two shelves, and a record of it."""
    category = _make_category(db_session, doc_org, f'COLD {uuid4().hex[:6]}')
    warm = _make_location(db_session, doc_org, doc_target_location, doc_user, 'Warm')
    cold = _make_location(db_session, doc_org, doc_target_location, doc_user, 'Cold')
    _rule_with_locations(
        client, doc_auth_headers, category_id=category, location_ids=[warm, cold]
    )
    item = _categorised_item(db_session, doc_org, doc_target_location, category)
    return {'category': category, 'warm': warm, 'cold': cold, 'item': item}


def _receipt(
    client: TestClient,
    headers: dict[str, str],
    partner: Partner,
    target: StorageLocation,
    item: Item,
) -> tuple[str, dict[str, Any]]:
    doc_id = _confirmed_in(
        client, headers, partner=partner, target_location=target, item=item
    )
    read = client.get(f'/api/v1/warehouse/documents/{doc_id}', headers=headers)
    assert read.status_code == status.HTTP_200_OK, read.text
    return doc_id, cast(dict[str, Any], read.json()['lines'][0])


@pytest.mark.integration
class TestAModuleCanTurnDownAPutawayShelf:
    def test_the_ranking_walks_past_a_refused_shelf_and_books_there(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        db_session: Session,
        doc_org: Organization,
        criterion: _Criterion,
        setup: dict[str, Any],
    ) -> None:
        criterion.refuses = {setup['warm'].id}

        doc_id, line = _receipt(
            client,
            doc_auth_headers,
            doc_partner,
            doc_target_location,
            setup['item'],
        )

        assert line['planned_location_id'] == str(setup['cold'].id), line
        assert line['planned_source'] == 'rule'
        assert line['planned_rule_warning'] is None
        asked = criterion.asked[0]
        assert asked.category_id == setup['category'].id
        assert asked.location_ids == [setup['warm'].id, setup['cold'].id]
        assert asked.quantity == 10

        complete = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert complete.status_code == status.HTTP_200_OK, complete.text
        db_session.expire_all()
        landed = db_session.scalars(
            select(Item.storage_location_id).where(
                Item.organization_id == doc_org.id,
                Item.category_id == setup['category'].id,
                Item.quantity > 0,
            )
        ).all()
        assert landed == [setup['cold'].id]

    def test_every_shelf_refused_sets_the_rule_aside_and_says_so(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        criterion: _Criterion,
        setup: dict[str, Any],
    ) -> None:
        criterion.refuses = {setup['warm'].id, setup['cold'].id}

        _, line = _receipt(
            client,
            doc_auth_headers,
            doc_partner,
            doc_target_location,
            setup['item'],
        )

        assert line['planned_location_id'] == str(doc_target_location.id), line
        assert line['planned_source'] == 'document'
        assert line['planned_rule_warning'] == 'refused'
        # The rule it set aside still rides along, for the reader.
        assert line['planned_rule_match_key'] == 'category'
        assert line['planned_over_capacity'] is None

    def test_a_module_switched_off_is_not_asked(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        db_session: Session,
        doc_org: Organization,
        criterion: _Criterion,
        setup: dict[str, Any],
    ) -> None:
        criterion.refuses = {setup['warm'].id}
        doc_org.enabled_modules = [m for m in doc_org.enabled_modules if m != _MODULE]
        db_session.commit()

        _, line = _receipt(
            client,
            doc_auth_headers,
            doc_partner,
            doc_target_location,
            setup['item'],
        )

        assert line['planned_location_id'] == str(setup['warm'].id), line
        assert criterion.asked == []
