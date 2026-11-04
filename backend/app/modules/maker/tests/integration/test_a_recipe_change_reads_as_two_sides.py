"""A recipe edit is journalled in the shape the journal screen can read.

Every other service records a change as `before`/`after` at the top of the
snapshot, and the audit screen renders that as "Field: old → new". This
service invented `{'changed': {field: {from, to}}}`, which the reader does
not parse — so the row came out as a literal
`Changed: {"qty_per_batch":{"from":2,"to":5}}`, and the unit came out as a
UUID. Both were found on the screen, after the tests on the table had passed.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.organization import Organization
from app.models.uom import Uom, UomCategory
from app.modules.maker.tests.integration.test_production_consume_create import (
    _template,
)

pytestmark = pytest.mark.integration


def _kilogram(db: Session) -> Uom:
    category = UomCategory(organization_id=None, name=f'Weight {uuid.uuid4().hex[:6]}')
    db.add(category)
    db.flush()
    uom = Uom(category_id=category.id, name='Kilogram', symbol='kg')
    db.add(uom)
    db.commit()
    db.refresh(uom)
    return uom


def _snapshot(entry: AuditLog) -> dict[str, Any]:
    """The entry's snapshot, which every entry these tests read has."""
    assert entry.snapshot is not None
    return entry.snapshot


def _entries(db: Session, org: Organization) -> list[AuditLog]:
    return (
        db.query(AuditLog)
        .filter(
            AuditLog.organization_id == org.id,
            AuditLog.target_type == 'maker_recipe',
            AuditLog.action == 'UPDATE',
        )
        .order_by(AuditLog.created_at.desc())
        .all()
    )


def _recipe_with_a_line(
    client: TestClient,
    headers: dict[str, str],
    db: Session,
    org: Organization,
) -> tuple[dict[str, Any], dict[str, Any]]:
    output = _template(db, org, name='Powidła śliwkowe')
    ingredient = _template(db, org, name='Śliwki węgierki')
    created = client.post(
        '/api/v1/maker/recipes',
        headers=headers,
        json={
            'output_template_id': str(output.id),
            'name': 'Review test A',
            'batch_yield_qty': '2',
        },
    )
    assert created.status_code == 201, created.text
    recipe = created.json()
    line = client.post(
        f'/api/v1/maker/recipes/{recipe["id"]}/bom-lines',
        headers=headers,
        json={
            'child_template_id': str(ingredient.id),
            'qty_per_batch': '2',
            'unit': 'szt',
        },
    )
    assert line.status_code == 201, line.text
    return recipe, line.json()


