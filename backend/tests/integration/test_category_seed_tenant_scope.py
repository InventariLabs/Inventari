"""The domain seed of one organization stays out of another's category list.

Onboarding applies the seed bundle of whichever workspace mode a tenant
picks. Category reads surface owner-less rows (``organization_id IS NULL``)
to *every* organization, so seeding without an owner used to fill the
category list of the whole installation — a tenant in the neutral mode found
33 groceries it never asked for.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.core.product_profiles import apply_profile_seed
from app.models.category import Category
from app.models.organization import Organization
from app.services.token_service import create_access_token

from ._core_api_helpers import make_other_org, make_user

_FOOD_CODES = {'pork', 'dairy', 'pasta'}


def _drop_installation_wide_categories(db_session: Session) -> None:
    """Start from an installation with no shared catalogue.

    The integration snapshot seeds the food catalogue installation-wide (the
    suite was written against the food vertical), which is the very state
    this test is about.
    """
    db_session.query(Category).filter(Category.organization_id.is_(None)).delete(
        synchronize_session=False
    )
    db_session.commit()


def _token_headers(user_id) -> dict[str, str]:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user_id)})}'
    }


@pytest.mark.integration
class TestCategorySeedTenantScope:
    def test_food_seed_is_invisible_to_another_organization(
        self,
        client,
        db_session: Session,
        test_household: Organization,
        auth_headers: dict,
    ):
        """A neutral organization sees nothing of the food tenant's catalogue."""
        _drop_installation_wide_categories(db_session)
        food_org = make_other_org(db_session)

        apply_profile_seed('food_home', db_session, organization_id=food_org.id)

        response = client.get('/api/v1/categories', headers=auth_headers)

        assert response.status_code == 200
        codes = {c['code'] for c in response.json()['items']}
        assert not (codes & _FOOD_CODES), (
            f'another organization sees the food seed: {sorted(codes & _FOOD_CODES)}'
        )

    def test_food_seed_is_visible_to_the_organization_that_chose_it(
        self,
        client,
        db_session: Session,
    ):
        """The tenant that picked the profile keeps its full catalogue."""
        _drop_installation_wide_categories(db_session)
        food_org = make_other_org(db_session)
        food_user = make_user(db_session, 'food-tenant@example.com', food_org.id)

        apply_profile_seed('food_home', db_session, organization_id=food_org.id)

        response = client.get(
            '/api/v1/categories', headers=_token_headers(food_user.id)
        )

        assert response.status_code == 200
        codes = {c['code'] for c in response.json()['items']}
        assert _FOOD_CODES <= codes, f'missing from the chooser: {_FOOD_CODES - codes}'

    def test_seeding_the_same_organization_twice_adds_nothing(
        self,
        db_session: Session,
    ):
        """Profile switching re-runs the seed; it must stay idempotent per owner."""
        _drop_installation_wide_categories(db_session)
        food_org = make_other_org(db_session)

        apply_profile_seed('food_home', db_session, organization_id=food_org.id)
        first = (
            db_session.query(Category)
            .filter(Category.organization_id == food_org.id)
            .count()
        )
        apply_profile_seed(
            'food_home', db_session, organization_id=food_org.id, insert_only=True
        )
        second = (
            db_session.query(Category)
            .filter(Category.organization_id == food_org.id)
            .count()
        )

        assert second == first, f'seed duplicated rows: {first} -> {second}'
