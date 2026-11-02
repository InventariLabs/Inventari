"""Integration tests for the hierarchical BOM tree and reparent endpoints."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.user import User
from app.modules.maker.models import BoMLine, MakerRecipe

pytestmark = pytest.mark.integration


def _make_template(
    db_session: Session, org: Organization, *, name: str
) -> ProductTemplate:
    template = ProductTemplate(
        organization_id=org.id,
        name=name,
        removal_strategy='FIFO',
    )
    db_session.add(template)
    db_session.commit()
    db_session.refresh(template)
    return template


def _ensure_recipe(
    db_session: Session, org: Organization, *, template_id: UUID
) -> MakerRecipe:
    """Get or create a default recipe for *template_id*."""
    existing = (
        db_session.query(MakerRecipe)
        .filter(
            MakerRecipe.organization_id == org.id,
            MakerRecipe.output_template_id == template_id,
            MakerRecipe.is_default.is_(True),
        )
        .first()
    )
    if existing:
        return existing
    recipe = MakerRecipe(
        organization_id=org.id,
        output_template_id=template_id,
        name='Test',
        batch_yield_qty=Decimal('1'),
        is_default=True,
    )
    db_session.add(recipe)
    db_session.commit()
    db_session.refresh(recipe)
    return recipe


def _make_line(
    db_session: Session,
    org: Organization,
    *,
    parent_id: UUID,
    child_id: UUID,
    qty: str = '1.0',
    unit: str = 'kg',
) -> BoMLine:
    recipe = _ensure_recipe(db_session, org, template_id=parent_id)
    line = BoMLine(
        organization_id=org.id,
        recipe_id=recipe.id,
        parent_template_id=parent_id,
        child_template_id=child_id,
        qty_per_batch=Decimal(qty),
        unit=unit,
    )
    db_session.add(line)
    db_session.commit()
    db_session.refresh(line)
    return line


class TestBomTree:
    URL_TREE = '/api/v1/maker/bom/tree/{template_id}'
    URL_MOVE = '/api/v1/maker/bom/{line_id}/move'

    def test_tree_returns_nested_structure(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        """Two-level BOM: A → B → C. Should appear nested in tree response."""
        a = _make_template(db_session, mk_org, name='Powidła')
        b = _make_template(db_session, mk_org, name='Konfitura')
        c = _make_template(db_session, mk_org, name='Śliwki')

        ab = _make_line(db_session, mk_org, parent_id=a.id, child_id=b.id)
        bc = _make_line(db_session, mk_org, parent_id=b.id, child_id=c.id)

        response = client.get(
            self.URL_TREE.format(template_id=a.id),
            headers=mk_auth_headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body['parent_template_id'] == str(a.id)
        root = body['root']
        assert root['line'] is None
        assert len(root['children']) == 1
        first = root['children'][0]
        assert first['line']['id'] == str(ab.id)
        assert len(first['children']) == 1
        grandchild = first['children'][0]
        assert grandchild['line']['id'] == str(bc.id)
        assert grandchild['children'] == []

    def test_tree_returns_empty_for_template_without_lines(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        leaf = _make_template(db_session, mk_org, name='Leaf')
        response = client.get(
            self.URL_TREE.format(template_id=leaf.id),
            headers=mk_auth_headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert body['root']['children'] == []

    def test_move_line_to_new_parent(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        """Move the plum-ingredient from Soup parent to Stew parent."""
        soup = _make_template(db_session, mk_org, name='Zupa')
        stew = _make_template(db_session, mk_org, name='Gulasz')
        plum = _make_template(db_session, mk_org, name='Śliwki')

        line = _make_line(db_session, mk_org, parent_id=soup.id, child_id=plum.id)

        response = client.post(
            self.URL_MOVE.format(line_id=line.id),
            headers=mk_auth_headers,
            json={'new_parent_template_id': str(stew.id)},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body['parent_template_id'] == str(stew.id)
        assert body['id'] == str(line.id)

        # Verify persisted state.
        db_session.expire_all()
        reloaded = db_session.get(BoMLine, line.id)
        assert reloaded is not None
        assert reloaded.parent_template_id == stew.id

    def test_move_under_a_template_named_past_the_recipe_limit(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        """A template name up to the catalogue's 255 still gets its recipe.

        The auto-created default recipe is named after the template, and a
        recipe name holds 200: the move answered 500 on the truncation.
        """
        soup = _make_template(db_session, mk_org, name='Zupa')
        stew = _make_template(db_session, mk_org, name='G' * 250)
        plum = _make_template(db_session, mk_org, name='Śliwki')
        line = _make_line(db_session, mk_org, parent_id=soup.id, child_id=plum.id)

        response = client.post(
            self.URL_MOVE.format(line_id=line.id),
            headers=mk_auth_headers,
            json={'new_parent_template_id': str(stew.id)},
        )
        assert response.status_code == 200, response.text

        db_session.expire_all()
        recipe = (
            db_session.query(MakerRecipe)
            .filter(MakerRecipe.output_template_id == stew.id)
            .one()
        )
        assert recipe.name == 'G' * 200
        assert recipe.is_default is True

    def test_move_rejects_self_parent(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        soup = _make_template(db_session, mk_org, name='A')
        plum = _make_template(db_session, mk_org, name='B')
        line = _make_line(db_session, mk_org, parent_id=soup.id, child_id=plum.id)
        response = client.post(
            self.URL_MOVE.format(line_id=line.id),
            headers=mk_auth_headers,
            json={'new_parent_template_id': str(plum.id)},
        )
        assert response.status_code == 400

    def test_move_rejects_cycle(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        """Moving the A→B line under B (its own child) would create a cycle."""
        a = _make_template(db_session, mk_org, name='A')
        b = _make_template(db_session, mk_org, name='B')
        ab = _make_line(db_session, mk_org, parent_id=a.id, child_id=b.id)

        response = client.post(
            self.URL_MOVE.format(line_id=ab.id),
            headers=mk_auth_headers,
            json={'new_parent_template_id': str(b.id)},
        )
        assert response.status_code == 400

    def test_move_rejects_duplicate_pair(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        """UNIQUE(parent, child) — moving the A→C line so it duplicates
        an existing A→C line must 400 (UNIQUE constraint violation)."""
        a = _make_template(db_session, mk_org, name='A')
        b = _make_template(db_session, mk_org, name='B')
        c = _make_template(db_session, mk_org, name='C')

        _make_line(db_session, mk_org, parent_id=a.id, child_id=c.id)
        bc = _make_line(db_session, mk_org, parent_id=b.id, child_id=c.id)

        response = client.post(
            self.URL_MOVE.format(line_id=bc.id),
            headers=mk_auth_headers,
            json={'new_parent_template_id': str(a.id)},
        )
        assert response.status_code == 400

    def test_move_other_org_line_isolated(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        mk_auth_headers: dict[str, str],
        mk_user: User,
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        """Move issued from a different org must not see the line."""
        soup_a = _make_template(db_session, mk_org, name='A')
        plum_a = _make_template(db_session, mk_org, name='B')
        line = _make_line(db_session, mk_org, parent_id=soup_a.id, child_id=plum_a.id)

        org_b = h.create_org('Maker Tree B', ['core', 'items', 'locations', 'maker'])
        user_b = h.create_user(org_b, email='b@example.com')
        headers_b = h.get_auth_headers(user_b)

        response = client.post(
            self.URL_MOVE.format(line_id=line.id),
            headers=headers_b,
            json={'new_parent_template_id': str(soup_a.id)},
        )
        assert response.status_code == 400
