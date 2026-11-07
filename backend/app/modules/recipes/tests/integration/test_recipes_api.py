"""
Integration tests for Recipes API.

Tests:
- POST   /api/recipes         — create recipe
- GET    /api/recipes         — list recipes (search, tags, favorite)
- GET    /api/recipes/{id}    — get single recipe
- PUT    /api/recipes/{id}    — update recipe
- DELETE /api/recipes/{id}    — delete recipe
- GET    /api/recipes/{id}/availability — ingredient availability
- GET    /api/recipes/available         — filtered list by availability
- POST   /api/recipes/{id}/picking/start       — start picking session
- POST   /api/recipes/{id}/picking/{sid}/scan  — scan ingredient
- POST   /api/recipes/{id}/picking/{sid}/complete
- POST   /api/recipes/{id}/picking/{sid}/cancel
- GET    /api/recipes/{id}/nutrition           — ingredient nutrition aggregation
- POST   /api/recipes/{id}/add-to-shopping-list — add missing to shopping list
- GET    /api/recipes/{id}/history             — cooking history
- PATCH  /api/recipes/{id}/history/{sid}       — edit notes/rating
"""

import uuid
import warnings
from decimal import Decimal
from typing import Any, cast

import pytest
from fastapi import status
from sqlalchemy import event, select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.testing import ShelfRow
from app.models.item import Item
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.uom import Uom
from app.models.user import User
from tests.integration._shelf import anchor_pending_records, post_on_shelf

RECIPE_URL = '/api/v1/recipes'

#: Statements a ten-line add may spend. The fixed shape is a handful —
#: recipe, availability, stock, catalogue, list, lines — and the catalogue
#: is one read for the whole page, so ten lines cost what two cost plus the
#: inserts. The shape this replaced resolved the unit with its own query
#: per merged line (measured 49 on this build): a hundred-ingredient
#: recipe paid a hundred reads.
_QUERY_BOUND = 35


def _real_image(fmt: str = 'PNG') -> bytes:
    """A file whose decoder reaches the end of it.

    Correct magic bytes on the front of a truncated file satisfy the
    signature check and nothing after it — a cover is now decoded and written
    out again, so these have to be pictures.
    """
    from io import BytesIO

    from PIL import Image

    buffer = BytesIO()
    Image.new('RGB', (8, 6), (120, 20, 20)).save(buffer, format=fmt)
    return buffer.getvalue()


def _recipe_payload(**overrides: Any) -> dict[str, Any]:
    base = {
        'name': 'Pizza Margherita',
        'description': 'Klasyczna pizza',
        'servings': 2,
        'prep_time_minutes': 30,
        'tags': ['obiad', 'włoskie'],
        'is_favorite': False,
        'ingredients': [],
    }
    base.update(overrides)
    return base


def _item_qty(db_session: Session, item_id: uuid.UUID) -> Decimal:
    """Fetch an item's quantity, asserting it exists (read in picking tests)."""
    item = db_session.scalars(select(Item).where(Item.id == item_id)).first()
    assert item is not None, f'Item {item_id} not found'
    return item.quantity


