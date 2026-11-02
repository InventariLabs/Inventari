"""
Integration tests for Putaway rules.

Each PutawayRule says: when receiving product P (or category C, or
context_tag X, or storage_type_code Y), auto-place at target_location
instead of the document's explicit target_location_id. Resolution
priority: product_template > category > context_tag > storage_type_code,
then by ``priority`` ascending (lower wins), then by created_at desc
(most recent wins on tie).

Tests:
- No rule: receipt lands at doc.target_location_id (default behaviour)
- Product rule: receipt lands at rule.target_location_id, NOT at doc target
- Category rule: matches via item.category_id → Category
- Priority ordering: most specific match wins
- Inactive rules: ignored even if matching
"""

from __future__ import annotations

from decimal import Decimal
from typing import cast
from uuid import UUID, uuid4

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.category import Category
from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.user import User
from tests.integration._shelf import anchor_pending_records


def _create_putaway(
    client: TestClient,
    headers: dict[str, str],
    *,
    product_template_id: str | None = None,
    category_id: str | None = None,
    context_tag: str | None = None,
    storage_type_code: str | None = None,
    target_location_id: str,
    priority: int = 100,
) -> dict[str, object]:
    payload: dict[str, object] = {
        'target_location_id': target_location_id,
        'priority': priority,
    }
    if product_template_id is not None:
        payload['product_template_id'] = product_template_id
    if category_id is not None:
        payload['category_id'] = category_id
    if context_tag is not None:
        payload['context_tag'] = context_tag
    if storage_type_code is not None:
        payload['location_type_code'] = storage_type_code
    resp = client.post(
        '/api/v1/warehouse/putaway-rules',
        headers=headers,
        json=payload,
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    return cast(dict[str, object], resp.json())


def _create_in(
    client: TestClient,
    headers: dict[str, str],
    *,
    partner_id: UUID,
    target_location_id: UUID,
    template_id: UUID,
    quantity: int,
) -> None:
    resp = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'IN',
            'partner_id': str(partner_id),
            'target_location_id': str(target_location_id),
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
    complete = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/complete',
        headers=headers,
        json={'complete_as_planned': True},
    )
    assert complete.status_code == status.HTTP_200_OK, complete.text


