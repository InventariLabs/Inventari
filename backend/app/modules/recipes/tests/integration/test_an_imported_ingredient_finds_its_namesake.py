"""An imported ingredient named exactly like a product is linked to it.

A recipe imported from JSON with "Rice", "Chicken breast", "Frozen peas" and
"Eggs" — four products of exactly those names in the pantry — arrived "Not
matched" on the review screen, read "Similar" on the recipe, and each had to
be linked by hand; the bulk "Find matches" screen proposed nothing for them
either without an AI connection. A name that is the product's own name is not
a guess: it is matched before any model is asked, and without one.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from fastapi import status
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models import ProductTemplate
from app.models.user import User

RECIPE_URL = '/api/v1/recipes'

pytestmark = pytest.mark.integration


def _product(db_session: Session, user: User, name: str) -> ProductTemplate:
    template = ProductTemplate(
        id=uuid4(), organization_id=user.organization_id, name=name
    )
    db_session.add(template)
    db_session.commit()
    return template


def _payload(*names: str) -> dict[str, Any]:
    return {
        'format': 'json',
        'data': {
            'name': 'Chicken fried rice',
            'servings': 2,
            'ingredients': [
                {'name': name, 'quantity': 200, 'uom': 'g'} for name in names
            ],
        },
    }


def test_the_review_screen_offers_the_product_of_the_same_name(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
    test_user: User,
) -> None:
    rice = _product(db_session, test_user, 'Rice')
    peas = _product(db_session, test_user, 'Frozen peas')
    _product(db_session, test_user, 'Rice crackers')

    response = client.post(
        f'{RECIPE_URL}/import/preview',
        json=_payload('Rice', 'frozen peas', 'Basmati'),
        headers=auth_headers,
    )

    assert response.status_code == status.HTTP_200_OK, response.text
    by_name = {i['name']: i for i in response.json()['ingredients']}
    assert by_name['Rice']['template_id'] == str(rice.id)
    assert by_name['Rice']['template_name'] == 'Rice'
    # Case is not a different product.
    assert by_name['frozen peas']['template_id'] == str(peas.id)
    # A name no product carries stays for the reader to decide.
    assert by_name['Basmati']['template_id'] is None


def test_a_direct_import_links_the_namesake_too(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
    test_user: User,
) -> None:
    eggs = _product(db_session, test_user, 'Eggs')

    response = client.post(
        f'{RECIPE_URL}/import', json=_payload('Eggs'), headers=auth_headers
    )

    assert response.status_code == status.HTTP_201_CREATED, response.text
    assert response.json()['ingredients'][0]['template_id'] == str(eggs.id)


def test_find_matches_proposes_the_namesake_without_an_ai_connection(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.public_api.llm import LlmPurposeUnboundError
    from app.modules.recipes import template_matcher

    rice = _product(db_session, test_user, 'Rice')
    created = client.post(
        RECIPE_URL,
        json={
            'name': 'Plain rice',
            'servings': 1,
            'ingredients': [
                {'name': 'Rice', 'quantity': '1'},
                {'name': 'Onion', 'quantity': '1'},
            ],
        },
        headers=auth_headers,
    )
    assert created.status_code == status.HTTP_201_CREATED, created.text

    async def unbound(*args: Any, **kwargs: Any) -> str:
        raise LlmPurposeUnboundError('recipes.text_parse')

    monkeypatch.setattr(template_matcher, 'call_llm_async', unbound)

    response = client.post(
        f'{RECIPE_URL}/ingredients/match-proposals', headers=auth_headers
    )

    assert response.status_code == status.HTTP_200_OK, response.text
    proposals = response.json()['proposals']
    assert [p['template_id'] for p in proposals] == [str(rice.id)]
