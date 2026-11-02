"""The receipt line says where it will land before it lands.

A putaway rule decides at execution time, so the decision used to become
visible only after the goods were booked — as "landed elsewhere". The read
of a pre-execution receipt now carries each line's planned location and the
source of the decision (serial / rule / document / record), computed at
read time by the same function the executor calls.

The discriminating test is ``test_preview_follows_a_rule_changed_between_
read_and_execute``: with two copies of the decision logic (a stored preview
and a live executor) the second read would still show the old shelf and the
execution would go to the new one. One function makes both answers move
together.
"""

from __future__ import annotations

from typing import cast
from uuid import UUID, uuid4

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.storage_location import StorageLocation
from app.models.user import User

from .test_putaway_rules import _create_putaway


def _make_location(
    db_session: Session,
    doc_org: Organization,
    doc_target_location: StorageLocation,
    doc_user: User,
    name: str,
) -> StorageLocation:
    loc = StorageLocation(
        organization_id=doc_org.id,
        storage_type_id=doc_target_location.storage_type_id,
        created_by=doc_user.id,
        name=name,
    )
    db_session.add(loc)
    db_session.commit()
    db_session.refresh(loc)
    return loc


def _confirmed_in(
    client: TestClient,
    headers: dict[str, str],
    *,
    partner_id: Partner,
    target_location_id: StorageLocation,
    template_id: UUID,
    quantity: int = 3,
) -> str:
    resp = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'IN',
            'partner_id': str(partner_id.id),
            'target_location_id': str(target_location_id.id),
            'lines': [
                {
                    'product_template_id': str(template_id),
                    'expected_quantity': quantity,
                }
            ],
        },
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    doc_id = cast(str, resp.json()['id'])
    confirm = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=headers
    )
    assert confirm.status_code == status.HTTP_200_OK, confirm.text
    return doc_id


@pytest.mark.integration
class TestReceiptPlannedLocation:
    def test_read_before_execution_shows_rule_target(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        db_session: Session,
        doc_org: Organization,
        doc_user: User,
    ) -> None:
        """A matching rule's target is on the line before execution."""
        from app.core.testing import ModuleTestHelper

        h = ModuleTestHelper(db_session)
        rule_loc = _make_location(
            db_session, doc_org, doc_target_location, doc_user, 'PAW1 Rule Shelf'
        )
        template = h.create_template(doc_org, name=f'PAW1 {uuid4().hex[:6]}')
        _create_putaway(
            client,
            doc_auth_headers,
            product_template_id=str(template.id),
            target_location_id=str(rule_loc.id),
        )
        doc_id = _confirmed_in(
            client,
            doc_auth_headers,
            partner_id=doc_partner,
            target_location_id=doc_target_location,
            template_id=template.id,
        )

        read = client.get(
            f'/api/v1/warehouse/documents/{doc_id}', headers=doc_auth_headers
        )
        assert read.status_code == status.HTTP_200_OK, read.text
        line = read.json()['lines'][0]
        assert line['planned_location_id'] == str(rule_loc.id)
        assert line['planned_location_name'] == 'PAW1 Rule Shelf'
        assert line['planned_source'] == 'rule'
        assert line['planned_rule_match_key'] == 'product_template'
        assert line['planned_rule_match_name'] == template.name
        assert line['planned_rule_id'] is not None

        # The executor must land the goods where the preview said they would
        # go — that equality is the whole point of one shared decision.
        complete = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert complete.status_code == status.HTTP_200_OK, complete.text
        after = client.get(
            f'/api/v1/warehouse/documents/{doc_id}', headers=doc_auth_headers
        )
        executed = after.json()['lines'][0]
        assert executed['executed_location_id'] == line['planned_location_id']

    def test_preview_follows_a_rule_changed_between_read_and_execute(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        db_session: Session,
        doc_org: Organization,
        doc_user: User,
    ) -> None:
        """One decision function: a rule edited after a read moves both the
        preview and the execution. A preview stored at read time would keep
        naming the old shelf while the goods went to the new one."""
        from app.core.testing import ModuleTestHelper

        h = ModuleTestHelper(db_session)
        first_loc = _make_location(
            db_session, doc_org, doc_target_location, doc_user, 'PAW1 First'
        )
        second_loc = _make_location(
            db_session, doc_org, doc_target_location, doc_user, 'PAW1 Second'
        )
        template = h.create_template(doc_org, name=f'PAW1 move {uuid4().hex[:6]}')
        rule = _create_putaway(
            client,
            doc_auth_headers,
            product_template_id=str(template.id),
            target_location_id=str(first_loc.id),
        )
        doc_id = _confirmed_in(
            client,
            doc_auth_headers,
            partner_id=doc_partner,
            target_location_id=doc_target_location,
            template_id=template.id,
        )

        before = client.get(
            f'/api/v1/warehouse/documents/{doc_id}', headers=doc_auth_headers
        )
        assert before.json()['lines'][0]['planned_location_id'] == str(first_loc.id)

        moved = client.put(
            f'/api/v1/warehouse/putaway-rules/{rule["id"]}',
            headers=doc_auth_headers,
            json={'target_location_id': str(second_loc.id)},
        )
        assert moved.status_code == status.HTTP_200_OK, moved.text

        after = client.get(
            f'/api/v1/warehouse/documents/{doc_id}', headers=doc_auth_headers
        )
        line = after.json()['lines'][0]
        assert line['planned_location_id'] == str(second_loc.id)
        assert line['planned_location_name'] == 'PAW1 Second'

        complete = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert complete.status_code == status.HTTP_200_OK, complete.text
        item = db_session.scalars(
            select(Item).where(Item.template_id == template.id)
        ).first()
        assert item is not None
        assert item.storage_location_id == second_loc.id
        assert line['planned_location_id'] == str(item.storage_location_id)

    def test_read_without_rule_shows_document_target(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        db_session: Session,
        doc_org: Organization,
    ) -> None:
        """No rule: the document's own target is the plan, source document."""
        from app.core.testing import ModuleTestHelper

        h = ModuleTestHelper(db_session)
        template = h.create_template(doc_org, name=f'PAW1 doc {uuid4().hex[:6]}')
        doc_id = _confirmed_in(
            client,
            doc_auth_headers,
            partner_id=doc_partner,
            target_location_id=doc_target_location,
            template_id=template.id,
        )
        read = client.get(
            f'/api/v1/warehouse/documents/{doc_id}', headers=doc_auth_headers
        )
        line = read.json()['lines'][0]
        assert line['planned_location_id'] == str(doc_target_location.id)
        assert line['planned_source'] == 'document'
        assert line['planned_rule_id'] is None
