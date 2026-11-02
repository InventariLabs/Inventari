"""A production recipe changes what a run consumes, so the journal sees it.

The maker module had one ``log_action`` call in its whole tree, on the
production order. Nothing recorded that a *formula* moved — and the formula is
read live at completion (``production_service._explode_planned_consumption``),
so a BOM line edited while an order is open changes what that order will take
off the shelf. The tab named "History" on the recipe screen is the production
history, not a change history, so a reader looking for "who changed this"
found a table that answered a different question and left reassured.

These tests walk the API, because the journal entry is what the organization
sees, not what a service returns.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.contracts import AuditAction, AuditTargetType
from app.models.audit_log import AuditLog
from app.models.organization import Organization
from app.models.product_template import ProductTemplate

pytestmark = pytest.mark.integration


def _snapshot(entry: AuditLog) -> dict[str, Any]:
    """The entry's snapshot, asserted present — an empty one is a failure."""
    assert entry.snapshot is not None
    return entry.snapshot


def _entries(
    db: Session, org_id: UUID, target_id: UUID | None = None
) -> list[AuditLog]:
    stmt = select(AuditLog).where(
        AuditLog.organization_id == org_id,
        AuditLog.target_type == AuditTargetType.MAKER_RECIPE.value,
    )
    if target_id is not None:
        stmt = stmt.where(AuditLog.target_id == target_id)
    return list(db.scalars(stmt.order_by(AuditLog.created_at)))


def _templates(db: Session, org_id: UUID, *names: str) -> tuple[ProductTemplate, ...]:
    rows = [ProductTemplate(organization_id=org_id, name=name) for name in names]
    db.add_all(rows)
    db.commit()
    for row in rows:
        db.refresh(row)
    return tuple(rows)


def _create_recipe(
    client: TestClient, headers: dict[str, str], output_id: UUID, name: str
) -> dict[str, Any]:
    resp = client.post(
        '/api/v1/maker/recipes',
        headers=headers,
        json={
            'output_template_id': str(output_id),
            'name': name,
            'batch_yield_qty': '1',
        },
    )
    assert resp.status_code in (200, 201), resp.text
    body: dict[str, Any] = resp.json()
    return body


