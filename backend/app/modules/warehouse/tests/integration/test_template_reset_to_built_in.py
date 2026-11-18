"""A copy that has gone wrong can be put back as the built-in it came from.

Refreshing a copy adds a second template beside it, and loading the
built-ins again skips every name already taken — so an organization that
broke its own copy had no way back except deleting it. Resetting rewrites
the body in place and leaves everything else the copy is (its name, whether
it prints by default) alone.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

BASE = '/api/v1/warehouse/templates'
BROKEN = '<p>{% if a &gt; 1 %}x{% endif %}</p>'


@pytest.mark.integration
class TestResetToBuiltIn:
    def _seeded(
        self, client: TestClient, headers: dict[str, str], name: str
    ) -> dict[str, Any]:
        assert client.post(f'{BASE}/seed-defaults', headers=headers).status_code == 201
        listed = client.get(BASE, headers=headers).json()['items']
        return next(t for t in listed if t['name'] == name)

    def _built_in_body(
        self, client: TestClient, headers: dict[str, str], name: str
    ) -> str:
        built_ins = client.get(f'{BASE}/built-in', headers=headers).json()
        body: str = next(b for b in built_ins if b['name'] == name)['body_html']
        return body

    def test_a_broken_copy_becomes_the_built_in_again(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        copy = self._seeded(client, doc_auth_headers, 'Standard Template')
        built_in = self._built_in_body(client, doc_auth_headers, 'Standard Template')
        broken = client.put(
            f'{BASE}/{copy["id"]}', headers=doc_auth_headers, json={'body_html': BROKEN}
        )
        assert broken.status_code == 200, broken.text
        assert (
            client.post(
                f'{BASE}/preview',
                headers=doc_auth_headers,
                json={'body_html': BROKEN},
            ).status_code
            != 200
        )

        reset = client.post(f'{BASE}/{copy["id"]}/reset', headers=doc_auth_headers)

        assert reset.status_code == 200, reset.text
        body = reset.json()
        assert body['id'] == copy['id']
        assert body['body_html'] == built_in
        assert body['name'] == 'Standard Template'
        assert body['is_default'] is copy['is_default']
        previewed = client.post(
            f'{BASE}/preview',
            headers=doc_auth_headers,
            json={'body_html': body['body_html']},
        )
        assert previewed.status_code == 200, previewed.text

    def test_the_default_flag_survives(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        copy = self._seeded(client, doc_auth_headers, 'Packing Slip')
        client.put(
            f'{BASE}/{copy["id"]}',
            headers=doc_auth_headers,
            json={'body_html': '<p>ours</p>', 'is_default': False},
        )
        reset = client.post(f'{BASE}/{copy["id"]}/reset', headers=doc_auth_headers)
        assert reset.status_code == 200, reset.text
        assert reset.json()['is_default'] is False

    def test_a_template_not_made_from_a_built_in_is_not_found(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        created = client.post(
            BASE,
            headers=doc_auth_headers,
            json={
                'name': 'Ours',
                'module': 'warehouse',
                'document_type': 'STANDARD',
                'body_html': '<p>ours</p>',
            },
        )
        assert created.status_code == 201, created.text

        reset = client.post(
            f'{BASE}/{created.json()["id"]}/reset', headers=doc_auth_headers
        )

        assert reset.status_code == 404, reset.text
        kept = client.get(f'{BASE}/{created.json()["id"]}', headers=doc_auth_headers)
        assert kept.json()['body_html'] == '<p>ours</p>'

    def test_the_list_says_which_copies_differ_from_the_built_in(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        copy = self._seeded(client, doc_auth_headers, 'Standard Template')
        assert copy['source_modified'] is False
        client.put(
            f'{BASE}/{copy["id"]}',
            headers=doc_auth_headers,
            json={'body_html': '<p>ours</p>'},
        )
        own = client.post(
            BASE,
            headers=doc_auth_headers,
            json={
                'name': 'Ours',
                'module': 'warehouse',
                'document_type': 'STANDARD',
                'body_html': '<p>ours</p>',
            },
        )
        assert own.status_code == 201, own.text

        by_name = {
            t['name']: t
            for t in client.get(BASE, headers=doc_auth_headers).json()['items']
        }
        assert by_name['Standard Template']['source_modified'] is True
        assert by_name['Ours']['source_modified'] is False

        client.post(f'{BASE}/{copy["id"]}/reset', headers=doc_auth_headers)
        again = {
            t['name']: t
            for t in client.get(BASE, headers=doc_auth_headers).json()['items']
        }
        assert again['Standard Template']['source_modified'] is False
