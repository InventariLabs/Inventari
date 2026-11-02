"""An equipment protocol copy is told when its built-in has moved on.

A copy belongs to the organization: nothing rewrites it, and nothing should.
The one thing it cannot know on its own is that the layout it was made from
has changed since — documents and purchase orders say it, equipment did not.
The list endpoint never passed ``built_ins``, so ``source_outdated`` was
never computed and came back False for everything.

The names are the wrinkle: this module names its built-ins in the seeding
language, and a copy is matched to its built-in by that name. Seeded in
Polish, read in English, nothing matched.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.template_models import DocumentTemplate

TEMPLATES = '/api/v1/equipment/templates'


def _seed(client: TestClient, headers: dict[str, str]) -> list[dict[str, Any]]:
    response = client.post(f'{TEMPLATES}/seed-defaults', headers=headers)
    assert response.status_code == status.HTTP_201_CREATED, response.text
    seeded: list[dict[str, Any]] = response.json()
    return seeded


def _move_the_builtin_on(db: Session, template_id: str) -> None:
    """What a released change to the built-in file looks like from here."""
    row = db.scalars(
        select(DocumentTemplate).where(DocumentTemplate.id == template_id)
    ).one()
    row.source_checksum = 'a checksum from an older layout'
    db.commit()


@pytest.mark.integration
class TestTheCopyIsToldItsBuiltInMovedOn:
    def test_a_fresh_copy_says_nothing(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        _seed(client, eq_auth_headers)

        listed = client.get(TEMPLATES, headers=eq_auth_headers)
        assert listed.status_code == status.HTTP_200_OK, listed.text
        assert listed.json()['items']
        assert all(not t['source_outdated'] for t in listed.json()['items'])

    def test_a_copy_of_an_older_layout_is_marked(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        db_session: Session,
    ) -> None:
        seeded = _seed(client, eq_auth_headers)
        _move_the_builtin_on(db_session, seeded[0]['id'])

        listed = client.get(TEMPLATES, headers=eq_auth_headers).json()['items']
        marked = {t['id']: t['source_outdated'] for t in listed}
        assert marked[seeded[0]['id']] is True
        assert marked[seeded[1]['id']] is False

    def test_the_language_it_was_seeded_in_does_not_hide_the_answer(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        db_session: Session,
    ) -> None:
        """Seeded in Polish, read in English — the built-in is the same file."""
        polish = dict(eq_auth_headers, **{'Accept-Language': 'pl'})
        seeded = _seed(client, polish)
        _move_the_builtin_on(db_session, seeded[0]['id'])

        listed = client.get(
            TEMPLATES, headers=dict(eq_auth_headers, **{'Accept-Language': 'en'})
        ).json()['items']
        marked = {t['id']: t['source_outdated'] for t in listed}
        assert marked[seeded[0]['id']] is True

    def test_the_current_built_in_can_be_copied_alongside(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        db_session: Session,
    ) -> None:
        seeded = _seed(client, eq_auth_headers)
        _move_the_builtin_on(db_session, seeded[0]['id'])

        response = client.post(
            f'{TEMPLATES}/{seeded[0]["id"]}/refresh-copy', headers=eq_auth_headers
        )
        assert response.status_code == status.HTTP_201_CREATED, response.text
        created = response.json()
        # Alongside, not over: the organization's own copy is untouched and
        # which of the two prints stays somebody's decision.
        assert created['id'] != seeded[0]['id']
        assert created['is_default'] is False

        still_there = client.get(TEMPLATES, headers=eq_auth_headers).json()['items']
        assert seeded[0]['id'] in {t['id'] for t in still_there}
