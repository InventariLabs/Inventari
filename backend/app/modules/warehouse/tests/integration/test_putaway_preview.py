"""The one-screen receive form asks the planner before the document exists.

The form shows each line's shelf and the reason while the reader is still
typing, and posting happens only after the whole sheet is filled. So the
decision has to be answerable for a receipt that has no row yet — and it
has to be the *same* decision the posting will make, or the shelf the reader
saw is not the shelf the goods reach.

These tests pin both halves: the preview names the rule, its match and the
shelf, and a document built from the same lines lands exactly there.
"""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.models.user import User

from .test_putaway_rules import _create_putaway
from .test_receipt_planned_location import _make_location


def _preview(
    client: TestClient,
    headers: dict[str, str],
    *,
    target_location_id: UUID,
    lines: list[dict[str, object]],
) -> list[dict[str, object]]:
    resp = client.post(
        '/api/v1/warehouse/putaway/preview',
        headers=headers,
        json={
            'target_location_id': str(target_location_id),
            'lines': lines,
        },
    )
    assert resp.status_code == status.HTTP_200_OK, resp.text
    return cast(list[dict[str, object]], resp.json())


def _posted_lines(
    lines: list[dict[str, object]],
) -> list[dict[str, object]]:
    """The same sheet under the document schema's field names.

    ``PutawayPreviewLineIn`` keeps the amount as ``quantity`` — the name the
    receive form states — while ``DocumentLineCreate`` names the same number
    ``expected_quantity``. The sheet is one; the two doors read it under
    their own names.
    """
    return [
        {
            **{key: value for key, value in line.items() if key != 'quantity'},
            'expected_quantity': line['quantity'],
        }
        for line in lines
    ]


