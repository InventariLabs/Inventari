"""Integration tests for per-recipe BOM line add/delete.

The legacy ``POST /maker/bom`` adapter resolves ``parent_template_id`` to the
template's *default* recipe, so it cannot express "add this ingredient to
that formula" once a product has more than one. These endpoints write to the
recipe named in the path.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.modules.maker.tests.integration.test_production_consume_create import (
    _template,
)

pytestmark = pytest.mark.integration


def _create_recipe(
    client: TestClient,
    headers: dict[str, str],
    template_id: uuid.UUID,
    *,
    name: str,
) -> dict[str, Any]:
    resp = client.post(
        '/api/v1/maker/recipes',
        headers=headers,
        json={'output_template_id': str(template_id), 'name': name},
    )
    assert resp.status_code == 201, resp.text
    body: dict[str, Any] = resp.json()
    return body


def _add_line(
    client: TestClient,
    headers: dict[str, str],
    recipe_id: str,
    child: ProductTemplate,
    *,
    qty: str = '2.0000',
    unit: str = 'kg',
    **extra: Any,
) -> Any:
    return client.post(
        f'/api/v1/maker/recipes/{recipe_id}/bom-lines',
        headers=headers,
        json={
            'child_template_id': str(child.id),
            'qty_per_batch': qty,
            'unit': unit,
            **extra,
        },
    )


def _detail(client: TestClient, headers: dict[str, str], recipe_id: str) -> Any:
    resp = client.get(f'/api/v1/maker/recipes/{recipe_id}', headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _other_org_headers(db_session: Session, h: ModuleTestHelper) -> dict[str, str]:
    other_org = h.create_org('Other Maker Org', ['core', 'items', 'maker'])
    other_user = h.create_user(other_org, email='other-maker@example.com')
    return h.get_auth_headers(other_user)


class TestAddRecipeBomLine:
    """POST /maker/recipes/{recipe_id}/bom-lines."""

    def test_add_line_lands_in_the_named_recipe_not_the_default(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        parent = _template(db_session, mk_org, name='Sausage')
        child = _template(db_session, mk_org, name='Pork')
        default_recipe = _create_recipe(
            client, mk_auth_headers, parent.id, name='House formula'
        )
        second_recipe = _create_recipe(
            client, mk_auth_headers, parent.id, name='Smoked variant'
        )

        resp = _add_line(client, mk_auth_headers, second_recipe['id'], child)

        assert resp.status_code == 201, resp.text
        assert resp.json()['child_template_id'] == str(child.id)
        assert resp.json()['parent_template_id'] == str(parent.id)
        assert len(_detail(client, mk_auth_headers, second_recipe['id'])['lines']) == 1
        # The default formula must stay untouched — this is the whole point.
        assert _detail(client, mk_auth_headers, default_recipe['id'])['lines'] == []

    def test_added_line_carries_qty_unit_and_yield_loss(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        parent = _template(db_session, mk_org, name='Bread')
        child = _template(db_session, mk_org, name='Flour')
        recipe = _create_recipe(client, mk_auth_headers, parent.id, name='Sourdough')

        resp = _add_line(
            client,
            mk_auth_headers,
            recipe['id'],
            child,
            qty='1.5000',
            unit='kg',
            yield_loss_pct='7.50',
            notes='sifted',
        )

        assert resp.status_code == 201, resp.text
        line = _detail(client, mk_auth_headers, recipe['id'])['lines'][0]
        assert line['qty_per_batch'] == '1.5000'
        assert line['unit'] == 'kg'
        assert line['yield_loss_pct'] == '7.50'
        assert line['notes'] == 'sifted'

    def test_add_same_ingredient_twice_returns_409(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        parent = _template(db_session, mk_org, name='Stew')
        child = _template(db_session, mk_org, name='Carrot')
        recipe = _create_recipe(client, mk_auth_headers, parent.id, name='Winter stew')
        assert (
            _add_line(client, mk_auth_headers, recipe['id'], child).status_code == 201
        )

        resp = _add_line(client, mk_auth_headers, recipe['id'], child)

        assert resp.status_code == 409

    def test_add_output_product_as_its_own_ingredient_returns_400(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        parent = _template(db_session, mk_org, name='Jam')
        recipe = _create_recipe(client, mk_auth_headers, parent.id, name='Plum jam')

        resp = _add_line(client, mk_auth_headers, recipe['id'], parent)

        assert resp.status_code == 400

    def test_the_self_reference_refusal_speaks_the_sessions_language(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        """The picker offers the output product, so this refusal is one a
        reader genuinely triggers — it must arrive translated and spell the
        module noun the way the rest of the module does (BOM, never BoM)."""
        parent = _template(db_session, mk_org, name='Jam')
        recipe = _create_recipe(client, mk_auth_headers, parent.id, name='Plum jam')

        resp = _add_line(client, mk_auth_headers, recipe['id'], parent)
        polish = _add_line(
            client,
            {**mk_auth_headers, 'Accept-Language': 'pl'},
            recipe['id'],
            parent,
        )

        message = resp.json()['detail']['message']
        assert resp.status_code == 400
        # The glossary spelling: the acronym in caps, never mixed-case.
        assert 'BOM' in message
        assert 'BoM' not in message
        assert polish.status_code == 400
        assert polish.json()['detail']['message'] == (
            'Linia receptury nie może odwoływać się do samego produktu — '
            'produkt stałby się składnikiem własnej receptury.'
        )

    def test_the_cycle_refusal_speaks_the_sessions_language(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        """A line closing a loop back to an output product is the other
        refusal the picker can trigger — it arrives translated like its
        self-reference sibling, spelling the module noun the glossary's
        way (BOM, never BoM)."""
        dough = _template(db_session, mk_org, name='Dough')
        pizza = _template(db_session, mk_org, name='Pizza')
        pizza_recipe = _create_recipe(
            client, mk_auth_headers, pizza.id, name='Margherita'
        )
        assert (
            _add_line(client, mk_auth_headers, pizza_recipe['id'], dough).status_code
            == 201
        )
        dough_recipe = _create_recipe(
            client, mk_auth_headers, dough.id, name='Base dough'
        )

        resp = _add_line(client, mk_auth_headers, dough_recipe['id'], pizza)
        polish = _add_line(
            client,
            {**mk_auth_headers, 'Accept-Language': 'pl'},
            dough_recipe['id'],
            pizza,
        )

        message = resp.json()['detail']['message']
        assert resp.status_code == 400
        # The glossary spelling: the acronym in caps, never mixed-case.
        assert 'BOM' in message
        assert 'BoM' not in message
        assert polish.status_code == 400
        assert polish.json()['detail']['message'] == (
            'Ta linia domknęłaby cykl: produkt stałby się składnikiem '
            'własnej receptury.'
        )

    def test_add_line_creating_a_cycle_returns_400(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        dough = _template(db_session, mk_org, name='Dough')
        pizza = _template(db_session, mk_org, name='Pizza')
        pizza_recipe = _create_recipe(
            client, mk_auth_headers, pizza.id, name='Margherita'
        )
        assert (
            _add_line(client, mk_auth_headers, pizza_recipe['id'], dough).status_code
            == 201
        )
        dough_recipe = _create_recipe(
            client, mk_auth_headers, dough.id, name='Base dough'
        )

        resp = _add_line(client, mk_auth_headers, dough_recipe['id'], pizza)

        assert resp.status_code == 400

    def test_add_line_to_unknown_recipe_returns_404(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        child = _template(db_session, mk_org, name='Salt')

        resp = _add_line(client, mk_auth_headers, str(uuid.uuid4()), child)

        assert resp.status_code == 404

    def test_the_unknown_recipe_refusal_speaks_the_makers_word(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        """The maker module's word is "receptura" — "przepis" belongs to the
        recipes module, and a 404 that crossed the module border took the
        other module's word with it."""
        child = _template(db_session, mk_org, name='Salt')

        resp = _add_line(
            client,
            {**mk_auth_headers, 'Accept-Language': 'pl'},
            str(uuid.uuid4()),
            child,
        )

        assert resp.status_code == 404
        assert resp.json()['detail']['message'] == ('Receptura nie została znaleziona')

    def test_add_line_to_another_orgs_recipe_returns_404(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
        h: ModuleTestHelper,
    ) -> None:
        parent = _template(db_session, mk_org, name='Cheese')
        child = _template(db_session, mk_org, name='Milk')
        recipe = _create_recipe(client, mk_auth_headers, parent.id, name='Gouda')

        resp = _add_line(client, _other_org_headers(db_session, h), recipe['id'], child)

        assert resp.status_code == 404


