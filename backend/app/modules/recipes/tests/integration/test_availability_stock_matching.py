"""Availability answers from the shelf, not from the ingredient's spelling.

The three defects these cover compound: an ingredient typed by hand carried
no lookup key, a substring search could not have used one anyway, and even
a hit compared 400 grams against a count of cans. Each test below fails on
any one of them, so they are written end-to-end through the API rather than
against the pieces.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.user import User
from tests.integration._shelf import anchor_pending_records

RECIPE_URL = '/api/v1/recipes'

pytestmark = pytest.mark.integration


def _uom_id(db: Session, symbol: str) -> uuid.UUID:
    row = db.execute(
        text('SELECT id FROM uoms WHERE symbol = :s'), {'s': symbol}
    ).fetchone()
    assert row is not None, f'UOM {symbol!r} is not seeded'
    return uuid.UUID(str(row[0]))


def _stock_a_can(
    db: Session,
    user: User,
    location: StorageLocation,
    *,
    name: str = 'Ciecierzyca w puszce',
    weight_value: Decimal | None = Decimal('400'),
    cans: int = 7,
) -> ProductTemplate:
    """Put *cans* pieces of a 400 g product on the shelf, counted in pieces."""
    pcs = _uom_id(db, 'pcs')
    template = ProductTemplate(
        id=uuid.uuid4(),
        organization_id=user.organization_id,
        name=name,
        uom_id=pcs,
        weight_value=weight_value,
        weight_uom_id=_uom_id(db, 'g') if weight_value is not None else None,
    )
    db.add(template)
    db.flush()
    db.add(
        Item(
            id=uuid.uuid4(),
            organization_id=user.organization_id,
            storage_location_id=location.id,
            name=name,
            template_id=template.id,
            uom_id=pcs,
            quantity=Decimal(cans),
        )
    )
    anchor_pending_records(db)
    db.commit()
    return template


def _recipe_asking_for_grams(
    client: TestClient,
    auth_headers: dict[str, str],
    db: Session,
    *,
    ingredient_name: str,
    grams: str = '400',
    name: str = 'Curry z ciecierzycą',
    template_id: uuid.UUID | None = None,
) -> str:
    """Create a recipe asking for an ingredient, linked to a product or not."""
    payload = {
        'name': name,
        'servings': 1,
        'instructions': 'Mix.',
        'ingredients': [
            {
                'name': ingredient_name,
                'quantity': grams,
                'uom_id': str(_uom_id(db, 'g')),
                'is_optional': False,
                **({'template_id': str(template_id)} if template_id else {}),
            }
        ],
    }
    response = client.post(RECIPE_URL, json=payload, headers=auth_headers)
    assert response.status_code == 201, response.text
    return str(response.json()['id'])


def _recipe_asking_without_unit(
    client: TestClient,
    auth_headers: dict[str, str],
    *,
    ingredient_name: str,
    quantity: str = '1',
    name: str = 'Curry z ciecierzycą',
) -> str:
    """Create a recipe whose ingredient carries no unit at all.

    The ingredient row shows a name and an amount; the unit lives under
    "More options". Whoever fills in only what they see creates exactly
    this shape.
    """
    payload = {
        'name': name,
        'servings': 1,
        'instructions': 'Mix.',
        'ingredients': [
            {
                'name': ingredient_name,
                'quantity': quantity,
                'is_optional': False,
            }
        ],
    }
    response = client.post(RECIPE_URL, json=payload, headers=auth_headers)
    assert response.status_code == 201, response.text
    return str(response.json()['id'])


def _availability(
    client: TestClient, auth_headers: dict[str, str], recipe_id: str
) -> dict[str, Any]:
    response = client.get(
        f'{RECIPE_URL}/{recipe_id}/availability', headers=auth_headers
    )
    assert response.status_code == 200, response.text
    ingredient: dict[str, Any] = response.json()['ingredients'][0]
    return ingredient


class TestAvailabilityFromTheShelf:
    def test_name_reaches_the_shelf_across_inflection_and_measure(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_storage_location: StorageLocation,
        db_session: Session,
    ) -> None:
        """ "Ciecierzyca z puszki", 400 g, against 7 cans of "Ciecierzyca w puszce"."""
        _stock_a_can(db_session, test_user, test_storage_location)
        recipe_id = _recipe_asking_for_grams(
            client, auth_headers, db_session, ingredient_name='Ciecierzyca z puszki'
        )

        ingredient = _availability(client, auth_headers, recipe_id)

        assert ingredient['status'] == 'available_approx'
        assert ingredient['match_type'] == 'fuzzy'
        assert ingredient['quantities_comparable'] is True
        assert ingredient['available_quantity'] == 2800.0
        assert ingredient['available_uom'] == 'g'
        assert ingredient['best_item'] is not None
        assert ingredient['best_item']['location'] is not None
        assert ingredient['best_item']['uom_symbol'] == 'pcs'

    def test_measures_that_cannot_meet_do_not_read_as_missing(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_storage_location: StorageLocation,
        db_session: Session,
    ) -> None:
        """Same shelf, no pack size recorded: report both readings, not a verdict."""
        _stock_a_can(db_session, test_user, test_storage_location, weight_value=None)
        recipe_id = _recipe_asking_for_grams(
            client, auth_headers, db_session, ingredient_name='Ciecierzyca z puszki'
        )

        ingredient = _availability(client, auth_headers, recipe_id)

        assert ingredient['status'] == 'incomparable'
        assert ingredient['quantities_comparable'] is False
        assert ingredient['available_quantity'] == 7.0
        assert ingredient['available_uom'] == 'pcs'
        assert ingredient['required_quantity'] == 400.0
        assert ingredient['required_uom'] == 'g'
        assert ingredient['best_item'] is not None

    def test_an_ingredient_without_a_measure_is_not_counted_as_in_stock(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_storage_location: StorageLocation,
        db_session: Session,
    ) -> None:
        """The goods are there, the comparison is not.

        The row already said "cannot compare"; the card's counter and
        the "I can cook" filter kept reading the same ingredient as available,
        so a recipe nobody could size up passed for one ready to cook.
        """
        _stock_a_can(db_session, test_user, test_storage_location)
        recipe_id = _recipe_asking_without_unit(
            client, auth_headers, ingredient_name='Ciecierzyca z puszki'
        )

        response = client.get(
            f'{RECIPE_URL}/{recipe_id}/availability', headers=auth_headers
        )
        data = response.json()
        assert data['match_percentage'] == 0.0
        assert data['ingredients'][0]['status'] == 'incomparable'

        listed = client.get(RECIPE_URL, headers=auth_headers)
        assert listed.status_code == 200, listed.text
        entry = next(r for r in listed.json()['items'] if r['id'] == recipe_id)
        assert entry['ingredients_available'] == 0
        assert entry['ingredients_total'] == 1
        assert entry['ingredients_incomparable'] == 1
        assert entry['match_percentage'] == 0.0

    def test_an_empty_shelf_is_missing_with_no_best_item(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
    ) -> None:
        _recipe_asking_for_grams(
            client, auth_headers, db_session, ingredient_name='Mleko kokosowe'
        )
        recipe_id = _recipe_asking_for_grams(
            client,
            auth_headers,
            db_session,
            ingredient_name='Mleko kokosowe',
            name='Curry bez mleka',
        )

        ingredient = _availability(client, auth_headers, recipe_id)

        assert ingredient['status'] == 'missing'
        assert ingredient['match_type'] is None
        assert ingredient['best_item'] is None

    def test_a_name_the_catalogue_merely_resembles_is_not_a_match(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_storage_location: StorageLocation,
        db_session: Session,
    ) -> None:
        """The negative that keeps the whole feature honest, end to end."""
        _stock_a_can(
            db_session,
            test_user,
            test_storage_location,
            name='Tunczyk w oleju',
            weight_value=Decimal('160'),
        )
        recipe_id = _recipe_asking_for_grams(
            client,
            auth_headers,
            db_session,
            ingredient_name='Olej',
            grams='30',
            name='Naleśniki',
        )

        ingredient = _availability(client, auth_headers, recipe_id)

        assert ingredient['status'] == 'missing'
        assert ingredient['best_item'] is None

    def test_stock_in_the_same_measure_still_compares_directly(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_storage_location: StorageLocation,
        db_session: Session,
    ) -> None:
        """Regression: nothing about the bridge disturbs a plain gram-to-gram sum."""
        grams = _uom_id(db_session, 'g')
        template = ProductTemplate(
            id=uuid.uuid4(),
            organization_id=test_user.organization_id,
            name='Maka pszenna typ 550',
            uom_id=grams,
        )
        db_session.add(template)
        db_session.flush()
        db_session.add(
            Item(
                id=uuid.uuid4(),
                organization_id=test_user.organization_id,
                storage_location_id=test_storage_location.id,
                name='Maka pszenna typ 550',
                template_id=template.id,
                uom_id=grams,
                quantity=Decimal('1000'),
            )
        )
        anchor_pending_records(db_session)
        db_session.commit()

        recipe_id = _recipe_asking_for_grams(
            client,
            auth_headers,
            db_session,
            ingredient_name='Mąka pszenna',
            grams='250',
            name='Naleśniki podstawowe',
        )

        ingredient = _availability(client, auth_headers, recipe_id)

        assert ingredient['status'] == 'available_approx'
        assert ingredient['quantities_comparable'] is True
        assert ingredient['available_quantity'] == 1000.0
        assert ingredient['available_uom'] == 'g'

    def test_a_name_with_accents_reaches_a_catalogue_name_with_accents(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_storage_location: StorageLocation,
        db_session: Session,
    ) -> None:
        """ "Ryż" against "Ryż 1 kg": both keep their letters, and the lookup
        key is folded to "ryz" before it reaches the database — which then
        found nothing and called the rice on the shelf missing."""
        _stock_a_can(
            db_session, test_user, test_storage_location, name='Ryż 1 kg', cans=2
        )
        recipe_id = _recipe_asking_for_grams(
            client,
            auth_headers,
            db_session,
            ingredient_name='Ryż',
            grams='200',
            name='Ryż z mlekiem',
        )

        ingredient = _availability(client, auth_headers, recipe_id)

        assert ingredient['status'] == 'available_approx'
        assert ingredient['match_type'] == 'fuzzy'

    @pytest.mark.parametrize(
        ('ingredient', 'product'),
        [
            ('Weißbrot', 'Weißbrot 500 g'),
            ('Œufs', 'Œufs bio'),
            ('Молоко', 'Молоко 1 л'),
            ('Phở', 'Phở gạo'),
        ],
    )
    def test_a_name_in_its_own_script_reaches_the_catalogue_name(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_storage_location: StorageLocation,
        db_session: Session,
        ingredient: str,
        product: str,
    ) -> None:
        """The lookup key is folded to ASCII for the verdict ("weis", "oeuf",
        "molo", "pho"), but the database only holds the letters as stored:
        "Weißbrot" never contains "weis". The fragment it is searched by keeps
        the spelling the recipe was typed in."""
        _stock_a_can(db_session, test_user, test_storage_location, name=product, cans=2)
        recipe_id = _recipe_asking_for_grams(
            client,
            auth_headers,
            db_session,
            ingredient_name=ingredient,
            grams='200',
            name='Kolacja',
        )

        found = _availability(client, auth_headers, recipe_id)

        assert found['status'] == 'available_approx'
        assert found['match_type'] == 'fuzzy'

    def test_an_exact_link_still_wins_and_reports_available(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_storage_location: StorageLocation,
        db_session: Session,
    ) -> None:
        template = _stock_a_can(db_session, test_user, test_storage_location)
        payload = {
            'name': 'Curry z linkiem',
            'servings': 1,
            'instructions': 'Mix.',
            'ingredients': [
                {
                    'name': 'Ciecierzyca z puszki',
                    'template_id': str(template.id),
                    'quantity': '400',
                    'uom_id': str(_uom_id(db_session, 'g')),
                    'is_optional': False,
                }
            ],
        }
        response = client.post(RECIPE_URL, json=payload, headers=auth_headers)
        assert response.status_code == 201, response.text

        ingredient = _availability(client, auth_headers, response.json()['id'])

        assert ingredient['status'] == 'available'
        assert ingredient['match_type'] == 'exact'
        assert ingredient['quantities_comparable'] is True

    def test_incomparable_stock_can_still_be_put_on_the_shopping_list(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_storage_location: StorageLocation,
        db_session: Session,
    ) -> None:
        """An exact link with no pack size reads 'available' — but nobody knows
        whether it covers the recipe, so shopping must not treat it as covered."""
        template = _stock_a_can(
            db_session, test_user, test_storage_location, weight_value=None
        )
        payload = {
            'name': 'Curry bez gramatury',
            'servings': 1,
            'instructions': 'Mix.',
            'ingredients': [
                {
                    'name': 'Ciecierzyca z puszki',
                    'template_id': str(template.id),
                    'quantity': '400',
                    'uom_id': str(_uom_id(db_session, 'g')),
                    'is_optional': False,
                }
            ],
        }
        recipe_id = client.post(RECIPE_URL, json=payload, headers=auth_headers).json()[
            'id'
        ]

        ingredient = _availability(client, auth_headers, recipe_id)
        assert ingredient['status'] == 'incomparable'
        assert ingredient['quantities_comparable'] is False

        added = client.post(
            f'{RECIPE_URL}/{recipe_id}/add-to-shopping-list',
            json={'servings': 1},
            headers=auth_headers,
        )
        assert added.status_code == 200, added.text
        assert added.json()['added_count'] == 1


class TestListCardAgreesWithEverythingElse:
    """The card on the list answered "0 of 1" over a full shelf.

    Every other surface — the detail screen, the cooking session, the planner's
    suggestion picker — asks the same availability function and matched the
    ingredient by name. The list endpoint filled the field from its schema
    default, so the one screen a reader sees first was the one that lied.
    """

    def test_list_reports_the_same_availability_as_the_detail_screen(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_storage_location: StorageLocation,
        db_session: Session,
    ) -> None:
        _stock_a_can(db_session, test_user, test_storage_location)
        recipe_id = _recipe_asking_for_grams(
            client,
            auth_headers,
            db_session,
            ingredient_name='ciecierzyca w puszce',
        )

        ingredient = _availability(client, auth_headers, recipe_id)
        assert ingredient['status'] in ('available', 'available_approx')

        listed = client.get(RECIPE_URL, headers=auth_headers)
        assert listed.status_code == 200, listed.text
        card = next(r for r in listed.json()['items'] if r['id'] == recipe_id)
        assert card['ingredients_total'] == 1
        assert card['ingredients_available'] == 1

    def test_list_reports_a_missing_ingredient_as_missing(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_storage_location: StorageLocation,
        db_session: Session,
    ) -> None:
        recipe_id = _recipe_asking_for_grams(
            client,
            auth_headers,
            db_session,
            ingredient_name='nic takiego nie ma na półce',
        )

        listed = client.get(RECIPE_URL, headers=auth_headers)
        assert listed.status_code == 200, listed.text
        card = next(r for r in listed.json()['items'] if r['id'] == recipe_id)
        assert card['ingredients_total'] == 1
        assert card['ingredients_available'] == 0


class TestAlwaysAtHomeIsFlaggedForTheShoppingDoor:
    """The availability payload carries the shopping rule's exclusion verdict.

    The "add missing" door reads this payload while the list behind it
    applies the organization's exclusions — half the rule was mirrored, so
    the button opened on ingredients the list would never add. Measured
    live: one missing, excluded ingredient, the click added zero lines.
    """

    def test_an_ingredient_excluded_by_name_is_flagged(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        db_session: Session,
    ) -> None:
        from app.modules.recipes._name_matching import match_key
        from app.modules.recipes.models import ShoppingExclusion

        db_session.add(
            ShoppingExclusion(
                organization_id=test_user.organization_id,
                name='Fresh Basil',
                name_normalized=match_key('Fresh Basil'),
            )
        )
        db_session.commit()
        recipe_id = _recipe_asking_for_grams(
            client, auth_headers, db_session, ingredient_name='fresh basil'
        )

        ingredient = _availability(client, auth_headers, recipe_id)

        assert ingredient['status'] == 'missing'
        assert ingredient['excluded'] is True

    def test_a_product_excluded_under_another_name_is_flagged(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        db_session: Session,
    ) -> None:
        from app.modules.recipes.models import ShoppingExclusion

        template = ProductTemplate(
            id=uuid.uuid4(),
            organization_id=test_user.organization_id,
            name='Bazylia świeża',
            uom_id=_uom_id(db_session, 'g'),
        )
        db_session.add(template)
        db_session.flush()
        db_session.add(
            ShoppingExclusion(
                organization_id=test_user.organization_id,
                name='Bazylia świeża',
                name_normalized='bazylia swieza',
                template_id=template.id,
            )
        )
        db_session.commit()
        # The recipe's spelling shares no exclusion name; only the product
        # link reaches the exclusion, and the flag must follow it.
        recipe_id = _recipe_asking_for_grams(
            client,
            auth_headers,
            db_session,
            ingredient_name='Bazylia',
            template_id=template.id,
        )

        ingredient = _availability(client, auth_headers, recipe_id)

        assert ingredient['excluded'] is True

    def test_an_ingredient_nobody_excluded_is_not_flagged(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
    ) -> None:
        recipe_id = _recipe_asking_for_grams(
            client, auth_headers, db_session, ingredient_name='fresh basil'
        )

        ingredient = _availability(client, auth_headers, recipe_id)

        assert ingredient['excluded'] is False
