"""Picking prefers the open pack and opens the sealed one it takes from.

A bag of flour that was opened last week keeps worse than the sealed bags
beside it, so on the same date it is the one to use. When a sealed bag
expires EARLIER than the open one, neither choice is the app's to make: the
scan lists both with their dates and leaves the cook to pick, the earlier
date first. Taking a part of a sealed bag opens it, the way Use partially
does, so the stock knows when it was opened.
"""

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.item import Item
from app.models.item_history import ItemHistory
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.user import User
from tests.integration._shelf import anchor_pending_records

RECIPE_URL = '/api/v1/recipes'
BARCODE = '5900000000024'
OPENED = {'opened': {'at': '2026-10-01T09:00:00+00:00'}}

pytestmark = pytest.mark.integration


def _opened_meta(use_by_in: int | None) -> dict[str, Any]:
    if use_by_in is None:
        return OPENED
    use_by = (date.today() + timedelta(days=use_by_in)).isoformat()
    return {'opened': {**OPENED['opened'], 'use_by': use_by}}


def _uom_id(db: Session, symbol: str) -> uuid.UUID:
    row = db.execute(
        text('SELECT id FROM uoms WHERE symbol = :s'), {'s': symbol}
    ).fetchone()
    assert row is not None, f'UOM {symbol!r} is not seeded'
    return uuid.UUID(str(row[0]))


def _flour(
    db: Session,
    user: User,
    shelf: StorageLocation,
    *packs: tuple[str, int, bool],
    use_by_in: int | None = None,
) -> ProductTemplate:
    """Flour on a 2 kg card with one record per ``(quantity, days to expiry, open)``."""
    pcs = _uom_id(db, 'pcs')
    template = ProductTemplate(
        id=uuid.uuid4(),
        organization_id=user.organization_id,
        name='Flour',
        barcode=BARCODE,
        uom_id=pcs,
        weight_value=Decimal('2'),
        weight_uom_id=_uom_id(db, 'kg'),
    )
    db.add(template)
    db.flush()
    for quantity, days, is_open in packs:
        db.add(
            Item(
                id=uuid.uuid4(),
                organization_id=user.organization_id,
                storage_location_id=shelf.id,
                name='Flour',
                template_id=template.id,
                uom_id=pcs,
                quantity=Decimal(quantity),
                expiry_date=date.today() + timedelta(days=days),
                meta_data=_opened_meta(use_by_in) if is_open else None,
            )
        )
    anchor_pending_records(db)
    db.commit()
    return template


def _records(db: Session, template: ProductTemplate) -> list[Item]:
    db.expire_all()
    return list(
        db.scalars(
            select(Item)
            .where(Item.template_id == template.id)
            .order_by(Item.created_at)
        )
    )


def _start(
    client: TestClient,
    headers: dict[str, str],
    db: Session,
    template: ProductTemplate,
    kilograms: str,
) -> tuple[str, str, dict[str, Any]]:
    recipe = client.post(
        RECIPE_URL,
        json={
            'name': 'Bread',
            'servings': 1,
            'instructions': 'Mix.',
            'ingredients': [
                {
                    'name': 'Flour',
                    'template_id': str(template.id),
                    'quantity': kilograms,
                    'uom_id': str(_uom_id(db, 'kg')),
                    'is_optional': False,
                }
            ],
        },
        headers=headers,
    )
    assert recipe.status_code == 201, recipe.text
    recipe_id = recipe.json()['id']
    start = client.post(
        f'{RECIPE_URL}/{recipe_id}/picking/start',
        json={'servings': 1},
        headers=headers,
    )
    assert start.status_code == 201, start.text
    body: dict[str, Any] = start.json()
    return recipe_id, body['picking_session_id'], body


def _scan(
    client: TestClient,
    headers: dict[str, str],
    recipe_id: str,
    session_id: str,
    **target: str | bool,
) -> dict[str, Any]:
    scan = client.post(
        f'{RECIPE_URL}/{recipe_id}/picking/{session_id}/scan',
        json=target,
        headers=headers,
    )
    assert scan.status_code == 200, scan.text
    body: dict[str, Any] = scan.json()
    return body