class TestTheJournalReadsARecipeChange:
    def test_a_renamed_recipe_carries_both_names(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        recipe, _ = _recipe_with_a_line(client, mk_auth_headers, db_session, mk_org)

        renamed = client.patch(
            f'/api/v1/maker/recipes/{recipe["id"]}',
            headers=mk_auth_headers,
            json={'name': 'Review test B'},
        )
        assert renamed.status_code == 200, renamed.text

        entry = _entries(db_session, mk_org)[0]
        assert _snapshot(entry)['before'] == {'name': 'Review test A'}
        assert _snapshot(entry)['after'] == {'name': 'Review test B'}
        assert 'changed' not in _snapshot(entry)

    def test_an_ingredient_change_says_which_ingredient(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        recipe, line = _recipe_with_a_line(client, mk_auth_headers, db_session, mk_org)

        edited = client.patch(
            f'/api/v1/maker/recipes/{recipe["id"]}/bom-lines/{line["id"]}',
            headers=mk_auth_headers,
            json={'qty_per_batch': '5'},
        )
        assert edited.status_code == 200, edited.text

        entry = _entries(db_session, mk_org)[0]
        assert _snapshot(entry)['before']['qty_per_batch'] == '2.0000'
        assert _snapshot(entry)['after']['qty_per_batch'] == '5.0000'
        # The line the change is about, beside the change — a recipe has
        # more than one.
        assert _snapshot(entry)['ingredient'] == 'Śliwki węgierki'
        assert _snapshot(entry)['name'] == 'Review test A'

    def test_a_unit_is_recorded_as_its_symbol(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        """`uom_id: null → 38690ddd-…` records a change nobody can read."""
        recipe, line = _recipe_with_a_line(client, mk_auth_headers, db_session, mk_org)
        uom = _kilogram(db_session)

        edited = client.patch(
            f'/api/v1/maker/recipes/{recipe["id"]}/bom-lines/{line["id"]}',
            headers=mk_auth_headers,
            json={'uom_id': str(uom.id)},
        )
        assert edited.status_code == 200, edited.text

        entry = _entries(db_session, mk_org)[0]
        assert _snapshot(entry)['after']['uom'] == 'kg'
        assert _snapshot(entry)['before']['uom'] is None
        assert 'uom_id' not in _snapshot(entry)['after']
        assert str(uom.id) not in str(_snapshot(entry))

    def test_a_cost_line_change_carries_both_amounts(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        recipe, _ = _recipe_with_a_line(client, mk_auth_headers, db_session, mk_org)
        created = client.post(
            f'/api/v1/maker/recipes/{recipe["id"]}/cost-lines',
            headers=mk_auth_headers,
            json={'kind': 'FIXED', 'label': 'Gaz', 'amount': '3.5'},
        )
        assert created.status_code == 201, created.text

        edited = client.patch(
            f'/api/v1/maker/recipes/{recipe["id"]}/cost-lines/{created.json()["id"]}',
            headers=mk_auth_headers,
            json={'amount': '4'},
        )
        assert edited.status_code == 200, edited.text

        entry = _entries(db_session, mk_org)[0]
        assert _snapshot(entry)['before'] == {'amount': '3.50'}
        assert _snapshot(entry)['after'] == {'amount': '4.00'}
        assert _snapshot(entry)['cost_line'] == 'Gaz'


class TestTheJournalKeepsTheExactDigits:
    def test_a_quantity_is_written_as_the_digits_the_column_holds(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        """A float would print 1234.5678 rounded to six figures on the screen."""
        recipe, line = _recipe_with_a_line(client, mk_auth_headers, db_session, mk_org)

        edited = client.patch(
            f'/api/v1/maker/recipes/{recipe["id"]}/bom-lines/{line["id"]}',
            headers=mk_auth_headers,
            json={'qty_per_batch': '1234.5678'},
        )
        assert edited.status_code == 200, edited.text

        entry = _entries(db_session, mk_org)[0]
        assert _snapshot(entry)['after']['qty_per_batch'] == '1234.5678'

    def test_the_same_quantity_with_other_digits_writes_nothing(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        recipe, line = _recipe_with_a_line(client, mk_auth_headers, db_session, mk_org)
        written = len(_entries(db_session, mk_org))

        edited = client.patch(
            f'/api/v1/maker/recipes/{recipe["id"]}/bom-lines/{line["id"]}',
            headers=mk_auth_headers,
            json={'qty_per_batch': '2.0000'},
        )
        assert edited.status_code == 200, edited.text

        assert len(_entries(db_session, mk_org)) == written

    def test_an_added_and_a_removed_ingredient_carry_the_exact_quantity(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        recipe, line = _recipe_with_a_line(client, mk_auth_headers, db_session, mk_org)
        extra = _template(db_session, mk_org, name='Cukier')
        added = client.post(
            f'/api/v1/maker/recipes/{recipe["id"]}/bom-lines',
            headers=mk_auth_headers,
            json={
                'child_template_id': str(extra.id),
                'qty_per_batch': '0.1',
                'unit': 'szt',
            },
        )
        assert added.status_code == 201, added.text
        removed = client.delete(
            f'/api/v1/maker/recipes/{recipe["id"]}/bom-lines/{added.json()["id"]}',
            headers=mk_auth_headers,
        )
        assert removed.status_code == 204, removed.text

        removal, addition = _entries(db_session, mk_org)[:2]
        assert _snapshot(addition)['qty_per_batch'] == '0.1000'
        assert _snapshot(removal)['qty_per_batch'] == '0.1000'
