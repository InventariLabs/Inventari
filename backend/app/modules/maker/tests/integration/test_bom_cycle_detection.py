"""Integration tests for BOM cycle detection on POST /bom."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.product_template import ProductTemplate

from .conftest import post_bom_line

pytestmark = pytest.mark.integration


class TestBomCycleDetection:
    """A BOM must never have parent→child cycles. Self-loops are caught too."""

    def test_cycle_two_node_rejected(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        a = ProductTemplate(organization_id=mk_org.id, name='A')
        b = ProductTemplate(organization_id=mk_org.id, name='B')
        db_session.add_all([a, b])
        db_session.commit()
        db_session.refresh(a)
        db_session.refresh(b)

        # A → B is fine.
        first = post_bom_line(
            client,
            mk_auth_headers,
            db_session,
            mk_org.id,
            {
                'parent_template_id': str(a.id),
                'child_template_id': str(b.id),
                'qty_per_batch': '1.000',
                'unit': 'kg',
            },
        )
        assert first.status_code == 201

        # Adding B → A would create a 2-cycle.
        second = post_bom_line(
            client,
            mk_auth_headers,
            db_session,
            mk_org.id,
            {
                'parent_template_id': str(b.id),
                'child_template_id': str(a.id),
                'qty_per_batch': '1.000',
                'unit': 'kg',
            },
        )
        assert second.status_code == 400
        assert 'cycle' in second.json()['detail']['message'].lower()

    def test_cycle_three_node_rejected(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        a = ProductTemplate(organization_id=mk_org.id, name='A')
        b = ProductTemplate(organization_id=mk_org.id, name='B')
        c = ProductTemplate(organization_id=mk_org.id, name='C')
        db_session.add_all([a, b, c])
        db_session.commit()
        db_session.refresh(a)
        db_session.refresh(b)
        db_session.refresh(c)

        # A → B, B → C
        for parent, child in [(a, b), (b, c)]:
            response = post_bom_line(
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
            assert response.status_code == 201

        # C → A must fail (would make A its own descendant via A→B→C→A).
        cycle_response = post_bom_line(
            client,
            mk_auth_headers,
            db_session,
            mk_org.id,
            {
                'parent_template_id': str(c.id),
                'child_template_id': str(a.id),
                'qty_per_batch': '1.000',
                'unit': 'kg',
            },
        )
        assert cycle_response.status_code == 400
        assert 'cycle' in cycle_response.json()['detail']['message'].lower()

    def test_diamond_bom_allowed(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        # Diamond is FINE: A→B, A→C, B→D, C→D — no ancestor of A is a
        # descendant of B or C; in particular, A is not reachable from D.
        a = ProductTemplate(organization_id=mk_org.id, name='A')
        b = ProductTemplate(organization_id=mk_org.id, name='B')
        c = ProductTemplate(organization_id=mk_org.id, name='C')
        d = ProductTemplate(organization_id=mk_org.id, name='D')
        db_session.add_all([a, b, c, d])
        db_session.commit()
        db_session.refresh(a)
        db_session.refresh(b)
        db_session.refresh(c)
        db_session.refresh(d)

        edges = [(a, b), (a, c), (b, d), (c, d)]
        for parent, child in edges:
            response = post_bom_line(
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
            assert response.status_code == 201, response.text
