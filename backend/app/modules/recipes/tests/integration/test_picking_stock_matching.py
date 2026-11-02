"""Picking answers "where is it" and "which one" for name-matched ingredients.

Every one of these paths used to be gated on ``template_id``. An ingredient
typed by hand has none, so the checklist showed no location, no recommended
item and no FEFO warning — for most ingredients, most of the time.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text, update
from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.recipes.models import RecipeIngredient
from tests.integration._shelf import anchor_pending_records

RECIPE_URL = '/api/v1/recipes'

pytestmark = pytest.mark.integration


def _uom_id(db: Session, symbol: str) -> uuid.UUID:
    row = db.execute(
        text('SELECT id FROM uoms WHERE symbol = :s'), {'s': symbol}
    ).fetchone()
    assert row is not None, f'UOM {symbol!r} is not seeded'
    return uuid.UUID(str(row[0]))


def _shelve(
    db: Session,
    user: User,
    location: StorageLocation,
    *,
    template_name: str,
    expiries: list[date | None],
) -> ProductTemplate:
    """Put one item per entry in *expiries* on the shelf, counted in pieces."""
    pcs = _uom_id(db, 'pcs')
    template = ProductTemplate(
        id=uuid.uuid4(),
        organization_id=user.organization_id,
        name=template_name,
        uom_id=pcs,
    )
    db.add(template)
    db.flush()
    for index, expiry in enumerate(expiries):
        db.add(
            Item(
                id=uuid.uuid4(),
                organization_id=user.organization_id,
                storage_location_id=location.id,
                name=template_name,
                template_id=template.id,
                uom_id=pcs,
                quantity=Decimal('5'),
                expiry_date=expiry,
                barcode=f'{template.id.hex[:8]}-{index}',
            )
        )
    anchor_pending_records(db)
    db.commit()
    return template


def _recipe_with_named_ingredient(
    client: TestClient,
    auth_headers: dict[str, str],
    db: Session,
    *,
    ingredient_name: str,
    recipe_name: str,
) -> str:
    payload = {
        'name': recipe_name,
        'servings': 1,
        'instructions': 'Mix.',
        'ingredients': [
            {
                'name': ingredient_name,
                'quantity': '2',
                'uom_id': str(_uom_id(db, 'pcs')),
                'is_optional': False,
            }
        ],
    }
    response = client.post(RECIPE_URL, json=payload, headers=auth_headers)
    assert response.status_code == 201, response.text
    return str(response.json()['id'])


def _start_picking(
    client: TestClient, auth_headers: dict[str, str], recipe_id: str
) -> dict[str, Any]:
    response = client.post(
        f'{RECIPE_URL}/{recipe_id}/picking/start',
        json={'servings': 1},
        headers=auth_headers,
    )
    assert response.status_code in (200, 201), response.text
    return dict(response.json())


class TestPickingFindsNameMatchedStock:
    def test_checklist_gets_a_location_and_a_recommended_item(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_storage_location: StorageLocation,
        db_session: Session,
    ) -> None:
        """ "Where is it and which one do I take" for an ingredient with no link."""
        _shelve(
            db_session,
            test_user,
            test_storage_location,
            template_name='Ciecierzyca w puszce',
            expiries=[date.today() + timedelta(days=90)],
        )
        recipe_id = _recipe_with_named_ingredient(
            client,
            auth_headers,
            db_session,
            ingredient_name='Ciecierzyca z puszki',
            recipe_name='Curry kompletacyjne',
        )

        item = _start_picking(client, auth_headers, recipe_id)['items_to_pick'][0]

        assert item['status'] == 'pending'
        assert item['recommended_item_id'] is not None
        assert item['location'] == test_storage_location.name

    def test_fefo_expiry_travels_with_the_recommendation(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_storage_location: StorageLocation,
        db_session: Session,
    ) -> None:
        """The soon-to-expire can is the one offered, with its date."""
        soon = date.today() + timedelta(days=3)
        _shelve(
            db_session,
            test_user,
            test_storage_location,
            template_name='Ciecierzyca w puszce',
            expiries=[date.today() + timedelta(days=200), soon],
        )
        recipe_id = _recipe_with_named_ingredient(
            client,
            auth_headers,
            db_session,
            ingredient_name='Ciecierzyca z puszki',
            recipe_name='Curry FEFO',
        )

        item = _start_picking(client, auth_headers, recipe_id)['items_to_pick'][0]

        assert item['fefo_expiry_date'] == str(soon)
        assert item['fefo_days_left'] is not None

    def test_scanning_the_fresher_can_warns_about_the_older_one(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_storage_location: StorageLocation,
        db_session: Session,
    ) -> None:
        """The FEFO warning fires for a name match, not only for a linked one."""
        soon = date.today() + timedelta(days=3)
        later = date.today() + timedelta(days=200)
        template = _shelve(
            db_session,
            test_user,
            test_storage_location,
            template_name='Ciecierzyca w puszce',
            expiries=[soon, later],
        )
        recipe_id = _recipe_with_named_ingredient(
            client,
            auth_headers,
            db_session,
            ingredient_name='Ciecierzyca z puszki',
            recipe_name='Curry ze skanowaniem',
        )
        session_id = _start_picking(client, auth_headers, recipe_id)[
            'picking_session_id'
        ]

        fresher = (
            db_session.query(Item)
            .filter(Item.template_id == template.id, Item.expiry_date == later)
            .one()
        )
        response = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/{session_id}/scan',
            json={'barcode': fresher.barcode},
            headers=auth_headers,
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body['status'] == 'fefo_mismatch'
        assert body['fefo_recommended_expiry_date'] == str(soon)


class TestPickingReportsTheLinkState:
    """``is_linked`` says whether the ingredient points at a product.

    Before the sheet inferred it from ``recommended_item_id``, which
       is the best item *found in stock* — so an ingredient that was linked but
       sold out read as "not linked", and the row asked the user to fix a link
       that was never broken.
    """

    def test_linked_and_unlinked_ingredients_report_their_link_state(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_storage_location: StorageLocation,
        db_session: Session,
    ) -> None:
        template = _shelve(
            db_session,
            test_user,
            test_storage_location,
            template_name='Ciecierzyca w puszce',
            expiries=[date.today() + timedelta(days=90)],
        )
        pcs = str(_uom_id(db_session, 'pcs'))
        payload = {
            'name': 'Curry powiązane i nie',
            'servings': 1,
            'instructions': 'Mix.',
            'ingredients': [
                {
                    'name': 'Ciecierzyca w puszce',
                    'template_id': str(template.id),
                    'quantity': '1',
                    'uom_id': pcs,
                    'is_optional': False,
                },
                {
                    'name': 'Bazylia suszona',
                    'quantity': '1',
                    'uom_id': pcs,
                    'is_optional': False,
                },
            ],
        }
        response = client.post(RECIPE_URL, json=payload, headers=auth_headers)
        assert response.status_code == 201, response.text
        recipe_id = str(response.json()['id'])

        items = _start_picking(client, auth_headers, recipe_id)['items_to_pick']
        by_name = {i['name']: i for i in items}

        assert by_name['Ciecierzyca w puszce']['is_linked'] is True
        assert by_name['Bazylia suszona']['is_linked'] is False

    def test_unlinked_ingredient_found_by_name_is_still_reported_unlinked(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_storage_location: StorageLocation,
        db_session: Session,
    ) -> None:
        """The case the sheet used to describe backwards: no link, but stock."""
        _shelve(
            db_session,
            test_user,
            test_storage_location,
            template_name='Ciecierzyca w puszce',
            expiries=[date.today() + timedelta(days=90)],
        )
        recipe_id = _recipe_with_named_ingredient(
            client,
            auth_headers,
            db_session,
            ingredient_name='Ciecierzyca z puszki',
            recipe_name='Curry po nazwie',
        )

        item = _start_picking(client, auth_headers, recipe_id)['items_to_pick'][0]

        assert item['is_linked'] is False
        assert item['recommended_item_id'] is not None
        assert item['status'] == 'pending'

    def test_linked_ingredient_without_stock_is_missing_not_unlinked(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        db_session: Session,
    ) -> None:
        """The row on the screenshot: badge "missing", link intact."""
        pcs = str(_uom_id(db_session, 'pcs'))
        template = ProductTemplate(
            id=uuid.uuid4(),
            organization_id=test_user.organization_id,
            name='Czarny pieprz',
            uom_id=uuid.UUID(pcs),
        )
        db_session.add(template)
        db_session.commit()
        payload = {
            'name': 'Gulasz bez pieprzu',
            'servings': 1,
            'instructions': 'Mix.',
            'ingredients': [
                {
                    'name': 'Czarny pieprz',
                    'template_id': str(template.id),
                    'quantity': '1',
                    'uom_id': pcs,
                    'is_optional': False,
                }
            ],
        }
        response = client.post(RECIPE_URL, json=payload, headers=auth_headers)
        assert response.status_code == 201, response.text
        recipe_id = str(response.json()['id'])

        item = _start_picking(client, auth_headers, recipe_id)['items_to_pick'][0]

        assert item['status'] == 'missing'
        assert item['is_linked'] is True
        assert item['recommended_item_id'] is None


class TestPickingSessionCanBeReread:
    """Linking mid-session is a correction in place, not a lost session.

    The sheet used to answer "this ingredient means nothing to me" by
    cancelling the session and throwing the user into the recipe editor.
    The link endpoint never needed that — so the session can simply be
    read again afterwards.
    """

    def _recipe_with_two_ingredients(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db: Session,
    ) -> tuple[str, dict[str, str]]:
        pcs = str(_uom_id(db, 'pcs'))
        payload = {
            'name': 'Gulasz do poprawki',
            'servings': 1,
            'instructions': 'Mix.',
            'ingredients': [
                {
                    'name': 'Ciecierzyca z puszki',
                    'quantity': '1',
                    'uom_id': pcs,
                    'is_optional': False,
                },
                {
                    'name': 'Włoszczyzna',
                    'quantity': '1',
                    'uom_id': pcs,
                    'is_optional': False,
                },
            ],
        }
        response = client.post(RECIPE_URL, json=payload, headers=auth_headers)
        assert response.status_code == 201, response.text
        body = response.json()
        ids = {ing['name']: ing['id'] for ing in body['ingredients']}
        return str(body['id']), ids

    def test_linking_mid_session_turns_the_row_pending_and_keeps_the_picked_one(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_storage_location: StorageLocation,
        db_session: Session,
    ) -> None:
        _shelve(
            db_session,
            test_user,
            test_storage_location,
            template_name='Ciecierzyca w puszce',
            expiries=[date.today() + timedelta(days=90)],
        )
        soup_greens = _shelve(
            db_session,
            test_user,
            test_storage_location,
            template_name='Zestaw warzyw na rosół',
            expiries=[date.today() + timedelta(days=30)],
        )
        recipe_id, ingredient_ids = self._recipe_with_two_ingredients(
            client, auth_headers, db_session
        )
        session = _start_picking(client, auth_headers, recipe_id)
        session_id = session['picking_session_id']
        chickpeas = next(
            i for i in session['items_to_pick'] if i['name'] == 'Ciecierzyca z puszki'
        )
        assert chickpeas['status'] == 'pending'

        picked = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/{session_id}/scan',
            json={'item_id': chickpeas['recommended_item_id']},
            headers=auth_headers,
        )
        assert picked.status_code == 200, picked.text

        linked = client.post(
            f'{RECIPE_URL}/{recipe_id}/ingredients/'
            f'{ingredient_ids["Włoszczyzna"]}/link-template',
            json={'template_id': str(soup_greens.id)},
            headers=auth_headers,
        )
        assert linked.status_code == 200, linked.text

        reread = client.get(
            f'{RECIPE_URL}/{recipe_id}/picking/{session_id}', headers=auth_headers
        )
        assert reread.status_code == 200, reread.text
        by_name = {i['name']: i for i in reread.json()['items_to_pick']}

        assert by_name['Włoszczyzna']['status'] == 'pending'
        assert by_name['Włoszczyzna']['is_linked'] is True
        assert by_name['Włoszczyzna']['recommended_item_id'] is not None
        # What was already taken off the shelf stays taken.
        assert by_name['Ciecierzyca z puszki']['status'] == 'picked'

    def test_reading_a_foreign_session_is_a_404(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
    ) -> None:
        recipe_id, _ = self._recipe_with_two_ingredients(
            client, auth_headers, db_session
        )
        response = client.get(
            f'{RECIPE_URL}/{recipe_id}/picking/{uuid.uuid4()}',
            headers=auth_headers,
        )
        assert response.status_code == 404


class TestPickingFoldsOnlySeasonings:
    """An ingredient counted in pieces is never pre-skipped by its amount.

    The checklist used to send every pcs/szt row at one or less — one egg,
    one onion, half a carton — into the collapsed seasonings section, the
    same symptom the recipe card dropped. What still folds away on its own
    is a small weight or volume, and what the cook skipped explicitly.
    """

    @staticmethod
    def _start_with_one_ingredient(
        client: TestClient,
        auth_headers: dict[str, str],
        db: Session,
        *,
        recipe_name: str,
        ingredient_name: str,
        quantity: str,
        uom_symbol: str,
    ) -> dict[str, Any]:
        response = client.post(
            RECIPE_URL,
            json={
                'name': recipe_name,
                'servings': 1,
                'instructions': 'Mix.',
                'ingredients': [
                    {
                        'name': ingredient_name,
                        'quantity': quantity,
                        'uom_id': str(_uom_id(db, uom_symbol)),
                        'is_optional': False,
                    }
                ],
            },
            headers=auth_headers,
        )
        assert response.status_code == 201, response.text
        body = response.json()

        # A row saved before the flag existed carries no value; that is the
        # state the heuristic reads an amount against. Rows written by the
        # API today carry an explicit False, which never reaches it.
        db.execute(
            update(RecipeIngredient)
            .where(RecipeIngredient.id == uuid.UUID(str(body['ingredients'][0]['id'])))
            .values(picking_skip=None)
        )
        db.commit()

        return _start_picking(client, auth_headers, str(body['id']))

    def test_a_single_piece_is_not_folded_away(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
    ) -> None:
        """One egg is a main ingredient, so it stays on the sheet."""
        session = self._start_with_one_ingredient(
            client,
            auth_headers,
            db_session,
            recipe_name='Jajko na kompletację',
            ingredient_name='Jajko',
            quantity='1',
            uom_symbol='pcs',
        )

        item = session['items_to_pick'][0]
        assert item['quantity_to_pick'] == 1
        assert item['status'] == 'missing'  # what to look for, not hidden

    def test_a_small_weight_still_folds_away(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
    ) -> None:
        """The seasonings fold-out keeps its own: 5 g of salt is a spice."""
        session = self._start_with_one_ingredient(
            client,
            auth_headers,
            db_session,
            recipe_name='Sól na kompletację',
            ingredient_name='Sól',
            quantity='5',
            uom_symbol='g',
        )

        item = session['items_to_pick'][0]
        assert item['status'] == 'skipped'
