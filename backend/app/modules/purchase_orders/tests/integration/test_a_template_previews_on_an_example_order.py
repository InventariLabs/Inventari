"""The purchase order template editor previews a layout on an example order.

The preview runs the same render the PDF goes through, so a half-written
layout answers with the renderer's sentence instead of an empty frame.
"""

from fastapi import status
from starlette.testclient import TestClient

URL = '/api/v1/purchase-orders/templates/preview'


def test_a_layout_comes_back_rendered(
    client: TestClient, po_auth_headers: dict[str, str]
) -> None:
    resp = client.post(
        URL,
        headers=po_auth_headers,
        json={
            'body_html': '<p lang="{{ lang }}">{{ po_number }} {{ vendor_name }}</p>'
        },
    )

    assert resp.status_code == status.HTTP_200_OK, resp.text
    html = resp.json()['html']
    assert 'PO/2026/0001' in html
    assert 'Acme Supplies' in html
    assert '{{' not in html


def test_the_built_in_layout_previews(
    client: TestClient, po_auth_headers: dict[str, str]
) -> None:
    from pathlib import Path

    import app.modules.purchase_orders as package

    body = (Path(package.__file__).parent / 'templates' / 'po_standard.html').read_text(
        encoding='utf-8'
    )

    resp = client.post(URL, headers=po_auth_headers, json={'body_html': body})

    assert resp.status_code == status.HTTP_200_OK, resp.text
    assert 'PO/2026/0001' in resp.json()['html']


def test_a_layout_that_does_not_render_is_refused_with_the_reason(
    client: TestClient, po_auth_headers: dict[str, str]
) -> None:
    resp = client.post(
        URL, headers=po_auth_headers, json={'body_html': '<p>{{ broken </p>'}
    )

    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert 'could not be rendered' in resp.text
