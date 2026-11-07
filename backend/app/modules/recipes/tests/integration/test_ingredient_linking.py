"""Integration tests for the global ingredient-linking screen.

- GET  /api/v1/recipes/ingredients/unlinked
- POST /api/v1/recipes/ingredients/match-proposals
- POST /api/v1/recipes/ingredients/link-templates

The screen's whole purpose is to clear ``template_id IS NULL`` across every
recipe at once, so the tests walk the three endpoints in the order the screen
does: list the backlog, propose matches for it, apply the approved subset.
"""

from __future__ import annotations

import uuid
from typing import Any
from uuid import uuid4

import pytest
from fastapi import status
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models import ProductTemplate
from app.models.organization import Organization
from app.models.user import User
from app.modules.recipes.models import Recipe, RecipeIngredient
from app.modules.recipes.template_matcher import TemplateMatchResult

RECIPE_URL = '/api/v1/recipes'
UNLINKED_URL = f'{RECIPE_URL}/ingredients/unlinked'
PROPOSALS_URL = f'{RECIPE_URL}/ingredients/match-proposals'
LINK_URL = f'{RECIPE_URL}/ingredients/link-templates'


def _recipe_payload(**overrides: Any) -> dict[str, Any]:
    base = {
        'name': 'Unlinked Recipe',
        'servings': 2,
        'ingredients': [],
    }
    base.update(overrides)
    return base


def _make_template(db_session: Session, user: User, name: str) -> ProductTemplate:
    template = ProductTemplate(
        id=uuid4(),
        organization_id=user.organization_id,
        name=name,
    )
    db_session.add(template)
    db_session.commit()
    return template


def _create_recipe(
    client: TestClient,
    auth_headers: dict[str, str],
    name: str,
    ingredients: list[dict[str, Any]],
) -> dict[str, Any]:
    response = client.post(
        RECIPE_URL,
        json=_recipe_payload(name=name, ingredients=ingredients),
        headers=auth_headers,
    )
    assert response.status_code == status.HTTP_201_CREATED, response.text
    payload: dict[str, Any] = response.json()
    return payload