class TestPickingPrefersTheOpenPack:
    def test_on_the_same_date_the_open_pack_is_recommended_over_a_larger_sealed_one(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        template = _flour(
            db_session,
            test_user,
            test_storage_location,
            ('3', 20, False),
            ('0.75', 20, True),
        )
        opened = next(r for r in _records(db_session, template) if r.meta_data)

        _, _, start = _start(client, auth_headers, db_session, template, '0.5')

        assert start['items_to_pick'][0]['recommended_item_id'] == str(opened.id)

    def test_a_barcode_scan_takes_the_open_pack_without_asking(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        template = _flour(
            db_session,
            test_user,
            test_storage_location,
            ('3', 20, False),
            ('0.75', 20, True),
        )
        recipe_id, session_id, _ = _start(
            client, auth_headers, db_session, template, '0.5'
        )

        body = _scan(client, auth_headers, recipe_id, session_id, barcode=BARCODE)

        assert body['status'] == 'picked'
        sealed, opened = _records(db_session, template)
        assert sealed.quantity == Decimal('3')
        assert opened.quantity == Decimal('0.5')

    def test_a_sealed_pack_with_an_earlier_date_is_offered_beside_the_open_one(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        template = _flour(
            db_session,
            test_user,
            test_storage_location,
            ('0.75', 20, True),
            ('2', 10, False),
        )
        recipe_id, session_id, _ = _start(
            client, auth_headers, db_session, template, '0.5'
        )

        body = _scan(client, auth_headers, recipe_id, session_id, barcode=BARCODE)

        assert body['status'] == 'disambiguation_required'
        first, second = body['candidates']
        assert (first['opened'], first['recommended']) == (False, True)
        assert (second['opened'], second['recommended']) == (True, False)
        assert first['expiry_date'] < second['expiry_date']
        assert second['opened_at'] == OPENED['opened']['at']
        # Nothing left the shelf while the cook decides.
        assert [r.quantity for r in _records(db_session, template)] == [
            Decimal('0.75'),
            Decimal('2'),
        ]

    def test_tapping_the_ingredient_asks_when_a_sealed_pack_expires_earlier(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        template = _flour(
            db_session,
            test_user,
            test_storage_location,
            ('0.75', 20, True),
            ('2', 10, False),
        )
        recipe_id, session_id, start = _start(
            client, auth_headers, db_session, template, '0.5'
        )
        tapped = start['items_to_pick'][0]['recommended_item_id']

        body = _scan(
            client,
            auth_headers,
            recipe_id,
            session_id,
            item_id=tapped,
            from_checklist=True,
        )

        assert body['status'] == 'disambiguation_required'
        assert [r.quantity for r in _records(db_session, template)] == [
            Decimal('0.75'),
            Decimal('2'),
        ]

    def test_choosing_a_candidate_is_not_asked_again(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        template = _flour(
            db_session,
            test_user,
            test_storage_location,
            ('0.75', 20, True),
            ('2', 10, False),
        )
        opened = next(r for r in _records(db_session, template) if r.meta_data)
        recipe_id, session_id, _ = _start(
            client, auth_headers, db_session, template, '0.5'
        )

        body = _scan(
            client, auth_headers, recipe_id, session_id, item_id=str(opened.id)
        )

        assert body['status'] == 'picked'
        assert _records(db_session, template)[0].quantity == Decimal('0.5')


class TestTakingFromASealedPackOpensIt:
    def test_a_part_of_a_bag_opens_one_bag_and_leaves_the_others_sealed(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        template = _flour(
            db_session, test_user, test_storage_location, ('3', 20, False)
        )
        sealed = _records(db_session, template)[0]
        recipe_id, session_id, _ = _start(
            client, auth_headers, db_session, template, '0.5'
        )

        body = _scan(
            client, auth_headers, recipe_id, session_id, item_id=str(sealed.id)
        )

        assert body['status'] == 'picked'
        records = _records(db_session, template)
        assert len(records) == 2
        stays_sealed = next(r for r in records if r.id == sealed.id)
        opened = next(r for r in records if r.id != sealed.id)
        assert stays_sealed.quantity == Decimal('2')
        assert not stays_sealed.meta_data
        assert opened.quantity == Decimal('0.75')
        assert opened.meta_data is not None
        assert opened.meta_data['opened']['at']
        assert opened.expiry_date == sealed.expiry_date
        actions = db_session.scalars(
            select(ItemHistory.action).where(ItemHistory.item_id == opened.id)
        ).all()
        assert 'OPENED' in actions

    def test_more_than_a_bag_with_a_part_over_opens_the_bag_the_part_comes_from(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        template = _flour(
            db_session, test_user, test_storage_location, ('3', 20, False)
        )
        sealed = _records(db_session, template)[0]
        recipe_id, session_id, _ = _start(
            client, auth_headers, db_session, template, '2.5'
        )

        body = _scan(
            client, auth_headers, recipe_id, session_id, item_id=str(sealed.id)
        )

        assert body['status'] == 'picked'
        assert body['session_complete'] is True
        records = _records(db_session, template)
        stays_sealed = next(r for r in records if r.id == sealed.id)
        opened = next(r for r in records if r.id != sealed.id)
        assert stays_sealed.quantity == Decimal('1')
        assert not stays_sealed.meta_data
        assert opened.quantity == Decimal('0.75')
        assert opened.meta_data is not None
        assert opened.meta_data['opened']['at']

    def test_taking_whole_bags_opens_nothing(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        template = _flour(
            db_session, test_user, test_storage_location, ('3', 20, False)
        )
        sealed = _records(db_session, template)[0]
        recipe_id, session_id, _ = _start(
            client, auth_headers, db_session, template, '2'
        )

        _scan(client, auth_headers, recipe_id, session_id, item_id=str(sealed.id))

        records = _records(db_session, template)
        assert len(records) == 1
        assert records[0].quantity == Decimal('2')
        assert not records[0].meta_data

    def test_a_part_of_an_open_pack_stays_in_that_pack(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        template = _flour(
            db_session, test_user, test_storage_location, ('0.75', 20, True)
        )
        opened = _records(db_session, template)[0]
        recipe_id, session_id, _ = _start(
            client, auth_headers, db_session, template, '0.5'
        )

        _scan(client, auth_headers, recipe_id, session_id, item_id=str(opened.id))

        records = _records(db_session, template)
        assert len(records) == 1
        assert records[0].quantity == Decimal('0.5')
        assert records[0].meta_data == OPENED


class TestAUseByShortensWhatCookingWaitsFor:
    def test_an_open_pack_with_a_near_use_by_is_used_before_a_sealed_one(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        # The open pack's batch is good for 20 days, the sealed one's for 10:
        # by batch dates the sealed one is first. The open pack's use-by of 3
        # days is what it is judged by, and that makes it the first to use.
        template = _flour(
            db_session,
            test_user,
            test_storage_location,
            ('2', 10, False),
            ('0.75', 20, True),
            use_by_in=3,
        )
        opened = next(r for r in _records(db_session, template) if r.meta_data)

        _, _, start = _start(client, auth_headers, db_session, template, '0.5')

        assert start['items_to_pick'][0]['recommended_item_id'] == str(opened.id)

    def test_without_a_use_by_the_earlier_batch_date_still_leads(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        template = _flour(
            db_session,
            test_user,
            test_storage_location,
            ('2', 10, False),
            ('0.75', 20, True),
        )
        sealed = next(r for r in _records(db_session, template) if not r.meta_data)

        _, _, start = _start(client, auth_headers, db_session, template, '0.5')

        assert start['items_to_pick'][0]['recommended_item_id'] == str(sealed.id)

    def test_a_use_by_in_the_past_puts_the_open_pack_after_a_fit_one(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        template = _flour(
            db_session,
            test_user,
            test_storage_location,
            ('2', 30, False),
            ('0.75', 20, True),
            use_by_in=-1,
        )
        sealed = next(r for r in _records(db_session, template) if not r.meta_data)

        _, _, start = _start(client, auth_headers, db_session, template, '0.5')

        assert start['items_to_pick'][0]['recommended_item_id'] == str(sealed.id)
