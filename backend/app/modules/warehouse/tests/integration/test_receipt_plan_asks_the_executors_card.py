"""The plan of a receipt line asks the planner the card the executor asks.

The executor settles which product card a line stands for before it asks the
planner where the goods go: the line's own, its record's, the one a record
without a card adopts, and — once the receipt is confirmed — the one a bare
barcode names. The plan shown beforehand (the one-screen preview, the read of
a draft, the count of receipts waiting for space) used to ask with only the
first two, so a card whose putaway rule was the whole answer showed the
document's shelf and the goods reached the rule's.
"""

from __future__ import annotations

from typing import cast
from uuid import uuid4

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.category import Category
from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.user import User

from .test_putaway_rule_location_list import _put_capacity, _stock_shelf
from .test_putaway_rules import _create_putaway
from .test_receipt_planned_location import _make_location


def _ruled_card(
    client: TestClient,
    headers: dict[str, str],
    db_session: Session,
    doc_org: Organization,
    doc_target_location: StorageLocation,
    doc_user: User,
    tag: str,
    *,
    barcode: str | None = None,
) -> tuple[ProductTemplate, StorageLocation]:
    """A card whose putaway rule sends it to a shelf of its own."""
    rule_loc = _make_location(
        db_session, doc_org, doc_target_location, doc_user, f'{tag} Rule Shelf'
    )
    template = ModuleTestHelper(db_session).create_template(
        doc_org, name=f'{tag} {uuid4().hex[:6]}', barcode=barcode
    )
    _create_putaway(
        client,
        headers,
        product_template_id=str(template.id),
        target_location_id=str(rule_loc.id),
    )
    return template, rule_loc


def _post_in(
    client: TestClient,
    headers: dict[str, str],
    partner: Partner,
    target: StorageLocation,
    line: dict[str, object],
) -> dict[str, object]:
    resp = client.post(
        '/api/v1/warehouse/documents/post',
        headers=headers,
        json={
            'type': 'IN',
            'partner_id': str(partner.id),
            'target_location_id': str(target.id),
            'lines': [line],
        },
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    return cast(dict[str, object], resp.json()['lines'][0])


@pytest.mark.integration
class TestReceiptPlanAsksTheExecutorsCard:
    def test_preview_of_a_record_without_a_card_names_the_adopted_cards_shelf(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        db_session: Session,
        doc_org: Organization,
        doc_user: User,
    ) -> None:
        """The record adopts the card of its name; the preview says so too."""
        template, rule_loc = _ruled_card(
            client,
            doc_auth_headers,
            db_session,
            doc_org,
            doc_target_location,
            doc_user,
            'RPC1',
        )
        record = Item(
            name=template.name,
            organization_id=doc_org.id,
            template_id=None,
            storage_location_id=doc_target_location.id,
            quantity=1,
        )
        db_session.add(record)
        db_session.commit()
        db_session.refresh(record)

        preview = client.post(
            '/api/v1/warehouse/putaway/preview',
            headers=doc_auth_headers,
            json={
                'target_location_id': str(doc_target_location.id),
                'lines': [{'item_id': str(record.id), 'quantity': 2}],
            },
        )
        assert preview.status_code == status.HTTP_200_OK, preview.text
        planned = preview.json()[0]
        assert planned['planned_location_id'] == str(rule_loc.id)
        assert planned['planned_source'] == 'rule'

        executed = _post_in(
            client,
            doc_auth_headers,
            doc_partner,
            doc_target_location,
            {'item_id': str(record.id), 'expected_quantity': 2},
        )
        assert executed['executed_location_id'] == planned['planned_location_id']

    def test_draft_line_with_only_a_barcode_is_planned_on_the_cards_shelf(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        db_session: Session,
        doc_org: Organization,
        doc_user: User,
    ) -> None:
        """Confirming settles the code onto the card; the draft already knows."""
        code = f'RPC2{uuid4().int % 10**9:09d}'
        _template, rule_loc = _ruled_card(
            client,
            doc_auth_headers,
            db_session,
            doc_org,
            doc_target_location,
            doc_user,
            'RPC2',
            barcode=code,
        )
        created = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [{'name': 'Scanned', 'barcode': code, 'expected_quantity': 3}],
            },
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        doc_id = created.json()['id']

        draft = client.get(
            f'/api/v1/warehouse/documents/{doc_id}', headers=doc_auth_headers
        )
        assert draft.status_code == status.HTTP_200_OK, draft.text
        planned = draft.json()['lines'][0]
        assert planned['planned_location_id'] == str(rule_loc.id)

        confirm = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        assert confirm.status_code == status.HTTP_200_OK, confirm.text
        complete = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert complete.status_code == status.HTTP_200_OK, complete.text
        assert (
            complete.json()['lines'][0]['executed_location_id']
            == planned['planned_location_id']
        )

    def test_the_full_shelf_count_reads_a_barcode_line_by_its_card(
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
        """A draft line known only by its code counts against its card's shelf."""
        code = f'RPC4{uuid4().int % 10**9:09d}'
        template, rule_loc = _ruled_card(
            client,
            doc_auth_headers,
            db_session,
            doc_org,
            doc_target_location,
            doc_user,
            'RPC4',
            barcode=code,
        )
        _put_capacity(
            client,
            doc_auth_headers,
            location_id=rule_loc,
            template_id=template.id,
            max_quantity='20',
        )
        _stock_shelf(
            db_session,
            async_engine_fixture,
            org=doc_org,
            location=rule_loc,
            template_id=template.id,
            quantity='20',
        )
        created = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [{'name': 'Scanned', 'barcode': code, 'expected_quantity': 3}],
            },
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text

        read = client.get(
            f'/api/v1/warehouse/putaway/occupancy/{doc_target_location.id}',
            headers=doc_auth_headers,
        )
        assert read.status_code == status.HTTP_200_OK, read.text
        stuck = [
            s
            for s in read.json()['signals']
            if s['code'] == 'receipt_lines_without_space'
        ]
        assert [s['count'] for s in stuck] == [1]


