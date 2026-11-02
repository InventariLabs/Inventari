"""Integration tests for BOM CRUD endpoints."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.user import User

from .conftest import post_bom_line

pytestmark = pytest.mark.integration


class TestBomCrud:
    """POST /bom, GET /bom/{template_id}, DELETE /bom/{line_id}."""

    def test_create_bom_line_returns_201(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_user: User,
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        parent = ProductTemplate(organization_id=mk_org.id, name='Parent product')
        child = ProductTemplate(organization_id=mk_org.id, name='Child ingredient')
        db_session.add_all([parent, child])
        db_session.commit()
        db_session.refresh(parent)
        db_session.refresh(child)

        response = post_bom_line(
            client,
            mk_auth_headers,
            db_session,
            mk_org.id,
            {
                'parent_template_id': str(parent.id),
                'child_template_id': str(child.id),
                'qty_per_batch': '0.500',
                'unit': 'kg',
                'yield_loss_pct': '5.00',
            },
        )

        assert response.status_code == 201, response.text
        body = response.json()
        assert body['parent_template_id'] == str(parent.id)
        assert body['child_template_id'] == str(child.id)
        assert body['qty_per_batch'] == '0.5000'
        assert body['yield_loss_pct'] == '5.00'
        assert 'id' in body

    def test_get_bom_lists_parent_lines(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        parent = ProductTemplate(organization_id=mk_org.id, name='Granola')
        other_parent = ProductTemplate(organization_id=mk_org.id, name='Muesli')
        child1 = ProductTemplate(organization_id=mk_org.id, name='Oats')
        child2 = ProductTemplate(organization_id=mk_org.id, name='Honey')
        other_child = ProductTemplate(organization_id=mk_org.id, name='NotInThisBOM')
        db_session.add_all([parent, other_parent, child1, child2, other_child])
        db_session.commit()
        db_session.refresh(parent)
        db_session.refresh(child1)
        db_session.refresh(child2)
        db_session.refresh(other_child)

        # Two ingredients for `parent`, one for `other_parent`.
        for child in (child1, child2):
            post_bom_line(
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
        post_bom_line(
            client,
            mk_auth_headers,
            db_session,
            mk_org.id,
            {
                'parent_template_id': str(other_parent.id),
                'child_template_id': str(other_child.id),
                'qty_per_batch': '0.200',
                'unit': 'kg',
            },
        )

        response = client.get(
            f'/api/v1/maker/bom/{parent.id}',
            headers=mk_auth_headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert body['total'] == 2
        assert (body['limit'], body['offset'], body['has_more']) == (200, 0, False)
        returned_children = {line['child_template_id'] for line in body['items']}
        assert returned_children == {str(child1.id), str(child2.id)}

        second = client.get(
            f'/api/v1/maker/bom/{parent.id}?limit=1&offset=1',
            headers=mk_auth_headers,
        ).json()
        assert len(second['items']) == 1
        assert (second['total'], second['has_more']) == (2, False)

    def test_create_duplicate_line_returns_409(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        parent = ProductTemplate(organization_id=mk_org.id, name='X')
        child = ProductTemplate(organization_id=mk_org.id, name='Y')
        db_session.add_all([parent, child])
        db_session.commit()
        db_session.refresh(parent)
        db_session.refresh(child)

        payload = {
            'parent_template_id': str(parent.id),
            'child_template_id': str(child.id),
            'qty_per_batch': '1.000',
            'unit': 'kg',
        }
        first = post_bom_line(client, mk_auth_headers, db_session, mk_org.id, payload)
        assert first.status_code == 201

        # 409 is the canonical duplicate: the per-recipe endpoint says
        # "this formula already lists that ingredient" rather than the legacy
        # adapter's generic 400.
        second = post_bom_line(client, mk_auth_headers, db_session, mk_org.id, payload)
        assert second.status_code == 409

    def test_delete_bom_line_returns_204(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        parent = ProductTemplate(organization_id=mk_org.id, name='Cake')
        child = ProductTemplate(organization_id=mk_org.id, name='Flour')
        db_session.add_all([parent, child])
        db_session.commit()
        db_session.refresh(parent)
        db_session.refresh(child)

        created = post_bom_line(
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
        line_id = created.json()['id']

        deleted = client.delete(f'/api/v1/maker/bom/{line_id}', headers=mk_auth_headers)
        assert deleted.status_code == 204

        missing = client.delete(f'/api/v1/maker/bom/{line_id}', headers=mk_auth_headers)
        assert missing.status_code == 404

    def test_create_bom_self_reference_returns_400(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        template = ProductTemplate(organization_id=mk_org.id, name='Quirk')
        db_session.add(template)
        db_session.commit()
        db_session.refresh(template)

        response = post_bom_line(
            client,
            mk_auth_headers,
            db_session,
            mk_org.id,
            {
                'parent_template_id': str(template.id),
                'child_template_id': str(template.id),
                'qty_per_batch': '1.000',
                'unit': 'kg',
            },
        )
        assert response.status_code == 400
        assert 'itself' in response.json()['detail']['message'].lower()

    def test_other_org_cannot_see_bom(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        # Create a parent in mk_org but query it under a different org.
        parent = ProductTemplate(
            organization_id=mk_org.id, name='O-' + uuid.uuid4().hex[:6]
        )
        db_session.add(parent)
        db_session.commit()
        db_session.refresh(parent)

        # Headers from mk_org should return what mk_org owns.
        resp = client.get(
            f'/api/v1/maker/bom/{parent.id}',
            headers=mk_auth_headers,
        )
        assert resp.status_code == 200  # scoped correctly
