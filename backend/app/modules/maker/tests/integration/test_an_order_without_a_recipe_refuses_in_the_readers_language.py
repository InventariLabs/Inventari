"""The missing-recipe refusal speaks the reader's language.

On /maker/production on a phone, in Polish: creating a draft for a
product without a recipe answered 400 with an English sentence wearing a
``lang: pl`` stamp. On a phone the toast is the only thing the reader
gets, so it is the thing that must translate. The refusal now raises
through the keyed rejection and the envelope translates it.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.storage_location import StorageLocation

from .conftest import _make_template

pytestmark = pytest.mark.integration

PL_HEADERS = {'Accept-Language': 'pl'}


def _post_order(
    client: TestClient,
    headers: dict[str, str],
    template_id: str,
    output_loc: StorageLocation,
) -> Any:
    return client.post(
        '/api/v1/maker/production/orders',
        headers=headers,
        json={
            'output_template_id': template_id,
            'planned_qty': '3',
            'output_location_id': str(output_loc.id),
        },
    )


class TestNoRecipeRefusal:
    def test_refuses_in_polish_with_a_truthful_language_claim(
        self,
        client: TestClient,
        mk_org: Organization,
        mk_auth_headers: dict[str, str],
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        template = _make_template(db_session, mk_org, name='Recipeless product')

        resp = _post_order(
            client,
            {**mk_auth_headers, **PL_HEADERS},
            str(template.id),
            mk_output_loc,
        )

        assert resp.status_code == 400, resp.text
        detail = resp.json()['detail']
        # The equality against the Polish sentence — not merely against
        # the en message or the key — is what fails while the handler
        # copies the raw English text: 'production_no_recipe' or the
        # English sentence both trip it.
        assert detail['message'] == (
            'Brak receptury dla tego produktu — najpierw utwórz recepturę'
        )
        assert detail['lang'] == 'pl'

    def test_the_same_refusal_stays_english_for_an_english_reader(
        self,
        client: TestClient,
        mk_org: Organization,
        mk_auth_headers: dict[str, str],
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        template = _make_template(db_session, mk_org, name='Recipeless product')

        resp = _post_order(client, mk_auth_headers, str(template.id), mk_output_loc)

        assert resp.status_code == 400, resp.text
        detail = resp.json()['detail']
        assert detail['message'] == ('No BOM for this product — create a BOM first')
        assert detail['lang'] == 'en'
