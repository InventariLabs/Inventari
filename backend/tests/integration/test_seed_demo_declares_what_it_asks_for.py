"""Every category code the demo seeder asks for is declared somewhere.

``make dev-up && make db-seed-demo`` used to stop halfway on a fresh
installation, asking for categories nobody had created. Two separate reasons,
and this pins both of the declarations they depend on:

* the food catalogue is declared by the ``food_home`` seed profile, and the
  seeder reads it back — the codes have to line up;
* the equipment catalogue is declared in the equipment module's metadata and
  copied per organization by ``system_on_enable``, so a template naming a code
  the module does not declare is a refusal waiting to happen.

Neither check needs a database or a live organization: they compare the codes
the seeder uses against the codes the declarations carry.
"""

from __future__ import annotations

import pytest

from seed_demo_data import EQUIPMENT_TEMPLATES, FOOD_TEMPLATES

pytestmark = pytest.mark.integration


def _declared_equipment_codes() -> set[str]:
    from app.modules.equipment._module_declarations import build_equipment_metadata

    metadata = build_equipment_metadata()
    declarations = metadata.categories
    return {decl.code.lower() for decl in declarations}


def _declared_food_codes() -> set[str]:
    from app.seed_profiles._food_home_categories_freezer import FREEZER_CATEGORIES
    from app.seed_profiles._food_home_categories_fridge import FRIDGE_CATEGORIES
    from app.seed_profiles._food_home_categories_pantry import PANTRY_CATEGORIES

    return {
        row['code'].lower()
        for group in (FREEZER_CATEGORIES, FRIDGE_CATEGORIES, PANTRY_CATEGORIES)
        for row in group
    }


class TestTheSeederAsksOnlyForDeclaredCategories:
    def test_every_equipment_template_names_a_declared_category(self) -> None:
        asked = {template[3].lower() for template in EQUIPMENT_TEMPLATES}

        assert asked <= _declared_equipment_codes()

    def test_every_food_template_names_a_declared_category(self) -> None:
        asked = {template[3].lower() for template in FOOD_TEMPLATES}

        assert asked <= _declared_food_codes()
