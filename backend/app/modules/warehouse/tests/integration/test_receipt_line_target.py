"""The worker names the shelf on the line, before execution.

A warehouse worker facing a full shelf had exactly one answer: put the
goods somewhere the system did not know about, and watch the books
disagree with the room. The line now carries its own target location —
settled after the serial-number record (one physical thing) and before
the rule (a rule about the goods may not overrule a person standing at
the shelf). A move away from the rule's target leaves both names in the
journal: "the rule said A-12, it landed on A-13".

``test_line_target_overrides_rule_and_document`` is the red proof: without
the column, the endpoint and the decision branch, the goods land wherever
the rule says and the PATCH answers 404/405.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.category import Category
from app.models.item import Item
from app.models.item_history import ItemHistory
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.storage_location import LocationUsage, StorageLocation
from app.models.user import User


def _make_location(
    db_session: Session,
    org: Organization,
    like: StorageLocation,
    user: User,
    name: str,
    **kwargs: Any,
) -> StorageLocation:
    loc = StorageLocation(
        organization_id=org.id,
        storage_type_id=like.storage_type_id,
        created_by=user.id,
        name=name,
        **kwargs,
    )
    db_session.add(loc)
    db_session.commit()
    db_session.refresh(loc)
    return loc


def _make_category(db_session: Session, org: Organization, name: str) -> Category:
    category = Category(
        organization_id=org.id,
        name=name,
    )
    db_session.add(category)
    db_session.commit()
    db_session.refresh(category)
    return category


def _putaway_rule(
    client: TestClient,
    headers: dict[str, str],
    *,
    category_id: Category,
    target_location_id: StorageLocation,
) -> None:
    resp = client.post(
        '/api/v1/warehouse/putaway-rules',
        headers=headers,
        json={
            'category_id': str(category_id.id),
            'target_location_id': str(target_location_id.id),
        },
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text


def _patch_line_target(
    client: TestClient,
    headers: dict[str, str],
    doc_id: str,
    line_id: str,
    target: UUID | None,
) -> httpx.Response:
    return cast(
        httpx.Response,
        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/lines/{line_id}',
            headers=headers,
            json={'target_location_id': str(target) if target else None},
        ),
    )


def _confirmed_in_with_item(
    client: TestClient,
    headers: dict[str, str],
    *,
    partner: Partner,
    target_location: StorageLocation,
    item: Item,
    quantity: int = 3,
) -> tuple[str, str]:
    resp = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'IN',
            'partner_id': str(partner.id),
            'target_location_id': str(target_location.id),
            'lines': [{'item_id': str(item.id), 'expected_quantity': quantity}],
        },
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    doc = resp.json()
    confirm = client.patch(
        f'/api/v1/warehouse/documents/{doc["id"]}/confirm', headers=headers
    )
    assert confirm.status_code == status.HTTP_200_OK, confirm.text
    return cast(str, doc['id']), cast(str, doc['lines'][0]['id'])


def _plain_item(db_session: Session, org: Organization, like: StorageLocation) -> Item:
    item = Item(
        name=f'PAW2 {uuid4().hex[:6]}',
        organization_id=org.id,
        storage_location_id=like.id,
        quantity=Decimal('1'),
    )
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)
    return item


@pytest.mark.integration
class TestReceiptLineTarget:
    def test_line_target_overrides_rule_and_document(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        db_session: Session,
        doc_org: Organization,
        doc_user: User,
    ) -> None:
        """The line's shelf wins over the rule and the document target."""
        category = _make_category(db_session, doc_org, f'PAW2 cat {uuid4().hex[:6]}')
        rule_loc = _make_location(
            db_session, doc_org, doc_target_location, doc_user, 'PAW2 Rule'
        )
        line_loc = _make_location(
            db_session, doc_org, doc_target_location, doc_user, 'PAW2 Line'
        )
        item = _plain_item(db_session, doc_org, doc_target_location)
        item.category_id = category.id
        db_session.commit()

        _putaway_rule(
            client,
            doc_auth_headers,
            category_id=category,
            target_location_id=rule_loc,
        )
        doc_id, line_id = _confirmed_in_with_item(
            client,
            doc_auth_headers,
            partner=doc_partner,
            target_location=doc_target_location,
            item=item,
        )

        patched = _patch_line_target(
            client, doc_auth_headers, doc_id, line_id, line_loc.id
        )
        assert patched.status_code == status.HTTP_200_OK, patched.text

        read = client.get(
            f'/api/v1/warehouse/documents/{doc_id}', headers=doc_auth_headers
        )
        line = read.json()['lines'][0]
        assert line['target_location_id'] == str(line_loc.id)
        assert line['planned_location_id'] == str(line_loc.id)
        assert line['planned_source'] == 'line'

        complete = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert complete.status_code == status.HTTP_200_OK, complete.text

        # The delivery landed on the line's shelf as a new record — the
        # record the line named stays where it stood, holding what was
        # already there.
        read = client.get(
            f'/api/v1/warehouse/documents/{doc_id}', headers=doc_auth_headers
        )
        line = read.json()['lines'][0]
        assert line['executed_location_id'] == str(line_loc.id)
        opened = db_session.scalars(
            select(Item).where(
                Item.organization_id == doc_org.id,
                Item.storage_location_id == line_loc.id,
            )
        ).all()
        assert any(row.name == item.name for row in opened)

    def test_serial_record_beats_line_target(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        db_session: Session,
        doc_org: Organization,
        doc_user: User,
    ) -> None:
        """One serial-numbered thing: the line may not split it elsewhere."""
        serial_loc = _make_location(
            db_session, doc_org, doc_target_location, doc_user, 'PAW2 Serial'
        )
        line_loc = _make_location(
            db_session, doc_org, doc_target_location, doc_user, 'PAW2 Other'
        )
        item = Item(
            name=f'PAW2 serial {uuid4().hex[:6]}',
            organization_id=doc_org.id,
            storage_location_id=serial_loc.id,
            serial_number=f'SN-{uuid4().hex[:8]}',
            quantity=Decimal('1'),
        )
        db_session.add(item)
        db_session.commit()

        doc_id, line_id = _confirmed_in_with_item(
            client,
            doc_auth_headers,
            partner=doc_partner,
            target_location=doc_target_location,
            item=item,
        )
        patched = _patch_line_target(
            client, doc_auth_headers, doc_id, line_id, line_loc.id
        )
        assert patched.status_code == status.HTTP_200_OK, patched.text

        read = client.get(
            f'/api/v1/warehouse/documents/{doc_id}', headers=doc_auth_headers
        )
        line = read.json()['lines'][0]
        assert line['planned_location_id'] == str(serial_loc.id)
        assert line['planned_source'] == 'serial'

    def test_line_target_from_other_org_reads_as_missing(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        db_session: Session,
        doc_org: Organization,
        doc_user: User,
    ) -> None:
        """A foreign shelf is refused the same way a missing one is — the
        answer may not confirm that the id exists somewhere else."""
        item = _plain_item(db_session, doc_org, doc_target_location)
        doc_id, line_id = _confirmed_in_with_item(
            client,
            doc_auth_headers,
            partner=doc_partner,
            target_location=doc_target_location,
            item=item,
        )

        foreign_org = Organization(name=f'PAW2 other {uuid4().hex[:6]}')
        db_session.add(foreign_org)
        db_session.commit()
        foreign_loc = _make_location(
            db_session, foreign_org, doc_target_location, doc_user, 'PAW2 Foreign'
        )

        patched = _patch_line_target(
            client, doc_auth_headers, doc_id, line_id, foreign_loc.id
        )
        assert 400 <= patched.status_code < 500, patched.text
        missing = _patch_line_target(client, doc_auth_headers, doc_id, line_id, uuid4())
        assert 400 <= missing.status_code < 500, missing.text
        # Same status, same code: the answer for a foreign id must not be
        # distinguishable from the answer for a missing one. (The message
        # echoes the probed id — which the caller already knows.)
        assert patched.status_code == missing.status_code
        assert patched.json()['detail']['code'] == missing.json()['detail']['code']

    def test_line_target_virtual_or_archived_is_refused(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        db_session: Session,
        doc_org: Organization,
        doc_user: User,
    ) -> None:
        """Goods land on shelves: not in the consumed/inventory/production
        counterparts, not in a location the organization archived away."""
        item = _plain_item(db_session, doc_org, doc_target_location)
        doc_id, line_id = _confirmed_in_with_item(
            client,
            doc_auth_headers,
            partner=doc_partner,
            target_location=doc_target_location,
            item=item,
        )

        virtual = _make_location(
            db_session,
            doc_org,
            doc_target_location,
            doc_user,
            'PAW2 Virtual',
            usage=LocationUsage.CUSTOMER.value,
        )
        archived = _make_location(
            db_session,
            doc_org,
            doc_target_location,
            doc_user,
            'PAW2 Archived',
            settings={'archived': True},
        )

        for loc in (virtual, archived):
            patched = _patch_line_target(
                client, doc_auth_headers, doc_id, line_id, loc.id
            )
            assert 400 <= patched.status_code < 500, f'{loc.name}: {patched.text}'

    def test_override_leaves_rule_and_landed_in_the_journal(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        db_session: Session,
        doc_org: Organization,
        doc_user: User,
    ) -> None:
        """Putting goods where the rule did not point is a decision someone
        should be able to read later — the journal keeps both names."""
        category = _make_category(
            db_session, doc_org, f'PAW2 journal cat {uuid4().hex[:6]}'
        )
        rule_loc = _make_location(
            db_session, doc_org, doc_target_location, doc_user, 'PAW2 Journal Rule'
        )
        line_loc = _make_location(
            db_session, doc_org, doc_target_location, doc_user, 'PAW2 Journal Line'
        )
        item = _plain_item(db_session, doc_org, doc_target_location)
        item.category_id = category.id
        db_session.commit()

        _putaway_rule(
            client,
            doc_auth_headers,
            category_id=category,
            target_location_id=rule_loc,
        )
        doc_id, line_id = _confirmed_in_with_item(
            client,
            doc_auth_headers,
            partner=doc_partner,
            target_location=doc_target_location,
            item=item,
        )
        patched = _patch_line_target(
            client, doc_auth_headers, doc_id, line_id, line_loc.id
        )
        assert patched.status_code == status.HTTP_200_OK, patched.text
        complete = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert complete.status_code == status.HTTP_200_OK, complete.text

        history = list(
            db_session.scalars(
                select(ItemHistory).where(
                    ItemHistory.source_document_id == UUID(doc_id)
                )
            ).all()
        )
        assert history, 'execution wrote no journal rows'
        joined = ' '.join(str(entry.changes) for entry in history if entry.changes)
        assert 'PAW2 Journal Rule' in joined
        assert 'PAW2 Journal Line' in joined


