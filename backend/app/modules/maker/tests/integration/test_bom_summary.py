"""Integration tests for GET /bom/summary — batched BOM existence query."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.product_template import ProductTemplate

from .conftest import post_bom_line

pytestmark = pytest.mark.integration


class TestBomSummary:
    """GET /api/v1/maker/bom/summary returns one entry per template with a BOM."""

    def test_bom_summary_returns_counts_for_parents(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        parent = ProductTemplate(organization_id=mk_org.id, name='Granola')
        child1 = ProductTemplate(organization_id=mk_org.id, name='Oats')
        child2 = ProductTemplate(organization_id=mk_org.id, name='Honey')
        db_session.add_all([parent, child1, child2])
        db_session.commit()
        db_session.refresh(parent)
        db_session.refresh(child1)
        db_session.refresh(child2)

        for child in (child1, child2):
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
            '/api/v1/maker/bom/summary',
            params={'template_ids': f'{parent.id},{uuid.uuid4()}'},
            headers=mk_auth_headers,
        )
        assert response.status_code == 200
        found = {e['template_id']: e for e in response.json()['items']}
        assert str(parent.id) in found
        assert found[str(parent.id)]['line_count'] == 2

    def test_bom_summary_empty_for_templates_without_bom(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        template = ProductTemplate(organization_id=mk_org.id, name='Lonely')
        db_session.add(template)
        db_session.commit()
        db_session.refresh(template)

        response = client.get(
            '/api/v1/maker/bom/summary',
            params={'template_ids': str(template.id)},
            headers=mk_auth_headers,
        )
        assert response.status_code == 200
        assert response.json()['items'] == []

    def test_bom_summary_empty_input_returns_empty(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
    ) -> None:
        response = client.get(
            '/api/v1/maker/bom/summary',
            params={'template_ids': ''},
            headers=mk_auth_headers,
        )
        assert response.status_code == 200
        assert response.json()['items'] == []

    def test_bom_summary_invalid_uuid_returns_400(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
    ) -> None:
        response = client.get(
            '/api/v1/maker/bom/summary',
            params={'template_ids': 'not-a-uuid'},
            headers=mk_auth_headers,
        )
        assert response.status_code == 400


class TestTemplateIdsWithBom:
    """GET /api/v1/maker/bom/template-ids feeds the "has a formula" filter.

    The product list is virtualised, so it cannot answer "does this row have a
    formula" for rows it has not fetched — the filter needs the whole set up
    front, and Core must not learn what a formula is to provide it.
    """

    def test_returns_only_templates_that_have_a_formula(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        parent = ProductTemplate(organization_id=mk_org.id, name='Granola')
        child = ProductTemplate(organization_id=mk_org.id, name='Oats')
        plain = ProductTemplate(organization_id=mk_org.id, name='Salt')
        db_session.add_all([parent, child, plain])
        db_session.commit()
        for template in (parent, child, plain):
            db_session.refresh(template)

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

        response = client.get('/api/v1/maker/bom/template-ids', headers=mk_auth_headers)

        assert response.status_code == 200
        ids = set(response.json()['template_ids'])
        assert str(parent.id) in ids
        assert str(plain.id) not in ids
        # An ingredient is not a product with a formula.
        assert str(child.id) not in ids

    def test_is_scoped_to_the_organization(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        other_org = Organization(name='Someone else')
        db_session.add(other_org)
        db_session.commit()
        db_session.refresh(other_org)

        foreign = ProductTemplate(organization_id=other_org.id, name='Their mix')
        db_session.add(foreign)
        db_session.commit()
        db_session.refresh(foreign)

        response = client.get('/api/v1/maker/bom/template-ids', headers=mk_auth_headers)

        assert response.status_code == 200
        assert str(foreign.id) not in set(response.json()['template_ids'])

    def test_requires_authentication(self, client: TestClient) -> None:
        response = client.get('/api/v1/maker/bom/template-ids')
        assert response.status_code == 401
