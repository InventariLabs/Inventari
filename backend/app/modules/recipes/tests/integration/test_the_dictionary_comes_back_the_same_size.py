"""The ingredient dictionary comes back the same size it left.

Export writes the organization's view — system rows and its own overrides.
Import used to make an override for every row it read, system rows
included, so the cheapest way to fix two values in a spreadsheet doubled
the list: every ingredient once as the system's and once as a "Custom"
copy with the same numbers, and from then on the copy applied.
"""

import csv
import io
import uuid
from collections.abc import Callable
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.modules.recipes.defaults_service import (
    export_defaults,
    import_defaults,
    list_defaults,
)
from app.modules.recipes.models import IngredientNutritionDefault

Rows = list[dict[str, str]]


def _row(
    name: str, kcal: str, org_id: uuid.UUID | None = None
) -> IngredientNutritionDefault:
    return IngredientNutritionDefault(
        id=uuid.uuid4(),
        organization_id=org_id,
        lang='en',
        name=name,
        name_normalized=name.lower(),
        calories_kcal=Decimal(kcal),
        protein_g=Decimal('3.40'),
        fat_g=None,
        source='system' if org_id is None else 'manual',
        is_system=org_id is None,
    )


async def _round_trip(
    db: AsyncSession,
    org_id: uuid.UUID,
    edit: Callable[[Rows], None] | None = None,
) -> dict[str, int]:
    sheet = await export_defaults(db, org_id, 'en', 'csv')
    items = list(csv.DictReader(io.StringIO(sheet)))
    if edit:
        edit(items)
    return await import_defaults(db, org_id, 'en', items)


async def _size(db: AsyncSession, org_id: uuid.UUID) -> int:
    _, total = await list_defaults(db, org_id, lang='en', limit=1000)
    return total


@pytest.mark.integration
@pytest.mark.asyncio
class TestTheDictionaryComesBackTheSameSize:
    async def test_an_untouched_export_changes_nothing(
        self, real_async_db_session: AsyncSession, async_test_user: User
    ) -> None:
        db = real_async_db_session
        org_id = async_test_user.organization_id
        assert org_id is not None
        db.add(_row('Milk', '42.00'))
        db.add(_row('Butter', '717.00', org_id))
        await db.commit()
        before = await _size(db, org_id)

        summary = await _round_trip(db, org_id)

        assert summary == {
            'created': 0,
            'overridden': 0,
            'updated': 0,
            'unchanged': 2,
            'errors': 0,
        }
        assert await _size(db, org_id) == before

    async def test_a_changed_system_row_becomes_one_override(
        self, real_async_db_session: AsyncSession, async_test_user: User
    ) -> None:
        db = real_async_db_session
        org_id = async_test_user.organization_id
        assert org_id is not None
        db.add(_row('Milk', '42.00'))
        await db.commit()
        before = await _size(db, org_id)

        def bump_milk(items: Rows) -> None:
            for item in items:
                if item['name'] == 'Milk':
                    item['calories_kcal'] = '50'

        first = await _round_trip(db, org_id, bump_milk)
        assert first['overridden'] == 1 and first['created'] == 0
        assert await _size(db, org_id) == before + 1

        # The export now lists Milk twice: the system's copy and the
        # override. Editing the override is the round trip the page offers.
        def bump_again(items: Rows) -> None:
            for item in items:
                if item['name'] == 'Milk' and item['is_system'] == 'False':
                    item['calories_kcal'] = '55'

        second = await _round_trip(db, org_id, bump_again)
        assert second['updated'] == 1 and second['overridden'] == 0
        assert await _size(db, org_id) == before + 1

    async def test_a_new_name_is_a_new_ingredient(
        self, real_async_db_session: AsyncSession, async_test_user: User
    ) -> None:
        db = real_async_db_session
        org_id = async_test_user.organization_id
        assert org_id is not None
        db.add(_row('Milk', '42.00'))
        await db.commit()

        summary = await import_defaults(
            db,
            org_id,
            'en',
            [{'name': 'Ghee', 'calories_kcal': '900', 'fiber_g': ''}],
        )

        assert summary['created'] == 1 and summary['errors'] == 0
