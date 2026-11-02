"""A delivery opens its record where the product already lives.

The receipt executor called ``items.create`` without a category, so the
record it opened stood outside the category filter while the product's
earlier records stood inside it: the delivery was on the shelf, absent
from every count and search by category, and nothing said so.

The executor inherits the filing the same way the transfer inherits the
fields of the record it splits: the record the line named answers first,
and with none named, the category the product's own records carry.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.category import Category
from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.storage_location import StorageLocation
from tests.integration._shelf import post_on_shelf

pytestmark = pytest.mark.integration


def _category(db: Session, org: Organization, name: str) -> Category:
    category = Category(organization_id=org.id, name=name)
    db.add(category)
    db.commit()
    db.refresh(category)
    return category


def _deliver(
    client: TestClient,
    headers: dict[str, str],
    *,
    partner: Partner,
    target: StorageLocation,
    line: dict[str, Any],
) -> None:
    resp = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'IN',
            'partner_id': str(partner.id),
            'target_location_id': str(target.id),
            'lines': [line],
        },
    )
    assert resp.status_code == 201, resp.text
    doc_id = resp.json()['id']
    confirm = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=headers
    )
    assert confirm.status_code == 200, confirm.text
    complete = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/complete',
        headers=headers,
        json={'complete_as_planned': True},
    )
    assert complete.status_code == 200, complete.text


def _records_on(
    db: Session, org_id: UUID, template_id: UUID, location_id: UUID
) -> list[Item]:
    return list(
        db.scalars(
            select(Item).where(
                Item.organization_id == org_id,
                Item.template_id == template_id,
                Item.storage_location_id == location_id,
                Item.is_deleted.is_(False),
            )
        ).all()
    )


@pytest.mark.integration
class TestReceivedRecordInheritsTheCategory:
    def test_a_delivery_of_a_filed_product_is_filed_the_same_way(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_partner: Partner,
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        db_session: Session,
        h: Any,
    ) -> None:
        """The product's records carry a category; the delivery opens its
        record under the same one, so the category filter sees it."""
        category = _category(db_session, doc_org, f'receipt-cat-{uuid4().hex[:6]}')
        template = h.create_template(doc_org, name=f'receipt-prod-{uuid4().hex[:6]}')
        standing = post_on_shelf(
            client, doc_auth_headers, template, doc_source_location.id, '10'
        )
        item = db_session.get(Item, UUID(standing['id']))
        assert item is not None
        item.category_id = category.id
        db_session.commit()

        _deliver(
            client,
            doc_auth_headers,
            partner=doc_partner,
            target=doc_target_location,
            line={'product_template_id': str(template.id), 'expected_quantity': 4},
        )

        opened = _records_on(
            db_session, doc_org.id, template.id, doc_target_location.id
        )
        assert len(opened) == 1, 'the delivery opens exactly one record on its shelf'
        assert opened[0].category_id == category.id, (
            'the delivery is filed where the product already lives'
        )

    def test_a_line_naming_a_record_follows_that_records_filing(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_partner: Partner,
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        db_session: Session,
        h: Any,
    ) -> None:
        """The record the line names answers first: the delivery is filed
        where the goods' record stands, even when the product's other
        records were filed elsewhere."""
        named_category = _category(db_session, doc_org, f'named-cat-{uuid4().hex[:6]}')
        other_category = _category(db_session, doc_org, f'other-cat-{uuid4().hex[:6]}')
        template = h.create_template(doc_org, name=f'named-prod-{uuid4().hex[:6]}')
        named = post_on_shelf(
            client, doc_auth_headers, template, doc_source_location.id, '10'
        )
        named_item = db_session.get(Item, UUID(named['id']))
        assert named_item is not None
        named_item.category_id = named_category.id
        db_session.commit()

        for _ in range(2):
            later = post_on_shelf(
                client, doc_auth_headers, template, doc_source_location.id, '1'
            )
            item = db_session.get(Item, UUID(later['id']))
            assert item is not None
            item.category_id = other_category.id
            db_session.commit()

        _deliver(
            client,
            doc_auth_headers,
            partner=doc_partner,
            target=doc_target_location,
            line={'item_id': str(named_item.id), 'expected_quantity': 4},
        )

        opened = _records_on(
            db_session, doc_org.id, template.id, doc_target_location.id
        )
        assert len(opened) == 1
        assert opened[0].category_id == named_category.id, (
            'the record the line named answers before the product majority'
        )