@pytest.mark.integration
class TestAReceivedLineKeepsItsShelf:
    def test_the_page_cannot_re_aim_a_line_the_open_session_received(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        db_session: Session,
        doc_org: Organization,
        doc_user: User,
    ) -> None:
        """Behind the open receiving dialog the page's own selects stay live.

        Changing the first one moved a line the session had already marked
        received, and its stock was later booked onto the new shelf. A line
        still waiting in the session can be re-aimed as before.
        """
        received_item = _plain_item(db_session, doc_org, doc_target_location)
        waiting_item = _plain_item(db_session, doc_org, doc_target_location)
        other_shelf = _make_location(
            db_session, doc_org, doc_target_location, doc_user, 'PAW2 Other'
        )
        created = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {'item_id': str(received_item.id), 'expected_quantity': 3},
                    {'item_id': str(waiting_item.id), 'expected_quantity': 2},
                ],
            },
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        doc = created.json()
        doc_id = doc['id']
        first, second = (line['id'] for line in doc['lines'])
        confirmed = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        assert confirmed.status_code == status.HTTP_200_OK, confirmed.text
        session = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/start',
            headers=doc_auth_headers,
        ).json()
        session_line = next(
            line for line in session['lines'] if line['document_line_id'] == first
        )
        received = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/{session["id"]}'
            '/short-receive',
            headers=doc_auth_headers,
            json={'line_id': session_line['id'], 'received_quantity': '3'},
        )
        assert received.status_code == status.HTTP_200_OK, received.text

        refused = _patch_line_target(
            client, doc_auth_headers, doc_id, first, other_shelf.id
        )
        assert refused.status_code == status.HTTP_400_BAD_REQUEST, refused.text
        assert 'already received' in refused.text

        moved = _patch_line_target(
            client, doc_auth_headers, doc_id, second, other_shelf.id
        )
        assert moved.status_code == status.HTTP_200_OK, moved.text
