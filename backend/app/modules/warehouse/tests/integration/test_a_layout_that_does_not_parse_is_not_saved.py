"""The warehouse and equipment editors refuse a layout that cannot render.

The warehouse preview already said so; Save stored the same body anyway.
Both editors write through the one shared template service, so the refusal
is the same sentence, and the line it names is the line of the body. The
check renders the way a print does: through the module's own partials, and
past the first value a document would have supplied.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import status
from starlette.testclient import TestClient

pytestmark = pytest.mark.integration

BROKEN = '<p>ok</p>\n<p>{{ broken </p>'


def test_the_warehouse_editor_refuses_the_body_on_save(
    client: TestClient, doc_auth_headers: dict[str, str]
) -> None:
    base = '/api/v1/warehouse/templates'
    created = client.post(
        base,
        headers=doc_auth_headers,
        json={
            'name': 'Own layout',
            'module': 'warehouse',
            'body_html': BROKEN,
            'document_type': 'STANDARD',
        },
    )

    assert created.status_code == status.HTTP_400_BAD_REQUEST, created.text
    assert 'line 2' in created.text
    ok = client.post(
        base,
        headers=doc_auth_headers,
        json={
            'name': 'Own layout',
            'module': 'warehouse',
            'body_html': '<p>{{ document_number }}</p>',
            'document_type': 'STANDARD',
        },
    )
    assert ok.status_code == status.HTTP_201_CREATED, ok.text
    edited = client.put(
        f'{base}/{ok.json()["id"]}',
        headers=doc_auth_headers,
        json={'body_html': BROKEN},
    )
    assert edited.status_code == status.HTTP_400_BAD_REQUEST, edited.text
    stored = client.get(f'{base}/{ok.json()["id"]}', headers=doc_auth_headers).json()
    assert stored['body_html'] == '<p>{{ document_number }}</p>'


BASE = '/api/v1/warehouse/templates'
BUILT_IN = Path(__file__).parents[2] / 'templates' / 'standard.html'


def _create(client: TestClient, headers: dict[str, str], body: str):  # type: ignore[no-untyped-def]
    return client.post(
        BASE,
        headers=headers,
        json={
            'name': 'Own layout',
            'module': 'warehouse',
            'body_html': body,
            'document_type': 'STANDARD',
        },
    )


def test_a_failure_below_the_first_missing_value_is_refused(
    client: TestClient, doc_auth_headers: dict[str, str]
) -> None:
    body = BUILT_IN.read_text().replace('</body>', '<p>{{ 1 / 0 }}</p></body>')
    assert '<p>{{ 1 / 0 }}</p>' in body

    response = _create(client, doc_auth_headers, body)

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.text
    assert 'division by zero' in response.text


def test_the_built_in_layout_saves_as_it_is(
    client: TestClient, doc_auth_headers: dict[str, str]
) -> None:
    response = _create(client, doc_auth_headers, BUILT_IN.read_text())

    assert response.status_code == status.HTTP_201_CREATED, response.text


def test_a_layout_including_a_partial_of_the_module_saves(
    client: TestClient, doc_auth_headers: dict[str, str]
) -> None:
    body = (
        "<div>{% include 'standard/parties/default.html' %}</div>"
        '<p>{{ document.number }}</p>'
    )

    response = _create(client, doc_auth_headers, body)

    assert response.status_code == status.HTTP_201_CREATED, response.text


def test_a_layout_including_a_partial_that_does_not_exist_is_refused(
    client: TestClient, doc_auth_headers: dict[str, str]
) -> None:
    response = _create(client, doc_auth_headers, "{% include 'standard/nope.html' %}")

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.text
    assert 'nope.html' in response.text
