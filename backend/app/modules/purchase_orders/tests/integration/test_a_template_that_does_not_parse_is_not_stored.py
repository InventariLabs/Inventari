"""A purchase order layout that does not render is refused at save.

A body stored with a syntax error, or one that fails when it runs, failed
every order's PDF with an unreadable 500, and the save that caused it said
nothing. The save names the line instead; a layout already stored in that
state prints the built-in one.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import status
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.template_models import DocumentTemplate

pytestmark = pytest.mark.integration

TEMPLATES = '/api/v1/purchase-orders/templates'
BROKEN = '<p>{{ broken </p>'


def _create(client: TestClient, headers: dict[str, str], body: str) -> Any:
    return client.post(
        TEMPLATES,
        headers=headers,
        json={
            'name': 'Own layout',
            'module': 'purchase_orders',
            'body_html': body,
            'document_type': 'STANDARD',
            'is_default': True,
        },
    )


def test_a_new_layout_with_a_syntax_error_is_refused_and_not_stored(
    client: TestClient, po_auth_headers: dict[str, str]
) -> None:
    response = _create(client, po_auth_headers, BROKEN)

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.text
    assert 'line 1' in response.text
    assert "unexpected '/'" in response.text
    listed = client.get(TEMPLATES, headers=po_auth_headers).json()['items']
    assert listed == []


@pytest.mark.parametrize(
    ('body', 'complaint'),
    [
        ('<p>{{ 1 / 0 }}</p>', 'division by zero'),
        ('<p>{{ po_number | no_such_filter }}</p>', 'no_such_filter'),
        ("<p>{{ 'a' + 1 }}</p>", 'concatenate'),
        ('<p>{{ none + 1 }}</p>', 'NoneType'),
        ('<p>{% for x in 5 %}x{% endfor %}</p>', 'not iterable'),
    ],
)
def test_a_layout_that_parses_but_does_not_render_is_refused(
    client: TestClient, po_auth_headers: dict[str, str], body: str, complaint: str
) -> None:
    response = _create(client, po_auth_headers, body)

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.text
    assert 'line 1' in response.text
    assert complaint in response.text
    assert client.get(TEMPLATES, headers=po_auth_headers).json()['items'] == []


def test_a_layout_reading_data_the_empty_context_lacks_is_saved(
    client: TestClient, po_auth_headers: dict[str, str]
) -> None:
    body = '<p>{{ po.partner.name | upper }} {{ total_net | round(2) }}</p>'

    response = _create(client, po_auth_headers, body)

    assert response.status_code == status.HTTP_201_CREATED, response.text


def test_an_edit_into_a_syntax_error_is_refused_and_the_body_stays(
    client: TestClient, po_auth_headers: dict[str, str]
) -> None:
    good = '<p>{{ po_number }}</p>'
    created = _create(client, po_auth_headers, good)
    assert created.status_code == status.HTTP_201_CREATED, created.text
    tpl_id = created.json()['id']

    response = client.put(
        f'{TEMPLATES}/{tpl_id}', headers=po_auth_headers, json={'body_html': BROKEN}
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.text
    kept = client.get(f'{TEMPLATES}/{tpl_id}', headers=po_auth_headers).json()
    assert kept['body_html'] == good


@pytest.mark.parametrize('stored', [BROKEN, '<p>{{ 1 / 0 }}</p>'])
def test_a_stored_layout_that_does_not_render_prints_the_built_in_one(
    stored: str,
    client: TestClient,
    po_auth_headers: dict[str, str],
    db_session: Session,
    po_org: Any,
    po_user: Any,
    po_partner: Any,
    po_template: Any,
) -> None:
    db_session.add(
        DocumentTemplate(
            organization_id=po_org.id,
            module='purchase_orders',
            name='Saved before the check',
            document_type='STANDARD',
            body_html=stored,
            is_default=True,
            created_by=po_user.id,
        )
    )
    db_session.flush()
    po = client.post(
        '/api/v1/purchase-orders',
        headers=po_auth_headers,
        json={
            'partner_id': str(po_partner.id),
            'lines': [
                {
                    'product_template_id': str(po_template.id),
                    'quantity_ordered': 5,
                    'unit_price': '5.00',
                    'tax_rate': '23.00',
                }
            ],
        },
    )
    po_id = po.json()['id']
    client.post(f'/api/v1/purchase-orders/{po_id}/confirm', headers=po_auth_headers)

    response = client.get(
        f'/api/v1/purchase-orders/{po_id}/pdf', headers=po_auth_headers
    )

    assert response.status_code == status.HTTP_200_OK, response.text
    assert response.headers['content-type'] == 'application/pdf'