@pytest.mark.integration
class TestEquipmentCategoryReceipt:
    def test_a_receipt_of_equipment_category_stock_opens_an_available_asset(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        db_session: Session,
        doc_org: Organization,
        doc_user: User,
    ) -> None:
        """The record a receipt opens in an equipment category is an asset.

        The assets list claims every record filed under an equipment-tagged
        category, so a receipt that opened one without the equipment
        namespace put an asset on the list with no status, shown as Unknown.
        """
        h = ModuleTestHelper(db_session)
        doc_org.enabled_modules = [*doc_org.enabled_modules, 'equipment']
        category = Category(
            name=f'RPC3 Laptops {uuid4().hex[:6]}',
            code=f'RPC3{uuid4().hex[:6]}',
            context_tag='equipment',
            organization_id=doc_org.id,
            field_definitions=[],
        )
        db_session.add(category)
        db_session.commit()
        template = h.create_template(doc_org, name=f'RPC3 {uuid4().hex[:6]}')
        _post_in(
            client,
            doc_auth_headers,
            doc_partner,
            doc_target_location,
            {'product_template_id': str(template.id), 'expected_quantity': 1},
        )
        first = db_session.scalars(
            select(Item).where(Item.template_id == template.id)
        ).one()
        first.category_id = category.id
        first.meta_data = {'equipment': {'equipment_status': 'AVAILABLE'}}
        db_session.commit()
        other_shelf = _make_location(
            db_session, doc_org, doc_target_location, doc_user, 'RPC3 Other Shelf'
        )

        _post_in(
            client,
            doc_auth_headers,
            doc_partner,
            doc_target_location,
            {
                'product_template_id': str(template.id),
                'expected_quantity': 2,
                'target_location_id': str(other_shelf.id),
            },
        )

        db_session.expire_all()
        opened = db_session.scalars(
            select(Item).where(Item.template_id == template.id, Item.id != first.id)
        ).one()
        assert opened.category_id == category.id
        assert (opened.meta_data or {}).get('equipment', {}).get(
            'equipment_status'
        ) == 'AVAILABLE'
