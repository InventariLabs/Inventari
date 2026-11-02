"""A copied layout knows which built-in it came from.

An organization that loads the built-in templates prints from its own copy
from then on — and nothing may overwrite that copy, because it is theirs to
edit. What was missing was any way to notice that the built-in it came from
has moved since: a copy made before the print geometry was fixed kept
printing the old one, with nothing on the screen to say so.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session


@pytest.mark.integration
class TestBuiltinDrift:
    def _seed(
        self, client: TestClient, headers: dict[str, str]
    ) -> list[dict[str, Any]]:
        response = client.post(
            '/api/v1/warehouse/templates/seed-defaults', headers=headers
        )
        assert response.status_code == 201, response.text
        seeded: list[dict[str, Any]] = response.json()
        return seeded

    def test_a_fresh_copy_records_where_it_came_from(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        seeded = self._seed(client, doc_auth_headers)
        assert seeded, 'seeding produced no templates'

        listed = client.get('/api/v1/warehouse/templates', headers=doc_auth_headers)
        assert listed.status_code == 200
        by_name = {t['name']: t for t in listed.json()['items']}
        standard = by_name['Standard Template']
        assert standard['source_builtin'] == 'Standard Template'
        assert standard['source_outdated'] is False

    def test_a_template_written_from_scratch_has_no_origin(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        created = client.post(
            '/api/v1/warehouse/templates',
            headers=doc_auth_headers,
            json={
                'name': 'Ours',
                'module': 'warehouse',
                'document_type': 'STANDARD',
                'body_html': '<p>{{ document.number }}</p>',
            },
        )
        assert created.status_code == 201, created.text

        listed = client.get('/api/v1/warehouse/templates', headers=doc_auth_headers)
        ours = next(t for t in listed.json()['items'] if t['name'] == 'Ours')
        assert ours['source_builtin'] is None
        assert ours['source_outdated'] is False

    def test_a_copy_of_an_older_built_in_says_so(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        db_session: Session,
    ) -> None:
        """The built-in moving on is simulated by the checksum the copy
        carries no longer matching — which is exactly what happens when the
        file in the repository changes."""
        self._seed(client, doc_auth_headers)
        db_session.execute(
            text(
                "UPDATE document_templates SET source_checksum = 'stale' "
                "WHERE module = 'warehouse' AND name = 'Standard Template'"
            )
        )
        db_session.commit()

        listed = client.get('/api/v1/warehouse/templates', headers=doc_auth_headers)
        standard = next(
            t for t in listed.json()['items'] if t['name'] == 'Standard Template'
        )
        assert standard['source_outdated'] is True

    def test_refreshing_puts_the_new_copy_alongside_the_old_one(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        db_session: Session,
    ) -> None:
        """Nothing an organization edited is overwritten, and the refreshed
        copy does not quietly become the one that prints."""
        self._seed(client, doc_auth_headers)
        listed = client.get('/api/v1/warehouse/templates', headers=doc_auth_headers)
        standard = next(
            t for t in listed.json()['items'] if t['name'] == 'Standard Template'
        )
        edited = client.put(
            f'/api/v1/warehouse/templates/{standard["id"]}',
            headers=doc_auth_headers,
            json={'body_html': '<p>OURS {{ document.number }}</p>'},
        )
        assert edited.status_code == 200, edited.text

        refreshed = client.post(
            f'/api/v1/warehouse/templates/{standard["id"]}/refresh-copy',
            headers=doc_auth_headers,
        )
        assert refreshed.status_code == 201, refreshed.text
        fresh = refreshed.json()
        assert fresh['id'] != standard['id']
        assert fresh['is_default'] is False
        assert fresh['source_outdated'] is False
        assert 'OURS' not in fresh['body_html']

        after = {
            t['id']: t
            for t in client.get(
                '/api/v1/warehouse/templates', headers=doc_auth_headers
            ).json()['items']
        }
        assert 'OURS' in after[standard['id']]['body_html'], (
            'the organization edit was overwritten'
        )
        assert after[standard['id']]['is_default'] is True

    def test_refreshing_a_template_with_no_origin_is_refused(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        created = client.post(
            '/api/v1/warehouse/templates',
            headers=doc_auth_headers,
            json={
                'name': 'Ours',
                'module': 'warehouse',
                'document_type': 'STANDARD',
                'body_html': '<p>x</p>',
            },
        )
        response = client.post(
            f'/api/v1/warehouse/templates/{created.json()["id"]}/refresh-copy',
            headers=doc_auth_headers,
        )
        assert response.status_code == 400, response.text
