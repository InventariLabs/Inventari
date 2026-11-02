"""A BOM line names a template of its own organization.

``child_template_id`` is a payload foreign key — the one class the tenancy
linter cannot see, because no org-filtered query ever reads it back through
the guarded paths. An unchecked id wrote a line pointing into another
organization's catalogue: a dangling reference inside the caller's own data,
invisible to every org-scoped reader. The recipes module validates the
identical field on its ingredient lines; the maker BOM now does the same.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.user import User
from app.services.token_service import get_password_hash

pytestmark = pytest.mark.integration


def _template(db: Session, org: Organization, *, name: str) -> ProductTemplate:
    import uuid

    template = ProductTemplate(
        organization_id=org.id,
        name=name,
        sku=f'SKU-{uuid.uuid4().hex[:8]}',
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    return template


def _default_recipe(db: Session, org: Organization, output_id: UUID) -> Any:
    from app.modules.maker.models import MakerRecipe

    recipe = MakerRecipe(
        organization_id=org.id,
        output_template_id=output_id,
        name='Cross-org probe',
        batch_yield_qty=Decimal('1'),
        is_default=True,
    )
    db.add(recipe)
    db.commit()
    db.refresh(recipe)
    return recipe


def _add_line(
    client: TestClient,
    headers: dict[str, str],
    recipe_id: UUID,
    child: UUID,
) -> Any:
    return client.post(
        f'/api/v1/maker/recipes/{recipe_id}/bom-lines',
        headers=headers,
        json={
            'child_template_id': str(child),
            'qty_per_batch': '1',
            'unit': 'pcs',
        },
    )


class TestABomLineNamesATemplateOfItsOwnOrganization:
    def test_a_foreign_organizations_template_is_refused(
        self,
        client: TestClient,
        mk_org: Organization,
        mk_auth_headers: dict[str, str],
        db_session: Session,
    ) -> None:
        import uuid as uuid_module

        other = Organization(
            name='Other catalogue',
            enabled_modules=['core', 'items', 'locations', 'categories', 'maker'],
        )
        db_session.add(other)
        db_session.commit()
        other_user = User(
            email=f'other-{uuid_module.uuid4().hex[:6]}@test.com',
            hashed_password=get_password_hash('pass'),
            full_name='Other',
            organization_id=other.id,
            role='admin',
            is_active=True,
        )
        db_session.add(other_user)
        db_session.commit()

        foreign_template = _template(db_session, other, name='Their flour')
        output = _template(db_session, mk_org, name='Own output')
        recipe = _default_recipe(db_session, mk_org, output.id)

        response = _add_line(client, mk_auth_headers, recipe.id, foreign_template.id)

        assert response.status_code == 404, response.text

    def test_an_own_organizations_template_is_still_accepted(
        self,
        client: TestClient,
        mk_org: Organization,
        mk_auth_headers: dict[str, str],
        db_session: Session,
    ) -> None:
        """Control: the guard refuses the foreign catalogue, not the editor."""
        child = _template(db_session, mk_org, name='Own flour')
        output = _template(db_session, mk_org, name='Own output too')
        recipe = _default_recipe(db_session, mk_org, output.id)

        response = _add_line(client, mk_auth_headers, recipe.id, child.id)

        assert response.status_code == 201, response.text
