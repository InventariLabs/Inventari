"""A putaway rule must not point into a hidden or virtual place.

A rule's target was validated only for existence — a location the
organization later archived, or one of the virtual counterparts (consumed,
inventory loss, production), passed as easily as a real shelf. The resolver
then steered every matching receipt straight into it: stock landed in a
place the lists and pickers hide, or was taken out of stock outright.

``test_receipt_lands_at_document_target_when_rule_target_is_archived`` is
the red proof: on the code before the fix, the archived rule still wins and
the goods settle in the hidden shelf; after the fix the rule is skipped, the
document target takes over, and the read says why.

Rule save and edit refuse such targets outright — the same questions, asked
of the same destination the line picker asks of its shelves.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.storage_location import LocationUsage, StorageLocation
from app.models.user import User

from .test_receipt_line_target import _make_category, _make_location


def _putaway_rule(
    client: TestClient,
    headers: dict[str, str],
    *,
    category_id: Any,
    target_location_id: StorageLocation,
) -> dict[str, object]:
    resp = client.post(
        '/api/v1/warehouse/putaway-rules',
        headers=headers,
        json={
            'category_id': str(category_id.id),
            'target_location_id': str(target_location_id.id),
        },
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    return cast(dict[str, object], resp.json())


def _archived_in(
    client: TestClient,
    headers: dict[str, str],
    *,
    partner: Partner,
    target_location: StorageLocation,
    item: Item,
    quantity: int = 3,
) -> str:
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
    complete = client.patch(
        f'/api/v1/warehouse/documents/{doc["id"]}/complete',
        headers=headers,
        json={'complete_as_planned': True},
    )
    assert complete.status_code == status.HTTP_200_OK, complete.text
    return cast(str, doc['id'])


@pytest.mark.integration
class TestPutawayRuleTargetScope:
    def test_receipt_lands_at_document_target_when_rule_target_is_archived(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        db_session: Session,
        doc_org: Organization,
        doc_user: User,
    ) -> None:
        """Archive the rule's shelf and the rule steps aside — visibly."""
        category = _make_category(db_session, doc_org, f'PAW3 {uuid4().hex[:6]}')
        rule_loc = _make_location(
            db_session, doc_org, doc_target_location, doc_user, 'PAW3 Doomed'
        )
        item = Item(
            name=f'PAW3 {uuid4().hex[:6]}',
            organization_id=doc_org.id,
            storage_location_id=doc_target_location.id,
            quantity=Decimal('1'),
            category_id=category.id,
        )
        db_session.add(item)
        db_session.commit()

        _putaway_rule(
            client,
            doc_auth_headers,
            category_id=category,
            target_location_id=rule_loc,
        )
        rule_loc.settings = {'archived': True}
        db_session.commit()

        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [{'item_id': str(item.id), 'expected_quantity': 3}],
            },
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        doc_id = resp.json()['id']
        confirm = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        assert confirm.status_code == status.HTTP_200_OK, confirm.text

        # Before execution the read already tells the truth: the plan is the
        # document's target, and it says why the rule did not take the line.
        read = client.get(
            f'/api/v1/warehouse/documents/{doc_id}', headers=doc_auth_headers
        )
        line = read.json()['lines'][0]
        assert line['planned_location_id'] == str(doc_target_location.id)
        assert line['planned_source'] == 'document'
        assert line['planned_rule_warning'] == 'archived'

        complete = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert complete.status_code == status.HTTP_200_OK, complete.text
        db_session.expire_all()
        landed = db_session.scalars(
            select(Item).where(Item.organization_id == doc_org.id)
        ).all()
        # Nothing may stand in the place the organization hid.
        assert all(row.storage_location_id != rule_loc.id for row in landed)

        after = client.get(
            f'/api/v1/warehouse/documents/{doc_id}', headers=doc_auth_headers
        )
        assert after.json()['lines'][0]['executed_location_id'] == str(
            doc_target_location.id
        )

    def test_receipt_lands_at_document_target_when_rule_target_is_virtual(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        db_session: Session,
        doc_org: Organization,
        doc_user: User,
    ) -> None:
        """A rule pointing at a counterpart place steps aside too.

        The archived case had a test; this one did not, and it is the worse
        of the two. A ``customer`` / ``inventory`` / ``production`` place is
        not a shelf — it is the far side of a movement — so a rule steering
        a receipt there would book goods straight out of stock the moment
        they arrived. Saving such a rule is refused, but a place can be
        turned into a counterpart after the rule was written, and from then
        on only the resolver stands between the delivery and the leak.

        What it fails on: drop the ``usage == 'internal'`` half of the
        planner's target test and the plan names the virtual place with
        source ``rule``.
        """
        category = _make_category(db_session, doc_org, f'PAW12 {uuid4().hex[:6]}')
        rule_loc = _make_location(
            db_session, doc_org, doc_target_location, doc_user, 'PAW12 Counterpart'
        )
        item = Item(
            name=f'PAW12 {uuid4().hex[:6]}',
            organization_id=doc_org.id,
            storage_location_id=doc_target_location.id,
            quantity=Decimal('1'),
            category_id=category.id,
        )
        db_session.add(item)
        db_session.commit()

        _putaway_rule(
            client,
            doc_auth_headers,
            category_id=category,
            target_location_id=rule_loc,
        )
        # The place becomes a counterpart after the rule was written — the
        # save-time refusal never sees this, only the resolver does.
        rule_loc.usage = 'customer'
        db_session.commit()

        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [{'item_id': str(item.id), 'expected_quantity': 3}],
            },
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        doc_id = resp.json()['id']
        confirm = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        assert confirm.status_code == status.HTTP_200_OK, confirm.text

        read = client.get(
            f'/api/v1/warehouse/documents/{doc_id}', headers=doc_auth_headers
        )
        line = read.json()['lines'][0]
        assert line['planned_location_id'] == str(doc_target_location.id)
        assert line['planned_source'] == 'document'
        assert line['planned_rule_warning'] == 'not_internal'

        complete = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert complete.status_code == status.HTTP_200_OK, complete.text
        db_session.expire_all()
        landed = db_session.scalars(
            select(Item).where(Item.organization_id == doc_org.id)
        ).all()
        # Nothing arrives on the far side of a movement.
        assert all(row.storage_location_id != rule_loc.id for row in landed)

    def test_rule_save_refuses_archived_and_virtual_targets(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        db_session: Session,
        doc_org: Organization,
        doc_user: User,
    ) -> None:
        """A rule for a hidden or virtual shelf is refused where it is
        written, with a message from the catalog."""
        category = _make_category(db_session, doc_org, f'PAW3 save {uuid4().hex[:6]}')
        archived = _make_location(
            db_session,
            doc_org,
            doc_target_location,
            doc_user,
            'PAW3 Archived',
            settings={'archived': True},
        )
        virtual = _make_location(
            db_session,
            doc_org,
            doc_target_location,
            doc_user,
            'PAW3 Virtual',
            usage=LocationUsage.CUSTOMER.value,
        )

        for loc in (archived, virtual):
            resp = client.post(
                '/api/v1/warehouse/putaway-rules',
                headers=doc_auth_headers,
                json={
                    'category_id': str(category.id),
                    'target_location_id': str(loc.id),
                },
            )
            assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.text
            assert 'PAW3' in resp.json()['detail']['message']

    def test_rule_edit_to_inactive_target_is_refused(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        db_session: Session,
        doc_org: Organization,
        doc_user: User,
    ) -> None:
        """Editing a good rule onto a hidden shelf is the same refusal."""
        category = _make_category(db_session, doc_org, f'PAW3 edit {uuid4().hex[:6]}')
        rule_loc = _make_location(
            db_session, doc_org, doc_target_location, doc_user, 'PAW3 Good'
        )
        rule = _putaway_rule(
            client,
            doc_auth_headers,
            category_id=category,
            target_location_id=rule_loc,
        )
        rule_loc.settings = {'archived': True}
        db_session.commit()

        resp = client.put(
            f'/api/v1/warehouse/putaway-rules/{rule["id"]}',
            headers=doc_auth_headers,
            json={'target_location_id': str(rule_loc.id)},
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.text

    def test_rule_targeting_archived_shelf_is_marked_on_the_list(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        db_session: Session,
        doc_org: Organization,
        doc_user: User,
    ) -> None:
        """A rule whose target went dark says so on the rules list, instead
        of reading as an ordinary, working rule."""
        category = _make_category(db_session, doc_org, f'PAW3 list {uuid4().hex[:6]}')
        rule_loc = _make_location(
            db_session, doc_org, doc_target_location, doc_user, 'PAW3 Marked'
        )
        _putaway_rule(
            client,
            doc_auth_headers,
            category_id=category,
            target_location_id=rule_loc,
        )
        rule_loc.settings = {'archived': True}
        db_session.commit()

        rules = client.get(
            '/api/v1/warehouse/putaway-rules', headers=doc_auth_headers
        ).json()['items']
        target_rule = next(
            r for r in rules if r['target_location_id'] == str(rule_loc.id)
        )
        assert target_rule['target_location_active'] is False

    def test_valid_rule_target_still_reads_clean(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        db_session: Session,
        doc_org: Organization,
        doc_user: User,
    ) -> None:
        """The mark is about the target's state, not about rules in
        general: a live rule on a live shelf reads clean."""
        category = _make_category(db_session, doc_org, f'PAW3 ok {uuid4().hex[:6]}')
        rule_loc = _make_location(
            db_session, doc_org, doc_target_location, doc_user, 'PAW3 Live'
        )
        _putaway_rule(
            client,
            doc_auth_headers,
            category_id=category,
            target_location_id=rule_loc,
        )
        rules = client.get(
            '/api/v1/warehouse/putaway-rules', headers=doc_auth_headers
        ).json()['items']
        target_rule = next(
            r for r in rules if r['target_location_id'] == str(rule_loc.id)
        )
        assert target_rule['target_location_active'] is True
