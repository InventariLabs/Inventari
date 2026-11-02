"""Integration tests for GET /bom/parents — list of templates that have a BOM."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.product_template import ProductTemplate

from .conftest import post_bom_line

pytestmark = pytest.mark.integration


class TestBomParents:
    """GET /api/v1/maker/bom/parents lists recipes (parents with >=1 line)."""

    def test_parents_returns_templates_with_lines(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        parent_a = ProductTemplate(organization_id=mk_org.id, name='Granola Bars')
        parent_b = ProductTemplate(organization_id=mk_org.id, name='Trail Mix')
        child = ProductTemplate(organization_id=mk_org.id, name='Oats')
        lonely = ProductTemplate(organization_id=mk_org.id, name='NoRecipe')
        db_session.add_all([parent_a, parent_b, child, lonely])
        db_session.commit()
        for p in (parent_a, parent_b, child):
            db_session.refresh(p)

        for parent in (parent_a, parent_b):
            resp = post_bom_line(
                client,
                mk_auth_headers,
                db_session,
                mk_org.id,
                {
                    'parent_template_id': str(parent.id),
                    'child_template_id': str(child.id),
                    'qty_per_batch': '0.100',
                    'unit': 'kg',
                },
            )
            assert resp.status_code == 201, resp.text

        response = client.get(
            '/api/v1/maker/bom/parents',
            headers=mk_auth_headers,
        )
        assert response.status_code == 200
        items = response.json()['items']
        by_id = {e['template_id']: e for e in items}
        assert str(parent_a.id) in by_id
        assert str(parent_b.id) in by_id
        assert str(lonely.id) not in by_id
        assert by_id[str(parent_a.id)]['name'] == 'Granola Bars'
        assert by_id[str(parent_a.id)]['line_count'] == 1

        first = client.get(
            '/api/v1/maker/bom/parents',
            params={'limit': 1},
            headers=mk_auth_headers,
        ).json()
        assert [e['name'] for e in first['items']] == ['Granola Bars']
        assert (first['total'], first['limit'], first['has_more']) == (2, 1, True)
        second = client.get(
            '/api/v1/maker/bom/parents',
            params={'limit': 1, 'offset': 1},
            headers=mk_auth_headers,
        ).json()
        assert [e['name'] for e in second['items']] == ['Trail Mix']
        assert (second['offset'], second['has_more']) == (1, False)

    def test_parents_empty_when_no_boms(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
    ) -> None:
        response = client.get(
            '/api/v1/maker/bom/parents',
            headers=mk_auth_headers,
        )
        assert response.status_code == 200
        assert response.json()['items'] == []

    def test_parents_is_org_scoped(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
        h: ModuleTestHelper,
    ) -> None:
        # BOM in mk_org
        parent = ProductTemplate(organization_id=mk_org.id, name='OrgRecipe')
        child = ProductTemplate(organization_id=mk_org.id, name='OrgChild')
        db_session.add_all([parent, child])
        db_session.commit()
        db_session.refresh(parent)
        db_session.refresh(child)
        post_bom_line(
            client,
            mk_auth_headers,
            db_session,
            mk_org.id,
            {
                'parent_template_id': str(parent.id),
                'child_template_id': str(child.id),
                'qty_per_batch': '1.000',
                'unit': 'kg',
            },
        )

        # Different org with maker enabled — must not see mk_org's recipes.
        other_org = h.create_org('Other Org', ['core', 'items', 'maker'])
        other_user = h.create_user(other_org, email='other@example.com')
        other_headers = h.get_auth_headers(other_user)

        response = client.get(
            '/api/v1/maker/bom/parents',
            headers=other_headers,
        )
        assert response.status_code == 200
        assert response.json()['items'] == []
