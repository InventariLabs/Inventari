"""A rule names an ordered list of shelves and checks capacity.

One target per rule meant one answer: the first shelf fills up, and the
rule keeps steering every later delivery onto the same full shelf. The
rule now carries an ordered list, and the resolver walks it: the first
shelf where the product's current stock, plus what this document's earlier
lines already sent there, plus this line's quantity still fits. A shelf
with no capacity entry always fits; a single-product shelf with another
product standing on it never does. Nothing fits → the plan falls back to
the first shelf on the list with an over-capacity mark — a warning, never
a refusal, because the goods have already arrived.

``test_overflow_moves_to_the_second_shelf`` is the red proof: on the
one-target rule the second shelf is unreachable and the goods queue up on
the full one. ``test_two_lines_of_one_document_count_together`` fails
whenever the lines are measured separately — the discriminator the plan
asks for by name.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.warehouse.tests.integration._records import (
    sow as _sow,
)
from tests.integration._shelf import anchor_pending_records

from .test_receipt_line_target import _make_category, _make_location


def _rule_with_locations(
    client: TestClient,
    headers: dict[str, str],
    *,
    category_id: Any,
    location_ids: list[StorageLocation],
) -> dict[str, object]:
    resp = client.post(
        '/api/v1/warehouse/putaway-rules',
        headers=headers,
        json={
            'category_id': str(category_id.id),
            'location_ids': [str(loc.id) for loc in location_ids],
        },
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    return cast(dict[str, object], resp.json())


def _put_capacity(
    client: TestClient,
    headers: dict[str, str],
    *,
    location_id: StorageLocation,
    template_id: UUID,
    max_quantity: str,
) -> None:
    resp = client.post(
        '/api/v1/warehouse/putaway/capacity',
        headers=headers,
        json={
            'location_id': str(location_id.id),
            'product_template_id': str(template_id),
            'max_quantity': max_quantity,
        },
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text


def _stock_shelf(
    db_session: Session,
    engine: AsyncEngine,
    *,
    org: Organization,
    location: StorageLocation,
    template_id: UUID,
    quantity: str,
) -> None:
    """One record on the shelf, through the items service.

    The record lands on the card the template names — ``put_on_shelf``
    asserts the card match — so the quant the capacity math reads is the
    bridge's, standing behind a real record.
    """
    template = db_session.get(ProductTemplate, template_id)
    assert template is not None
    _sow(db_session, engine, org, template, location.id, quantity)
    db_session.commit()


def _categorised_item(
    db_session: Session,
    org: Organization,
    like: StorageLocation,
    category_id: Any,
    template_id: UUID | None = None,
) -> Item:
    item = Item(
        name=f'PAW5 {uuid4().hex[:6]}',
        organization_id=org.id,
        storage_location_id=like.id,
        quantity=Decimal('0'),
        category_id=category_id.id,
        template_id=template_id,
    )
    db_session.add(item)
    anchor_pending_records(db_session)
    db_session.commit()
    db_session.refresh(item)
    return item


def _confirmed_in(
    client: TestClient,
    headers: dict[str, str],
    *,
    partner: Partner,
    target_location: StorageLocation,
    item: Item,
    lines: list[dict[str, object]] | None = None,
) -> str:
    resp = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'IN',
            'partner_id': str(partner.id),
            'target_location_id': str(target_location.id),
            'lines': lines or [{'item_id': str(item.id), 'expected_quantity': 10}],
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
class TestPutawayRuleLocationList:
    def test_overflow_moves_to_the_second_shelf(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_org: Organization,
        doc_user: User,
    ) -> None:
        """First shelf full (190/200), delivery of 30 → the second shelf."""
        from app.core.testing import ModuleTestHelper

        h = ModuleTestHelper(db_session)
        category = _make_category(db_session, doc_org, f'PAW5 {uuid4().hex[:6]}')
        template = h.create_template(doc_org, name=f'PAW5 {uuid4().hex[:6]}')
        first = _make_location(
            db_session, doc_org, doc_target_location, doc_user, 'PAW5 First'
        )
        second = _make_location(
            db_session, doc_org, doc_target_location, doc_user, 'PAW5 Second'
        )
        _rule_with_locations(
            client, doc_auth_headers, category_id=category, location_ids=[first, second]
        )
        _put_capacity(
            client,
            doc_auth_headers,
            location_id=first,
            template_id=template.id,
            max_quantity='200',
        )
        # 190 already on the first shelf.
        _stock_shelf(
            db_session,
            async_engine_fixture,
            org=doc_org,
            location=first,
            template_id=template.id,
            quantity='190',
        )

        item = _categorised_item(
            db_session, doc_org, doc_target_location, category, template.id
        )
        doc_id = _confirmed_in(
            client,
            doc_auth_headers,
            partner=doc_partner,
            target_location=doc_target_location,
            item=item,
            lines=[{'item_id': str(item.id), 'expected_quantity': 30}],
        )
        read = client.get(
            f'/api/v1/warehouse/documents/{doc_id}', headers=doc_auth_headers
        )
        line = read.json()['lines'][0]
        assert line['planned_location_id'] == str(second.id), line
        assert line['planned_source'] == 'rule'

        complete = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert complete.status_code == status.HTTP_200_OK, complete.text
        db_session.expire_all()
        landed = db_session.scalar(
            select(Item).where(
                Item.organization_id == doc_org.id,
                Item.storage_location_id == second.id,
                Item.template_id == template.id,
            )
        )
        assert landed is not None

    def test_two_lines_of_one_document_count_together(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_org: Organization,
        doc_user: User,
    ) -> None:
        """170 on the shelf, capacity 200, two lines of 30.

        Counted apart, each line sees 170 + 30 = 200 and "fits", so both
        pile onto one shelf. Counted together, the first fills it to exactly
        200 and the second — 170 + 30 + 30 = 230 — moves on to the next.
        The test fails on the line it is meant to catch: the one that
        forgets what earlier lines of the same document already sent.

        The numbers are load-bearing, and this docstring used to say 180.
        At 180 the first line alone would overflow and be sent on, and the
        test would stop telling the two readings apart at all."""
        from app.core.testing import ModuleTestHelper

        h = ModuleTestHelper(db_session)
        category = _make_category(db_session, doc_org, f'PAW5 b {uuid4().hex[:6]}')
        template = h.create_template(doc_org, name=f'PAW5 b {uuid4().hex[:6]}')
        first = _make_location(
            db_session, doc_org, doc_target_location, doc_user, 'PAW5 B First'
        )
        second = _make_location(
            db_session, doc_org, doc_target_location, doc_user, 'PAW5 B Second'
        )
        _rule_with_locations(
            client, doc_auth_headers, category_id=category, location_ids=[first, second]
        )
        _put_capacity(
            client,
            doc_auth_headers,
            location_id=first,
            template_id=template.id,
            max_quantity='200',
        )
        _stock_shelf(
            db_session,
            async_engine_fixture,
            org=doc_org,
            location=first,
            template_id=template.id,
            quantity='170',
        )

        item = _categorised_item(
            db_session, doc_org, doc_target_location, category, template.id
        )
        doc_id = _confirmed_in(
            client,
            doc_auth_headers,
            partner=doc_partner,
            target_location=doc_target_location,
            item=item,
            lines=[
                {'item_id': str(item.id), 'expected_quantity': 30},
                {'item_id': str(item.id), 'expected_quantity': 30},
            ],
        )
        read = client.get(
            f'/api/v1/warehouse/documents/{doc_id}', headers=doc_auth_headers
        )
        lines = read.json()['lines']
        planned = [line['planned_location_id'] for line in lines]
        assert planned[0] == str(first.id)
        assert planned[1] == str(second.id)

    def test_single_product_shelf_with_other_stock_is_skipped(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_org: Organization,
        doc_user: User,
    ) -> None:
        """A single-product shelf already holding another product never
        fits, capacity or not — the resolver moves on to the next one."""
        from app.core.testing import ModuleTestHelper

        h = ModuleTestHelper(db_session)
        category = _make_category(db_session, doc_org, f'PAW5 c {uuid4().hex[:6]}')
        template = h.create_template(doc_org, name=f'PAW5 c {uuid4().hex[:6]}')
        first = _make_location(
            db_session, doc_org, doc_target_location, doc_user, 'PAW5 C First'
        )
        second = _make_location(
            db_session, doc_org, doc_target_location, doc_user, 'PAW5 C Second'
        )
        _rule_with_locations(
            client, doc_auth_headers, category_id=category, location_ids=[first, second]
        )
        client.put(
            f'/api/v1/warehouse/putaway/capacity-settings/{first.id}',
            headers=doc_auth_headers,
            json={'single_product': True},
        )
        other_template = h.create_template(
            doc_org, name=f'PAW5 c other {uuid4().hex[:6]}'
        )
        _stock_shelf(
            db_session,
            async_engine_fixture,
            org=doc_org,
            location=first,
            template_id=other_template.id,
            quantity='5',
        )

        item = _categorised_item(
            db_session, doc_org, doc_target_location, category, template.id
        )
        doc_id = _confirmed_in(
            client,
            doc_auth_headers,
            partner=doc_partner,
            target_location=doc_target_location,
            item=item,
        )
        read = client.get(
            f'/api/v1/warehouse/documents/{doc_id}', headers=doc_auth_headers
        )
        line = read.json()['lines'][0]
        assert line['planned_location_id'] == str(second.id)

    def test_no_fit_plans_first_shelf_with_over_capacity(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_org: Organization,
        doc_user: User,
    ) -> None:
        """Every shelf full: the plan names the first shelf, marked, with
        the numbers — and execution is not blocked by the warning."""
        from app.core.testing import ModuleTestHelper

        h = ModuleTestHelper(db_session)
        category = _make_category(db_session, doc_org, f'PAW5 d {uuid4().hex[:6]}')
        template = h.create_template(doc_org, name=f'PAW5 d {uuid4().hex[:6]}')
        first = _make_location(
            db_session, doc_org, doc_target_location, doc_user, 'PAW5 D First'
        )
        second = _make_location(
            db_session, doc_org, doc_target_location, doc_user, 'PAW5 D Second'
        )
        _rule_with_locations(
            client, doc_auth_headers, category_id=category, location_ids=[first, second]
        )
        for loc in (first, second):
            _put_capacity(
                client,
                doc_auth_headers,
                location_id=loc,
                template_id=template.id,
                max_quantity='20',
            )
            _stock_shelf(
                db_session,
                async_engine_fixture,
                org=doc_org,
                location=loc,
                template_id=template.id,
                quantity='20',
            )

        item = _categorised_item(
            db_session, doc_org, doc_target_location, category, template.id
        )
        doc_id = _confirmed_in(
            client,
            doc_auth_headers,
            partner=doc_partner,
            target_location=doc_target_location,
            item=item,
        )
        read = client.get(
            f'/api/v1/warehouse/documents/{doc_id}', headers=doc_auth_headers
        )
        line = read.json()['lines'][0]
        assert line['planned_location_id'] == str(first.id)
        assert line['planned_over_capacity'] is True
        assert Decimal(line['planned_capacity_used']) == Decimal('20')
        assert Decimal(line['planned_capacity_max']) == Decimal('20')

        # The goods have already arrived: the warning books them anyway.
        complete = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert complete.status_code == status.HTTP_200_OK, complete.text

    def test_rule_save_rejects_an_empty_location_list(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
    ) -> None:
        resp = client.post(
            '/api/v1/warehouse/putaway-rules',
            headers=doc_auth_headers,
            json={'category_id': str(uuid4()), 'location_ids': []},
        )
        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT, resp.text

    def test_rule_update_reorders_kept_locations(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        db_session: Session,
        doc_org: Organization,
        doc_user: User,
    ) -> None:
        """Saving an existing rule whose new list keeps its own shelves —
        the reorder shape — replaces the collection without tripping the
        (rule, location) unique constraint."""
        second = _make_location(
            db_session,
            doc_org,
            doc_target_location,
            doc_user,
            f'PAW5 L2 {uuid4().hex[:6]}',
        )
        category = _make_category(db_session, doc_org, f'PAW5 r {uuid4().hex[:6]}')
        rule = _rule_with_locations(
            client,
            doc_auth_headers,
            category_id=category,
            location_ids=[doc_target_location, second],
        )
        resp = client.put(
            f'/api/v1/warehouse/putaway-rules/{rule["id"]}',
            headers=doc_auth_headers,
            json={'location_ids': [str(second.id), str(doc_target_location.id)]},
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        assert [loc['location_id'] for loc in resp.json()['locations']] == [
            str(second.id),
            str(doc_target_location.id),
        ]

    def test_rule_update_appends_a_location(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        db_session: Session,
        doc_org: Organization,
        doc_user: User,
    ) -> None:
        second = _make_location(
            db_session,
            doc_org,
            doc_target_location,
            doc_user,
            f'PAW5 L2 {uuid4().hex[:6]}',
        )
        category = _make_category(db_session, doc_org, f'PAW5 a {uuid4().hex[:6]}')
        rule = _rule_with_locations(
            client,
            doc_auth_headers,
            category_id=category,
            location_ids=[doc_target_location],
        )
        resp = client.put(
            f'/api/v1/warehouse/putaway-rules/{rule["id"]}',
            headers=doc_auth_headers,
            json={'location_ids': [str(doc_target_location.id), str(second.id)]},
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        assert [loc['location_id'] for loc in resp.json()['locations']] == [
            str(doc_target_location.id),
            str(second.id),
        ]

    def test_rule_update_removes_a_location(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        db_session: Session,
        doc_org: Organization,
        doc_user: User,
    ) -> None:
        second = _make_location(
            db_session,
            doc_org,
            doc_target_location,
            doc_user,
            f'PAW5 L2 {uuid4().hex[:6]}',
        )
        category = _make_category(db_session, doc_org, f'PAW5 d {uuid4().hex[:6]}')
        rule = _rule_with_locations(
            client,
            doc_auth_headers,
            category_id=category,
            location_ids=[doc_target_location, second],
        )
        resp = client.put(
            f'/api/v1/warehouse/putaway-rules/{rule["id"]}',
            headers=doc_auth_headers,
            json={'location_ids': [str(doc_target_location.id)]},
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        assert [loc['location_id'] for loc in resp.json()['locations']] == [
            str(doc_target_location.id)
        ]
        read = client.get(
            f'/api/v1/warehouse/putaway-rules/{rule["id"]}', headers=doc_auth_headers
        )
        assert read.status_code == status.HTTP_200_OK, read.text
        assert [loc['location_id'] for loc in read.json()['locations']] == [
            str(doc_target_location.id)
        ]

    def test_legacy_single_target_creates_a_one_element_list(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        db_session: Session,
        doc_org: Organization,
    ) -> None:
        """The one-shelf field still works — it reads as a list of one, so
        existing callers keep speaking the old shape."""
        from app.core.testing import ModuleTestHelper

        ModuleTestHelper(db_session)
        category = _make_category(db_session, doc_org, f'PAW5 e {uuid4().hex[:6]}')
        resp = client.post(
            '/api/v1/warehouse/putaway-rules',
            headers=doc_auth_headers,
            json={
                'category_id': str(category.id),
                'target_location_id': str(doc_target_location.id),
            },
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        rule = resp.json()
        assert [loc['location_id'] for loc in rule['locations']] == [
            str(doc_target_location.id)
        ]
        assert rule['target_location_id'] == str(doc_target_location.id)

    def test_one_shelf_without_a_cap_behaves_exactly_as_before_the_list(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        db_session: Session,
        doc_org: Organization,
        doc_user: User,
    ) -> None:
        """The regression the shelf list owes the organizations that never
        asked for it.

        Almost every rule in the world is one shelf with no capacity entry.
        Nothing in this file measured that case end to end: the list tests
        all give a rule two shelves and a limit, and the one-shelf test that
        exists checks the API's shape, never the resolver. So the promise
        "a rule with a single uncapped shelf behaves exactly as it did" was
        carried only by the old suite, which nobody would think to re-read
        while changing this one.

        Here it is, asserted: the plan names the shelf with source ``rule``,
        carries no over-capacity mark and no numbers to read one from, and
        the goods land there.
        """
        from app.core.testing import ModuleTestHelper

        h = ModuleTestHelper(db_session)
        category = _make_category(db_session, doc_org, f'PAW12 r {uuid4().hex[:6]}')
        template = h.create_template(doc_org, name=f'PAW12 r {uuid4().hex[:6]}')
        only = _make_location(
            db_session, doc_org, doc_target_location, doc_user, 'PAW12 Only Shelf'
        )
        _rule_with_locations(
            client,
            doc_auth_headers,
            category_id=category,
            location_ids=[only],
        )
        item = _categorised_item(
            db_session, doc_org, doc_target_location, category, template.id
        )
        doc_id = _confirmed_in(
            client,
            doc_auth_headers,
            partner=doc_partner,
            target_location=doc_target_location,
            item=item,
        )

        read = client.get(
            f'/api/v1/warehouse/documents/{doc_id}', headers=doc_auth_headers
        )
        line = read.json()['lines'][0]
        assert line['planned_location_id'] == str(only.id)
        assert line['planned_source'] == 'rule'
        # No capacity anywhere near this shelf: nothing to be over, and no
        # pair for a reader to mistake for one.
        assert not line['planned_over_capacity']
        assert line['planned_capacity_max'] is None

        complete = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert complete.status_code == status.HTTP_200_OK, complete.text
        after = client.get(
            f'/api/v1/warehouse/documents/{doc_id}', headers=doc_auth_headers
        )
        assert after.json()['lines'][0]['executed_location_id'] == str(only.id)
