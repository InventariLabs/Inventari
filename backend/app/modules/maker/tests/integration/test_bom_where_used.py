"""Integration tests for where-used (reverse BOM edge).

Test contract:
  - ``GET /maker/bom/where-used?template_id=`` returns every recipe whose
    BOM consumes the template (recipe.lines.child_template_id JOIN
    recipe.output_template_id), with recipe name, output template name and
    per-batch consumption
  - Direct usage only — nested sub-assemblies are NOT reported
    transitively; cycles do not confuse the result
  - Org-scoping: recipes of other organizations are invisible
  - Empty result for templates used nowhere
"""

from __future__ import annotations

from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.product_template import ProductTemplate

pytestmark = pytest.mark.integration


def _make_template(db: Session, org: Organization, name: str) -> ProductTemplate:
    template = ProductTemplate(organization_id=org.id, name=name)
    db.add(template)
    db.commit()
    db.refresh(template)
    return template


def _make_recipe_and_line(
    client: TestClient,
    headers: dict[str, str],
    *,
    db_session: Session,
    org: Organization,
    output_name: str,
    child_id: UUID,
    qty: str = '1',
    unit: str = 'kg',
) -> tuple[UUID, str]:
    """Create a maker recipe with one BOM line via the public API."""
    output = _make_template(db_session, org, output_name)
    resp = client.post(
        '/api/v1/maker/recipes',
        headers=headers,
        json={'output_template_id': str(output.id), 'name': output_name},
    )
    assert resp.status_code == 201, resp.text
    recipe_id = resp.json()['id']
    line_resp = client.post(
        f'/api/v1/maker/recipes/{recipe_id}/bom-lines',
        headers=headers,
        json={
            'child_template_id': str(child_id),
            'qty_per_batch': qty,
            'unit': unit,
        },
    )
    assert line_resp.status_code == 201, line_resp.text
    return recipe_id, output_name


class TestWhereUsed:
    """GET /maker/bom/where-used?template_id=."""

    def test_where_used_lists_all_consuming_recipes(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        flour = _make_template(db_session, mk_org, 'Flour')
        _make_recipe_and_line(
            client,
            mk_auth_headers,
            db_session=db_session,
            org=mk_org,
            output_name='Bread',
            child_id=flour.id,
            qty='0.5',
        )
        _make_recipe_and_line(
            client,
            mk_auth_headers,
            db_session=db_session,
            org=mk_org,
            output_name='Pasta',
            child_id=flour.id,
            qty='0.2',
        )
        # A recipe that does NOT use flour — must stay absent.
        _make_recipe_and_line(
            client,
            mk_auth_headers,
            db_session=db_session,
            org=mk_org,
            output_name='Jam',
            child_id=_make_template(db_session, mk_org, 'Fruit').id,
        )

        resp = client.get(
            '/api/v1/maker/bom/where-used',
            headers=mk_auth_headers,
            params={'template_id': str(flour.id)},
        )
        assert resp.status_code == 200, resp.text
        items = resp.json()['items']
        assert len(items) == 2
        by_name = {item['recipe_name']: item for item in items}
        assert set(by_name) == {'Bread', 'Pasta'}
        bread = by_name['Bread']
        assert bread['qty_per_batch'] == '0.5000'
        assert bread['unit'] == 'kg'
        assert bread['output_template_name'] == 'Bread'
        # recipe_id points at a real maker recipe (uuid-shaped, non-empty).
        assert UUID(bread['recipe_id']) is not None

        paged = client.get(
            '/api/v1/maker/bom/where-used',
            headers=mk_auth_headers,
            params={'template_id': str(flour.id), 'limit': 1},
        ).json()
        assert len(paged['items']) == 1
        assert (paged['total'], paged['has_more']) == (2, True)

    def test_where_used_empty_for_unused_template(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        lonely = _make_template(db_session, mk_org, 'Lonely')
        resp = client.get(
            '/api/v1/maker/bom/where-used',
            headers=mk_auth_headers,
            params={'template_id': str(lonely.id)},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()['items'] == []

    def test_where_used_is_direct_only_not_transitive(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        """A template used only inside a sub-assembly is not reported for
        the top-level recipe (single JOIN, no recursion)."""
        flour = _make_template(db_session, mk_org, 'Flour')
        dough = _make_template(db_session, mk_org, 'Dough')
        # Dough uses flour; the sub-assembly recipe uses dough.
        _make_recipe_and_line(
            client,
            mk_auth_headers,
            db_session=db_session,
            org=mk_org,
            output_name='Dough',
            child_id=flour.id,
        )
        _make_recipe_and_line(
            client,
            mk_auth_headers,
            db_session=db_session,
            org=mk_org,
            output_name='Bread',
            child_id=dough.id,
        )

        resp = client.get(
            '/api/v1/maker/bom/where-used',
            headers=mk_auth_headers,
            params={'template_id': str(flour.id)},
        )
        items = resp.json()['items']
        assert [item['recipe_name'] for item in items] == ['Dough']

    def test_where_used_ignores_cycles(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        """A self-referencing-looking graph (A uses B, B uses A) reports
        each edge once without walking it."""
        a = _make_template(db_session, mk_org, 'A')
        b = _make_template(db_session, mk_org, 'B')
        _make_recipe_and_line(
            client,
            mk_auth_headers,
            db_session=db_session,
            org=mk_org,
            output_name='A',
            child_id=b.id,
        )
        _make_recipe_and_line(
            client,
            mk_auth_headers,
            db_session=db_session,
            org=mk_org,
            output_name='B',
            child_id=a.id,
        )

        resp = client.get(
            '/api/v1/maker/bom/where-used',
            headers=mk_auth_headers,
            params={'template_id': str(a.id)},
        )
        items = resp.json()['items']
        assert [item['recipe_name'] for item in items] == ['B']

    def test_where_used_is_org_scoped(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        h: ModuleTestHelper,
        db_session: Session,
    ) -> None:
        other_org = h.create_org('Other Org', ['core', 'maker'])
        shared = _make_template(db_session, mk_org, 'Shared Ingredient')
        # Other org's recipe uses the same template id — invisible for us.
        # The API refuses this write now (a BOM line names a template of its
        # own organization), so the rogue row is planted directly in the
        # database: the read side must scope by organization even when a row
        # like this one exists — the write guard and the read scope are two
        # halves, and only together do they close the hole.
        from decimal import Decimal

        from app.modules.maker.models import BoMLine, MakerRecipe

        foreign_output = _make_template(db_session, other_org, 'Foreign output')
        foreign_recipe = MakerRecipe(
            organization_id=other_org.id,
            output_template_id=foreign_output.id,
            name='Foreign Recipe',
            batch_yield_qty=Decimal('1'),
            is_default=True,
        )
        db_session.add(foreign_recipe)
        db_session.flush()
        db_session.add(
            BoMLine(
                organization_id=other_org.id,
                recipe_id=foreign_recipe.id,
                parent_template_id=foreign_output.id,
                child_template_id=shared.id,
                qty_per_batch=Decimal('1'),
                unit='kg',
            )
        )
        db_session.commit()

        resp = client.get(
            '/api/v1/maker/bom/where-used',
            headers=mk_auth_headers,
            params={'template_id': str(shared.id)},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()['items'] == []
