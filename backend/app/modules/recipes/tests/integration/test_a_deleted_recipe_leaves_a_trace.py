"""Deleting is the one act in these modules the organization journal keeps.

The screen calls itself "the immutable record of this organisation's actions",
and for a recipe or a meal plan it held nothing at all: one could be written,
edited four times and thrown away, and the row that held its name was the only
copy of it anywhere. The owner's rule is deliberately narrow — edits and
additions in these modules stay out of the log, a deleted record goes in,
because nothing else can rebuild it. These tests pin both halves of that: one
entry naming what went, and silence for everything that is not a deletion.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.contracts import AuditAction
from app.models.audit_log import AuditLog
from app.models.user import User

RECIPE_URL = '/api/v1/recipes'
PLAN_URL = '/api/v1/recipes/meal-plans'


def _recipe_payload(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {'name': 'Naleśniki', 'servings': 2, 'ingredients': []}
    base.update(overrides)
    return base


def _plan_payload(**overrides: Any) -> dict[str, Any]:
    today = date.today()
    base: dict[str, Any] = {
        'name': 'Tydzień 23',
        'start_date': today.isoformat(),
        'end_date': (today + timedelta(days=6)).isoformat(),
        'enabled_slots': ['LUNCH'],
        'default_servings': 2,
    }
    base.update(overrides)
    return base


def _journal(
    db_session: Session, org_id: UUID | None, target_type: str
) -> list[AuditLog]:
    """This organization's entries about one kind of record, oldest first."""
    return list(
        db_session.scalars(
            select(AuditLog)
            .where(
                AuditLog.organization_id == org_id,
                AuditLog.target_type == target_type,
            )
            .order_by(AuditLog.created_at)
        ).all()
    )


@pytest.mark.integration
class TestADeletedRecipeLeavesATrace:
    def test_the_entry_names_the_recipe_and_who_deleted_it(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
    ) -> None:
        created = client.post(
            RECIPE_URL, json=_recipe_payload(name='Naleśniki'), headers=auth_headers
        )
        assert created.status_code == 201
        recipe_id = created.json()['id']

        deleted = client.delete(f'{RECIPE_URL}/{recipe_id}', headers=auth_headers)
        assert deleted.status_code == 204

        db_session.expire_all()
        entries = _journal(db_session, test_user.organization_id, 'recipe')
        assert len(entries) == 1
        entry = entries[0]
        assert entry.target_id == UUID(recipe_id)
        assert entry.action == AuditAction.HARD_DELETE
        assert entry.user_id == test_user.id
        # The name is the point: after the delete there is nothing left to
        # look it up from.
        assert entry.snapshot == {'name': 'Naleśniki'}

    def test_editing_a_recipe_writes_nothing(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
    ) -> None:
        recipe_id = client.post(
            RECIPE_URL, json=_recipe_payload(), headers=auth_headers
        ).json()['id']

        edited = client.put(
            f'{RECIPE_URL}/{recipe_id}',
            json={
                'name': 'Naleśniki z serem',
                'ingredients': [{'name': 'Twaróg', 'quantity': '250'}],
            },
            headers=auth_headers,
        )
        assert edited.status_code == 200

        db_session.expire_all()
        assert _journal(db_session, test_user.organization_id, 'recipe') == []

    def test_a_batch_names_every_recipe_it_removes(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
    ) -> None:
        """The same deletion by another button leaves the same rows."""
        created_ids = [
            client.post(
                RECIPE_URL, json=_recipe_payload(name=name), headers=auth_headers
            ).json()['id']
            for name in ('Pierogi', 'Barszcz')
        ]

        deleted = client.post(
            f'{RECIPE_URL}/bulk-delete',
            json={'recipe_ids': created_ids},
            headers=auth_headers,
        )
        assert deleted.status_code == 200
        assert deleted.json()['deleted'] == 2

        db_session.expire_all()
        entries = _journal(db_session, test_user.organization_id, 'recipe')
        assert {(entry.snapshot or {})['name'] for entry in entries} == {
            'Pierogi',
            'Barszcz',
        }
        assert {entry.action for entry in entries} == {AuditAction.HARD_DELETE}
        assert all((entry.meta_data or {}).get('bulk') is True for entry in entries)


@pytest.mark.integration
class TestADeletedMealPlanLeavesATrace:
    def test_the_entry_names_the_plan_and_who_deleted_it(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
    ) -> None:
        created = client.post(
            PLAN_URL, json=_plan_payload(name='Tydzień 23'), headers=auth_headers
        )
        assert created.status_code == 201
        plan_id = created.json()['id']

        deleted = client.delete(f'{PLAN_URL}/{plan_id}', headers=auth_headers)
        assert deleted.status_code == 204

        db_session.expire_all()
        entries = _journal(db_session, test_user.organization_id, 'meal_plan')
        assert len(entries) == 1
        entry = entries[0]
        assert entry.target_id == UUID(plan_id)
        assert entry.action == AuditAction.HARD_DELETE
        assert entry.user_id == test_user.id
        assert entry.snapshot == {'name': 'Tydzień 23'}

    def test_filling_the_plan_writes_nothing(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
    ) -> None:
        """A meal added to a plan, or a plan renamed, is not a journal act."""
        plan_id = client.post(
            PLAN_URL, json=_plan_payload(), headers=auth_headers
        ).json()['id']
        recipe_id = client.post(
            RECIPE_URL, json=_recipe_payload(), headers=auth_headers
        ).json()['id']

        added = client.post(
            f'{PLAN_URL}/{plan_id}/entries',
            json={
                'date': date.today().isoformat(),
                'slot': 'LUNCH',
                'recipe_id': recipe_id,
                'order': 0,
            },
            headers=auth_headers,
        )
        assert added.status_code == 201
        renamed = client.put(
            f'{PLAN_URL}/{plan_id}', json={'name': 'Nowy tydzień'}, headers=auth_headers
        )
        assert renamed.status_code == 200

        db_session.expire_all()
        assert _journal(db_session, test_user.organization_id, 'meal_plan') == []
