"""The warehouse and equipment editors refuse a layout Jinja cannot parse.

The warehouse preview already said so; Save stored the same body anyway.
Both editors write through the one shared template service, so the refusal
is the same sentence, and the line it names is the line of the body.
"""

from __future__ import annotations

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