@pytest.mark.integration
class TestPutawayRulesResolution:
    """Service-level: receipt's target location resolves via active rules."""

    def test_receipt_without_rule_uses_doc_target(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        db_session: Session,
        doc_org: Organization,
    ) -> None:
        """No rule → receipt lands at doc.target_location_id (default)."""
        from app.core.testing import ModuleTestHelper

        h = ModuleTestHelper(db_session)
        template = h.create_template(doc_org, name=f'Putaway Default {uuid4().hex[:6]}')

        _create_in(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            target_location_id=doc_target_location.id,
            template_id=template.id,
            quantity=5,
        )

        # The newly created Item should live at doc_target_location.
        item = db_session.scalars(
            select(Item).where(Item.template_id == template.id)
        ).first()
        assert item is not None
        assert item.storage_location_id == doc_target_location.id

    def test_receipt_with_product_rule_overrides_doc_target(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        db_session: Session,
        doc_org: Organization,
        doc_user: User,
    ) -> None:
        """Product-level rule wins over the document's target_location_id."""
        from app.core.testing import ModuleTestHelper

        h = ModuleTestHelper(db_session)

        # Second location in the same org.
        other_loc = StorageLocation(
            organization_id=doc_org.id,
            storage_type_id=doc_source_location.storage_type_id,
            created_by=doc_user.id,
            name='Putaway Product Target',
        )
        db_session.add(other_loc)
        db_session.commit()
        db_session.refresh(other_loc)

        template = h.create_template(doc_org, name=f'Putaway Product {uuid4().hex[:6]}')
        _create_putaway(
            client,
            doc_auth_headers,
            product_template_id=str(template.id),
            target_location_id=str(other_loc.id),
        )

        # Doc target_location is doc_target_location; rule says OTHER.
        _create_in(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            target_location_id=doc_target_location.id,
            template_id=template.id,
            quantity=3,
        )

        item = db_session.scalars(
            select(Item).where(Item.template_id == template.id)
        ).first()
        assert item is not None
        # Rule wins: item lives at OTHER, not at doc_target_location.
        assert item.storage_location_id == other_loc.id

    def test_receipt_with_category_rule_matches(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        db_session: Session,
        doc_org: Organization,
        doc_user: User,
    ) -> None:
        """Category-level rule matches via item.category_id.

        DocumentLine schema doesn't carry ``category_id`` — the
        category on the line is inferred from the item being received.
        This test pre-creates an Item with category_id set, then sends
        an IN document with that item's id on the line so the
        existing-item branch of the receipt executor can match the rule.
        """
        from app.core.testing import ModuleTestHelper

        h = ModuleTestHelper(db_session)

        other_loc = StorageLocation(
            organization_id=doc_org.id,
            storage_type_id=doc_target_location.storage_type_id,
            created_by=doc_user.id,
            name='Putaway Category Target',
        )
        db_session.add(other_loc)
        db_session.commit()
        db_session.refresh(other_loc)

        category = Category(
            organization_id=doc_org.id,
            name=f'Cat Putaway {uuid4().hex[:6]}',
        )
        db_session.add(category)
        db_session.commit()
        db_session.refresh(category)

        template = h.create_template(doc_org, name=f'Putaway Cat {uuid4().hex[:6]}')

        _create_putaway(
            client,
            doc_auth_headers,
            category_id=str(category.id),
            target_location_id=str(other_loc.id),
        )

        pre_item = Item(
            organization_id=doc_org.id,
            storage_location_id=doc_target_location.id,
            category_id=category.id,
            template_id=template.id,
            name=f'CatPre {uuid4().hex[:6]}',
            quantity=Decimal('5'),
        )
        db_session.add(pre_item)
        anchor_pending_records(db_session)
        db_session.commit()
        db_session.refresh(pre_item)

        # Receive to bump the item; existing-item branch hits putaway.
        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'item_id': str(pre_item.id),
                        'product_template_id': str(template.id),
                        'expected_quantity': 2,
                    }
                ],
            },
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        doc_id = cast(str, resp.json()['id'])
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

        db_session.refresh(pre_item)
        # Category rule wins → the goods live at OTHER (putaway_loc), not
        # at doc_target_location. The rule is about the goods, so the
        # record follows them: a delivery steered here opens a record at
        # the rule's location rather than topping up one standing
        # elsewhere, and the stock and the record name the same shelf.
        from app.core.testing import ShelfRow

        shelf = db_session.scalars(
            select(ShelfRow).where(
                ShelfRow.organization_id == doc_org.id,
                ShelfRow.product_template_id == template.id,
                ShelfRow.storage_location_id == other_loc.id,
            )
        ).first()
        assert shelf is not None
        assert shelf.quantity >= Decimal('2')

    def test_receipt_with_context_tag_rule_matches(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        db_session: Session,
        doc_org: Organization,
        doc_user: User,
    ) -> None:
        """a context_tag rule matches via the item's Category.context_tag.

        The receipt executor used to pass category_context_tag=None, so such
        a rule could never fire.
        """
        from app.core.testing import ModuleTestHelper

        h = ModuleTestHelper(db_session)

        other_loc = StorageLocation(
            organization_id=doc_org.id,
            storage_type_id=doc_target_location.storage_type_id,
            created_by=doc_user.id,
            name='Putaway Context Target',
        )
        db_session.add(other_loc)
        db_session.commit()
        db_session.refresh(other_loc)

        context_tag = f'cold-{uuid4().hex[:6]}'
        category = Category(
            organization_id=doc_org.id,
            name=f'Cat Tag {uuid4().hex[:6]}',
            context_tag=context_tag,
        )
        db_session.add(category)
        db_session.commit()
        db_session.refresh(category)

        template = h.create_template(doc_org, name=f'Putaway Tag {uuid4().hex[:6]}')

        _create_putaway(
            client,
            doc_auth_headers,
            context_tag=context_tag,
            target_location_id=str(other_loc.id),
        )

        pre_item = Item(
            organization_id=doc_org.id,
            storage_location_id=doc_target_location.id,
            category_id=category.id,
            template_id=template.id,
            name=f'TagPre {uuid4().hex[:6]}',
            quantity=Decimal('5'),
        )
        db_session.add(pre_item)
        anchor_pending_records(db_session)
        db_session.commit()
        db_session.refresh(pre_item)

        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'item_id': str(pre_item.id),
                        'product_template_id': str(template.id),
                        'expected_quantity': 2,
                    }
                ],
            },
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        doc_id = cast(str, resp.json()['id'])
        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        complete = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert complete.status_code == status.HTTP_200_OK, complete.text

        from app.core.testing import ShelfRow

        shelf = db_session.scalars(
            select(ShelfRow).where(
                ShelfRow.organization_id == doc_org.id,
                ShelfRow.product_template_id == template.id,
                ShelfRow.storage_location_id == other_loc.id,
            )
        ).first()
        assert shelf is not None
        assert shelf.quantity >= Decimal('2')

    def test_receipt_with_storage_type_code_rule_matches(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        db_session: Session,
        doc_org: Organization,
        doc_user: User,
        doc_storage_type: StorageType,
    ) -> None:
        """a storage_type_code rule matches via the doc target's type.

        The receipt executor used to pass storage_type_code=None, so such a
        rule could never fire.
        """
        from app.core.testing import ModuleTestHelper

        h = ModuleTestHelper(db_session)

        other_loc = StorageLocation(
            organization_id=doc_org.id,
            storage_type_id=doc_target_location.storage_type_id,
            created_by=doc_user.id,
            name='Putaway Type Target',
        )
        db_session.add(other_loc)
        db_session.commit()
        db_session.refresh(other_loc)

        template = h.create_template(doc_org, name=f'Putaway Typ {uuid4().hex[:6]}')

        _create_putaway(
            client,
            doc_auth_headers,
            storage_type_code=doc_storage_type.type_code,
            target_location_id=str(other_loc.id),
        )

        _create_in(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            target_location_id=doc_target_location.id,
            template_id=template.id,
            quantity=3,
        )

        item = db_session.scalars(
            select(Item).where(Item.template_id == template.id)
        ).first()
        assert item is not None
        assert item.storage_location_id == other_loc.id

    def test_multi_key_rule_matches_when_any_key_matches(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        db_session: Session,
        doc_org: Organization,
        doc_user: User,
        doc_storage_type: StorageType,
    ) -> None:
        """a rule with several keys behaves as an OR, not an AND.

        The rule carries both a category key and a storage_type_code key.
        The category matches the item, while the storage type does NOT match
        the document target's type — the rule must still fire.
        """
        from app.core.testing import ModuleTestHelper

        h = ModuleTestHelper(db_session)

        other_loc = StorageLocation(
            organization_id=doc_org.id,
            storage_type_id=doc_target_location.storage_type_id,
            created_by=doc_user.id,
            name='Multi Key Target',
        )
        db_session.add(other_loc)
        db_session.commit()
        db_session.refresh(other_loc)

        category = Category(
            organization_id=doc_org.id,
            name=f'Cat Multi {uuid4().hex[:6]}',
        )
        db_session.add(category)
        db_session.commit()
        db_session.refresh(category)

        # A second storage type: valid for save-time validation, but NOT the
        # type of the document's target location.
        freezer_type = h.create_storage_type(
            'Freezer', 'FREEZER', organization_id=doc_org.id
        )

        template = h.create_template(doc_org, name=f'MultiKey {uuid4().hex[:6]}')

        _create_putaway(
            client,
            doc_auth_headers,
            category_id=str(category.id),
            storage_type_code=freezer_type.type_code,
            target_location_id=str(other_loc.id),
        )

        pre_item = Item(
            organization_id=doc_org.id,
            storage_location_id=doc_target_location.id,
            category_id=category.id,
            template_id=template.id,
            name=f'MultiPre {uuid4().hex[:6]}',
            quantity=Decimal('5'),
        )
        db_session.add(pre_item)
        anchor_pending_records(db_session)
        db_session.commit()
        db_session.refresh(pre_item)

        assert doc_target_location.storage_type_id != freezer_type.id

        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'item_id': str(pre_item.id),
                        'product_template_id': str(template.id),
                        'expected_quantity': 2,
                    }
                ],
            },
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        doc_id = cast(str, resp.json()['id'])
        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        complete = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert complete.status_code == status.HTTP_200_OK, complete.text

        # For an existing item, putaway manifests on the shelf: the received
        # stock lands at the rule's target, not the document's target.
        from app.core.testing import ShelfRow

        shelf = db_session.scalars(
            select(ShelfRow).where(
                ShelfRow.organization_id == doc_org.id,
                ShelfRow.product_template_id == template.id,
                ShelfRow.storage_location_id == other_loc.id,
            )
        ).first()
        assert shelf is not None
        assert shelf.quantity >= Decimal('2')

    def test_unknown_context_tag_rejected(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
    ) -> None:
        """a rule on a context tag that exists nowhere can never fire —
        reject it at save instead of accepting a dead rule.: the 400
               carries a readable message the UI can surface."""
        bogus_tag = f'TO-NIE-ISTNIEJE-{uuid4().hex[:6]}'
        resp = client.post(
            '/api/v1/warehouse/putaway-rules',
            headers=doc_auth_headers,
            json={
                'context_tag': bogus_tag,
                'target_location_id': str(doc_target_location.id),
            },
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        detail = resp.json()['detail']
        message = detail['message'] if isinstance(detail, dict) else detail
        assert bogus_tag in message
        # it names the value the user typed, not the column it failed
        # against — the message is for a warehouse worker, not a schema.
        assert 'context_tag' not in message.lower()

    def test_unknown_storage_type_code_rejected(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
    ) -> None:
        """a rule on a storage type code that exists nowhere can never
        fire — reject it at save instead of accepting a dead rule.: the
               400 carries a readable message the UI can surface."""
        bogus_code = f'ZMYSLONY-{uuid4().hex[:6]}'
        resp = client.post(
            '/api/v1/warehouse/putaway-rules',
            headers=doc_auth_headers,
            json={
                'location_type_code': bogus_code,
                'target_location_id': str(doc_target_location.id),
            },
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        detail = resp.json()['detail']
        message = detail['message'] if isinstance(detail, dict) else detail
        assert bogus_code in message
        assert 'storage type' in message.lower()

    def test_create_rule_with_valid_context_tag_returns_201(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        db_session: Session,
        doc_org: Organization,
    ) -> None:
        """the happy path of save-time key validation — a rule on an
        existing context tag is accepted and echoed back."""
        context_tag = f'cold-{uuid4().hex[:6]}'
        category = Category(
            organization_id=doc_org.id,
            name=f'Cat Save {uuid4().hex[:6]}',
            context_tag=context_tag,
        )
        db_session.add(category)
        db_session.commit()

        resp = client.post(
            '/api/v1/warehouse/putaway-rules',
            headers=doc_auth_headers,
            json={
                'context_tag': context_tag,
                'target_location_id': str(doc_target_location.id),
                'priority': 10,
            },
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        data = resp.json()
        assert data['context_tag'] == context_tag
        assert data['target_location_id'] == str(doc_target_location.id)
        assert data['priority'] == 10

    def test_priority_ordering_most_specific_wins(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        db_session: Session,
        doc_org: Organization,
        doc_user: User,
    ) -> None:
        """Product-level rule beats category-level rule.

        Both rules target different locations; product should win
        because it's more specific. The resolver picks the most specific
        match (product > category > context_tag > storage_type_code),
        independent of the ``priority`` column when specificity differs.
        """
        from app.core.testing import ModuleTestHelper

        h = ModuleTestHelper(db_session)

        product_loc = StorageLocation(
            organization_id=doc_org.id,
            storage_type_id=doc_target_location.storage_type_id,
            created_by=doc_user.id,
            name='Product Loc',
        )
        category_loc = StorageLocation(
            organization_id=doc_org.id,
            storage_type_id=doc_target_location.storage_type_id,
            created_by=doc_user.id,
            name='Category Loc',
        )
        db_session.add_all([product_loc, category_loc])
        db_session.commit()
        for loc in (product_loc, category_loc):
            db_session.refresh(loc)

        category = Category(
            organization_id=doc_org.id,
            name=f'Cat Pri {uuid4().hex[:6]}',
        )
        db_session.add(category)
        db_session.commit()
        db_session.refresh(category)

        template = h.create_template(doc_org, name=f'Pri {uuid4().hex[:6]}')

        # Category rule (less specific) at LOW priority
        _create_putaway(
            client,
            doc_auth_headers,
            category_id=str(category.id),
            target_location_id=str(category_loc.id),
            priority=10,
        )
        # Product rule (more specific) at HIGH priority
        _create_putaway(
            client,
            doc_auth_headers,
            product_template_id=str(template.id),
            target_location_id=str(product_loc.id),
            priority=999,
        )

        # Pre-create item with category so the existing-item branch
        # can match the category rule for the test setup.
        pre_item = Item(
            organization_id=doc_org.id,
            storage_location_id=doc_target_location.id,
            category_id=category.id,
            template_id=template.id,
            name=f'PriPre {uuid4().hex[:6]}',
            quantity=Decimal('1'),
        )
        db_session.add(pre_item)
        anchor_pending_records(db_session)
        db_session.commit()
        db_session.refresh(pre_item)

        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'item_id': str(pre_item.id),
                        'product_template_id': str(template.id),
                        'expected_quantity': 1,
                    }
                ],
            },
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        doc_id = cast(str, resp.json()['id'])
        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )

        from app.core.testing import ShelfRow

        # Product rule wins → stock at product_loc for the
        # template exists. Category rule would have placed it at
        # category_loc, so its absence proves the priority ordering.
        product_shelf = db_session.scalars(
            select(ShelfRow).where(
                ShelfRow.organization_id == doc_org.id,
                ShelfRow.product_template_id == template.id,
                ShelfRow.storage_location_id == product_loc.id,
            )
        ).first()
        assert product_shelf is not None
        category_shelf = db_session.scalars(
            select(ShelfRow).where(
                ShelfRow.organization_id == doc_org.id,
                ShelfRow.product_template_id == template.id,
                ShelfRow.storage_location_id == category_loc.id,
            )
        ).first()
        assert category_shelf is None

    def test_inactive_rule_ignored(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        db_session: Session,
        doc_org: Organization,
        doc_user: User,
    ) -> None:
        """is_active=False rules don't trigger — fallback to doc.target."""
        from app.core.testing import ModuleTestHelper

        h = ModuleTestHelper(db_session)

        inactive_loc = StorageLocation(
            organization_id=doc_org.id,
            storage_type_id=doc_target_location.storage_type_id,
            created_by=doc_user.id,
            name='Inactive Loc',
        )
        db_session.add(inactive_loc)
        db_session.commit()
        db_session.refresh(inactive_loc)

        template = h.create_template(doc_org, name=f'Inactive {uuid4().hex[:6]}')

        # Create rule then deactivate via PATCH.
        resp = client.post(
            '/api/v1/warehouse/putaway-rules',
            headers=doc_auth_headers,
            json={
                'product_template_id': str(template.id),
                'target_location_id': str(inactive_loc.id),
                'is_active': False,
            },
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text

        # IN lands at doc.target_location (rule ignored).
        _create_in(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            target_location_id=doc_target_location.id,
            template_id=template.id,
            quantity=1,
        )

        item = db_session.scalars(
            select(Item).where(Item.template_id == template.id)
        ).first()
        assert item is not None
        assert item.storage_location_id == doc_target_location.id


@pytest.mark.integration
class TestPutawayRulesDisplayNames:
    """List/get responses carry human-readable names for UUID references."""

    def test_list_and_get_include_display_names(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        db_session: Session,
        doc_org: Organization,
    ) -> None:
        from app.core.testing import ModuleTestHelper

        h = ModuleTestHelper(db_session)
        template = h.create_template(doc_org, name=f'Names {uuid4().hex[:6]}')
        category = Category(
            organization_id=doc_org.id,
            name=f'Cat Names {uuid4().hex[:6]}',
        )
        db_session.add(category)
        db_session.commit()
        db_session.refresh(category)

        created = _create_putaway(
            client,
            doc_auth_headers,
            product_template_id=str(template.id),
            category_id=str(category.id),
            target_location_id=str(doc_target_location.id),
        )
        assert created['product_template_name'] == template.name
        assert created['category_name'] == category.name
        assert created['target_location_name'] == doc_target_location.name

        listed = client.get('/api/v1/warehouse/putaway-rules', headers=doc_auth_headers)
        assert listed.status_code == status.HTTP_200_OK, listed.text
        row = next(r for r in listed.json()['items'] if r['id'] == created['id'])
        assert row['product_template_name'] == template.name
        assert row['category_name'] == category.name
        assert row['target_location_name'] == doc_target_location.name

        fetched = client.get(
            f'/api/v1/warehouse/putaway-rules/{created["id"]}',
            headers=doc_auth_headers,
        )
        assert fetched.status_code == status.HTTP_200_OK, fetched.text
        assert fetched.json()['product_template_name'] == template.name
        assert fetched.json()['target_location_name'] == doc_target_location.name

    def test_display_names_null_when_reference_missing(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        db_session: Session,
        doc_org: Organization,
    ) -> None:
        """Rule without template/category → names are null, target still named."""
        # the context tag must exist on a category, so seed one.
        context_tag = f'ctx-{uuid4().hex[:6]}'
        category = Category(
            organization_id=doc_org.id,
            name=f'Cat Null {uuid4().hex[:6]}',
            context_tag=context_tag,
        )
        db_session.add(category)
        db_session.commit()
        db_session.refresh(category)

        created = _create_putaway(
            client,
            doc_auth_headers,
            context_tag=context_tag,
            target_location_id=str(doc_target_location.id),
        )
        assert created['product_template_name'] is None
        assert created['category_name'] is None
        assert created['target_location_name'] == doc_target_location.name


@pytest.mark.integration
class TestPutawayRuleValidationLanguage:
    """a rejection a warehouse worker can read, in their language."""

    def test_unknown_context_tag_rejected_in_request_language(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
    ) -> None:
        resp = client.post(
            '/api/v1/warehouse/putaway-rules',
            headers={**doc_auth_headers, 'Accept-Language': 'pl'},
            json={
                'context_tag': 'nie_ma_takiego',
                'target_location_id': str(doc_target_location.id),
                'priority': 100,
            },
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.text
        detail = resp.text
        assert 'nie_ma_takiego' in detail
        # The message was written for a developer, in English, whatever the
        # request asked for.
        assert 'must match a context_tag' not in detail
        assert 'Nieznana' in detail or 'nieznan' in detail.lower()

    def test_unknown_storage_type_rejected_in_request_language(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
    ) -> None:
        resp = client.post(
            '/api/v1/warehouse/putaway-rules',
            headers={**doc_auth_headers, 'Accept-Language': 'pl'},
            json={
                'location_type_code': 'NIE_MA',
                'target_location_id': str(doc_target_location.id),
                'priority': 100,
            },
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.text
        assert 'NIE_MA' in resp.text
        assert 'must match a type_code' not in resp.text
        assert 'Nieznany' in resp.text or 'nieznan' in resp.text.lower()