@pytest.mark.integration
class TestRecipesCRUD:
    def test_create_recipe(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        r = client.post(RECIPE_URL, json=_recipe_payload(), headers=auth_headers)
        assert r.status_code == status.HTTP_201_CREATED
        data = r.json()
        assert data['name'] == 'Pizza Margherita'
        assert data['servings'] == 2
        assert data['tags'] == ['obiad', 'włoskie']
        assert 'id' in data

    def test_create_recipe_with_ingredients(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        payload = _recipe_payload(
            name='Owsianka',
            ingredients=[
                {
                    'name': 'Płatki owsiane',
                    'quantity': '100',
                    'is_optional': False,
                    'sort_order': 0,
                }
            ],
        )
        r = client.post(RECIPE_URL, json=payload, headers=auth_headers)
        assert r.status_code == status.HTTP_201_CREATED
        data = r.json()
        assert len(data['ingredients']) == 1
        assert data['ingredients'][0]['name'] == 'Płatki owsiane'

    def test_create_recipe_with_allergens_and_aggregation(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """EU 1169/2011 allergens round-trip + computed recipe-level union."""
        payload = _recipe_payload(
            name='Mleko z mąką',
            ingredients=[
                {'name': 'Mleko 3,2%', 'quantity': '200', 'allergens': ['milk']},
                {'name': 'Mąka pszenna', 'quantity': '100', 'allergens': ['gluten']},
                {'name': 'Pomidor', 'quantity': '50', 'allergens': []},
            ],
        )
        r = client.post(RECIPE_URL, json=payload, headers=auth_headers)
        assert r.status_code == status.HTTP_201_CREATED
        data = r.json()
        # Canonical order from the closed 14-key list
        assert data['allergens'] == ['gluten', 'milk']
        assert data['ingredients'][0]['allergens'] == ['milk']

        # Computed on read — GET detail reflects the union
        r2 = client.get(f'{RECIPE_URL}/{data["id"]}', headers=auth_headers)
        assert r2.status_code == status.HTTP_200_OK
        assert r2.json()['allergens'] == ['gluten', 'milk']

        # Updating one ingredient changes the aggregate immediately
        r3 = client.put(
            f'{RECIPE_URL}/{data["id"]}',
            json={
                'ingredients': [
                    {'name': 'Pomidor', 'quantity': '50', 'allergens': []},
                ]
            },
            headers=auth_headers,
        )
        assert r3.status_code == status.HTTP_200_OK
        assert r3.json()['allergens'] == []

    def test_create_recipe_rejects_unknown_allergen_key(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        payload = _recipe_payload(
            ingredients=[
                {'name': 'X', 'quantity': '1', 'allergens': ['milk', 'bogus']},
            ],
        )
        r = client.post(RECIPE_URL, json=payload, headers=auth_headers)
        assert r.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_lookup_infers_allergens_from_name(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        r = client.get(
            f'{RECIPE_URL}/ingredient-defaults/lookup',
            params={'name': 'Mleko 2%', 'lang': 'pl'},
            headers=auth_headers,
        )
        assert r.status_code == status.HTTP_200_OK
        assert r.json()['allergens'] == ['milk']

    def test_list_recipes_empty(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        r = client.get(RECIPE_URL, headers=auth_headers)
        assert r.status_code == status.HTTP_200_OK
        data = r.json()
        assert data['items'] == []
        assert data['total'] == 0
        assert data['has_more'] is False

    def test_list_recipes_returns_total_and_sort(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        client.post(
            RECIPE_URL,
            json=_recipe_payload(name='Beta'),
            headers=auth_headers,
        )
        client.post(
            RECIPE_URL,
            json=_recipe_payload(name='Alpha'),
            headers=auth_headers,
        )
        client.post(
            RECIPE_URL,
            json=_recipe_payload(name='Gamma'),
            headers=auth_headers,
        )

        # Paginated envelope carries the real total
        r = client.get(f'{RECIPE_URL}?limit=2&offset=0', headers=auth_headers)
        assert r.status_code == status.HTTP_200_OK
        data = r.json()
        assert len(data['items']) == 2
        assert data['total'] == 3
        assert data['has_more'] is True

        # Name sort
        r = client.get(f'{RECIPE_URL}?sort=name&limit=50', headers=auth_headers)
        assert r.status_code == status.HTTP_200_OK
        names = [item['name'] for item in r.json()['items']]
        assert names == ['Alpha', 'Beta', 'Gamma']

    def test_list_recipes_search(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        client.post(
            RECIPE_URL,
            json=_recipe_payload(name='Pierogi ruskie'),
            headers=auth_headers,
        )
        client.post(
            RECIPE_URL, json=_recipe_payload(name='Bigos'), headers=auth_headers
        )

        r = client.get(f'{RECIPE_URL}?search=pierogi', headers=auth_headers)
        assert r.status_code == status.HTTP_200_OK
        names = [item['name'] for item in r.json()['items']]
        assert any('Pierogi' in n for n in names)
        assert not any('Bigos' in n for n in names)

    def test_list_recipes_filter_favorite(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        client.post(
            RECIPE_URL,
            json=_recipe_payload(name='Ulubiona', is_favorite=True),
            headers=auth_headers,
        )
        client.post(
            RECIPE_URL,
            json=_recipe_payload(name='Zwykła', is_favorite=False),
            headers=auth_headers,
        )

        r = client.get(f'{RECIPE_URL}?is_favorite=true', headers=auth_headers)
        assert r.status_code == status.HTTP_200_OK
        names = [item['name'] for item in r.json()['items']]
        assert 'Ulubiona' in names

    def test_get_recipe(self, client: TestClient, auth_headers: dict[str, str]) -> None:
        create_r = client.post(RECIPE_URL, json=_recipe_payload(), headers=auth_headers)
        recipe_id = create_r.json()['id']

        r = client.get(f'{RECIPE_URL}/{recipe_id}', headers=auth_headers)
        assert r.status_code == status.HTTP_200_OK
        assert r.json()['id'] == recipe_id

    def test_get_recipe_enriches_uom_symbol(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
    ) -> None:
        """GET detail returns uom_symbol next to uom_id.

        The print view reads ``recipe.ingredients[].uom_symbol`` (schema
        declares it "Enriched at read time"), but it came back null because
        the read path never attached the unit relation.
        """
        uom = db_session.scalar(select(Uom).where(Uom.symbol == 'g'))
        assert uom is not None

        create_r = client.post(
            RECIPE_URL,
            json=_recipe_payload(
                ingredients=[
                    {
                        'name': 'Mąka pszenna',
                        'quantity': '300',
                        'uom_id': str(uom.id),
                    },
                ]
            ),
            headers=auth_headers,
        )
        assert create_r.status_code == status.HTTP_201_CREATED
        recipe_id = create_r.json()['id']

        r = client.get(f'{RECIPE_URL}/{recipe_id}', headers=auth_headers)
        assert r.status_code == status.HTTP_200_OK
        ingredient = r.json()['ingredients'][0]
        assert ingredient['uom_id'] == str(uom.id)
        assert ingredient['uom_symbol'] == 'g'

    def test_get_recipe_not_found(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        from uuid import uuid4

        r = client.get(f'{RECIPE_URL}/{uuid4()}', headers=auth_headers)
        assert r.status_code == status.HTTP_404_NOT_FOUND

    def test_update_recipe(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        create_r = client.post(RECIPE_URL, json=_recipe_payload(), headers=auth_headers)
        recipe_id = create_r.json()['id']

        r = client.put(
            f'{RECIPE_URL}/{recipe_id}',
            json={'name': 'Pizza Marinara', 'is_favorite': True},
            headers=auth_headers,
        )
        assert r.status_code == status.HTTP_200_OK
        data = r.json()
        assert data['name'] == 'Pizza Marinara'
        assert data['is_favorite'] is True

    def test_update_recipe_ingredients_returns_fresh(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """PUT with new ingredients must return the updated ingredient list.

        Regression guard: previously the refresh was swallowed in a
        try/except and, with expire_on_commit=False, the stale relationship
        collection could be returned instead of the new ingredients.
        """
        create_r = client.post(
            RECIPE_URL,
            json=_recipe_payload(
                ingredients=[
                    {'name': 'Old flour', 'quantity': '200', 'is_optional': False}
                ]
            ),
            headers=auth_headers,
        )
        recipe_id = create_r.json()['id']

        r = client.put(
            f'{RECIPE_URL}/{recipe_id}',
            json={
                'ingredients': [
                    {'name': 'New flour', 'quantity': '500', 'is_optional': False},
                    {'name': 'New yeast', 'quantity': '10', 'is_optional': False},
                ]
            },
            headers=auth_headers,
        )
        assert r.status_code == status.HTTP_200_OK
        data = r.json()
        names = [ing['name'] for ing in data['ingredients']]
        assert names == ['New flour', 'New yeast']
        assert 'Old flour' not in names

    def test_delete_recipe(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        create_r = client.post(RECIPE_URL, json=_recipe_payload(), headers=auth_headers)
        recipe_id = create_r.json()['id']

        r = client.delete(f'{RECIPE_URL}/{recipe_id}', headers=auth_headers)
        assert r.status_code == status.HTTP_204_NO_CONTENT

        r2 = client.get(f'{RECIPE_URL}/{recipe_id}', headers=auth_headers)
        assert r2.status_code == status.HTTP_404_NOT_FOUND

    def test_duplicate_recipe_copies_fields(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """POST /recipes/{id}/duplicate → deep copy with " (copy)" suffix.

        The copy keeps ingredients/tags/instructions but starts fresh:
        no image_url, no source_url, is_favorite=False, new id.
        """
        create_r = client.post(
            RECIPE_URL,
            json=_recipe_payload(
                name='Pizza',
                description='Opis',
                instructions='Krok 1\nKrok 2',
                is_favorite=True,
                ingredients=[
                    {
                        'name': 'Mąka',
                        'quantity': '300',
                        'is_optional': False,
                        'sort_order': 0,
                    },
                    {
                        'name': 'Ser',
                        'quantity': '150',
                        'is_optional': True,
                        'sort_order': 1,
                    },
                ],
            ),
            headers=auth_headers,
        )
        recipe_id = create_r.json()['id']
        assert create_r.json()['is_favorite'] is True

        r = client.post(f'{RECIPE_URL}/{recipe_id}/duplicate', headers=auth_headers)
        assert r.status_code == status.HTTP_201_CREATED
        data = r.json()

        assert data['id'] != recipe_id
        assert data['name'] == 'Pizza (copy)'
        assert data['description'] == 'Opis'
        assert data['instructions'] == 'Krok 1\nKrok 2'
        assert data['tags'] == ['obiad', 'włoskie']
        assert data['is_favorite'] is False
        assert data['image_url'] is None
        assert data['source_url'] is None
        assert [ing['name'] for ing in data['ingredients']] == ['Mąka', 'Ser']
        assert data['ingredients'][0]['is_optional'] is False
        assert data['ingredients'][1]['is_optional'] is True

        # The original is untouched
        r_orig = client.get(f'{RECIPE_URL}/{recipe_id}', headers=auth_headers)
        assert r_orig.status_code == status.HTTP_200_OK
        assert r_orig.json()['name'] == 'Pizza'
        assert r_orig.json()['is_favorite'] is True

    @pytest.mark.parametrize(
        'source_url',
        [
            'javascript:alert(1)',
            'data:text/html,<script>alert(1)</script>',
            'vbscript:msgbox(1)',
        ],
    )
    def test_create_rejects_non_web_source_url(
        self, client: TestClient, auth_headers: dict[str, str], source_url: str
    ) -> None:
        """`source_url` lands in an href, so only http(s) gets stored."""
        r = client.post(
            RECIPE_URL,
            json=_recipe_payload(source_url=source_url),
            headers=auth_headers,
        )
        assert r.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT, r.text

    def test_create_accepts_a_web_source_url(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        r = client.post(
            RECIPE_URL,
            json=_recipe_payload(source_url='https://example.com/recipe'),
            headers=auth_headers,
        )
        assert r.status_code == status.HTTP_201_CREATED, r.text
        assert r.json()['source_url'] == 'https://example.com/recipe'

    def test_update_cannot_smuggle_a_source_url_past_the_validator(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """`PUT /recipes/{id}` would be the practical path.

        ``RecipeUpdate`` carries no ``source_url`` at all, so the field is not
        editable and the create-time validator is the only way in. Asserted
        here because "the schema happens to omit it" is exactly the kind of
        thing a later edit restores without noticing.
        """
        from app.modules.recipes.schemas import RecipeUpdate

        assert 'source_url' not in RecipeUpdate.model_fields

        created = client.post(
            RECIPE_URL,
            json=_recipe_payload(source_url='https://example.com/recipe'),
            headers=auth_headers,
        )
        recipe_id = created.json()['id']

        r = client.put(
            f'{RECIPE_URL}/{recipe_id}',
            json={'name': 'Renamed', 'source_url': 'javascript:alert(1)'},
            headers=auth_headers,
        )

        assert r.status_code == status.HTTP_200_OK, r.text
        assert r.json()['source_url'] == 'https://example.com/recipe'

    def test_duplicate_recipe_not_found(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        r = client.post(f'{RECIPE_URL}/{uuid.uuid4()}/duplicate', headers=auth_headers)
        assert r.status_code == status.HTTP_404_NOT_FOUND

    def test_bulk_delete_recipes(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        ids = [
            client.post(
                RECIPE_URL, json=_recipe_payload(name=f'Bulk {i}'), headers=auth_headers
            ).json()['id']
            for i in range(3)
        ]

        r = client.post(
            f'{RECIPE_URL}/bulk-delete',
            json={'recipe_ids': ids[:2]},
            headers=auth_headers,
        )
        assert r.status_code == status.HTTP_200_OK
        assert r.json()['deleted'] == 2

        # Deleted recipes are gone, the third one remains
        for deleted_id in ids[:2]:
            r2 = client.get(f'{RECIPE_URL}/{deleted_id}', headers=auth_headers)
            assert r2.status_code == status.HTTP_404_NOT_FOUND
        r3 = client.get(f'{RECIPE_URL}/{ids[2]}', headers=auth_headers)
        assert r3.status_code == status.HTTP_200_OK

    def test_bulk_tag_recipes_appends_and_deduplicates(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        id_a = client.post(
            RECIPE_URL,
            json=_recipe_payload(name='Tag A', tags=['obiad']),
            headers=auth_headers,
        ).json()['id']
        id_b = client.post(
            RECIPE_URL,
            json=_recipe_payload(name='Tag B', tags=[]),
            headers=auth_headers,
        ).json()['id']

        r = client.post(
            f'{RECIPE_URL}/bulk-tag',
            json={'recipe_ids': [id_a, id_b], 'tags': ['obiad', 'Włoskie']},
            headers=auth_headers,
        )
        assert r.status_code == status.HTTP_200_OK
        assert r.json()['updated'] == 2

        # Existing tag kept, new tag appended, case normalized to lowercase
        data_a = client.get(f'{RECIPE_URL}/{id_a}', headers=auth_headers).json()
        assert data_a['tags'] == ['obiad', 'włoskie']
        data_b = client.get(f'{RECIPE_URL}/{id_b}', headers=auth_headers).json()
        assert data_b['tags'] == ['obiad', 'włoskie']

    def test_unauthenticated_request_rejected(self, client: TestClient) -> None:
        """Request without token → 401."""
        r = client.get(RECIPE_URL)
        assert r.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.integration
class TestIngredientDefaultsRouter:
    def test_create_lookup_and_list_ingredient_default(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        payload = {
            'name': 'Buckwheat groats',
            'lang': 'en',
            'calories_kcal': '343',
            'protein_g': '13.3',
            'fat_g': '3.4',
            'carbs_g': '71.5',
        }

        create_response = client.post(
            f'{RECIPE_URL}/ingredient-defaults',
            json=payload,
            headers=auth_headers,
        )
        assert create_response.status_code == status.HTTP_201_CREATED
        created = create_response.json()
        assert created['name'] == 'Buckwheat groats'
        assert created['source'] == 'manual'

        lookup_response = client.get(
            f'{RECIPE_URL}/ingredient-defaults/lookup',
            params={'name': 'buckwheat groats', 'lang': 'en'},
            headers=auth_headers,
        )
        assert lookup_response.status_code == status.HTTP_200_OK
        lookup = lookup_response.json()
        assert lookup['found'] is True
        assert Decimal(lookup['calories_kcal']) == Decimal('343.00')

        list_response = client.get(
            f'{RECIPE_URL}/ingredient-defaults',
            params={'q': 'buckwheat', 'lang': 'en'},
            headers=auth_headers,
        )
        assert list_response.status_code == status.HTTP_200_OK
        data = list_response.json()
        assert data['total'] >= 1
        assert any(item['id'] == created['id'] for item in data['items'])

    def test_the_dictionary_pages_like_every_other_list(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        for name in ('Amaranth', 'Barley', 'Couscous'):
            created = client.post(
                f'{RECIPE_URL}/ingredient-defaults',
                json={'name': name, 'lang': 'en', 'calories_kcal': '100'},
                headers=auth_headers,
            )
            assert created.status_code == status.HTTP_201_CREATED, created.text

        page = client.get(
            f'{RECIPE_URL}/ingredient-defaults',
            params={'lang': 'en', 'limit': 2, 'offset': 1},
            headers=auth_headers,
        ).json()

        assert page['limit'] == 2
        assert page['offset'] == 1
        assert len(page['items']) == 2
        assert page['has_more'] is (page['total'] > 3)
        assert 'page' not in page
        assert 'page_size' not in page

    def test_import_refuses_more_rows_than_the_cap(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """the byte limit alone does not bound the work.

        A few hundred kilobytes of JSON is hundreds of thousands of entries,
        each costing a lookup and an insert inside one request.
        """
        import json as json_module
        from io import BytesIO

        from app.core.upload_validation import MAX_IMPORT_ROWS

        payload = json_module.dumps(
            [
                {'name': f'entry-{i}', 'lang': 'en', 'calories_kcal': '1'}
                for i in range(MAX_IMPORT_ROWS + 1)
            ]
        ).encode()

        r = client.post(
            f'{RECIPE_URL}/ingredient-defaults/import',
            files={'file': ('defaults.json', BytesIO(payload), 'application/json')},
            headers=auth_headers,
        )

        assert r.status_code == status.HTTP_400_BAD_REQUEST, r.text
        assert str(MAX_IMPORT_ROWS) in r.text

    @pytest.mark.parametrize(
        ('filename', 'payload'),
        [
            ('photo.jpg', b'\xff\xd8\xff\xe0\x00\x10JFIF'),
            ('defaults.json', b'{"name": "Millet", "lang": "en"}'),
        ],
    )
    def test_import_names_what_it_expects_when_the_file_is_unreadable(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        filename: str,
        payload: bytes,
    ) -> None:
        """A wrong file is answered with what the import takes, not a parser trace."""
        from io import BytesIO

        r = client.post(
            f'{RECIPE_URL}/ingredient-defaults/import',
            files={'file': (filename, BytesIO(payload), 'application/octet-stream')},
            headers=auth_headers,
        )

        assert r.status_code == status.HTTP_400_BAD_REQUEST, r.text
        detail = r.json()['detail']
        assert detail['code'] == 'INGREDIENT_DEFAULTS_UNREADABLE_FILE'
        assert '.json or .csv' in detail['message']
        assert 'Expecting value' not in detail['message']

    def test_import_accepts_a_file_within_the_cap(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """The cap must not get in the way of a real import."""
        import json as json_module
        from io import BytesIO

        payload = json_module.dumps(
            [{'name': 'Millet flakes', 'lang': 'en', 'calories_kcal': '350'}]
        ).encode()

        r = client.post(
            f'{RECIPE_URL}/ingredient-defaults/import',
            files={'file': ('defaults.json', BytesIO(payload), 'application/json')},
            headers=auth_headers,
        )

        assert r.status_code == status.HTTP_200_OK, r.text

    def test_lookup_falls_back_across_languages(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """nutrition lookup must not depend on the UI language.

        An EN-only entry must still resolve when the UI is PL — the old
        hard lang filter turned nutrition data off after a language switch.
        """
        client.post(
            f'{RECIPE_URL}/ingredient-defaults',
            json={
                'name': 'Owsianka z chia',
                'lang': 'en',
                'calories_kcal': '380',
                'protein_g': '10',
            },
            headers=auth_headers,
        )
        r = client.get(
            f'{RECIPE_URL}/ingredient-defaults/lookup',
            params={'name': 'Owsianka z chia', 'lang': 'pl'},
            headers=auth_headers,
        )
        assert r.status_code == status.HTTP_200_OK
        data = r.json()
        assert data['found'] is True
        assert Decimal(data['calories_kcal']) == Decimal('380.00')

    def test_lookup_prefers_current_language_when_both_exist(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """with entries in both languages the UI language wins."""
        for lang, kcal in (('pl', '400'), ('en', '380')):
            client.post(
                f'{RECIPE_URL}/ingredient-defaults',
                json={
                    'name': 'Kasza jaglana z jablkiem',
                    'lang': lang,
                    'calories_kcal': kcal,
                },
                headers=auth_headers,
            )
        r = client.get(
            f'{RECIPE_URL}/ingredient-defaults/lookup',
            params={'name': 'Kasza jaglana z jablkiem', 'lang': 'pl'},
            headers=auth_headers,
        )
        assert r.status_code == status.HTTP_200_OK
        assert r.json()['found'] is True
        assert Decimal(r.json()['calories_kcal']) == Decimal('400.00')


@pytest.mark.integration
class TestRecipeAvailability:
    def test_availability_no_ingredients(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        create_r = client.post(
            RECIPE_URL, json=_recipe_payload(ingredients=[]), headers=auth_headers
        )
        recipe_id = create_r.json()['id']

        r = client.get(f'{RECIPE_URL}/{recipe_id}/availability', headers=auth_headers)
        assert r.status_code == status.HTTP_200_OK
        data = r.json()
        assert data['match_percentage'] == 1.0
        assert data['ingredients'] == []

    def test_availability_unknown_ingredient(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """An ingredient naming nothing lookupable → 'unknown'."""
        payload = _recipe_payload(
            ingredients=[{'name': '1/2', 'quantity': '1', 'is_optional': False}]
        )
        create_r = client.post(RECIPE_URL, json=payload, headers=auth_headers)
        recipe_id = create_r.json()['id']

        r = client.get(f'{RECIPE_URL}/{recipe_id}/availability', headers=auth_headers)
        assert r.status_code == status.HTTP_200_OK
        ing = r.json()['ingredients'][0]
        assert ing['status'] == 'unknown'
        assert ing['best_item'] is None

    def test_availability_named_ingredient_without_stock_is_missing(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """A nameable ingredient with nothing on the shelf is 'missing', not 'unknown'.

        No template and no group name is the ordinary case for an
        ingredient typed by hand; the name itself is the lookup key, so the
        honest answer is "we have none", not "we cannot tell what this is".
        """
        payload = _recipe_payload(
            ingredients=[
                {'name': 'Szczypta soli', 'quantity': '1', 'is_optional': False}
            ]
        )
        create_r = client.post(RECIPE_URL, json=payload, headers=auth_headers)
        recipe_id = create_r.json()['id']

        r = client.get(f'{RECIPE_URL}/{recipe_id}/availability', headers=auth_headers)
        assert r.status_code == status.HTTP_200_OK
        ing = r.json()['ingredients'][0]
        assert ing['status'] == 'missing'
        assert ing['best_item'] is None

    def test_availability_missing_ingredient(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        db_session: Session,
    ) -> None:
        """Ingredient with template_id but no items in stock → 'missing'."""
        template = ProductTemplate(
            id=uuid.uuid4(),
            organization_id=test_user.organization_id,
            name='Mąka pszenna',
        )
        db_session.add(template)
        db_session.commit()

        payload = _recipe_payload(
            ingredients=[
                {
                    'name': 'Mąka pszenna',
                    'template_id': str(template.id),
                    'quantity': '0.300',
                    'is_optional': False,
                }
            ]
        )
        create_r = client.post(RECIPE_URL, json=payload, headers=auth_headers)
        recipe_id = create_r.json()['id']

        r = client.get(f'{RECIPE_URL}/{recipe_id}/availability', headers=auth_headers)
        assert r.status_code == status.HTTP_200_OK
        ing = r.json()['ingredients'][0]
        assert ing['status'] == 'missing'

    def test_available_recipes_endpoint(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        r = client.get(f'{RECIPE_URL}/available', headers=auth_headers)
        assert r.status_code == status.HTTP_200_OK
        assert isinstance(r.json()['items'], list)

    def test_available_recipes_with_matched_item(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_storage_location: StorageLocation,
        db_session: Session,
    ) -> None:
        """
        Regression: GET /available returned ORM object in dict → PydanticSerializationError.
        Test creates a recipe with template and item in stock, then calls /available.
        """
        template = ProductTemplate(
            id=uuid.uuid4(),
            organization_id=test_user.organization_id,
            name='Mąka pszenna dostępna',
            uom_id=_grams(db_session),
        )
        db_session.add(template)
        db_session.flush()

        item = Item(
            id=uuid.uuid4(),
            organization_id=test_user.organization_id,
            storage_location_id=test_storage_location.id,
            name='Mąka pszenna dostępna',
            template_id=template.id,
            quantity=Decimal('1000'),
            uom_id=_grams(db_session),
        )
        db_session.add(item)
        anchor_pending_records(db_session)
        db_session.commit()

        payload = _recipe_payload(
            name='Chleb',
            servings=1,
            ingredients=[
                {
                    'name': 'Mąka pszenna dostępna',
                    'template_id': str(template.id),
                    'quantity': '500',
                    'is_optional': False,
                }
            ],
        )
        client.post(RECIPE_URL, json=payload, headers=auth_headers)

        r = client.get(f'{RECIPE_URL}/available', headers=auth_headers)
        assert r.status_code == status.HTTP_200_OK
        data = r.json()['items']
        assert isinstance(data, list)
        assert len(data) >= 1
        recipe_entry = next((e for e in data if e['name'] == 'Chleb'), None)
        assert recipe_entry is not None
        # Flat fields (not nested ORM object)
        assert 'id' in recipe_entry
        assert 'match_percentage' in recipe_entry
        assert 'ingredients_available' in recipe_entry

    def test_availability_with_available_item(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_storage_location: StorageLocation,
        db_session: Session,
    ) -> None:
        """Ingredient with item in stock → status 'available', required_quantity rounded."""
        template = ProductTemplate(
            id=uuid.uuid4(),
            organization_id=test_user.organization_id,
            name='Jajka testowe',
            uom_id=_grams(db_session),
        )
        db_session.add(template)
        db_session.flush()

        item = Item(
            id=uuid.uuid4(),
            organization_id=test_user.organization_id,
            storage_location_id=test_storage_location.id,
            name='Jajka testowe',
            template_id=template.id,
            quantity=Decimal('12'),
            uom_id=_grams(db_session),
        )
        db_session.add(item)
        anchor_pending_records(db_session)
        db_session.commit()

        payload = _recipe_payload(
            name='Omlet',
            servings=3,
            ingredients=[
                {
                    'name': 'Jajka testowe',
                    'template_id': str(template.id),
                    'quantity': '2',
                    'is_optional': False,
                }
            ],
        )
        create_r = client.post(RECIPE_URL, json=payload, headers=auth_headers)
        recipe_id = create_r.json()['id']

        # Check for 5 servings (2 * 5/3 = 3.333... → should be 3.333)
        r = client.get(
            f'{RECIPE_URL}/{recipe_id}/availability?servings=5', headers=auth_headers
        )
        assert r.status_code == status.HTTP_200_OK
        ing = r.json()['ingredients'][0]
        assert ing['status'] == 'available'
        # required_quantity must not have more than 3 decimal places
        qty_str = str(ing['required_quantity'])
        decimal_part = qty_str.split('.')[-1] if '.' in qty_str else ''
        assert len(decimal_part) <= 3, f'Too many decimal places: {qty_str}'

    def test_availability_missing_when_insufficient_stock(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_storage_location: StorageLocation,
        db_session: Session,
    ) -> None:
        """
        Stock: 200g flour. Recipe: 300g per 1 serving.
        → status 'insufficient': the flour is there, just not enough of it.
        Reading that as 'missing' sent people shopping for what they had.
        """
        template = ProductTemplate(
            id=uuid.uuid4(),
            organization_id=test_user.organization_id,
            name='Mąka niewystarczająca',
            uom_id=_grams(db_session),
        )
        db_session.add(template)
        db_session.flush()

        item = Item(
            id=uuid.uuid4(),
            organization_id=test_user.organization_id,
            storage_location_id=test_storage_location.id,
            name='Mąka niewystarczająca',
            template_id=template.id,
            quantity=Decimal('200'),
            uom_id=_grams(db_session),
        )
        db_session.add(item)
        anchor_pending_records(db_session)
        db_session.commit()

        payload = _recipe_payload(
            name='Chleb z niedoborem',
            servings=1,
            ingredients=[
                {
                    'name': 'Mąka niewystarczająca',
                    'template_id': str(template.id),
                    'quantity': '300',
                    'is_optional': False,
                }
            ],
        )
        create_r = client.post(RECIPE_URL, json=payload, headers=auth_headers)
        recipe_id = create_r.json()['id']

        r = client.get(f'{RECIPE_URL}/{recipe_id}/availability', headers=auth_headers)
        assert r.status_code == status.HTTP_200_OK
        data = r.json()
        ing = data['ingredients'][0]
        assert ing['status'] == 'insufficient'
        assert ing['available_quantity'] == 200.0
        assert ing['required_quantity'] == 300.0
        assert data['match_percentage'] == 0.0

    def test_availability_missing_when_more_servings_exceed_stock(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_storage_location: StorageLocation,
        db_session: Session,
    ) -> None:
        """
        Stock: 500g pasta. Recipe: 200g for 2 servings.
        - 2 servings → need 200g → 'available' ✓
        - 6 servings → need 600g → 'insufficient' (500 < 600)
        """
        template = ProductTemplate(
            id=uuid.uuid4(),
            organization_id=test_user.organization_id,
            name='Makaron skalowanie',
            uom_id=_grams(db_session),
        )
        db_session.add(template)
        db_session.flush()

        item = Item(
            id=uuid.uuid4(),
            organization_id=test_user.organization_id,
            storage_location_id=test_storage_location.id,
            name='Makaron skalowanie',
            template_id=template.id,
            quantity=Decimal('500'),
            uom_id=_grams(db_session),
        )
        db_session.add(item)
        anchor_pending_records(db_session)
        db_session.commit()

        payload = _recipe_payload(
            name='Makaron skalowany',
            servings=2,
            ingredients=[
                {
                    'name': 'Makaron skalowanie',
                    'template_id': str(template.id),
                    'quantity': '200',
                    'is_optional': False,
                }
            ],
        )
        create_r = client.post(RECIPE_URL, json=payload, headers=auth_headers)
        recipe_id = create_r.json()['id']

        # 2 servings → 200g → should be available
        r2 = client.get(
            f'{RECIPE_URL}/{recipe_id}/availability?servings=2', headers=auth_headers
        )
        assert r2.json()['ingredients'][0]['status'] == 'available'

        # 6 servings → 600g > 500g in stock → not enough
        r6 = client.get(
            f'{RECIPE_URL}/{recipe_id}/availability?servings=6', headers=auth_headers
        )
        assert r6.json()['ingredients'][0]['status'] == 'insufficient'

    def test_availability_available_when_stock_split_across_items(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_storage_location: StorageLocation,
        db_session: Session,
    ) -> None:
        """
        Stock split across 2 items of 150g each = 300g total.
        Recipe requires 250g → sum of items suffices → 'available'.
        """
        template = ProductTemplate(
            id=uuid.uuid4(),
            organization_id=test_user.organization_id,
            name='Ryż podzielony',
            uom_id=_grams(db_session),
        )
        db_session.add(template)
        db_session.flush()

        for qty in [Decimal('150'), Decimal('150')]:
            db_session.add(
                Item(
                    id=uuid.uuid4(),
                    organization_id=test_user.organization_id,
                    storage_location_id=test_storage_location.id,
                    name='Ryż podzielony',
                    template_id=template.id,
                    quantity=qty,
                    uom_id=_grams(db_session),
                )
            )
        anchor_pending_records(db_session)
        db_session.commit()

        payload = _recipe_payload(
            name='Ryż z warzywami',
            servings=1,
            ingredients=[
                {
                    'name': 'Ryż podzielony',
                    'template_id': str(template.id),
                    'quantity': '250',
                    'is_optional': False,
                }
            ],
        )
        create_r = client.post(RECIPE_URL, json=payload, headers=auth_headers)
        recipe_id = create_r.json()['id']

        r = client.get(f'{RECIPE_URL}/{recipe_id}/availability', headers=auth_headers)
        assert r.status_code == status.HTTP_200_OK
        assert r.json()['ingredients'][0]['status'] == 'available'


@pytest.mark.integration
class TestRecipePickingSession:
    """Tests for picking session endpoints."""

    def _create_recipe_with_item(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> tuple[str, Any]:
        """Helper: creates template + item + recipe with that ingredient."""
        grams = _get_uom_id(db_session, 'g')
        assert grams is not None, "'g' is not seeded"
        template = ProductTemplate(
            id=uuid.uuid4(),
            organization_id=test_user.organization_id,
            name='Makaron testowy',
            uom_id=uuid.UUID(grams),
        )
        db_session.add(template)
        db_session.commit()
        record = post_on_shelf(
            client, auth_headers, template, test_storage_location.id, '500'
        )

        payload = _recipe_payload(
            name='Makaron z sosem',
            servings=2,
            ingredients=[
                {
                    'name': 'Makaron testowy',
                    'template_id': str(template.id),
                    'uom_id': grams,
                    'quantity': '200',
                    'is_optional': False,
                }
            ],
        )
        r = client.post(RECIPE_URL, json=payload, headers=auth_headers)
        return r.json()['id'], uuid.UUID(record['id'])

    def test_start_picking_session(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        recipe_id, _ = self._create_recipe_with_item(
            client, auth_headers, db_session, test_user, test_storage_location
        )
        r = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/start',
            json={'servings': 2},
            headers=auth_headers,
        )
        assert r.status_code == 201
        data = r.json()
        assert 'picking_session_id' in data
        assert data['servings'] == 2
        assert len(data['items_to_pick']) == 1
        assert data['items_to_pick'][0]['status'] == 'pending'

    def test_picking_scan_by_item_id(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        """
        Regression: PickingScanResponse was missing session_complete and ingredient_id fields.
        """
        recipe_id, item_id = self._create_recipe_with_item(
            client, auth_headers, db_session, test_user, test_storage_location
        )
        start_r = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/start',
            json={'servings': 2},
            headers=auth_headers,
        )
        session_id = start_r.json()['picking_session_id']

        scan_r = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/{session_id}/scan',
            json={'item_id': str(item_id)},
            headers=auth_headers,
        )
        assert scan_r.status_code == 200
        data = scan_r.json()
        assert data['status'] == 'picked'
        assert data['ingredient_name'] is not None
        assert 'ingredient_id' in data
        assert 'session_complete' in data
        # Only ingredient picked → session should be complete
        assert data['session_complete'] is True

    def test_picking_cancel_once(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        """Canceling a session should return 204."""
        recipe_id, _ = self._create_recipe_with_item(
            client, auth_headers, db_session, test_user, test_storage_location
        )
        start_r = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/start',
            json={'servings': 1},
            headers=auth_headers,
        )
        session_id = start_r.json()['picking_session_id']
        # Try to cancel it
        r = client.delete(
            f'{RECIPE_URL}/{recipe_id}/picking/{session_id}',
            headers=auth_headers,
        )
        assert r.status_code == 204
        # Verify session is actually canceled - trying to scan should fail
        template = ProductTemplate(
            id=uuid.uuid4(), organization_id=test_user.organization_id, name='Test Prod'
        )
        db_session.add(template)
        db_session.flush()
        item = Item(
            id=uuid.uuid4(),
            organization_id=test_user.organization_id,
            storage_location_id=test_storage_location.id,
            name='Test Item',
            template_id=template.id,
            quantity=Decimal('100'),
        )
        db_session.add(item)
        anchor_pending_records(db_session)
        db_session.commit()
        # Try to scan on canceled session - should fail
        scan_r = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/{session_id}/scan',
            json={'item_id': str(item.id)},
            headers=auth_headers,
        )
        assert scan_r.status_code == 404

    def test_picking_scan_by_barcode_from_template(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        """Test scanning barcode existing in ProductTemplate."""
        barcode = '5900000000001'
        template = ProductTemplate(
            id=uuid.uuid4(),
            organization_id=test_user.organization_id,
            name='Produkt z kodem',
            barcode=barcode,
            uom_id=_grams(db_session),
        )
        db_session.add(template)
        db_session.flush()

        item = Item(
            id=uuid.uuid4(),
            organization_id=test_user.organization_id,
            storage_location_id=test_storage_location.id,
            name='Item produktu z kodem',
            template_id=template.id,
            barcode=None,  # no direct barcode on item
            quantity=Decimal('1000'),
            uom_id=_grams(db_session),
        )
        db_session.add(item)
        anchor_pending_records(db_session)
        db_session.commit()

        recipe_payload = _recipe_payload(
            name='Przepis z kodem',
            ingredients=[
                {
                    'name': 'Produkt z kodem',
                    'template_id': str(template.id),
                    'quantity': '100',
                    'is_optional': False,
                }
            ],
        )
        create_recipe_res = client.post(
            RECIPE_URL, json=recipe_payload, headers=auth_headers
        )
        recipe_id = create_recipe_res.json()['id']

        start_res = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/start',
            json={'servings': 1},
            headers=auth_headers,
        )
        session_id = start_res.json()['picking_session_id']

        # Scan the template barcode
        scan_res = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/{session_id}/scan',
            json={'barcode': barcode},
            headers=auth_headers,
        )
        assert scan_res.status_code == 200
        assert scan_res.json()['status'] == 'picked'

    def test_picking_scan_not_in_recipe(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        """Scanning product that is in stock but not in the recipe."""
        recipe_id, _ = self._create_recipe_with_item(
            client, auth_headers, db_session, test_user, test_storage_location
        )

        template_extra = ProductTemplate(
            id=uuid.uuid4(),
            organization_id=test_user.organization_id,
            name='Obcy produkt',
        )
        db_session.add(template_extra)
        db_session.flush()

        item_extra = Item(
            id=uuid.uuid4(),
            organization_id=test_user.organization_id,
            storage_location_id=test_storage_location.id,
            name='Obcy produkt',
            template_id=template_extra.id,
            quantity=Decimal('100'),
        )
        db_session.add(item_extra)
        anchor_pending_records(db_session)
        db_session.commit()

        start_res = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/start',
            json={'servings': 1},
            headers=auth_headers,
        )
        session_id = start_res.json()['picking_session_id']

        scan_res = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/{session_id}/scan',
            json={'item_id': str(item_extra.id)},
            headers=auth_headers,
        )
        assert scan_res.status_code == 200
        assert scan_res.json()['status'] == 'not_in_recipe'
        assert 'not an ingredient' in scan_res.json()['message']

    def test_picking_scan_wrong_barcode(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        """Scanning unknown barcode."""
        recipe_id, _ = self._create_recipe_with_item(
            client, auth_headers, db_session, test_user, test_storage_location
        )
        start_res = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/start',
            json={'servings': 1},
            headers=auth_headers,
        )
        session_id = start_res.json()['picking_session_id']

        scan_res = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/{session_id}/scan',
            json={'barcode': 'unknown-code-999'},
            headers=auth_headers,
        )
        assert scan_res.status_code == 200
        assert scan_res.json()['status'] == 'not_in_recipe'
        assert 'not recognized' in scan_res.json()['message']

    def test_picking_scan_multiple_items_same_ingredient(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        """Scanning same ingredient twice should fail (already_picked)."""
        recipe_id, item_id = self._create_recipe_with_item(
            client, auth_headers, db_session, test_user, test_storage_location
        )
        start_r = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/start',
            json={'servings': 1},
            headers=auth_headers,
        )
        session_id = start_r.json()['picking_session_id']
        # Scan first time
        scan1 = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/{session_id}/scan',
            json={'item_id': str(item_id)},
            headers=auth_headers,
        )
        assert scan1.json()['status'] == 'picked'
        assert scan1.json()['session_complete'] is True
        # Try to scan same item again
        scan2 = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/{session_id}/scan',
            json={'item_id': str(item_id)},
            headers=auth_headers,
        )
        assert scan2.json()['status'] == 'already_picked'
        assert 'already been picked' in scan2.json()['message']

    def test_picking_with_insufficient_quantity(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        """Test when item has less quantity than required (should still mark picked but note info)."""
        template = ProductTemplate(
            id=uuid.uuid4(),
            organization_id=test_user.organization_id,
            name='Insufficient Item',
            uom_id=_grams(db_session),
        )
        db_session.add(template)
        db_session.flush()
        # Only 50g, but need 200g
        item = Item(
            id=uuid.uuid4(),
            organization_id=test_user.organization_id,
            storage_location_id=test_storage_location.id,
            name='Insufficient Item',
            template_id=template.id,
            quantity=Decimal('50'),
            uom_id=_grams(db_session),
        )
        db_session.add(item)
        anchor_pending_records(db_session)
        db_session.commit()
        recipe_id = _create_recipe_with_template(
            client, auth_headers, str(template.id), name='Big Recipe', qty='200'
        )
        start_r = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/start',
            json={'servings': 1},
            headers=auth_headers,
        )
        session_id = start_r.json()['picking_session_id']
        # Scan the item
        scan_r = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/{session_id}/scan',
            json={'item_id': str(item.id)},
            headers=auth_headers,
        )
        assert scan_r.status_code == 200
        assert scan_r.json()['status'] == 'picked'  # Still marked as picked
        # But item_remaining_quantity should reflect partial consumption
        assert scan_r.json()['item_remaining_quantity'] is not None

    def test_picking_partial_then_second_item_completes(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        """Partial pick from item1 then item2 completes the ingredient.

        Regression guard: previously the first (partial) scan marked the
        ingredient as picked and blocked any further scans, even though the
        required quantity was not reached.
        """
        grams = _get_uom_id(db_session, 'g')
        assert grams is not None, "'g' is not seeded"
        template = ProductTemplate(
            id=uuid.uuid4(),
            organization_id=test_user.organization_id,
            name='Partial Flour',
            uom_id=uuid.UUID(grams),
        )
        db_session.add(template)
        db_session.commit()
        pkg1 = post_on_shelf(
            client, auth_headers, template, test_storage_location.id, 50
        )
        pkg2 = post_on_shelf(
            client, auth_headers, template, test_storage_location.id, 200
        )
        item1_id, item2_id = uuid.UUID(pkg1['id']), uuid.UUID(pkg2['id'])

        recipe_id = _create_recipe_with_template(
            client,
            auth_headers,
            str(template.id),
            name='Partial Recipe',
            qty='200',
            uom_id=grams,
        )
        start_r = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/start',
            json={'servings': 1},
            headers=auth_headers,
        )
        session_id = start_r.json()['picking_session_id']
        ingredient_id = start_r.json()['items_to_pick'][0]['ingredient_id']

        # 1) Scan first package — only 50 of 200 needed → partial
        scan1 = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/{session_id}/scan',
            json={'item_id': str(item1_id)},
            headers=auth_headers,
        )
        assert scan1.status_code == 200
        d1 = scan1.json()
        assert d1['status'] == 'picked'
        assert float(d1['quantity_consumed']) == 50.0
        assert d1['session_complete'] is False
        assert d1['ingredient_remaining_quantity'] is not None
        assert float(d1['ingredient_remaining_quantity']) == 150.0

        # 2) Scan second package — consumes the remaining 150 → complete
        scan2 = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/{session_id}/scan',
            json={'item_id': str(item2_id)},
            headers=auth_headers,
        )
        assert scan2.status_code == 200
        d2 = scan2.json()
        assert d2['status'] == 'picked'
        assert float(d2['quantity_consumed']) == 150.0
        assert d2['session_complete'] is True
        assert d2['ingredient_remaining_quantity'] is None

        # Verify stock decremented correctly
        db_session.expire_all()
        q1 = _item_qty(db_session, item1_id)
        q2 = _item_qty(db_session, item2_id)
        assert q1 == Decimal('0')
        assert q2 == Decimal('50')

        # 3) Undo must restore BOTH items (multi-item breakdown)
        undo_r = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/{session_id}/undo',
            json={'ingredient_id': str(ingredient_id)},
            headers=auth_headers,
        )
        assert undo_r.status_code == 200
        assert float(undo_r.json()['restored_quantity']) == 200.0

        db_session.expire_all()
        r1 = _item_qty(db_session, item1_id)
        r2 = _item_qty(db_session, item2_id)
        assert r1 == Decimal('50')
        assert r2 == Decimal('200')

    def test_picking_undo_restores_quantity(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        """Undo should restore consumed quantity and revert status to pending."""
        recipe_id, item_id = self._create_recipe_with_item(
            client, auth_headers, db_session, test_user, test_storage_location
        )
        start_r = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/start',
            json={'servings': 2},
            headers=auth_headers,
        )
        session_id = start_r.json()['picking_session_id']
        ingredient_id = start_r.json()['items_to_pick'][0]['ingredient_id']

        original_qty = _item_qty(db_session, item_id)

        scan_r = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/{session_id}/scan',
            json={'item_id': str(item_id)},
            headers=auth_headers,
        )
        assert scan_r.json()['status'] == 'picked'
        consumed = Decimal(scan_r.json()['quantity_consumed'])

        undo_r = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/{session_id}/undo',
            json={'ingredient_id': str(ingredient_id)},
            headers=auth_headers,
        )
        assert undo_r.status_code == 200
        data = undo_r.json()
        assert float(data['restored_quantity']) == float(consumed)

        db_session.expire_all()
        restored_qty = _item_qty(db_session, item_id)
        assert restored_qty == original_qty

    def test_picking_cancel_restores_consumed_quantity(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        """Cancel after a partial pick must restore consumed stock to inventory.

        Regression guard: previously cancel only flipped session status and
        left already-picked quantities permanently removed from inventory
        (Item.quantity drift).
        """
        recipe_id, item_id = self._create_recipe_with_item(
            client, auth_headers, db_session, test_user, test_storage_location
        )
        start_r = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/start',
            json={'servings': 2},
            headers=auth_headers,
        )
        session_id = start_r.json()['picking_session_id']

        original_qty = _item_qty(db_session, item_id)

        scan_r = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/{session_id}/scan',
            json={'item_id': str(item_id)},
            headers=auth_headers,
        )
        assert scan_r.json()['status'] == 'picked'
        assert Decimal(scan_r.json()['quantity_consumed']) > 0

        cancel_r = client.delete(
            f'{RECIPE_URL}/{recipe_id}/picking/{session_id}',
            headers=auth_headers,
        )
        assert cancel_r.status_code == 204

        db_session.expire_all()
        restored_qty = _item_qty(db_session, item_id)
        assert restored_qty == original_qty

    def test_picking_scan_and_undo_syncs_the_shelf_without_run_async_warning(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        recipe_id, item_id = self._create_recipe_with_item(
            client, auth_headers, db_session, test_user, test_storage_location
        )
        item = db_session.scalars(select(Item).where(Item.id == item_id)).first()
        start_r = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/start',
            json={'servings': 2},
            headers=auth_headers,
        )
        session_id = start_r.json()['picking_session_id']
        ingredient_id = start_r.json()['items_to_pick'][0]['ingredient_id']

        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter('always')
            scan_r = client.post(
                f'{RECIPE_URL}/{recipe_id}/picking/{session_id}/scan',
                json={'item_id': str(item_id)},
                headers=auth_headers,
            )
            assert scan_r.status_code == 200
            undo_r = client.post(
                f'{RECIPE_URL}/{recipe_id}/picking/{session_id}/undo',
                json={'ingredient_id': str(ingredient_id)},
                headers=auth_headers,
            )
            assert undo_r.status_code == 200

        run_async_warnings = [
            warning
            for warning in captured
            if 'run_async() called from within an async context' in str(warning.message)
        ]
        assert run_async_warnings == []

        db_session.expire_all()
        assert item is not None
        shelf = db_session.scalars(
            select(ShelfRow).where(
                ShelfRow.organization_id == test_user.organization_id,
                ShelfRow.product_template_id == item.template_id,
                ShelfRow.storage_location_id == test_storage_location.id,
            )
        ).first()
        restored_item = db_session.scalars(
            select(Item).where(Item.id == item_id)
        ).first()
        assert restored_item is not None
        assert shelf is not None
        assert restored_item.quantity == Decimal('500')
        assert shelf.quantity == Decimal('500')

    def test_picking_undo_not_picked_returns_error(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        """Undo on an unpicked ingredient should return an error."""
        recipe_id, _ = self._create_recipe_with_item(
            client, auth_headers, db_session, test_user, test_storage_location
        )
        start_r = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/start',
            json={'servings': 2},
            headers=auth_headers,
        )
        session_id = start_r.json()['picking_session_id']
        ingredient_id = start_r.json()['items_to_pick'][0]['ingredient_id']

        undo_r = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/{session_id}/undo',
            json={'ingredient_id': str(ingredient_id)},
            headers=auth_headers,
        )
        assert undo_r.status_code in [400, 404]


# ---------------------------------------------------------------------------
# helpers shared between extension tests
# ---------------------------------------------------------------------------


def _create_template_with_nutrition(
    db_session: Session, org_id: Any, name: str
) -> 'ProductTemplate':
    """Creates a ProductTemplate with sample nutrition_info (per 100 g)."""
    template = ProductTemplate(
        id=uuid.uuid4(),
        organization_id=org_id,
        name=name,
        meta_data={
            'nutrition': {
                'calories_kcal': 350.0,
                'protein_g': 12.0,
                'fat_g': 5.0,
                'carbs_g': 65.0,
                'fiber_g': 2.5,
                'sugar_g': 1.0,
                'salt_g': 0.5,
            }
        },
    )
    db_session.add(template)
    db_session.flush()
    return template


def _create_recipe_with_template(
    client: TestClient,
    auth_headers: dict[str, str],
    template_id: str,
    name: str = 'Oatmeal',
    servings: int = 1,
    qty: str = '100',
    uom_id: str | None = None,
) -> str:
    """Creates a recipe whose ingredient is linked to a ProductTemplate."""
    ingredient: dict[str, Any] = {
        'name': 'Test ingredient',
        'template_id': template_id,
        'quantity': qty,
        'is_optional': False,
    }
    if uom_id:
        ingredient['uom_id'] = uom_id
    payload = _recipe_payload(name=name, servings=servings, ingredients=[ingredient])
    r = client.post(RECIPE_URL, json=payload, headers=auth_headers)
    assert r.status_code == 201
    return cast(str, r.json()['id'])


def _get_uom_id(db_session: Session, symbol: str = 'g') -> str | None:
    """Returns the UUID of the UOM with the given symbol, or None if not found."""
    from sqlalchemy import text

    row = db_session.execute(
        text('SELECT id FROM uoms WHERE symbol = :s'), {'s': symbol}
    ).fetchone()
    return str(row[0]) if row else None


def _grams(db_session: Session) -> uuid.UUID:
    """The system unit ``g``, for a product whose stock a recipe line is measured against."""
    grams = _get_uom_id(db_session, 'g')
    assert grams is not None, "'g' is not seeded"
    return uuid.UUID(grams)


@pytest.mark.integration
class TestRecipeNutrition:
    def test_nutrition_returns_structure(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """GET /nutrition on recipe with no ingredients → valid structure, coverage 1.0."""
        create_r = client.post(
            RECIPE_URL, json=_recipe_payload(ingredients=[]), headers=auth_headers
        )
        recipe_id = create_r.json()['id']

        r = client.get(f'{RECIPE_URL}/{recipe_id}/nutrition', headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert 'per_serving' in data
        assert 'total' in data
        assert 'coverage' in data
        assert 'ingredients' in data
        # No ingredients → nothing is missing → coverage defaults to 1.0
        assert data['coverage'] == 1.0

    def test_nutrition_calculates_from_template(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        db_session: Session,
    ) -> None:
        """GET /nutrition with template that has nutrition_info → calories computed."""
        template = _create_template_with_nutrition(
            db_session, test_user.organization_id, 'Nutritional Flour'
        )
        db_session.commit()
        uom_id = _get_uom_id(db_session, 'g')

        recipe_id = _create_recipe_with_template(
            client,
            auth_headers,
            str(template.id),
            name='Nutrition Oatmeal',
            servings=1,
            qty='100',
            uom_id=uom_id,
        )

        r = client.get(f'{RECIPE_URL}/{recipe_id}/nutrition', headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        # 100 g × 350 kcal/100 g = 350 kcal per serving
        assert data['per_serving']['calories_kcal'] == pytest.approx(350.0, abs=1.0)
        assert data['per_serving']['protein_g'] == pytest.approx(12.0, abs=0.5)
        assert data['coverage'] == pytest.approx(1.0)

    def test_nutrition_uses_the_product_the_name_resolves_to(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        db_session: Session,
    ) -> None:
        """No hard link: the matched product beats a default keyed on the name.

        The ingredient is spelled differently from the catalogue entry, so
        before the matcher this fell straight through to generic defaults —
        or to nothing at all — while the real product's data sat unused.
        """
        _create_template_with_nutrition(
            db_session, test_user.organization_id, 'Maka pszenna typ 550'
        )
        db_session.commit()
        uom_id = _get_uom_id(db_session, 'g')

        recipe_id = client.post(
            RECIPE_URL,
            json=_recipe_payload(
                name='Naleśniki bez linku',
                servings=1,
                ingredients=[
                    {
                        'name': 'Mąka pszenna',
                        'quantity': '100',
                        'uom_id': uom_id,
                        'is_optional': False,
                    }
                ],
            ),
            headers=auth_headers,
        ).json()['id']

        r = client.get(f'{RECIPE_URL}/{recipe_id}/nutrition', headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert data['per_serving']['calories_kcal'] == pytest.approx(350.0, abs=1.0)
        assert data['per_serving']['protein_g'] == pytest.approx(12.0, abs=0.5)
        assert data['coverage'] == pytest.approx(1.0)

    def test_nutrition_scales_with_servings_param(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        db_session: Session,
    ) -> None:
        """GET /nutrition?servings=2 → total == 2 × per_serving."""
        template = _create_template_with_nutrition(
            db_session, test_user.organization_id, 'Nutritional Rice'
        )
        db_session.commit()
        uom_id = _get_uom_id(db_session, 'g')

        recipe_id = _create_recipe_with_template(
            client,
            auth_headers,
            str(template.id),
            name='Rice Nutrition Scaling',
            servings=1,
            qty='100',
            uom_id=uom_id,
        )

        r2 = client.get(
            f'{RECIPE_URL}/{recipe_id}/nutrition?servings=2', headers=auth_headers
        )
        assert r2.status_code == 200
        data = r2.json()
        assert data['total']['calories_kcal'] == pytest.approx(
            data['per_serving']['calories_kcal'] * 2, abs=1.0
        )

    def test_nutrition_coverage_partial(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        db_session: Session,
    ) -> None:
        """One ingredient with data, one without → coverage == 0.5."""
        template = _create_template_with_nutrition(
            db_session, test_user.organization_id, 'Golden Egg'
        )
        db_session.commit()
        uom_id = _get_uom_id(db_session, 'g')

        payload = _recipe_payload(
            name='Omelette Coverage Test',
            servings=1,
            ingredients=[
                {
                    'name': 'Golden Egg',
                    'template_id': str(template.id),
                    'quantity': '100',
                    'uom_id': uom_id,
                    'is_optional': False,
                },
                {
                    'name': 'Sea Salt',
                    'quantity': '5',
                    'is_optional': False,
                },
            ],
        )
        r = client.post(RECIPE_URL, json=payload, headers=auth_headers)
        recipe_id = r.json()['id']

        rn = client.get(f'{RECIPE_URL}/{recipe_id}/nutrition', headers=auth_headers)
        assert rn.status_code == 200
        assert rn.json()['coverage'] == pytest.approx(0.5)

    def test_nutrition_fallback_to_template_weight(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        db_session: Session,
    ) -> None:
        """A counted unit on a product with weight_value → fallback to its weight."""
        # Template: 1 unit = 500g
        template = _create_template_with_nutrition(
            db_session, test_user.organization_id, 'Heavy Bread'
        )
        template.weight_value = Decimal('500')
        uom_id = _get_uom_id(db_session, 'g')
        assert uom_id is not None
        template.weight_uom_id = uuid.UUID(uom_id)
        db_session.commit()

        # Recipe: 1 piece
        recipe_id = _create_recipe_with_template(
            client,
            auth_headers,
            str(template.id),
            name='Bread Nutrition Fallback',
            servings=1,
            qty='1',
            uom_id=_get_uom_id(db_session, 'pcs'),
        )

        r = client.get(f'{RECIPE_URL}/{recipe_id}/nutrition', headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        # 500g bread * 350 kcal/100g = 1750 kcal
        assert data['total']['calories_kcal'] == pytest.approx(1750.0, abs=5.0)


@pytest.mark.integration
class TestRecipeShoppingList:
    def test_add_missing_creates_new_list(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        db_session: Session,
    ) -> None:
        """POST /add-to-shopping-list creates a new list and adds missing ingredients."""
        template = ProductTemplate(
            id=uuid.uuid4(),
            organization_id=test_user.organization_id,
            name='Missing Ingredient',
        )
        db_session.add(template)
        db_session.commit()

        recipe_id = _create_recipe_with_template(
            client,
            auth_headers,
            str(template.id),
            name='Recipe Missing Item',
            qty='200',
        )

        r = client.post(
            f'{RECIPE_URL}/{recipe_id}/add-to-shopping-list',
            json={'servings': 1},
            headers=auth_headers,
        )
        assert r.status_code == 200
        data = r.json()
        assert data['added_count'] == 1
        assert 'shopping_list_id' in data
        assert data['shopping_list_id'] is not None
        # A shopping list, named as one: called after the recipe, it went on
        # to receive every other recipe's missing goods under that name.
        assert data['list_name'] == 'Shopping list'

    def test_the_adds_query_count_does_not_grow_with_the_line_count(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        db_session: Session,
        async_engine_fixture: Any,
    ) -> None:
        """The add's statement count stays put while the recipe grows lines.

        Rounding reads the unit's step, and the loop used to resolve the
        unit per merged line with its own query — the request's query count
        grew with the ingredient count (a recipe may name a hundred). A
        count of one reader's calls is the narrower pin: it stays green
        when the same query moves anywhere else on the line. The bound
        below is on the request's own statements, counted on the engine the
        request runs on and nothing else. It sits at the count the path spends
        today (35, measured), so a read added at any step of the path fails
        it, not only this exact function; when the path gets cheaper the
        bound must come down with it, or the room left spends the next
        addition unseen.
        """
        g_id = _get_uom_id(db_session, 'g')
        assert g_id is not None
        ingredients = [
            {
                'name': f'Counted Ingredient {n}',
                'quantity': '200',
                'uom_id': g_id,
                'is_optional': False,
            }
            for n in range(10)
        ]
        r = client.post(
            RECIPE_URL,
            json=_recipe_payload(
                name='Recipe With Units', servings=1, ingredients=ingredients
            ),
            headers=auth_headers,
        )
        assert r.status_code == 201, r.text
        recipe_id = r.json()['id']

        statements = {'count': 0}

        def _count_statement(*_args: Any) -> None:
            statements['count'] += 1

        # The request runs on the fixture's async engine, so the counter sits
        # on that engine alone — not on the Engine class, where any other
        # engine's activity inside the window would count against the bound.
        # Only the POST runs inside the window; the fixture writes are done.
        request_engine = async_engine_fixture.sync_engine
        event.listen(request_engine, 'before_cursor_execute', _count_statement)
        try:
            r = client.post(
                f'{RECIPE_URL}/{recipe_id}/add-to-shopping-list',
                json={'servings': 1},
                headers=auth_headers,
            )
        finally:
            event.remove(request_engine, 'before_cursor_execute', _count_statement)
        assert r.status_code == 200, r.text
        assert r.json()['added_count'] == 10

        assert statements['count'] <= _QUERY_BOUND, (
            f'{statements["count"]} statements for a ten-line add — the '
            'request is paying per line again'
        )

    def test_add_missing_to_existing_list(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        db_session: Session,
    ) -> None:
        """POST /add-to-shopping-list appends to an existing list."""
        from app.modules.shopping_lists.models import ShoppingList

        existing_list = ShoppingList(
            organization_id=test_user.organization_id,
            created_by=test_user.id,
            name='My List',
        )
        db_session.add(existing_list)
        db_session.commit()
        db_session.refresh(existing_list)

        template = ProductTemplate(
            id=uuid.uuid4(),
            organization_id=test_user.organization_id,
            name='Existing List Ingredient',
        )
        db_session.add(template)
        db_session.commit()

        recipe_id = _create_recipe_with_template(
            client, auth_headers, str(template.id), name='Recipe For List', qty='100'
        )

        r = client.post(
            f'{RECIPE_URL}/{recipe_id}/add-to-shopping-list',
            json={'shopping_list_id': str(existing_list.id), 'servings': 1},
            headers=auth_headers,
        )
        assert r.status_code == 200
        data = r.json()
        assert data['shopping_list_id'] == str(existing_list.id)
        assert data['added_count'] == 1
        assert data['list_name'] == 'My List'

    def test_add_missing_twice_skips_existing_items(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        db_session: Session,
    ) -> None:
        """re-adding missing ingredients to the same list must not
        duplicate rows already present on that list."""
        from app.modules.shopping_lists.models import ShoppingList

        existing_list = ShoppingList(
            organization_id=test_user.organization_id,
            created_by=test_user.id,
            name='Dedup List',
        )
        db_session.add(existing_list)
        db_session.commit()
        db_session.refresh(existing_list)

        template = ProductTemplate(
            id=uuid.uuid4(),
            organization_id=test_user.organization_id,
            name='Dedup Ingredient',
        )
        db_session.add(template)
        db_session.commit()

        recipe_id = _create_recipe_with_template(
            client, auth_headers, str(template.id), name='Recipe Dedup', qty='100'
        )

        url = f'{RECIPE_URL}/{recipe_id}/add-to-shopping-list'
        payload = {'shopping_list_id': str(existing_list.id), 'servings': 1}

        r1 = client.post(url, json=payload, headers=auth_headers)
        assert r1.status_code == 200
        assert r1.json()['added_count'] == 1

        r2 = client.post(url, json=payload, headers=auth_headers)
        assert r2.status_code == 200
        assert r2.json()['added_count'] == 0

        items_r = client.get(
            f'/api/v1/shopping-lists/{existing_list.id}/items',
            headers=auth_headers,
        )
        assert items_r.status_code == 200
        assert len(items_r.json()['items']) == 1

    def test_add_missing_when_all_available_returns_400(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_storage_location: StorageLocation,
        db_session: Session,
    ) -> None:
        """When all ingredients are in stock and no list_id given → 400."""
        template = ProductTemplate(
            id=uuid.uuid4(),
            organization_id=test_user.organization_id,
            name='In Stock Ingredient',
            uom_id=_grams(db_session),
        )
        db_session.add(template)
        db_session.flush()

        db_session.add(
            Item(
                id=uuid.uuid4(),
                organization_id=test_user.organization_id,
                storage_location_id=test_storage_location.id,
                name='In Stock Ingredient',
                template_id=template.id,
                quantity=Decimal('500'),
                uom_id=_grams(db_session),
            )
        )
        anchor_pending_records(db_session)
        db_session.commit()

        recipe_id = _create_recipe_with_template(
            client, auth_headers, str(template.id), name='Recipe No Gaps', qty='100'
        )

        r = client.post(
            f'{RECIPE_URL}/{recipe_id}/add-to-shopping-list',
            json={'servings': 1},
            headers=auth_headers,
        )
        assert r.status_code == 400

    def test_add_missing_unknown_shopping_list_404(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        db_session: Session,
    ) -> None:
        """Non-existent shopping_list_id → 404."""
        template = ProductTemplate(
            id=uuid.uuid4(),
            organization_id=test_user.organization_id,
            name='Ingredient 404',
        )
        db_session.add(template)
        db_session.commit()

        recipe_id = _create_recipe_with_template(
            client, auth_headers, str(template.id), name='Recipe 404 List', qty='100'
        )

        r = client.post(
            f'{RECIPE_URL}/{recipe_id}/add-to-shopping-list',
            json={'shopping_list_id': str(uuid.uuid4()), 'servings': 1},
            headers=auth_headers,
        )
        assert r.status_code == 404

    def test_add_missing_notes_follow_request_language(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        db_session: Session,
    ) -> None:
        """item notes and error-language follow the request language."""
        template = ProductTemplate(
            id=uuid.uuid4(),
            organization_id=test_user.organization_id,
            name='Localized Note Ingredient',
        )
        db_session.add(template)
        db_session.commit()

        recipe_id = _create_recipe_with_template(
            client,
            auth_headers,
            str(template.id),
            name='Recipe Localized Notes',
            qty='200',
        )

        pl_headers = {**auth_headers, 'Accept-Language': 'pl'}
        r = client.post(
            f'{RECIPE_URL}/{recipe_id}/add-to-shopping-list',
            json={'servings': 1},
            headers=pl_headers,
        )
        assert r.status_code == 200
        data = r.json()
        list_id = data['shopping_list_id']
        assert data['added_count'] == 1

        items_r = client.get(
            f'/api/v1/shopping-lists/{list_id}/items', headers=pl_headers
        )
        assert items_r.status_code == 200
        items = items_r.json()['items']
        assert len(items) == 1
        # Server-generated notes must be in the request language, not English.
        assert items[0]['notes'] == 'Do przepisu: Recipe Localized Notes'

    def test_add_missing_preserves_ingredient_uom(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        db_session: Session,
    ) -> None:
        """Ingredient UoM (e.g. grams) must reach the shopping list item
        and be returned as a joined uom object on subsequent GET."""
        uom_id = _get_uom_id(db_session, 'g')
        assert uom_id is not None, 'system uom "g" must be seeded'

        template = ProductTemplate(
            id=uuid.uuid4(),
            organization_id=test_user.organization_id,
            name='Recipe Grams Ingredient',
        )
        db_session.add(template)
        db_session.commit()

        recipe_id = _create_recipe_with_template(
            client,
            auth_headers,
            str(template.id),
            name='Recipe Grams',
            qty='200',
            uom_id=uom_id,
        )

        r = client.post(
            f'{RECIPE_URL}/{recipe_id}/add-to-shopping-list',
            json={'servings': 1},
            headers=auth_headers,
        )
        assert r.status_code == 200
        data = r.json()
        assert data['added_count'] == 1
        list_id = data['shopping_list_id']

        # Re-fetch the items via the items endpoint — it returns the full
        # ShoppingListItem schema (with joined uom).
        items_r = client.get(
            f'/api/v1/shopping-lists/{list_id}/items',
            headers=auth_headers,
        )
        assert items_r.status_code == 200, items_r.text
        items = items_r.json()['items']
        assert len(items) == 1
        added = items[0]
        assert added['uom_id'] == uom_id
        assert added['uom'] is not None
        assert added['uom']['symbol'] == 'g'
        assert added['name'] == 'Test ingredient'


@pytest.mark.integration
class TestCookingHistory:
    def _complete_session(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> tuple[str, str]:
        """Helper: creates a recipe, starts and completes a session. Returns (recipe_id, session_id)."""
        template = ProductTemplate(
            id=uuid.uuid4(),
            organization_id=test_user.organization_id,
            name='History Ingredient',
            uom_id=_grams(db_session),
        )
        db_session.add(template)
        db_session.flush()

        item = Item(
            id=uuid.uuid4(),
            organization_id=test_user.organization_id,
            storage_location_id=test_storage_location.id,
            name='History Ingredient',
            template_id=template.id,
            quantity=Decimal('500'),
            uom_id=_grams(db_session),
        )
        db_session.add(item)
        anchor_pending_records(db_session)
        db_session.commit()

        recipe_id = _create_recipe_with_template(
            client,
            auth_headers,
            str(template.id),
            name='Recipe With History',
            qty='100',
        )

        start_r = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/start',
            json={'servings': 1},
            headers=auth_headers,
        )
        session_id = start_r.json()['picking_session_id']

        # Pick ingredient and complete session
        client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/{session_id}/scan',
            json={'item_id': str(item.id)},
            headers=auth_headers,
        )
        client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/{session_id}/complete',
            headers=auth_headers,
        )
        return recipe_id, session_id

    def test_history_empty_before_completing(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """GET /history on a new recipe → empty list."""
        create_r = client.post(
            RECIPE_URL, json=_recipe_payload(ingredients=[]), headers=auth_headers
        )
        recipe_id = create_r.json()['id']

        r = client.get(f'{RECIPE_URL}/{recipe_id}/history', headers=auth_headers)
        assert r.status_code == 200
        assert r.json()['items'] == []

    def test_history_shows_completed_session(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        """Completed session appears in history with correct fields."""
        recipe_id, session_id = self._complete_session(
            client, auth_headers, db_session, test_user, test_storage_location
        )

        r = client.get(f'{RECIPE_URL}/{recipe_id}/history', headers=auth_headers)
        assert r.status_code == 200
        items = r.json()['items']
        assert len(items) == 1
        entry = items[0]
        assert entry['session_id'] == session_id
        assert entry['servings'] == 1
        assert entry['items_picked'] == 1
        assert entry['items_skipped'] == 0
        assert entry['notes'] is None
        assert entry['rating'] is None

    def test_history_in_progress_session_not_included(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        """An in-progress (not completed) session must not appear in history."""
        template = ProductTemplate(
            id=uuid.uuid4(),
            organization_id=test_user.organization_id,
            name='In Progress Ingredient',
        )
        db_session.add(template)
        db_session.flush()

        db_session.add(
            Item(
                id=uuid.uuid4(),
                organization_id=test_user.organization_id,
                storage_location_id=test_storage_location.id,
                name='In Progress Ingredient',
                template_id=template.id,
                quantity=Decimal('300'),
            )
        )
        anchor_pending_records(db_session)
        db_session.commit()

        recipe_id = _create_recipe_with_template(
            client, auth_headers, str(template.id), name='In Progress Recipe', qty='100'
        )

        # Start session but do not complete it
        client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/start',
            json={'servings': 1},
            headers=auth_headers,
        )

        r = client.get(f'{RECIPE_URL}/{recipe_id}/history', headers=auth_headers)
        assert r.status_code == 200
        assert r.json()['items'] == []

    def test_patch_history_adds_notes_and_rating(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        """PATCH /history/{sid} saves notes and rating, returns updated object."""
        recipe_id, session_id = self._complete_session(
            client, auth_headers, db_session, test_user, test_storage_location
        )

        r = client.patch(
            f'{RECIPE_URL}/{recipe_id}/history/{session_id}',
            json={'notes': 'Came out great!', 'rating': 5},
            headers=auth_headers,
        )
        assert r.status_code == 200
        data = r.json()
        assert data['notes'] == 'Came out great!'
        assert data['rating'] == 5
        assert data['session_id'] == session_id

    def test_patch_history_invalid_rating_422(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        """Rating > 5 → 422."""
        recipe_id, session_id = self._complete_session(
            client, auth_headers, db_session, test_user, test_storage_location
        )

        r = client.patch(
            f'{RECIPE_URL}/{recipe_id}/history/{session_id}',
            json={'rating': 10},
            headers=auth_headers,
        )
        assert r.status_code == 422

    def test_patch_history_unknown_session_404(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Non-existent session_id → 404."""
        create_r = client.post(
            RECIPE_URL, json=_recipe_payload(ingredients=[]), headers=auth_headers
        )
        recipe_id = create_r.json()['id']

        r = client.patch(
            f'{RECIPE_URL}/{recipe_id}/history/{uuid.uuid4()}',
            json={'notes': 'Test'},
            headers=auth_headers,
        )
        assert r.status_code == 404

    def test_patch_history_clears_notes(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        """PATCH with notes=null must clear the existing note."""
        recipe_id, session_id = self._complete_session(
            client, auth_headers, db_session, test_user, test_storage_location
        )

        # First set a note
        client.patch(
            f'{RECIPE_URL}/{recipe_id}/history/{session_id}',
            json={'notes': 'To be removed'},
            headers=auth_headers,
        )

        r = client.patch(
            f'{RECIPE_URL}/{recipe_id}/history/{session_id}',
            json={'notes': None},
            headers=auth_headers,
        )
        assert r.status_code == 200
        assert r.json()['notes'] is None


@pytest.mark.integration
class TestRecipeImageUpload:
    """Tests for recipe image upload/delete endpoints (coverage for router lines 456+)."""

    def test_upload_recipe_image(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """POST /recipes/{id}/image - upload recipe cover image."""
        create_r = client.post(
            RECIPE_URL, json=_recipe_payload(ingredients=[]), headers=auth_headers
        )
        recipe_id = create_r.json()['id']

        from io import BytesIO

        image_data = BytesIO(_real_image('PNG'))

        r = client.post(
            f'{RECIPE_URL}/{recipe_id}/image',
            files={'image': ('test.png', image_data, 'image/png')},
            headers=auth_headers,
        )
        assert r.status_code == 200
        assert 'image_url' in r.json()

    def test_stored_extension_comes_from_the_mime_not_the_filename(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """the upload used to name the stored file after whatever the
        client called it, so `cover.php`/`cover.svg` could land in the storage
        backend and be served back. The extension now follows the validated
        content type, which the magic bytes have to agree with.
        """
        from io import BytesIO

        create_r = client.post(
            RECIPE_URL, json=_recipe_payload(ingredients=[]), headers=auth_headers
        )
        recipe_id = create_r.json()['id']
        png = BytesIO(_real_image('PNG'))

        r = client.post(
            f'{RECIPE_URL}/{recipe_id}/image',
            files={'image': ('payload.svg', png, 'image/png')},
            headers=auth_headers,
        )

        assert r.status_code == 200, r.text
        url = r.json()['image_url']
        assert url.endswith('.png'), url
        assert '.svg' not in url

    def test_upload_refused_when_the_file_stops_before_the_picture_does(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Right magic bytes, nothing behind them.

        The signature check reads the first few bytes and the file passed it;
        the cover is now decoded and written out again, so a file that ends
        mid-picture is refused instead of being stored and served as a broken
        frame.
        """
        from io import BytesIO

        create_r = client.post(
            RECIPE_URL, json=_recipe_payload(ingredients=[]), headers=auth_headers
        )
        recipe_id = create_r.json()['id']
        truncated = BytesIO(_real_image('PNG')[:20])

        r = client.post(
            f'{RECIPE_URL}/{recipe_id}/image',
            files={'image': ('half.png', truncated, 'image/png')},
            headers=auth_headers,
        )

        assert r.status_code == 400, r.text

    def test_upload_refused_when_bytes_contradict_the_content_type(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """The MIME alone is client-supplied — the magic bytes decide."""
        from io import BytesIO

        create_r = client.post(
            RECIPE_URL, json=_recipe_payload(ingredients=[]), headers=auth_headers
        )
        recipe_id = create_r.json()['id']

        r = client.post(
            f'{RECIPE_URL}/{recipe_id}/image',
            files={
                'image': (
                    'cover.png',
                    BytesIO(b'<svg onload="alert(1)"></svg>'),
                    'image/png',
                )
            },
            headers=auth_headers,
        )

        assert r.status_code == 400, r.text

    def test_delete_recipe_image(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """DELETE /recipes/{id}/image - delete recipe cover image."""
        create_r = client.post(
            RECIPE_URL, json=_recipe_payload(ingredients=[]), headers=auth_headers
        )
        recipe_id = create_r.json()['id']

        r = client.delete(
            f'{RECIPE_URL}/{recipe_id}/image',
            headers=auth_headers,
        )
        assert r.status_code == 204


@pytest.mark.integration
class TestRecipeEdgeCases:
    """Tests for edge cases and error conditions to improve coverage."""

    def test_get_availability_with_multiple_optional_ingredients(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
    ) -> None:
        """Test availability calculation with optional ingredients (match % should exclude them)."""
        template_required = ProductTemplate(
            id=uuid.uuid4(),
            organization_id=test_user.organization_id,
            name='Required Item',
        )
        template_optional = ProductTemplate(
            id=uuid.uuid4(),
            organization_id=test_user.organization_id,
            name='Optional Item',
        )
        db_session.add_all([template_required, template_optional])
        db_session.flush()
        db_session.commit()

        payload = _recipe_payload(
            name='Mixed Recipe',
            ingredients=[
                {
                    'name': 'Required Item',
                    'template_id': str(template_required.id),
                    'quantity': '100',
                    'is_optional': False,
                },
                {
                    'name': 'Optional Item',
                    'template_id': str(template_optional.id),
                    'quantity': '50',
                    'is_optional': True,
                },
            ],
        )
        create_r = client.post(RECIPE_URL, json=payload, headers=auth_headers)
        recipe_id = create_r.json()['id']

        r = client.get(f'{RECIPE_URL}/{recipe_id}/availability', headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        # match_percentage should be 0 (no required items available)
        assert data['match_percentage'] == 0.0

    def test_list_recipes_with_multiple_tags(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Test listing recipes with various tag combinations."""
        for i in range(3):
            client.post(
                RECIPE_URL,
                json=_recipe_payload(
                    name=f'PastaRecipe{i}',
                    tags=['pasta', 'italian', 'dinner']
                    if i % 2 == 0
                    else ['soup', 'light'],
                ),
                headers=auth_headers,
            )

        r = client.get(f'{RECIPE_URL}?search=Pasta', headers=auth_headers)
        assert r.status_code == 200
        names = [item['name'] for item in r.json()['items']]
        # Should find pasta recipes by name search
        pasta_recipes = [n for n in names if 'Pasta' in n]
        assert len(pasta_recipes) >= 1


# ---------------------------------------------------------------------------
# Import / Export
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestRecipeExport:
    def test_export_json_returns_200(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Export as internal JSON format."""
        r = client.post(
            RECIPE_URL, json=_recipe_payload(name='Export Test'), headers=auth_headers
        )
        recipe_id = r.json()['id']

        r = client.get(
            f'{RECIPE_URL}/{recipe_id}/export?format=json', headers=auth_headers
        )
        assert r.status_code == 200
        data = r.json()
        assert data['name'] == 'Export Test'
        assert data['servings'] == 2
        assert 'ingredients' in data
        assert '_export_version' in data

    def test_export_schema_org_returns_200(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Export as Schema.org Recipe format."""
        r = client.post(
            RECIPE_URL,
            json=_recipe_payload(name='Schema Org Test'),
            headers=auth_headers,
        )
        recipe_id = r.json()['id']

        r = client.get(
            f'{RECIPE_URL}/{recipe_id}/export?format=schema_org', headers=auth_headers
        )
        assert r.status_code == 200
        data = r.json()
        assert data['@type'] == 'Recipe'
        assert data['name'] == 'Schema Org Test'
        assert '@context' in data

    def test_export_invalid_format_returns_400(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        r = client.post(RECIPE_URL, json=_recipe_payload(), headers=auth_headers)
        recipe_id = r.json()['id']

        r = client.get(
            f'{RECIPE_URL}/{recipe_id}/export?format=xml', headers=auth_headers
        )
        assert r.status_code == 400

    def test_export_not_found_returns_404(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        r = client.get(
            f'{RECIPE_URL}/{uuid.uuid4()}/export?format=json', headers=auth_headers
        )
        assert r.status_code == 404

    def test_export_json_includes_ingredients(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Exported JSON includes full ingredient list."""
        payload = _recipe_payload(
            name='Pasta Carbonara',
            ingredients=[
                {'name': 'Spaghetti', 'quantity': '200', 'is_optional': False},
                {'name': 'Jajka', 'quantity': '3', 'is_optional': False},
            ],
        )
        r = client.post(RECIPE_URL, json=payload, headers=auth_headers)
        recipe_id = r.json()['id']

        r = client.get(
            f'{RECIPE_URL}/{recipe_id}/export?format=json', headers=auth_headers
        )
        assert r.status_code == 200
        exported = r.json()
        assert len(exported['ingredients']) == 2
        names = [i['name'] for i in exported['ingredients']]
        assert 'Spaghetti' in names


@pytest.mark.integration
class TestRecipeImport:
    def test_export_preview_and_reviewed_save_preserve_ingredient_metadata(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """The app previews JSON and creates a reviewed recipe instead of importing directly."""
        ingredients = [
            {
                'name': 'Bay leaf',
                'quantity': 1,
                'is_spice': True,
                'allergens': ['mustard'],
            },
            {
                'name': 'Flour',
                'quantity': 200,
                'is_spice': False,
                'allergens': ['gluten', 'milk'],
            },
            {'name': 'Water', 'quantity': 100, 'is_spice': False, 'allergens': []},
        ]
        created = client.post(
            RECIPE_URL,
            json=_recipe_payload(ingredients=ingredients),
            headers=auth_headers,
        )
        assert created.status_code == 201
        exported = client.get(
            f'{RECIPE_URL}/{created.json()["id"]}/export?format=json',
            headers=auth_headers,
        )
        assert exported.status_code == 200
        preview = client.post(
            f'{RECIPE_URL}/import/preview',
            json={'format': 'json', 'data': exported.json()},
            headers=auth_headers,
        )
        assert preview.status_code == 200
        reviewed = preview.json()['ingredients']
        for actual, expected in zip(reviewed, ingredients, strict=True):
            assert actual['is_spice'] == expected['is_spice']
            assert actual['allergens'] == expected['allergens']
        saved = client.post(
            RECIPE_URL, json=_recipe_payload(ingredients=reviewed), headers=auth_headers
        )
        assert saved.status_code == 201
        reread = client.get(f'{RECIPE_URL}/{saved.json()["id"]}', headers=auth_headers)
        assert reread.status_code == 200
        for actual, expected in zip(
            reread.json()['ingredients'], ingredients, strict=True
        ):
            assert actual['is_spice'] == expected['is_spice']
            assert actual['allergens'] == expected['allergens']

    def test_json_preview_defaults_missing_ingredient_metadata(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.post(
            f'{RECIPE_URL}/import/preview',
            json={
                'format': 'json',
                'data': _recipe_payload(
                    ingredients=[{'name': 'Water', 'quantity': 100}]
                ),
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        for ingredient in response.json()['ingredients']:
            assert ingredient['is_spice'] is False
            assert ingredient['allergens'] == []

    def test_import_from_json_returns_201(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Import a recipe from internal JSON format."""
        import_data = {
            'format': 'json',
            'data': {
                '_export_version': 1,
                'name': 'Imported Recipe',
                'description': 'Imported description',
                'servings': 4,
                'prep_time_minutes': 20,
                'tags': ['import', 'test'],
                'instructions': 'Mix everything.',
                'ingredients': [
                    {
                        'name': 'Flour',
                        'quantity': 200.0,
                        'uom': 'g',
                        'is_optional': False,
                    },
                ],
            },
        }
        r = client.post(f'{RECIPE_URL}/import', json=import_data, headers=auth_headers)
        assert r.status_code == 201
        data = r.json()
        assert data['name'] == 'Imported Recipe'
        assert data['servings'] == 4
        assert data['tags'] == ['import', 'test']

    def test_import_from_json_creates_recipe(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Imported recipe is visible in the list."""
        import_data = {
            'format': 'json',
            'data': {
                '_export_version': 1,
                'name': 'Listed Import',
                'servings': 2,
                'ingredients': [],
            },
        }
        r = client.post(f'{RECIPE_URL}/import', json=import_data, headers=auth_headers)
        assert r.status_code == 201

        list_r = client.get(f'{RECIPE_URL}?search=Listed+Import', headers=auth_headers)
        assert list_r.status_code == 200
        assert any(rec['name'] == 'Listed Import' for rec in list_r.json()['items'])

    def test_import_missing_name_returns_400(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """JSON import without name field → 400 (canonical ValueError mapping)."""
        import_data = {
            'format': 'json',
            'data': {'_export_version': 1, 'servings': 2, 'ingredients': []},
        }
        r = client.post(f'{RECIPE_URL}/import', json=import_data, headers=auth_headers)
        assert r.status_code == 400

    def test_import_invalid_format_returns_400(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Unknown import format → 400."""
        r = client.post(
            f'{RECIPE_URL}/import',
            json={'format': 'csv', 'data': {}},
            headers=auth_headers,
        )
        assert r.status_code == 400

    def test_import_url_invalid_url_returns_400(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Import from invalid URL → 400."""
        r = client.post(
            f'{RECIPE_URL}/import',
            json={'format': 'url', 'url': 'not-a-url'},
            headers=auth_headers,
        )
        assert r.status_code == 400

    def test_import_unauthenticated_rejected(self, client: TestClient) -> None:
        r = client.post(f'{RECIPE_URL}/import', json={})
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# Tag management
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestRecipeTagManagement:
    def test_list_tags_empty(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """GET /tags returns empty list when no recipes."""
        r = client.get(f'{RECIPE_URL}/tags', headers=auth_headers)
        assert r.status_code == 200
        assert r.json()['items'] == []

    def test_list_tags_aggregated_from_recipes(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Tags from multiple recipes are deduplicated and returned."""
        client.post(
            RECIPE_URL,
            json=_recipe_payload(name='R1', tags=['obiad', 'polska']),
            headers=auth_headers,
        )
        client.post(
            RECIPE_URL,
            json=_recipe_payload(name='R2', tags=['obiad', 'szybkie']),
            headers=auth_headers,
        )

        r = client.get(f'{RECIPE_URL}/tags', headers=auth_headers)
        assert r.status_code == 200
        tag_names = [t['name'] for t in r.json()['items']]
        assert 'obiad' in tag_names
        assert 'polska' in tag_names
        assert 'szybkie' in tag_names
        assert tag_names.count('obiad') == 1  # deduplicated

    def test_list_tags_includes_count(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Each tag object has a 'count' field (number of recipes using it)."""
        client.post(
            RECIPE_URL,
            json=_recipe_payload(name='A', tags=['shared']),
            headers=auth_headers,
        )
        client.post(
            RECIPE_URL,
            json=_recipe_payload(name='B', tags=['shared']),
            headers=auth_headers,
        )

        r = client.get(f'{RECIPE_URL}/tags', headers=auth_headers)
        assert r.status_code == 200
        tags_by_name = {t['name']: t for t in r.json()['items']}
        assert tags_by_name['shared']['count'] == 2

    def test_list_tags_counts_follow_the_collection(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """The chips count the view, not the organization.

        A collection showing zero recipes used to keep "obiad 1" on its
        chips — a number that answered for recipes the reader could not
        see, and that clicking turned into zero results.
        """
        inside = client.post(
            RECIPE_URL,
            json=_recipe_payload(name='Inside', tags=['obiad']),
            headers=auth_headers,
        ).json()
        client.post(
            RECIPE_URL,
            json=_recipe_payload(name='Outside', tags=['obiad']),
            headers=auth_headers,
        )
        collection = client.post(
            f'{RECIPE_URL}/collections',
            json={'name': 'Week'},
            headers=auth_headers,
        ).json()
        client.post(
            f'{RECIPE_URL}/collections/{collection["id"]}/recipes',
            json={'recipe_id': inside['id']},
            headers=auth_headers,
        )

        r = client.get(
            f'{RECIPE_URL}/tags',
            params={'collection_id': collection['id']},
            headers=auth_headers,
        )
        assert r.status_code == 200
        tags_by_name = {t['name']: t for t in r.json()['items']}
        assert tags_by_name['obiad']['count'] == 1

    def test_list_tags_counts_follow_the_search(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Counts narrow with a search the same way the list does."""
        client.post(
            RECIPE_URL,
            json=_recipe_payload(name='Pasta', tags=['obiad']),
            headers=auth_headers,
        )
        client.post(
            RECIPE_URL,
            json=_recipe_payload(name='Pizza', tags=['obiad']),
            headers=auth_headers,
        )

        r = client.get(
            f'{RECIPE_URL}/tags',
            params={'search': 'past'},
            headers=auth_headers,
        )
        assert r.status_code == 200
        tags_by_name = {t['name']: t for t in r.json()['items']}
        assert tags_by_name['obiad']['count'] == 1

    def test_patch_tag_color(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """PATCH /tags/{name}/color sets a color for a tag."""
        client.post(
            RECIPE_URL,
            json=_recipe_payload(name='ColorRecipe', tags=['lunch']),
            headers=auth_headers,
        )

        r = client.patch(
            f'{RECIPE_URL}/tags/lunch/color',
            json={'color': '#FF5733'},
            headers=auth_headers,
        )
        assert r.status_code == 200
        data = r.json()
        assert data['name'] == 'lunch'
        assert data['color'] == '#FF5733'

    def test_patch_tag_color_null_clears_it(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """The tag manager's "clear colour" button could only ever 422.

        `color: str` had no way to say "none", so the button was on screen,
        translated, and unusable. The column was nullable the whole time.
        """
        client.post(
            RECIPE_URL,
            json=_recipe_payload(name='ClearRecipe', tags=['supper']),
            headers=auth_headers,
        )
        client.patch(
            f'{RECIPE_URL}/tags/supper/color',
            json={'color': '#123456'},
            headers=auth_headers,
        )

        r = client.patch(
            f'{RECIPE_URL}/tags/supper/color',
            json={'color': None},
            headers=auth_headers,
        )
        assert r.status_code == 200
        assert r.json() == {'name': 'supper', 'color': None}

        listed = client.get(f'{RECIPE_URL}/tags', headers=auth_headers)
        by_name = {t['name']: t for t in listed.json()['items']}
        assert by_name['supper']['color'] is None

    def test_patch_tag_color_null_on_uncoloured_tag_is_a_no_op(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        client.post(
            RECIPE_URL,
            json=_recipe_payload(name='PlainRecipe', tags=['plain']),
            headers=auth_headers,
        )

        r = client.patch(
            f'{RECIPE_URL}/tags/plain/color',
            json={'color': None},
            headers=auth_headers,
        )
        assert r.status_code == 200
        assert r.json()['color'] is None

    def test_patch_tag_color_invalid_hex_returns_422(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Invalid hex color → 422."""
        client.post(
            RECIPE_URL,
            json=_recipe_payload(name='Rx', tags=['dinner']),
            headers=auth_headers,
        )
        r = client.patch(
            f'{RECIPE_URL}/tags/dinner/color',
            json={'color': 'notacolor'},
            headers=auth_headers,
        )
        assert r.status_code == 422

    def test_tag_color_returned_in_list(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """After setting a color, GET /tags returns it in the color field."""
        client.post(
            RECIPE_URL,
            json=_recipe_payload(name='Colored', tags=['veggie']),
            headers=auth_headers,
        )
        client.patch(
            f'{RECIPE_URL}/tags/veggie/color',
            json={'color': '#00AA00'},
            headers=auth_headers,
        )

        r = client.get(f'{RECIPE_URL}/tags', headers=auth_headers)
        tags = {t['name']: t for t in r.json()['items']}
        assert tags['veggie']['color'] == '#00AA00'

    def test_merge_tags_renames_across_recipes(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """POST /tags/merge renames old_tag → new_tag in all recipes."""
        r1 = client.post(
            RECIPE_URL,
            json=_recipe_payload(name='M1', tags=['oldtag', 'obiad']),
            headers=auth_headers,
        )
        r2 = client.post(
            RECIPE_URL,
            json=_recipe_payload(name='M2', tags=['oldtag']),
            headers=auth_headers,
        )
        id1, id2 = r1.json()['id'], r2.json()['id']

        r = client.post(
            f'{RECIPE_URL}/tags/merge',
            json={'old_tag': 'oldtag', 'new_tag': 'newtag'},
            headers=auth_headers,
        )
        assert r.status_code == 200
        data = r.json()
        assert data['updated_recipes'] == 2

        for rid in [id1, id2]:
            rec = client.get(f'{RECIPE_URL}/{rid}', headers=auth_headers).json()
            assert 'newtag' in rec['tags']
            assert 'oldtag' not in rec['tags']

    def test_merge_tags_old_tag_not_found_returns_404(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        r = client.post(
            f'{RECIPE_URL}/tags/merge',
            json={'old_tag': 'nonexistent', 'new_tag': 'other'},
            headers=auth_headers,
        )
        assert r.status_code == 404

    def test_merge_tags_into_existing_deduplicates(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Merging oldtag into a tag that already exists on the recipe deduplicates."""
        r = client.post(
            RECIPE_URL,
            json=_recipe_payload(name='Dedup', tags=['alpha', 'beta']),
            headers=auth_headers,
        )
        rid = r.json()['id']

        client.post(
            f'{RECIPE_URL}/tags/merge',
            json={'old_tag': 'alpha', 'new_tag': 'beta'},
            headers=auth_headers,
        )

        rec = client.get(f'{RECIPE_URL}/{rid}', headers=auth_headers).json()
        assert rec['tags'].count('beta') == 1
        assert 'alpha' not in rec['tags']


@pytest.mark.integration
class TestIngredientTemplateLinking:
    """ProductTemplate autocomplete + ingredient link endpoint."""

    def test_search_product_templates_returns_matches(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        db_session: Session,
    ) -> None:
        from uuid import uuid4

        from app.models import ProductTemplate

        tpl = ProductTemplate(
            id=uuid4(),
            organization_id=test_user.organization_id,
            name='Organic Spaghetti',
        )
        db_session.add(tpl)
        db_session.commit()

        r = client.get(
            '/api/v1/items/product-templates',
            params={'search': 'spaghetti'},
            headers=auth_headers,
        )
        assert r.status_code == 200
        names = [t['name'] for t in r.json()]
        assert 'Organic Spaghetti' in names

    def test_search_offers_the_catalogue_wording_for_the_recipe_wording(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        db_session: Session,
    ) -> None:
        """Without this the user cannot link by hand even when they want to.

        Typing the ingredient as the recipe words it suggested nothing,
        because the whole phrase is a substring of no catalogue name.
        """
        from uuid import uuid4

        from app.models import ProductTemplate

        db_session.add(
            ProductTemplate(
                id=uuid4(),
                organization_id=test_user.organization_id,
                name='Ciecierzyca w puszce',
            )
        )
        db_session.commit()

        r = client.get(
            '/api/v1/items/product-templates',
            params={'search': 'Ciecierzyca z puszki'},
            headers=auth_headers,
        )
        assert r.status_code == 200
        assert [t['name'] for t in r.json()] == ['Ciecierzyca w puszce']

    def test_link_ingredient_template_sets_template_id(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        db_session: Session,
    ) -> None:
        from uuid import uuid4

        from app.models import ProductTemplate

        template = ProductTemplate(
            id=uuid4(),
            organization_id=test_user.organization_id,
            name='Linked Tomato',
        )
        db_session.add(template)
        db_session.commit()

        # Recipe with an ingredient WITHOUT template_id
        r = client.post(
            RECIPE_URL,
            json=_recipe_payload(
                name='Unlinked Recipe',
                ingredients=[{'name': 'Tomato', 'quantity': '1', 'is_optional': False}],
            ),
            headers=auth_headers,
        )
        assert r.status_code == 201
        recipe_id = r.json()['id']
        ingredient_id = r.json()['ingredients'][0]['id']

        r = client.post(
            f'{RECIPE_URL}/{recipe_id}/ingredients/{ingredient_id}/link-template',
            json={'template_id': str(template.id)},
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text
        linked = r.json()['ingredients'][0]
        assert linked['template_id'] == str(template.id)

        # Persisted — fetch again
        r = client.get(f'{RECIPE_URL}/{recipe_id}', headers=auth_headers)
        assert r.json()['ingredients'][0]['template_id'] == str(template.id)

    def test_link_ingredient_template_unknown_returns_404(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        db_session: Session,
    ) -> None:
        from uuid import uuid4

        r = client.post(
            RECIPE_URL,
            json=_recipe_payload(
                name='Unlinked Recipe 2',
                ingredients=[{'name': 'Tomato', 'quantity': '1', 'is_optional': False}],
            ),
            headers=auth_headers,
        )
        recipe_id = r.json()['id']
        ingredient_id = r.json()['ingredients'][0]['id']

        r = client.post(
            f'{RECIPE_URL}/{recipe_id}/ingredients/{ingredient_id}/link-template',
            json={'template_id': str(uuid4())},
            headers=auth_headers,
        )
        assert r.status_code == 404


@pytest.mark.integration
def test_add_to_shopping_list_rejected_when_module_disabled(
    db_session: Session,
    client: TestClient,
) -> None:
    """the write path must fail cleanly when shopping_lists is off —
    hiding the button in the UI is not enough, the API stays reachable."""
    from app.models.organization import Organization
    from app.services.token_service import create_access_token

    org = Organization(
        name='No Shopping Lists Org',
        enabled_modules=['core', 'items', 'recipes'],
    )
    db_session.add(org)
    db_session.flush()
    user = User(
        email='nosl@example.com',
        hashed_password='dummy',
        full_name='No SL User',
        organization_id=org.id,
        role='admin',
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()

    headers = {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }
    recipe_id = client.post(
        RECIPE_URL,
        json=_recipe_payload(
            name='Guarded Recipe',
            ingredients=[
                {
                    'name': 'Maka',
                    'template_id': None,
                    'quantity': '300',
                    'is_optional': False,
                }
            ],
        ),
        headers=headers,
    ).json()['id']

    r = client.post(
        f'{RECIPE_URL}/{recipe_id}/add-to-shopping-list',
        json={'servings': 2},
        headers=headers,
    )
    assert r.status_code == status.HTTP_403_FORBIDDEN, r.text


@pytest.mark.integration
class TestDeleteTag:
    """A typo in a comma-separated field used to be permanent.

    The panel could merge one tag into another and give it a colour; nothing
    took a tag away, so every misspelling stayed on the list for good.
    """

    def _make_recipe(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        name: str,
        tags: list[str],
    ) -> dict[str, Any]:
        response = client.post(
            '/api/v1/recipes',
            json={'name': name, 'tags': tags, 'servings': 2},
            headers=auth_headers,
        )
        assert response.status_code == 201
        created: dict[str, Any] = response.json()
        return created

    def test_delete_tag_strips_it_from_every_recipe(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        self._make_recipe(client, auth_headers, 'Soup', ['dinner', 'quik'])
        self._make_recipe(client, auth_headers, 'Stew', ['quik'])

        response = client.delete('/api/v1/recipes/tags/quik', headers=auth_headers)

        assert response.status_code == 200
        assert response.json() == {'name': 'quik', 'updated_recipes': 2}

        tags = {
            row['name']
            for row in client.get('/api/v1/recipes/tags', headers=auth_headers).json()[
                'items'
            ]
        }
        assert 'quik' not in tags
        assert 'dinner' in tags

    def test_delete_tag_leaves_the_other_tags_alone(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        created = self._make_recipe(client, auth_headers, 'Soup', ['dinner', 'quik'])

        client.delete('/api/v1/recipes/tags/quik', headers=auth_headers)

        recipe = client.get(
            f'/api/v1/recipes/{created["id"]}', headers=auth_headers
        ).json()
        assert recipe['tags'] == ['dinner']

    def test_delete_unknown_tag_returns_404(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.delete(
            '/api/v1/recipes/tags/nothing-here', headers=auth_headers
        )

        assert response.status_code == 404
