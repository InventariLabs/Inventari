"""The maker refusals speak the reader's language.

The module's refusals used to be raw English literals: a Polish reader met a
sentence about a line that cannot be its own parent in the tree editor's error
slot and "Overproduction is disabled in settings" on a run card, right next to
siblings that already read from the error catalog. Each refusal a reader can
trigger now raises through the keyed rejection, and these tests pin the
sentences they see.

The assertions are equalities against the Polish text, not status codes: with
a service reverted to its literal the response still answers 400, and only
the sentence tells the two builds apart.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from itertools import pairwise
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.modules.maker.models import MakerRecipe

from .conftest import _make_template

pytestmark = pytest.mark.integration

PL_HEADERS = {'Accept-Language': 'pl'}


def _polish(headers: dict[str, str]) -> dict[str, str]:
    return {**headers, **PL_HEADERS}


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
    child_id: uuid.UUID,
) -> dict[str, Any]:
    resp = client.post(
        f'/api/v1/maker/recipes/{recipe_id}/bom-lines',
        headers=headers,
        json={
            'child_template_id': str(child_id),
            'qty_per_batch': '2.0000',
            'unit': 'kg',
        },
    )
    assert resp.status_code == 201, resp.text
    body: dict[str, Any] = resp.json()
    return body


def _move(
    client: TestClient,
    headers: dict[str, str],
    line_id: str,
    new_parent_id: uuid.UUID,
) -> Any:
    return client.post(
        f'/api/v1/maker/bom/{line_id}/move',
        headers=headers,
        json={'new_parent_template_id': str(new_parent_id)},
    )


def _draft_order(
    client: TestClient,
    headers: dict[str, str],
    template_id: uuid.UUID,
    output_loc: StorageLocation,
) -> dict[str, Any]:
    resp = client.post(
        '/api/v1/maker/production/orders',
        headers=headers,
        json={
            'output_template_id': str(template_id),
            'planned_qty': '2',
            'output_location_id': str(output_loc.id),
        },
    )
    assert resp.status_code == 201, resp.text
    body: dict[str, Any] = resp.json()
    return body


def _message(response: Any) -> str:
    message: str = response.json()['detail']['message']
    return message


def _chain(
    db: Session,
    org: Organization,
    client: TestClient,
    headers: dict[str, str],
    *,
    levels: int,
) -> list[ProductTemplate]:
    """A BOM nested exactly ``levels`` deep: product 0 consumes 1, and so on.

    The templates and their default recipes are written straight to the
    session, but every *line* goes through the public endpoint — which is
    the point of the depth test: nothing on the write side refuses a chain
    this deep, so the refusal can only come from the read that resolves it.
    """
    templates = [
        _make_template(db, org, name=f'Chain level {i}') for i in range(levels)
    ]
    for parent, child in pairwise(templates):
        recipe = MakerRecipe(
            organization_id=org.id,
            output_template_id=parent.id,
            name=f'Recipe {parent.name}',
            batch_yield_qty=Decimal('1'),
            is_default=True,
        )
        db.add(recipe)
        db.commit()
        db.refresh(recipe)
        _add_line(client, headers, str(recipe.id), child.id)
    return templates


class TestTreeMoveRefusals:
    """POST /maker/bom/{line_id}/move — the tree editor's error slot."""

    def test_moving_a_line_under_its_own_ingredient_speaks_polish(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        soup = _make_template(db_session, mk_org, name='Zupa')
        plum = _make_template(db_session, mk_org, name='Śliwki')
        recipe = _create_recipe(client, mk_auth_headers, soup.id, name='Zupa warzywna')
        line = _add_line(client, mk_auth_headers, recipe['id'], plum.id)

        resp = _move(client, _polish(mk_auth_headers), line['id'], plum.id)

        assert resp.status_code == 400, resp.text
        assert _message(resp) == (
            'Linia receptury nie może odwoływać się do samego produktu — '
            'produkt stałby się składnikiem własnej receptury.'
        )
        assert resp.json()['detail']['lang'] == 'pl'

    def test_moving_a_line_onto_a_pair_that_already_exists_speaks_polish(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        first = _make_template(db_session, mk_org, name='Ciasto')
        second = _make_template(db_session, mk_org, name='Nadzienie')
        plum = _make_template(db_session, mk_org, name='Śliwki')
        first_recipe = _create_recipe(
            client, mk_auth_headers, first.id, name='Ciasto kruche'
        )
        second_recipe = _create_recipe(
            client, mk_auth_headers, second.id, name='Nadzienie śliwkowe'
        )
        _add_line(client, mk_auth_headers, first_recipe['id'], plum.id)
        line = _add_line(client, mk_auth_headers, second_recipe['id'], plum.id)

        resp = _move(client, _polish(mk_auth_headers), line['id'], first.id)

        assert resp.status_code == 400, resp.text
        assert _message(resp) == (
            'Ta receptura ma już ten składnik — linia między tymi produktami '
            'już istnieje.'
        )
        assert resp.json()['detail']['lang'] == 'pl'

    def test_moving_a_line_that_does_not_exist_speaks_polish(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        parent = _make_template(db_session, mk_org, name='Zupa')

        resp = _move(client, _polish(mk_auth_headers), str(uuid.uuid4()), parent.id)

        assert resp.status_code == 400, resp.text
        # The glossary spelling of the module noun rides the refusal too.
        assert _message(resp) == 'Pozycja BOM nie została znaleziona'


class TestTreeDepthRefusal:
    """GET /maker/bom/tree — the editor opens the whole tree; a BOM deeper
    than the resolver's limit refuses there rather than in the console."""

    def test_a_bom_nested_past_the_limit_speaks_polish(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        chain = _chain(db_session, mk_org, client, mk_auth_headers, levels=12)

        resp = client.get(
            f'/api/v1/maker/bom/tree/{chain[0].id}',
            headers=_polish(mk_auth_headers),
        )

        assert resp.status_code == 400, resp.text
        assert _message(resp) == (
            'Ta receptura jest zagnieżdżona głębiej niż 10 poziomów — '
            'nie da się jej rozwinąć.'
        )
        assert resp.json()['detail']['lang'] == 'pl'


class TestRunRefusals:
    """POST/PATCH /maker/production/orders/{id} — the run card's toast."""

    def test_completing_an_order_that_is_not_a_draft_speaks_polish(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        template = _make_template(db_session, mk_org, name='Konfitura')
        _create_recipe(client, mk_auth_headers, template.id, name='Konfitura śliwkowa')
        order = _draft_order(client, mk_auth_headers, template.id, mk_output_loc)
        assert (
            client.post(
                f'/api/v1/maker/production/orders/{order["id"]}/cancel',
                headers=mk_auth_headers,
                json={},
            ).status_code
            == 200
        )

        resp = client.post(
            f'/api/v1/maker/production/orders/{order["id"]}/complete',
            headers=_polish(mk_auth_headers),
            json={},
        )

        assert resp.status_code == 400, resp.text
        assert _message(resp) == (
            'To zlecenie produkcyjne ma już status CANCELLED — zakończyć można '
            'tylko wersję roboczą.'
        )

    def test_cancelling_a_cancelled_order_speaks_polish(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        template = _make_template(db_session, mk_org, name='Powidła')
        _create_recipe(client, mk_auth_headers, template.id, name='Powidła śliwkowe')
        order = _draft_order(client, mk_auth_headers, template.id, mk_output_loc)
        assert (
            client.post(
                f'/api/v1/maker/production/orders/{order["id"]}/cancel',
                headers=mk_auth_headers,
                json={},
            ).status_code
            == 200
        )

        resp = client.post(
            f'/api/v1/maker/production/orders/{order["id"]}/cancel',
            headers=_polish(mk_auth_headers),
            json={},
        )

        assert resp.status_code == 400, resp.text
        assert _message(resp) == (
            'To zlecenie produkcyjne ma już status CANCELLED — anulować można '
            'tylko wersję roboczą.'
        )

    def test_editing_a_cancelled_order_speaks_polish(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        template = _make_template(db_session, mk_org, name='Marmolada')
        _create_recipe(client, mk_auth_headers, template.id, name='Marmolada śliwkowa')
        order = _draft_order(client, mk_auth_headers, template.id, mk_output_loc)
        assert (
            client.post(
                f'/api/v1/maker/production/orders/{order["id"]}/cancel',
                headers=mk_auth_headers,
                json={},
            ).status_code
            == 200
        )

        resp = client.patch(
            f'/api/v1/maker/production/orders/{order["id"]}',
            headers=_polish(mk_auth_headers),
            json={'planned_qty': '3'},
        )

        assert resp.status_code == 400, resp.text
        assert _message(resp) == (
            'To zlecenie produkcyjne ma już status CANCELLED — edytować można '
            'tylko wersję roboczą.'
        )

    def test_completing_with_a_zero_output_speaks_polish(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        template = _make_template(db_session, mk_org, name='Pasta')
        _create_recipe(client, mk_auth_headers, template.id, name='Pasta śliwkowa')
        order = _draft_order(client, mk_auth_headers, template.id, mk_output_loc)

        resp = client.post(
            f'/api/v1/maker/production/orders/{order["id"]}/complete',
            headers=_polish(mk_auth_headers),
            json={'actual_qty': '0'},
        )

        assert resp.status_code == 400, resp.text
        assert _message(resp) == 'Ilość wyprodukowana musi być większa od zera.'

    def test_overproducing_with_the_setting_off_speaks_polish(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        template = _make_template(db_session, mk_org, name='Pieczywo')
        _create_recipe(client, mk_auth_headers, template.id, name='Chleb na zakwasie')
        order = _draft_order(client, mk_auth_headers, template.id, mk_output_loc)
        assert (
            client.patch(
                '/api/v1/maker/settings',
                headers=mk_auth_headers,
                json={'allow_overproduction': False},
            ).status_code
            == 200
        )

        resp = client.post(
            f'/api/v1/maker/production/orders/{order["id"]}/complete',
            headers=_polish(mk_auth_headers),
            json={'actual_qty': '3'},
        )

        assert resp.status_code == 400, resp.text
        assert _message(resp) == (
            'Nadprodukcja jest wyłączona w ustawieniach — to zlecenie nie może '
            'wyprodukować więcej niż zaplanowano.'
        )


class TestBreakdownRefusal:
    """GET /maker/breakdown/{template_id}?recipe_id= — a formula id the
    organization does not have answers in the reader's language."""

    def test_an_unknown_formula_speaks_polish(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        template = _make_template(db_session, mk_org, name='Sok')
        unknown_recipe_id = uuid.uuid4()

        resp = client.get(
            f'/api/v1/maker/breakdown/{template.id}',
            params={'qty': '1', 'recipe_id': str(unknown_recipe_id)},
            headers=_polish(mk_auth_headers),
        )

        assert resp.status_code == 400, resp.text
        assert _message(resp) == (
            f'Receptura {unknown_recipe_id} nie istnieje w tej organizacji'
        )
        assert resp.json()['detail']['lang'] == 'pl'
