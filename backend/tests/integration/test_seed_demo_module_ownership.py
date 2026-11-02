"""What the demo seeder writes on an equipment record, and where it files it.

The seeder builds ``Item`` rows through the ORM rather than the service layer,
so nothing else fills in the two marks the rest of the application reads: the
``meta_data['equipment']`` namespace and the ``module_name`` derived from it.
Without them a seeded server is a record no list owns — the core inventory
shows it with "remove one unit" beside it, and the module that made it cannot
find it. The categories moved per organization in ``modcat01``, which is how
the seed started producing them: a lookup over global categories alone came
back empty and every ``cat_ids.get(...)`` quietly returned ``None``.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.module_ownership import unclaimed_by_a_module
from app.models.category import Category
from app.models.item import Item
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.user import User
from app.modules.equipment._assets_service import _asset_filters
from seed_demo_data import (
    EQUIPMENT_TEMPLATES,
    SeedCategoriesMissingError,
    _create_equipment_items,
    _resolve_category_ids,
)

pytestmark = pytest.mark.integration


def _category(org_id: uuid.UUID | None, code: str, *, tag: str | None) -> Category:
    return Category(
        id=uuid.uuid4(),
        organization_id=org_id,
        name=code.title(),
        code=code,
        context_tag=tag,
        is_active=True,
    )


@pytest.fixture
def equipment_categories(
    db_session: Session, test_household: Organization
) -> dict[str, uuid.UUID]:
    """The categories the equipment module's on_enable would have seeded."""
    codes = sorted({t[3] for t in EQUIPMENT_TEMPLATES})
    rows = [
        _category(test_household.id, code.upper(), tag='equipment') for code in codes
    ]
    db_session.add_all(rows)
    db_session.commit()
    return {row.code.lower(): row.id for row in rows}


@pytest.fixture
def equipment_locations(
    db_session: Session, test_household: Organization, test_user: User
) -> dict[str, StorageLocation]:
    """A site → room → shelf chain, because the seeder only fills leaves."""
    stype = StorageType(
        id=uuid.uuid4(),
        organization_id=test_household.id,
        name='IT Rack',
        type_code=f'IT_RACK_{uuid.uuid4().hex[:6]}',
        behavior_mode='NONE',
    )
    db_session.add(stype)
    db_session.flush()

    chain: dict[str, StorageLocation] = {}
    parent_id = None
    for key in ('site', 'room', 'shelf'):
        node = StorageLocation(
            id=uuid.uuid4(),
            organization_id=test_household.id,
            name=f'Equipment {key}',
            storage_type_id=stype.id,
            parent_id=parent_id,
            context_tag='equipment',
            created_by=test_user.id,
        )
        db_session.add(node)
        db_session.flush()
        chain[key] = node
        parent_id = node.id
    db_session.commit()
    return chain


@pytest.fixture
def equipment_template(
    db_session: Session, test_household: Organization
) -> ProductTemplate:
    template = ProductTemplate(
        id=uuid.uuid4(),
        organization_id=test_household.id,
        name='Dell PowerEdge R750',
        brand='Dell',
        barcode=f'SEEDTEST{uuid.uuid4().hex[:8]}',
        meta_data={'equipment': {'cpu': 'Xeon'}},
    )
    db_session.add(template)
    db_session.commit()
    return template


class TestResolveCategoryIds:
    def test_it_finds_the_categories_the_organization_owns(
        self,
        db_session: Session,
        test_household: Organization,
        equipment_categories: dict[str, uuid.UUID],
    ) -> None:
        """Module categories are per-organization rows since ``modcat01``."""
        resolved = _resolve_category_ids(
            db_session, test_household.id, catalogue='equipment'
        )

        assert resolved['server'] == equipment_categories['server']

    def test_a_food_code_does_not_answer_for_an_equipment_shelf(
        self,
        db_session: Session,
        test_household: Organization,
        equipment_categories: dict[str, uuid.UUID],
    ) -> None:
        """'other' exists in both catalogues; the tag decides which is meant."""
        food_other = _category(test_household.id, 'other', tag=None)
        db_session.add(food_other)
        db_session.commit()

        equipment = _resolve_category_ids(
            db_session, test_household.id, catalogue='equipment'
        )
        food = _resolve_category_ids(db_session, test_household.id)

        assert food_other.id not in equipment.values()
        assert food['other'] == food_other.id

    def test_a_tagged_food_category_still_answers_the_food_lookup(
        self, db_session: Session, test_household: Organization
    ) -> None:
        """The food catalogue is not the untagged one.

        The food profile tags its categories by storage context —
        ``cold_storage``, ``dry_goods`` — and only the fallback "other" has no
        tag at all. Asking for an untagged category found exactly that one, so
        ``make dev-up && make db-seed-demo`` on a fresh installation refused
        twenty-seven food codes that were sitting in the table all along.
        """
        chilled = _category(test_household.id, 'cheese', tag='cold_storage')
        dry = _category(test_household.id, 'pasta', tag='dry_goods')
        untagged = _category(test_household.id, 'other', tag=None)
        db_session.add_all([chilled, dry, untagged])
        db_session.commit()

        resolved = _resolve_category_ids(db_session, test_household.id)

        assert resolved['cheese'] == chilled.id
        assert resolved['pasta'] == dry.id
        assert resolved['other'] == untagged.id

    def test_the_organizations_own_record_wins_over_a_global_one(
        self, db_session: Session, test_household: Organization
    ) -> None:
        db_session.add(_category(None, 'dairy', tag=None))
        own = _category(test_household.id, 'dairy', tag=None)
        db_session.add(own)
        db_session.commit()

        resolved = _resolve_category_ids(db_session, test_household.id)

        assert resolved['dairy'] == own.id

    def test_another_organization_does_not_answer(
        self, db_session: Session, test_household: Organization
    ) -> None:
        """The code may resolve — but never to the neighbour's row.

        This used to assert the code was absent altogether, which held only
        while the food lookup asked for untagged categories and so could not
        see the organization's own tagged ones. It can now, so the question
        that matters is whose row answers.
        """
        stranger = Organization(id=uuid.uuid4(), name='Neighbour')
        db_session.add(stranger)
        db_session.flush()
        neighbours = _category(stranger.id, 'dairy', tag=None)
        db_session.add(neighbours)
        db_session.commit()

        resolved = _resolve_category_ids(db_session, test_household.id)

        assert resolved.get('dairy') != neighbours.id