@pytest.mark.integration
class TestPutawayPreview:
    def test_preview_names_the_rule_and_its_reason(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        db_session: Session,
        doc_org: Organization,
        doc_user: User,
    ) -> None:
        """An unsaved line gets the rule's shelf, the match and the source."""
        from app.core.testing import ModuleTestHelper

        h = ModuleTestHelper(db_session)
        rule_loc = _make_location(
            db_session, doc_org, doc_target_location, doc_user, 'PVW1 Rule Shelf'
        )
        template = h.create_template(doc_org, name=f'PVW1 {uuid4().hex[:6]}')
        _create_putaway(
            client,
            doc_auth_headers,
            product_template_id=str(template.id),
            target_location_id=str(rule_loc.id),
        )

        lines = _preview(
            client,
            doc_auth_headers,
            target_location_id=doc_target_location.id,
            lines=[{'product_template_id': str(template.id), 'quantity': 4}],
        )

        assert len(lines) == 1
        line = lines[0]
        assert line['planned_location_id'] == str(rule_loc.id)
        assert line['planned_location_name'] == 'PVW1 Rule Shelf'
        assert line['planned_source'] == 'rule'
        assert line['planned_rule_match_key'] == 'product_template'
        assert line['planned_rule_match_name'] == template.name
        assert line['planned_over_capacity'] is False

    def test_posting_lands_where_the_preview_named(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Any,
        db_session: Session,
        doc_org: Organization,
        doc_user: User,
    ) -> None:
        """The shelf shown on the form is the shelf the goods reach."""
        from app.core.testing import ModuleTestHelper

        h = ModuleTestHelper(db_session)
        rule_loc = _make_location(
            db_session, doc_org, doc_target_location, doc_user, 'PVW2 Rule Shelf'
        )
        template = h.create_template(doc_org, name=f'PVW2 {uuid4().hex[:6]}')
        _create_putaway(
            client,
            doc_auth_headers,
            product_template_id=str(template.id),
            target_location_id=str(rule_loc.id),
        )
        lines = [
            {'product_template_id': str(template.id), 'quantity': 4},
        ]
        preview = _preview(
            client,
            doc_auth_headers,
            target_location_id=doc_target_location.id,
            lines=lines,
        )
        partner_id = cast(UUID, doc_partner.id)

        posted = client.post(
            '/api/v1/warehouse/documents/post',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(partner_id),
                'target_location_id': str(doc_target_location.id),
                'lines': _posted_lines(lines),
            },
        )
        assert posted.status_code == status.HTTP_201_CREATED, posted.text
        executed = posted.json()['lines'][0]
        assert executed['executed_location_id'] == preview[0]['planned_location_id']

    def test_line_target_outranks_the_rule(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        db_session: Session,
        doc_org: Organization,
        doc_user: User,
    ) -> None:
        """A shelf the worker names is the decision, and the preview says so."""
        from app.core.testing import ModuleTestHelper

        h = ModuleTestHelper(db_session)
        rule_loc = _make_location(
            db_session, doc_org, doc_target_location, doc_user, 'PVW3 Rule Shelf'
        )
        chosen_loc = _make_location(
            db_session, doc_org, doc_target_location, doc_user, 'PVW3 Chosen Shelf'
        )
        template = h.create_template(doc_org, name=f'PVW3 {uuid4().hex[:6]}')
        _create_putaway(
            client,
            doc_auth_headers,
            product_template_id=str(template.id),
            target_location_id=str(rule_loc.id),
        )

        line = _preview(
            client,
            doc_auth_headers,
            target_location_id=doc_target_location.id,
            lines=[
                {
                    'product_template_id': str(template.id),
                    'quantity': 4,
                    'target_location_id': str(chosen_loc.id),
                }
            ],
        )[0]

        assert line['planned_location_id'] == str(chosen_loc.id)
        assert line['planned_location_name'] == 'PVW3 Chosen Shelf'
        assert line['planned_source'] == 'line'

    def test_two_step_receiving_previews_the_area_the_goods_are_booked_into(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Any,
        db_session: Session,
        doc_org: Organization,
        doc_user: User,
    ) -> None:
        """A warehouse that receives in two steps books its area, not the shelf.

        The landing step is the executor's: the goods stop in the receiving
        area whatever shelf the rules or the worker chose, and the putaway
        task carries them on from there. A preview that named the shelf
        would promise a place the goods never reach.
        """
        from app.core.testing import ModuleTestHelper

        h = ModuleTestHelper(db_session)
        rule_loc = _make_location(
            db_session, doc_org, doc_target_location, doc_user, 'PVW5 Rule Shelf'
        )
        chosen_loc = _make_location(
            db_session, doc_org, doc_target_location, doc_user, 'PVW5 Chosen Shelf'
        )
        template = h.create_template(doc_org, name=f'PVW5 {uuid4().hex[:6]}')
        _create_putaway(
            client,
            doc_auth_headers,
            product_template_id=str(template.id),
            target_location_id=str(rule_loc.id),
        )
        chosen = client.put(
            f'/api/v1/warehouse/putaway/receiving-modes/{doc_target_location.id}',
            headers=doc_auth_headers,
            json={'two_step': True},
        )
        assert chosen.status_code == status.HTTP_200_OK, chosen.text
        area_id = chosen.json()['receiving_location_id']

        lines: list[dict[str, object]] = [
            {'product_template_id': str(template.id), 'quantity': 4},
            {
                'product_template_id': str(template.id),
                'quantity': 2,
                'target_location_id': str(chosen_loc.id),
            },
        ]
        preview = _preview(
            client,
            doc_auth_headers,
            target_location_id=doc_target_location.id,
            lines=lines,
        )

        # The rule and the named shelf both answer with the area: the
        # landing step is the same one the executor applies.
        assert [line['planned_location_id'] for line in preview] == [area_id, area_id]
        assert [line['planned_location_name'] for line in preview] == [
            'Receiving',
            'Receiving',
        ]
        assert [line['planned_source'] for line in preview] == [
            'receiving',
            'receiving',
        ]

        posted = client.post(
            '/api/v1/warehouse/documents/post',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(cast(UUID, doc_partner.id)),
                'target_location_id': str(doc_target_location.id),
                'lines': _posted_lines(lines),
            },
        )
        assert posted.status_code == status.HTTP_201_CREATED, posted.text
        assert [line['executed_location_id'] for line in posted.json()['lines']] == [
            area_id,
            area_id,
        ]

    def test_preview_without_a_rule_falls_back_to_the_destination(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        db_session: Session,
        doc_org: Organization,
    ) -> None:
        """Nothing to route by means the delivery's own destination."""
        from app.core.testing import ModuleTestHelper

        template = ModuleTestHelper(db_session).create_template(
            doc_org, name=f'PVW4 {uuid4().hex[:6]}'
        )

        line = _preview(
            client,
            doc_auth_headers,
            target_location_id=doc_target_location.id,
            lines=[{'product_template_id': str(template.id), 'quantity': 1}],
        )[0]

        assert line['planned_location_id'] == str(doc_target_location.id)
        assert line['planned_source'] == 'document'
