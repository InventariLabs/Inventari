"""Fixtures for maker module integration tests."""

from decimal import Decimal
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy.orm import Session

from app.core.contracts import UserContextDTO
from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.user import User
from app.modules.maker.models import MakerRecipe


@pytest.fixture
def h(db_session: Session) -> ModuleTestHelper:
    return ModuleTestHelper(db_session)


@pytest.fixture
def mk_org(h: ModuleTestHelper) -> Organization:
    return h.create_org(
        'Maker Test Org',
        [
            'core',
            'items',
            'locations',
            'categories',
            'stats',
            'maker',
        ],
    )


@pytest.fixture
def mk_user(h: ModuleTestHelper, mk_org: Organization) -> User:
    return h.create_user(mk_org, email='maker@example.com')


@pytest.fixture
def mk_auth_headers(h: ModuleTestHelper, mk_user: User) -> dict[str, str]:
    return h.get_auth_headers(mk_user)


@pytest.fixture
def mk_user_context(mk_user: User) -> UserContextDTO:
    return UserContextDTO(
        id=mk_user.id,
        organization_id=mk_user.organization_id,
    )


@pytest.fixture
def mk_storage_type(h: ModuleTestHelper) -> StorageType:
    return h.create_storage_type('Cold Storage', 'COLD_STORAGE')


@pytest.fixture
def mk_input_loc(
    h: ModuleTestHelper,
    mk_org: Organization,
    mk_storage_type: StorageType,
    mk_user: User,
) -> StorageLocation:
    return h.create_storage_location(
        mk_org,
        mk_storage_type,
        mk_user,
        name='Ingredient Store',
    )


@pytest.fixture
def mk_output_loc(
    h: ModuleTestHelper,
    mk_org: Organization,
    mk_storage_type: StorageType,
    mk_user: User,
) -> StorageLocation:
    return h.create_storage_location(
        mk_org,
        mk_storage_type,
        mk_user,
        name='Output Store',
    )


def post_bom_line(
    client: TestClient,
    headers: dict[str, str],
    db: Session,
    org_id: UUID,
    payload: dict[str, str],
) -> Response:
    """Add an ingredient through the per-recipe endpoint.

    Stands in for the removed ``POST /maker/bom``, which took a
    ``parent_template_id`` and resolved it to that product's *default*
    recipe, creating one when it was missing. Tests keep the old payload
    shape; the recipe is resolved here instead of by an endpoint the
    application no longer has.
    """
    parent_id = UUID(payload['parent_template_id'])
    recipe = (
        db.query(MakerRecipe)
        .filter(
            MakerRecipe.organization_id == org_id,
            MakerRecipe.output_template_id == parent_id,
            MakerRecipe.is_default.is_(True),
        )
        .first()
    )
    if recipe is None:
        recipe = MakerRecipe(
            organization_id=org_id,
            output_template_id=parent_id,
            name='Default',
            batch_yield_qty=Decimal('1'),
            is_default=True,
        )
        db.add(recipe)
        db.commit()
        db.refresh(recipe)
    body = {k: v for k, v in payload.items() if k != 'parent_template_id'}
    response: Response = client.post(
        f'/api/v1/maker/recipes/{recipe.id}/bom-lines',
        headers=headers,
        json=body,
    )
    return response


def _make_template(
    db: Session,
    org: Organization,
    *,
    name: str,
    removal_strategy: str = 'FIFO',
) -> ProductTemplate:
    """Create an org-scoped ProductTemplate with the given removal strategy."""
    template = ProductTemplate(
        organization_id=org.id,
        name=name,
        removal_strategy=removal_strategy,
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    return template