@pytest.mark.integration
class TestUnlinkedIngredientsList:
    def test_lists_only_unlinked_ingredients_with_their_recipe(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        db_session: Session,
    ) -> None:
        template = _make_template(db_session, test_user, 'Linked Tomato')
        _create_recipe(
            client,
            auth_headers,
            'Recipe A',
            [
                {
                    'name': 'Tomato',
                    'quantity': '2',
                    'template_id': str(template.id),
                },
                {'name': 'Onion', 'quantity': '1', 'ingredient_group_name': 'onion'},
            ],
        )
        _create_recipe(
            client,
            auth_headers,
            'Recipe B',
            [{'name': 'Carrot', 'quantity': '3'}],
        )

        response = client.get(UNLINKED_URL, headers=auth_headers)
        assert response.status_code == status.HTTP_200_OK, response.text
        data = response.json()
        assert data['total'] == 2
        # The linked Tomato still counts: an empty backlog means "all linked"
        # only when there are ingredients to be linked.
        assert data['ingredient_total'] == 3
        rows = {(item['name'], item['recipe_name']) for item in data['items']}
        assert rows == {('Onion', 'Recipe A'), ('Carrot', 'Recipe B')}
        onion = next(item for item in data['items'] if item['name'] == 'Onion')
        assert onion['match_name'] == 'onion'
        assert onion['recipe_id']
        assert onion['uom_symbol'] == 'g'

    def test_excludes_recipes_of_other_organizations(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        db_session: Session,
    ) -> None:
        other_org = Organization(name='Other org')
        db_session.add(other_org)
        db_session.commit()
        foreign_recipe = Recipe(
            id=uuid4(),
            organization_id=other_org.id,
            name='Foreign Recipe',
            servings=1,
            created_by=test_user.id,
        )
        foreign_recipe.ingredients = [
            RecipeIngredient(
                id=uuid4(),
                name='Secret Ingredient',
                quantity=1,
                sort_order=0,
            )
        ]
        db_session.add(foreign_recipe)
        db_session.commit()

        response = client.get(UNLINKED_URL, headers=auth_headers)
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {
            'items': [],
            'total': 0,
            'limit': 200,
            'offset': 0,
            'has_more': False,
            'total_capped': False,
            'ingredient_total': 0,
        }

    def test_the_backlog_pages_by_limit_and_offset(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        _create_recipe(
            client,
            auth_headers,
            'Recipe A',
            [
                {'name': 'Onion', 'quantity': '1'},
                {'name': 'Carrot', 'quantity': '1'},
                {'name': 'Leek', 'quantity': '1'},
            ],
        )

        first = client.get(f'{UNLINKED_URL}?limit=2', headers=auth_headers).json()
        second = client.get(
            f'{UNLINKED_URL}?limit=2&offset=2', headers=auth_headers
        ).json()

        assert [item['name'] for item in first['items']] == ['Onion', 'Carrot']
        assert (first['total'], first['has_more']) == (3, True)
        assert [item['name'] for item in second['items']] == ['Leek']
        assert (second['offset'], second['has_more']) == (2, False)


@pytest.mark.integration
class TestIngredientMatchProposals:
    def test_proposes_for_every_unlinked_ingredient_of_the_same_name(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        db_session: Session,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        template = _make_template(db_session, test_user, 'Onion Powder')
        _create_recipe(
            client,
            auth_headers,
            'Recipe A',
            [{'name': 'Onion', 'quantity': '1'}],
        )
        _create_recipe(
            client,
            auth_headers,
            'Recipe B',
            [{'name': 'Onion', 'quantity': '2'}, {'name': 'Carrot', 'quantity': '1'}],
        )

        from app.modules.recipes import ingredient_linking_service

        async def fake_match(
            db: Any,
            org_id: uuid.UUID,
            group_names: list[str],
            usage_ctx: dict[str, Any] | None = None,
        ) -> list[TemplateMatchResult]:
            return [
                TemplateMatchResult(
                    ingredient_index=index,
                    template_id=template.id if name == 'Onion' else None,
                )
                for index, name in enumerate(group_names)
            ]

        monkeypatch.setattr(ingredient_linking_service, 'match_templates', fake_match)

        response = client.post(PROPOSALS_URL, headers=auth_headers)
        assert response.status_code == status.HTTP_200_OK, response.text
        data = response.json()
        assert data['considered'] == 3
        proposed_names = {item['template_name'] for item in data['proposals']}
        assert proposed_names == {'Onion Powder'}
        assert len(data['proposals']) == 2, 'both Onion rows get the proposal'
        assert all(
            item['template_id'] == str(template.id) for item in data['proposals']
        )

    def test_answers_503_when_no_ai_connection_is_bound(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        db_session: Session,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.core.public_api.llm import LlmPurposeUnboundError
        from app.modules.recipes import template_matcher

        _make_template(db_session, test_user, 'Some Product')
        _create_recipe(
            client,
            auth_headers,
            'Recipe A',
            [{'name': 'Onion', 'quantity': '1'}],
        )

        async def unbound(*args: Any, **kwargs: Any) -> str:
            raise LlmPurposeUnboundError('recipes.text_parse')

        monkeypatch.setattr(template_matcher, 'call_llm_async', unbound)

        response = client.post(PROPOSALS_URL, headers=auth_headers)
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert response.json()['detail']['code'] == 'LLM_PURPOSE_UNBOUND'

    def test_a_failing_llm_answer_is_an_empty_proposal_list(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        db_session: Session,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.modules.recipes import template_matcher

        _make_template(db_session, test_user, 'Some Product')
        _create_recipe(
            client,
            auth_headers,
            'Recipe A',
            [{'name': 'Onion', 'quantity': '1'}],
        )

        async def broken(*args: Any, **kwargs: Any) -> str:
            raise RuntimeError('provider down')

        monkeypatch.setattr(template_matcher, 'call_llm_async', broken)

        response = client.post(PROPOSALS_URL, headers=auth_headers)
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['proposals'] == []
        assert data['considered'] == 1


@pytest.mark.integration
class TestBulkLinkIngredients:
    def test_links_ingredients_across_recipes_in_one_call(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        db_session: Session,
    ) -> None:
        onion = _make_template(db_session, test_user, 'Onion Powder')
        milk = _make_template(db_session, test_user, 'Milk 2%')
        recipe_a = _create_recipe(
            client,
            auth_headers,
            'Recipe A',
            [
                {'name': 'Onion', 'quantity': '1'},
                {'name': 'Carrot', 'quantity': '1'},
            ],
        )
        recipe_b = _create_recipe(
            client,
            auth_headers,
            'Recipe B',
            [{'name': 'Milk', 'quantity': '1'}],
        )

        response = client.post(
            LINK_URL,
            json={
                'links': [
                    {
                        'ingredient_id': recipe_a['ingredients'][0]['id'],
                        'template_id': str(onion.id),
                    },
                    {
                        'ingredient_id': recipe_b['ingredients'][0]['id'],
                        'template_id': str(milk.id),
                    },
                ]
            },
            headers=auth_headers,
        )
        assert response.status_code == status.HTTP_200_OK, response.text
        data = response.json()
        assert data['linked'] == 2
        assert {uuid.UUID(rid) for rid in data['recipe_ids']} == {
            uuid.UUID(recipe_a['id']),
            uuid.UUID(recipe_b['id']),
        }

        refreshed_a = client.get(
            f'{RECIPE_URL}/{recipe_a["id"]}', headers=auth_headers
        ).json()
        assert refreshed_a['ingredients'][0]['template_id'] == str(onion.id)
        assert refreshed_a['ingredients'][1]['template_id'] is None
        refreshed_b = client.get(
            f'{RECIPE_URL}/{recipe_b["id"]}', headers=auth_headers
        ).json()
        assert refreshed_b['ingredients'][0]['template_id'] == str(milk.id)

        remaining = client.get(UNLINKED_URL, headers=auth_headers).json()
        assert [item['name'] for item in remaining['items']] == ['Carrot']

    def test_unknown_template_returns_404_and_writes_nothing(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        db_session: Session,
    ) -> None:
        template = _make_template(db_session, test_user, 'Onion Powder')
        recipe = _create_recipe(
            client,
            auth_headers,
            'Recipe A',
            [{'name': 'Onion', 'quantity': '1'}],
        )

        response = client.post(
            LINK_URL,
            json={
                'links': [
                    {
                        'ingredient_id': recipe['ingredients'][0]['id'],
                        'template_id': str(uuid4()),
                    }
                ]
            },
            headers=auth_headers,
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

        refreshed = client.get(
            f'{RECIPE_URL}/{recipe["id"]}', headers=auth_headers
        ).json()
        assert refreshed['ingredients'][0]['template_id'] is None
        assert str(template.id)  # template exists but was never applied

    def test_unknown_ingredient_returns_404(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        db_session: Session,
    ) -> None:
        template = _make_template(db_session, test_user, 'Onion Powder')

        response = client.post(
            LINK_URL,
            json={
                'links': [
                    {'ingredient_id': str(uuid4()), 'template_id': str(template.id)}
                ]
            },
            headers=auth_headers,
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_ingredient_of_another_organization_returns_404(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        db_session: Session,
    ) -> None:
        template = _make_template(db_session, test_user, 'Onion Powder')
        other_org = Organization(name='Other org')
        db_session.add(other_org)
        db_session.commit()
        foreign_recipe = Recipe(
            id=uuid4(),
            organization_id=other_org.id,
            name='Foreign Recipe',
            servings=1,
            created_by=test_user.id,
        )
        foreign_recipe.ingredients = [
            RecipeIngredient(
                id=uuid4(),
                name='Paper',
                quantity=1,
                sort_order=0,
            )
        ]
        db_session.add(foreign_recipe)
        db_session.commit()
        foreign_ingredient_id = foreign_recipe.ingredients[0].id

        response = client.post(
            LINK_URL,
            json={
                'links': [
                    {
                        'ingredient_id': str(foreign_ingredient_id),
                        'template_id': str(template.id),
                    }
                ]
            },
            headers=auth_headers,
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND
