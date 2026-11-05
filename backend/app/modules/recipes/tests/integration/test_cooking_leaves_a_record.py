"""What cooking leaves behind when there is no document module to ask.

In a household profile ``warehouse`` is not enabled, so no RW document is
written and the organization journal knows nothing about picking. The item's
own history is the only account of the ubytek there will ever be, and it used
to read ``{'old': 500.0, 'new': 499.0}`` — a number that changed, with nothing
saying why. Stock takes have written a reason into that same field for a long
time; cooking now does too.
"""

import uuid
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.audit_log import AuditLog
from app.models.item import Item
from app.models.item_history import ItemHistory
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.uom import Uom
from app.models.user import User
from tests.integration._shelf import post_on_shelf

RECIPE_URL = '/api/v1/recipes'


def _recipe_with_one_ingredient(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
    test_user: User,
    test_storage_location: StorageLocation,
) -> tuple[str, uuid.UUID]:
    grams = db_session.scalar(select(Uom.id).where(Uom.symbol == 'g'))
    assert grams is not None, "'g' is not seeded"
    template = ProductTemplate(
        id=uuid.uuid4(),
        organization_id=test_user.organization_id,
        name='Flour',
        uom_id=grams,
    )
    db_session.add(template)
    db_session.flush()

    db_session.commit()
    record = post_on_shelf(
        client, auth_headers, template, test_storage_location.id, '500'
    )

    payload: dict[str, Any] = {
        'name': 'Pancakes',
        'description': '',
        'servings': 2,
        'prep_time_minutes': 10,
        'tags': [],
        'is_favorite': False,
        'ingredients': [
            {
                'name': 'Flour',
                'template_id': str(template.id),
                'uom_id': str(grams),
                'quantity': '200',
                'is_optional': False,
            }
        ],
    }
    resp = client.post(RECIPE_URL, json=payload, headers=auth_headers)
    assert resp.status_code == 201
    return resp.json()['id'], uuid.UUID(record['id'])


def _history_for(db_session: Session, item_id: uuid.UUID) -> list[ItemHistory]:
    return list(
        db_session.scalars(
            select(ItemHistory)
            .where(ItemHistory.item_id == item_id)
            .order_by(ItemHistory.created_at)
        ).all()
    )


def _audit_for(db_session: Session, item_id: uuid.UUID) -> list[AuditLog]:
    return list(
        db_session.scalars(
            select(AuditLog)
            .where(AuditLog.target_id == item_id)
            .order_by(AuditLog.created_at)
        ).all()
    )


@pytest.mark.integration
class TestCookingLeavesARecord:
    def test_the_history_entry_says_which_recipe_took_it(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        recipe_id, item_id = _recipe_with_one_ingredient(
            client, auth_headers, db_session, test_user, test_storage_location
        )
        start = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/start',
            json={'servings': 2},
            headers=auth_headers,
        )
        session_id = start.json()['picking_session_id']
        scan = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/{session_id}/scan',
            json={'item_id': str(item_id)},
            headers=auth_headers,
        )
        assert scan.status_code == 200

        db_session.expire_all()
        entries = [
            h
            for h in _history_for(db_session, item_id)
            if (h.changes or {}).get('reason') == 'recipe_picking'
        ]
        assert len(entries) == 1
        changes = entries[0].changes or {}
        assert changes['recipe_name'] == 'Pancakes'
        assert changes['servings'] == 2
        assert changes['ingredient_name'] == 'Flour'
        assert changes['picking_session_id'] == session_id

    def test_the_organization_log_says_the_cooking_took_it(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        """Not only the item's own history -- the log the whole org reads.

        The two records answer different questions. The item's history
        answers "what happened to this flour"; the organization log answers
        "what happened here", and it is the one an administrator opens
        months later. A quantity change reached it with an empty reason,
        so a bag of flour going down read the same whether somebody cooked
        with it or mistyped a number into the quantity field.
        """
        recipe_id, item_id = _recipe_with_one_ingredient(
            client, auth_headers, db_session, test_user, test_storage_location
        )
        start = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/start',
            json={'servings': 2},
            headers=auth_headers,
        )
        session_id = start.json()['picking_session_id']
        client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/{session_id}/scan',
            json={'item_id': str(item_id)},
            headers=auth_headers,
        )

        db_session.expire_all()
        entries = [
            e for e in _audit_for(db_session, item_id) if e.action == 'QUANTITY_CHANGE'
        ]
        assert len(entries) == 1
        assert entries[0].reason == 'recipe_picking'
        # The rest of the context rides along, so the entry names the dish
        # rather than only the kind of act.
        assert (entries[0].meta_data or {})['recipe_name'] == 'Pancakes'
        assert (entries[0].meta_data or {})['ingredient_name'] == 'Flour'

    def test_a_return_says_it_is_a_return(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        """Undo writes the same shape of entry, so the two legs are legible.

        Both directions used to be a bare pair of numbers, and a take followed
        by a return read exactly like a take followed by a take.
        """
        recipe_id, item_id = _recipe_with_one_ingredient(
            client, auth_headers, db_session, test_user, test_storage_location
        )
        start = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/start',
            json={'servings': 2},
            headers=auth_headers,
        )
        session_id = start.json()['picking_session_id']
        ingredient_id = start.json()['items_to_pick'][0]['ingredient_id']
        client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/{session_id}/scan',
            json={'item_id': str(item_id)},
            headers=auth_headers,
        )
        undo = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/{session_id}/undo',
            json={'ingredient_id': str(ingredient_id)},
            headers=auth_headers,
        )
        assert undo.status_code == 200

        db_session.expire_all()
        reasons = [
            (h.changes or {}).get('reason') for h in _history_for(db_session, item_id)
        ]
        assert 'recipe_picking' in reasons
        assert 'recipe_picking_undo' in reasons

    def test_completing_takes_no_document_and_leaves_the_stock_taken(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        """The household path: no warehouse module, and the flour stays gone.

        Cooking used to end with the session still ``active``, so the next
        "Get ingredients" cancelled it and put the flour back — a meal that had
        been eaten reappearing in the cupboard.
        """
        recipe_id, item_id = _recipe_with_one_ingredient(
            client, auth_headers, db_session, test_user, test_storage_location
        )
        start = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/start',
            json={'servings': 2},
            headers=auth_headers,
        )
        session_id = start.json()['picking_session_id']
        scan = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/{session_id}/scan',
            json={'item_id': str(item_id)},
            headers=auth_headers,
        )
        assert scan.json()['session_complete'] is True

        # What the sheet does on the last ingredient.
        done = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/{session_id}/complete',
            headers=auth_headers,
        )
        assert done.status_code == 200

        from app.modules.recipes.models import PickingSession

        db_session.expire_all()
        session = db_session.scalars(
            select(PickingSession).where(PickingSession.id == uuid.UUID(session_id))
        ).first()
        assert session is not None
        assert session.status == 'completed'
        assert session.completed_at is not None

        item = db_session.scalars(select(Item).where(Item.id == item_id)).first()
        assert item is not None
        assert item.quantity == Decimal('300')

        # And opening the dialog again does not take it back.
        again = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/start',
            json={'servings': 2},
            headers=auth_headers,
        )
        assert again.json()['picking_session_id'] != session_id
        assert again.json()['resumed'] is False

        db_session.expire_all()
        item = db_session.scalars(select(Item).where(Item.id == item_id)).first()
        assert item is not None
        assert item.quantity == Decimal('300')


def _ledger_for_session(
    client: TestClient, auth_headers: dict[str, str], session_id: str
) -> list[dict[str, Any]]:
    resp = client.get(
        '/api/v1/stock-moves',
        params={'reference_id': session_id},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    return list(resp.json()['items'])


@pytest.mark.integration
class TestCookingInTheMovesRegister:
    """The moves register names cooking as its source, in both directions.

    The register is the one screen a household has for "where did the flour
    go", and every leg of a pick used to be filed under the record it changed:
    the source column said "Record", and a put-back read as a delivery from
    outside. The session is what caused the movement, so it is what the row
    points at.
    """

    def _start_and_take(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> tuple[str, str, str]:
        recipe_id, item_id = _recipe_with_one_ingredient(
            client, auth_headers, db_session, test_user, test_storage_location
        )
        start = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/start',
            json={'servings': 2},
            headers=auth_headers,
        )
        session_id = start.json()['picking_session_id']
        ingredient_id = start.json()['items_to_pick'][0]['ingredient_id']
        scan = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/{session_id}/scan',
            json={'item_id': str(item_id)},
            headers=auth_headers,
        )
        assert scan.status_code == 200
        return recipe_id, session_id, ingredient_id

    def test_a_take_and_its_undo_both_point_at_the_session(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        recipe_id, session_id, ingredient_id = self._start_and_take(
            client, auth_headers, db_session, test_user, test_storage_location
        )
        undo = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/{session_id}/undo',
            json={'ingredient_id': ingredient_id},
            headers=auth_headers,
        )
        assert undo.status_code == 200

        rows = _ledger_for_session(client, auth_headers, session_id)
        assert {r['reference_type'] for r in rows} == {'recipe_picking'}
        taken = [r for r in rows if r['to_location_id'] is None]
        returned = [r for r in rows if r['from_location_id'] is None]
        assert len(taken) == 1
        assert len(returned) == 1
        assert Decimal(taken[0]['quantity']) == Decimal('200')
        assert Decimal(returned[0]['quantity']) == Decimal('200')

    def test_calling_the_cooking_off_points_at_the_session(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        recipe_id, session_id, _ = self._start_and_take(
            client, auth_headers, db_session, test_user, test_storage_location
        )
        cancel = client.delete(
            f'{RECIPE_URL}/{recipe_id}/picking/{session_id}',
            headers=auth_headers,
        )
        assert cancel.status_code in (200, 204)

        rows = _ledger_for_session(client, auth_headers, session_id)
        assert len(rows) == 2
        assert {r['reference_type'] for r in rows} == {'recipe_picking'}