class TestDeleteRecipeBomLine:
    """DELETE /maker/recipes/{recipe_id}/bom-lines/{line_id}."""

    def test_delete_line_removes_it_from_the_recipe(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        parent = _template(db_session, mk_org, name='Soup')
        child = _template(db_session, mk_org, name='Onion')
        recipe = _create_recipe(client, mk_auth_headers, parent.id, name='Onion soup')
        line = _add_line(client, mk_auth_headers, recipe['id'], child).json()

        resp = client.delete(
            f'/api/v1/maker/recipes/{recipe["id"]}/bom-lines/{line["id"]}',
            headers=mk_auth_headers,
        )

        assert resp.status_code == 204
        assert _detail(client, mk_auth_headers, recipe['id'])['lines'] == []

    def test_delete_line_belonging_to_another_recipe_returns_404(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        parent = _template(db_session, mk_org, name='Cake')
        child = _template(db_session, mk_org, name='Sugar')
        recipe = _create_recipe(client, mk_auth_headers, parent.id, name='Sponge')
        other_recipe = _create_recipe(
            client, mk_auth_headers, parent.id, name='Chocolate'
        )
        line = _add_line(client, mk_auth_headers, recipe['id'], child).json()

        resp = client.delete(
            f'/api/v1/maker/recipes/{other_recipe["id"]}/bom-lines/{line["id"]}',
            headers=mk_auth_headers,
        )

        assert resp.status_code == 404
        assert len(_detail(client, mk_auth_headers, recipe['id'])['lines']) == 1

    def test_delete_line_of_another_orgs_recipe_returns_404(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
        h: ModuleTestHelper,
    ) -> None:
        parent = _template(db_session, mk_org, name='Butter')
        child = _template(db_session, mk_org, name='Cream')
        recipe = _create_recipe(client, mk_auth_headers, parent.id, name='Churned')
        line = _add_line(client, mk_auth_headers, recipe['id'], child).json()

        resp = client.delete(
            f'/api/v1/maker/recipes/{recipe["id"]}/bom-lines/{line["id"]}',
            headers=_other_org_headers(db_session, h),
        )

        assert resp.status_code == 404
        assert len(_detail(client, mk_auth_headers, recipe['id'])['lines']) == 1


class TestPatchRecipeBomLineScoping:
    """PATCH must respect the recipe in the path, not just the org."""

    def test_patch_line_through_another_recipe_returns_404(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        parent = _template(db_session, mk_org, name='Pasta')
        child = _template(db_session, mk_org, name='Egg')
        recipe = _create_recipe(client, mk_auth_headers, parent.id, name='Tagliatelle')
        other_recipe = _create_recipe(
            client, mk_auth_headers, parent.id, name='Pappardelle'
        )
        line = _add_line(client, mk_auth_headers, recipe['id'], child).json()

        resp = client.patch(
            f'/api/v1/maker/recipes/{other_recipe["id"]}/bom-lines/{line["id"]}',
            headers=mk_auth_headers,
            json={'qty_per_batch': '9.0000'},
        )

        assert resp.status_code == 404
        unchanged = _detail(client, mk_auth_headers, recipe['id'])['lines'][0]
        assert Decimal(unchanged['qty_per_batch']) == Decimal('2.0000')