class TestTheJournalSeesTheRecipe:
    def test_creating_a_recipe_leaves_an_entry_naming_it(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        (output,) = _templates(db_session, mk_org.id, 'Plum jam')

        recipe = _create_recipe(client, mk_auth_headers, output.id, 'Jam v1')

        entries = _entries(db_session, mk_org.id, UUID(recipe['id']))
        assert len(entries) == 1
        assert entries[0].action == AuditAction.CREATE.value
        assert _snapshot(entries[0])['name'] == 'Jam v1'
        assert _snapshot(entries[0])['output'] == 'Plum jam'

    def test_a_rename_carries_both_sides_and_nothing_else(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        """An entry listing every field would not say which one moved."""
        (output,) = _templates(db_session, mk_org.id, 'Plum jam')
        recipe = _create_recipe(client, mk_auth_headers, output.id, 'Jam v1')

        resp = client.patch(
            f'/api/v1/maker/recipes/{recipe["id"]}',
            headers=mk_auth_headers,
            json={'name': 'Jam v2'},
        )
        assert resp.status_code == 200, resp.text

        entries = _entries(db_session, mk_org.id, UUID(recipe['id']))
        update = entries[-1]
        assert update.action == AuditAction.UPDATE.value
        # The two sides, in the shape the journal screen renders — the
        # service's own `{'changed': {field: {from, to}}}` was printed at the
        # reader as raw JSON.
        assert _snapshot(update)['before'] == {'name': 'Jam v1'}
        assert _snapshot(update)['after'] == {'name': 'Jam v2'}

    def test_a_write_that_changes_nothing_leaves_nothing(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        (output,) = _templates(db_session, mk_org.id, 'Plum jam')
        recipe = _create_recipe(client, mk_auth_headers, output.id, 'Jam v1')
        before = len(_entries(db_session, mk_org.id, UUID(recipe['id'])))

        resp = client.patch(
            f'/api/v1/maker/recipes/{recipe["id"]}',
            headers=mk_auth_headers,
            json={'name': 'Jam v1'},
        )
        assert resp.status_code == 200, resp.text

        assert len(_entries(db_session, mk_org.id, UUID(recipe['id']))) == before

    def test_deleting_a_recipe_is_recorded_while_its_name_still_exists(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        (output,) = _templates(db_session, mk_org.id, 'Plum jam')
        recipe = _create_recipe(client, mk_auth_headers, output.id, 'Jam v1')

        resp = client.delete(
            f'/api/v1/maker/recipes/{recipe["id"]}', headers=mk_auth_headers
        )
        assert resp.status_code == 204, resp.text

        entries = _entries(db_session, mk_org.id, UUID(recipe['id']))
        removal = entries[-1]
        assert removal.action == AuditAction.HARD_DELETE.value
        assert _snapshot(removal)['name'] == 'Jam v1'


class TestTheJournalSeesTheLines:
    def test_adding_an_ingredient_names_it_and_the_recipe(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        output, sugar = _templates(db_session, mk_org.id, 'Plum jam', 'Sugar')
        recipe = _create_recipe(client, mk_auth_headers, output.id, 'Jam v1')

        resp = client.post(
            f'/api/v1/maker/recipes/{recipe["id"]}/bom-lines',
            headers=mk_auth_headers,
            json={
                'child_template_id': str(sugar.id),
                'qty_per_batch': '0.500',
                'unit': 'kg',
            },
        )
        assert resp.status_code == 201, resp.text

        entry = _entries(db_session, mk_org.id, UUID(recipe['id']))[-1]
        assert _snapshot(entry)['name'] == 'Jam v1'
        assert _snapshot(entry)['ingredient_added'] == 'Sugar'
        assert _snapshot(entry)['qty_per_batch'] == 0.5

    def test_the_quantity_a_run_will_consume_is_recorded_both_ways(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        """The change the task was filed for: 0.2 kg of wax becomes 99 kg."""
        output, wax = _templates(db_session, mk_org.id, 'Candle', 'Wax')
        recipe = _create_recipe(client, mk_auth_headers, output.id, 'Candle v1')
        created = client.post(
            f'/api/v1/maker/recipes/{recipe["id"]}/bom-lines',
            headers=mk_auth_headers,
            json={
                'child_template_id': str(wax.id),
                'qty_per_batch': '0.200',
                'unit': 'kg',
            },
        )
        assert created.status_code == 201, created.text
        line_id = created.json()['id']

        resp = client.patch(
            f'/api/v1/maker/recipes/{recipe["id"]}/bom-lines/{line_id}',
            headers=mk_auth_headers,
            json={'qty_per_batch': '99'},
        )
        assert resp.status_code == 200, resp.text

        entry = _entries(db_session, mk_org.id, UUID(recipe['id']))[-1]
        assert _snapshot(entry)['ingredient'] == 'Wax'
        assert _snapshot(entry)['before']['qty_per_batch'] == 0.2
        assert _snapshot(entry)['after']['qty_per_batch'] == 99.0

    def test_removing_an_ingredient_is_recorded_from_either_door(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        """The tree view deletes a line by id, without naming the recipe."""
        output, wax = _templates(db_session, mk_org.id, 'Candle', 'Wax')
        recipe = _create_recipe(client, mk_auth_headers, output.id, 'Candle v1')
        created = client.post(
            f'/api/v1/maker/recipes/{recipe["id"]}/bom-lines',
            headers=mk_auth_headers,
            json={
                'child_template_id': str(wax.id),
                'qty_per_batch': '0.200',
                'unit': 'kg',
            },
        )
        assert created.status_code == 201, created.text

        resp = client.delete(
            f'/api/v1/maker/bom/{created.json()["id"]}', headers=mk_auth_headers
        )
        assert resp.status_code == 204, resp.text

        entry = _entries(db_session, mk_org.id, UUID(recipe['id']))[-1]
        assert _snapshot(entry)['ingredient_removed'] == 'Wax'
        assert _snapshot(entry)['qty_per_batch'] == 0.2