class TestSeedingEquipment:
    def test_every_seeded_asset_carries_both_marks(
        self,
        db_session: Session,
        test_household: Organization,
        test_user: User,
        equipment_categories: dict[str, uuid.UUID],
        equipment_locations: dict[str, StorageLocation],
        equipment_template: ProductTemplate,
    ) -> None:
        created = _create_equipment_items(
            db_session,
            test_household.id,
            test_user.id,
            [(equipment_template, 'server')],
            equipment_locations,
            {},
            equipment_categories,
        )
        db_session.commit()

        assert created > 0
        seeded = list(
            db_session.scalars(
                select(Item).where(Item.template_id == equipment_template.id)
            )
        )
        assert len(seeded) == created
        for item in seeded:
            assert item.category_id == equipment_categories['server']
            assert item.module_name == 'equipment'
            assert item.meta_data['equipment']['equipment_status'] == 'AVAILABLE'

    def test_the_core_inventory_does_not_show_them_and_the_module_does(
        self,
        db_session: Session,
        test_household: Organization,
        test_user: User,
        equipment_categories: dict[str, uuid.UUID],
        equipment_locations: dict[str, StorageLocation],
        equipment_template: ProductTemplate,
    ) -> None:
        """The symptom, stated as the two lists disagreeing about one record."""
        _create_equipment_items(
            db_session,
            test_household.id,
            test_user.id,
            [(equipment_template, 'server')],
            equipment_locations,
            {},
            equipment_categories,
        )
        db_session.commit()

        seeded_ids = set(
            db_session.scalars(
                select(Item.id).where(Item.template_id == equipment_template.id)
            )
        )
        core_visible = set(
            db_session.scalars(
                select(Item.id).where(
                    Item.organization_id == test_household.id,
                    unclaimed_by_a_module({'equipment'}),
                )
            )
        )
        module_visible = set(
            db_session.scalars(
                select(Item.id).where(
                    *_asset_filters(
                        test_household.id,
                        search=None,
                        category_id=None,
                        storage_id=None,
                        status=None,
                        checked_out=False,
                    )
                )
            )
        )

        assert not seeded_ids & core_visible
        assert seeded_ids <= module_visible

    def test_the_marks_hold_the_record_when_the_category_does_not(
        self,
        db_session: Session,
        test_household: Organization,
        test_user: User,
        equipment_categories: dict[str, uuid.UUID],
        equipment_locations: dict[str, StorageLocation],
        equipment_template: ProductTemplate,
    ) -> None:
        """The category speaks first, so take it away and hear the second mark.

        A record filed under no category is not hypothetical — the equipment
        form never required one — and it is the state the 71 seeded servers
        were in. With ``module_name`` written the core still leaves it alone.
        """
        _create_equipment_items(
            db_session,
            test_household.id,
            test_user.id,
            [(equipment_template, 'server')],
            equipment_locations,
            {},
            equipment_categories,
        )
        db_session.query(Item).filter(Item.template_id == equipment_template.id).update(
            {Item.category_id: None}, synchronize_session=False
        )
        db_session.commit()

        seeded_ids = set(
            db_session.scalars(
                select(Item.id).where(Item.template_id == equipment_template.id)
            )
        )
        core_visible = set(
            db_session.scalars(
                select(Item.id).where(
                    Item.organization_id == test_household.id,
                    unclaimed_by_a_module({'equipment'}),
                )
            )
        )
        module_visible = set(
            db_session.scalars(
                select(Item.id).where(
                    *_asset_filters(
                        test_household.id,
                        search=None,
                        category_id=None,
                        storage_id=None,
                        status=None,
                        checked_out=False,
                    )
                )
            )
        )

        assert not seeded_ids & core_visible
        assert seeded_ids <= module_visible

    def test_a_missing_category_stops_the_run_and_names_the_code(
        self,
        db_session: Session,
        test_household: Organization,
        test_user: User,
        equipment_locations: dict[str, StorageLocation],
        equipment_template: ProductTemplate,
    ) -> None:
        """The quiet ``None`` is the whole disease — it has to be loud."""
        with pytest.raises(SeedCategoriesMissingError) as excinfo:
            _create_equipment_items(
                db_session,
                test_household.id,
                test_user.id,
                [(equipment_template, 'server')],
                equipment_locations,
                {},
                {},
            )

        assert 'server' in str(excinfo.value)
        assert (
            db_session.scalar(
                select(Item.id)
                .where(Item.template_id == equipment_template.id)
                .limit(1)
            )
            is None
        )
