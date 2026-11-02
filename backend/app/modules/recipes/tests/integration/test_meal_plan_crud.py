"""Integration tests for Meal Plan CRUD and Entry management."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any

import pytest
from sqlalchemy import select
from starlette.testclient import TestClient

from app.models.product_template import ProductTemplate
from app.models.uom import Uom
from app.models.user import User

PLAN_URL = '/api/v1/recipes/meal-plans'


def _plan_payload(**overrides: Any) -> dict[str, Any]:
    today = date.today()
    base = {
        'name': 'Test Week',
        'start_date': today.isoformat(),
        'end_date': (today + timedelta(days=6)).isoformat(),
        'enabled_slots': ['LUNCH', 'DINNER'],
        'default_servings': 2,
    }
    base.update(overrides)
    return base


def _recipe_payload(**overrides: Any) -> dict[str, Any]:
    base = {
        'name': 'Test Recipe',
        'servings': 2,
        'ingredients': [],
    }
    base.update(overrides)
    return base


@pytest.mark.integration
class TestMealPlanCRUD:
    def test_create_plan_success(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        r = client.post(PLAN_URL, json=_plan_payload(), headers=auth_headers)
        assert r.status_code == 201
        data = r.json()
        assert data['name'] == 'Test Week'
        assert data['enabled_slots'] == ['LUNCH', 'DINNER']
        assert data['default_servings'] == 2
        assert data['entries'] == []

    def test_create_plan_exceeds_14_days_returns_400(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        today = date.today()
        r = client.post(
            PLAN_URL,
            json=_plan_payload(
                start_date=today.isoformat(),
                end_date=(today + timedelta(days=15)).isoformat(),
            ),
            headers=auth_headers,
        )
        assert r.status_code == 400

    def test_create_plan_end_before_start_returns_400(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        today = date.today()
        r = client.post(
            PLAN_URL,
            json=_plan_payload(
                start_date=today.isoformat(),
                end_date=(today - timedelta(days=1)).isoformat(),
            ),
            headers=auth_headers,
        )
        assert r.status_code == 400

    def test_create_plan_empty_slots_returns_400(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        r = client.post(
            PLAN_URL,
            json=_plan_payload(enabled_slots=[]),
            headers=auth_headers,
        )
        assert r.status_code == 400

    def test_get_plan_success(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        plan_id = client.post(
            PLAN_URL, json=_plan_payload(), headers=auth_headers
        ).json()['id']
        r = client.get(f'{PLAN_URL}/{plan_id}', headers=auth_headers)
        assert r.status_code == 200
        assert r.json()['id'] == plan_id

    def test_get_plan_not_found_returns_404(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        import uuid

        r = client.get(f'{PLAN_URL}/{uuid.uuid4()}', headers=auth_headers)
        assert r.status_code == 404

    def test_list_plans(self, client: TestClient, auth_headers: dict[str, str]) -> None:
        client.post(PLAN_URL, json=_plan_payload(name='Plan A'), headers=auth_headers)
        client.post(PLAN_URL, json=_plan_payload(name='Plan B'), headers=auth_headers)
        r = client.get(PLAN_URL, headers=auth_headers)
        assert r.status_code == 200
        assert len(r.json()) >= 2

    def test_update_plan_name(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        plan_id = client.post(
            PLAN_URL, json=_plan_payload(), headers=auth_headers
        ).json()['id']
        r = client.put(
            f'{PLAN_URL}/{plan_id}', json={'name': 'Updated'}, headers=auth_headers
        )
        assert r.status_code == 200
        assert r.json()['name'] == 'Updated'

    def test_delete_plan_success(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        plan_id = client.post(
            PLAN_URL, json=_plan_payload(), headers=auth_headers
        ).json()['id']
        r = client.delete(f'{PLAN_URL}/{plan_id}', headers=auth_headers)
        assert r.status_code == 204
        r2 = client.get(f'{PLAN_URL}/{plan_id}', headers=auth_headers)
        assert r2.status_code == 404

    def test_plan_requires_auth(self, client: TestClient) -> None:
        r = client.get(PLAN_URL)
        assert r.status_code == 401


@pytest.mark.integration
class TestMealPlanEntries:
    def _create_plan_and_recipe(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> tuple[str, str]:
        plan_id = client.post(
            PLAN_URL, json=_plan_payload(), headers=auth_headers
        ).json()['id']
        recipe_id = client.post(
            '/api/v1/recipes', json=_recipe_payload(), headers=auth_headers
        ).json()['id']
        return plan_id, recipe_id

    def test_add_entry_success(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        plan_id, recipe_id = self._create_plan_and_recipe(client, auth_headers)
        today = date.today()
        payload = {
            'date': today.isoformat(),
            'slot': 'LUNCH',
            'recipe_id': recipe_id,
            'order': 0,
        }
        r = client.post(
            f'{PLAN_URL}/{plan_id}/entries', json=payload, headers=auth_headers
        )
        assert r.status_code == 201
        data = r.json()
        assert data['recipe_id'] == recipe_id
        assert data['slot'] == 'LUNCH'

    def test_add_entry_date_outside_plan_range_returns_409(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        plan_id, recipe_id = self._create_plan_and_recipe(client, auth_headers)
        out_of_range = (date.today() + timedelta(days=30)).isoformat()
        payload = {
            'date': out_of_range,
            'slot': 'LUNCH',
            'recipe_id': recipe_id,
            'order': 0,
        }
        r = client.post(
            f'{PLAN_URL}/{plan_id}/entries', json=payload, headers=auth_headers
        )
        assert r.status_code == 409

    def test_add_entry_disabled_slot_returns_409(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        plan_id, recipe_id = self._create_plan_and_recipe(client, auth_headers)
        today = date.today()
        payload = {
            'date': today.isoformat(),
            'slot': 'BREAKFAST',  # not in enabled_slots=['LUNCH','DINNER']
            'recipe_id': recipe_id,
            'order': 0,
        }
        r = client.post(
            f'{PLAN_URL}/{plan_id}/entries', json=payload, headers=auth_headers
        )
        assert r.status_code == 409

    def test_delete_entry_success(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        plan_id, recipe_id = self._create_plan_and_recipe(client, auth_headers)
        today = date.today()
        entry_id = client.post(
            f'{PLAN_URL}/{plan_id}/entries',
            json={
                'date': today.isoformat(),
                'slot': 'LUNCH',
                'recipe_id': recipe_id,
                'order': 0,
            },
            headers=auth_headers,
        ).json()['id']
        r = client.delete(
            f'{PLAN_URL}/{plan_id}/entries/{entry_id}', headers=auth_headers
        )
        assert r.status_code == 204

    def test_move_entry_to_another_day_and_slot(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """PUT with date+slot moves the entry (drag & drop support)."""
        plan_id, recipe_id = self._create_plan_and_recipe(client, auth_headers)
        today = date.today()
        entry_id = client.post(
            f'{PLAN_URL}/{plan_id}/entries',
            json={
                'date': today.isoformat(),
                'slot': 'LUNCH',
                'recipe_id': recipe_id,
                'order': 0,
            },
            headers=auth_headers,
        ).json()['id']

        tomorrow = (today + timedelta(days=1)).isoformat()
        r = client.put(
            f'{PLAN_URL}/{plan_id}/entries/{entry_id}',
            json={'date': tomorrow, 'slot': 'DINNER'},
            headers=auth_headers,
        )
        assert r.status_code == 200
        data = r.json()
        assert data['date'] == tomorrow
        assert data['slot'] == 'DINNER'

    def test_move_entry_rejects_date_outside_plan_range(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        plan_id, recipe_id = self._create_plan_and_recipe(client, auth_headers)
        today = date.today()
        entry_id = client.post(
            f'{PLAN_URL}/{plan_id}/entries',
            json={
                'date': today.isoformat(),
                'slot': 'LUNCH',
                'recipe_id': recipe_id,
                'order': 0,
            },
            headers=auth_headers,
        ).json()['id']

        out_of_range = (today + timedelta(days=30)).isoformat()
        r = client.put(
            f'{PLAN_URL}/{plan_id}/entries/{entry_id}',
            json={'date': out_of_range},
            headers=auth_headers,
        )
        assert r.status_code == 409

    def test_move_entry_rejects_disabled_slot(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        plan_id, recipe_id = self._create_plan_and_recipe(client, auth_headers)
        today = date.today()
        entry_id = client.post(
            f'{PLAN_URL}/{plan_id}/entries',
            json={
                'date': today.isoformat(),
                'slot': 'LUNCH',
                'recipe_id': recipe_id,
                'order': 0,
            },
            headers=auth_headers,
        ).json()['id']

        r = client.put(
            f'{PLAN_URL}/{plan_id}/entries/{entry_id}',
            json={'slot': 'BREAKFAST'},  # not in enabled_slots
            headers=auth_headers,
        )
        assert r.status_code == 409

    def test_move_entry_avoids_order_collision(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Moving onto a cell that already has an entry with the same order
        bumps the moved entry to the end of the target cell."""
        plan_id, recipe_id = self._create_plan_and_recipe(client, auth_headers)
        today = date.today()
        tomorrow = (today + timedelta(days=1)).isoformat()

        entry_a = client.post(
            f'{PLAN_URL}/{plan_id}/entries',
            json={
                'date': today.isoformat(),
                'slot': 'LUNCH',
                'recipe_id': recipe_id,
                'order': 0,
            },
            headers=auth_headers,
        ).json()['id']
        # Occupant of the target cell with order 0
        client.post(
            f'{PLAN_URL}/{plan_id}/entries',
            json={
                'date': tomorrow,
                'slot': 'LUNCH',
                'recipe_id': recipe_id,
                'order': 0,
            },
            headers=auth_headers,
        )

        r = client.put(
            f'{PLAN_URL}/{plan_id}/entries/{entry_a}',
            json={'date': tomorrow, 'slot': 'LUNCH'},
            headers=auth_headers,
        )
        assert r.status_code == 200
        data = r.json()
        assert data['date'] == tomorrow
        assert data['slot'] == 'LUNCH'
        assert data['order'] == 1

    def test_copy_plan_to_week_success(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """POST /meal-plans/{id}/copy-to clones entries into a NEW plan.

        The new plan covers the target range so copied entries are visible in
        the calendar (previously they landed in the source plan, outside its
        date range, and were never rendered).
        """
        plan_id, recipe_id = self._create_plan_and_recipe(client, auth_headers)
        today = date.today()
        client.post(
            f'{PLAN_URL}/{plan_id}/entries',
            json={
                'date': today.isoformat(),
                'slot': 'LUNCH',
                'recipe_id': recipe_id,
                'order': 0,
            },
            headers=auth_headers,
        )
        client.post(
            f'{PLAN_URL}/{plan_id}/entries',
            json={
                'date': (today + timedelta(days=1)).isoformat(),
                'slot': 'DINNER',
                'recipe_id': recipe_id,
                'order': 0,
            },
            headers=auth_headers,
        )

        target_start = today + timedelta(days=7)
        target_end = today + timedelta(days=13)
        r = client.post(
            f'{PLAN_URL}/{plan_id}/copy-to',
            json={
                'start_date': target_start.isoformat(),
                'end_date': target_end.isoformat(),
            },
            headers=auth_headers,
        )
        assert r.status_code == 200
        data = r.json()
        assert data['copied'] == 2
        assert data['skipped'] == 0

        new_plan = data['plan']
        assert new_plan['id'] != plan_id
        assert new_plan['start_date'] == target_start.isoformat()
        assert new_plan['end_date'] == target_end.isoformat()
        # Settings are inherited from the source plan
        assert new_plan['enabled_slots'] == ['LUNCH', 'DINNER']
        assert new_plan['default_servings'] == 2
        # Auto-generated date-based name, not the source name
        assert new_plan['name']
        assert new_plan['name'] != 'Test Week'

        entry_keys = {(e['date'], e['slot']) for e in new_plan['entries']}
        assert entry_keys == {
            (target_start.isoformat(), 'LUNCH'),
            ((target_start + timedelta(days=1)).isoformat(), 'DINNER'),
        }

        # Source plan remains untouched (range and entries)
        src = client.get(f'{PLAN_URL}/{plan_id}', headers=auth_headers).json()
        src_keys = {(e['date'], e['slot']) for e in src['entries']}
        assert src_keys == {
            (today.isoformat(), 'LUNCH'),
            ((today + timedelta(days=1)).isoformat(), 'DINNER'),
        }

    def test_copy_plan_skips_out_of_range_entries(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Entries whose shifted date falls outside the target range are skipped."""
        plan_id, recipe_id = self._create_plan_and_recipe(client, auth_headers)
        today = date.today()
        # Day 0 and day 6 of the source week
        for offset in (0, 6):
            client.post(
                f'{PLAN_URL}/{plan_id}/entries',
                json={
                    'date': (today + timedelta(days=offset)).isoformat(),
                    'slot': 'LUNCH',
                    'recipe_id': recipe_id,
                    'order': 0,
                },
                headers=auth_headers,
            )

        target_start = today + timedelta(days=7)
        r = client.post(
            f'{PLAN_URL}/{plan_id}/copy-to',
            json={
                'start_date': target_start.isoformat(),
                'end_date': target_start.isoformat(),  # 1-day range
            },
            headers=auth_headers,
        )
        assert r.status_code == 200
        data = r.json()
        assert data['copied'] == 1
        assert data['skipped'] == 1
        assert [e['date'] for e in data['plan']['entries']] == [
            target_start.isoformat()
        ]

    def test_copy_plan_rejects_past_start(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        plan_id, recipe_id = self._create_plan_and_recipe(client, auth_headers)
        r = client.post(
            f'{PLAN_URL}/{plan_id}/copy-to',
            json={
                'start_date': (date.today() - timedelta(days=1)).isoformat(),
                'end_date': date.today().isoformat(),
            },
            headers=auth_headers,
        )
        assert r.status_code == 400

    def test_copy_plan_rejects_range_over_14_days(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        plan_id, recipe_id = self._create_plan_and_recipe(client, auth_headers)
        start = date.today() + timedelta(days=1)
        r = client.post(
            f'{PLAN_URL}/{plan_id}/copy-to',
            json={
                'start_date': start.isoformat(),
                'end_date': (start + timedelta(days=15)).isoformat(),
            },
            headers=auth_headers,
        )
        assert r.status_code == 400

    def test_plan_daily_nutrition_summary(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        db_session: Any,
    ) -> None:
        """GET plan aggregates per-date nutrition across entries."""
        template = ProductTemplate(
            id=uuid.uuid4(),
            organization_id=test_user.organization_id,
            name='Nutrition Flour',
            meta_data={
                'nutrition': {
                    'calories_kcal': 350.0,
                    'protein_g': 12.0,
                    'fat_g': 5.0,
                    'carbs_g': 65.0,
                }
            },
        )
        db_session.add(template)
        db_session.flush()
        uom = db_session.scalar(select(Uom).where(Uom.symbol == 'g'))
        assert uom is not None
        db_session.commit()

        recipe_id = client.post(
            '/api/v1/recipes',
            json={
                'name': 'Nutrition Meal',
                'servings': 1,
                'ingredients': [
                    {
                        'name': 'Nutrition Flour',
                        'template_id': str(template.id),
                        'quantity': '100',
                        'uom_id': str(uom.id),
                        'is_optional': False,
                    }
                ],
            },
            headers=auth_headers,
        ).json()['id']

        plan_id = client.post(
            PLAN_URL, json=_plan_payload(), headers=auth_headers
        ).json()['id']
        client.post(
            f'{PLAN_URL}/{plan_id}/entries',
            json={
                'date': date.today().isoformat(),
                'slot': 'LUNCH',
                'recipe_id': recipe_id,
                'order': 0,
            },
            headers=auth_headers,
        )
        client.post(
            f'{PLAN_URL}/{plan_id}/entries',
            json={
                'date': (date.today() + timedelta(days=1)).isoformat(),
                'slot': 'LUNCH',
                'recipe_id': recipe_id,
                'order': 0,
            },
            headers=auth_headers,
        )

        r = client.get(f'{PLAN_URL}/{plan_id}', headers=auth_headers)
        assert r.status_code == 200
        summary = r.json()['daily_nutrition_summary']
        assert len(summary) == 2
        # 100 g × 350 kcal/100 g = 350 kcal per day (default servings 2 ×
        # recipe servings... single entry, effective servings 2 → 700 kcal)
        day = next(s for s in summary if s['date'] == date.today().isoformat())
        assert day['calories_kcal'] == pytest.approx(700.0, abs=2.0)
        assert day['protein_g'] == pytest.approx(24.0, abs=1.0)
        assert day['carbs_g'] == pytest.approx(130.0, abs=2.0)
        # The product carries its own values, so nothing here is generic.
        assert day['generic_values'] is False

    def test_plan_daily_nutrition_absent_is_null_not_zero(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """A nutrient nobody measured is null, so the table can print a dash.

        Zero is a measurement. A plan of recipes whose ingredients carry no
        nutrition data used to report "0 g" for every nutrient, one screen
        away from "nutrition data available for 0% of ingredients".
        """
        plan_id, recipe_id = self._create_plan_and_recipe(client, auth_headers)
        client.post(
            f'{PLAN_URL}/{plan_id}/entries',
            json={
                'date': date.today().isoformat(),
                'slot': 'LUNCH',
                'recipe_id': recipe_id,
                'order': 0,
            },
            headers=auth_headers,
        )

        summary = client.get(f'{PLAN_URL}/{plan_id}', headers=auth_headers).json()[
            'daily_nutrition_summary'
        ]
        assert len(summary) == 1
        day = summary[0]
        assert day['calories_kcal'] is None
        assert day['protein_g'] is None
        assert day['fat_g'] is None
        assert day['carbs_g'] is None

    def test_a_half_measured_recipe_contributes_nothing(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        db_session: Any,
    ) -> None:
        """Either the day describes the food, or it says nothing about it.

        A product whose profile knows calories and fat but not protein or
        carbs used to fill two of the four columns. The dashes beside them
        read as zeroes, and the calorie count read as a fact about a day the
        application elsewhere reports no data for.
        """
        template = ProductTemplate(
            id=uuid.uuid4(),
            organization_id=test_user.organization_id,
            name='Half Measured Oil',
            meta_data={'nutrition': {'calories_kcal': 900.0, 'fat_g': 100.0}},
        )
        db_session.add(template)
        db_session.flush()
        uom = db_session.scalar(select(Uom).where(Uom.symbol == 'g'))
        assert uom is not None
        db_session.commit()

        recipe_id = client.post(
            '/api/v1/recipes',
            json={
                'name': 'Half Measured Meal',
                'servings': 1,
                'ingredients': [
                    {
                        'name': 'Half Measured Oil',
                        'template_id': str(template.id),
                        'quantity': '100',
                        'uom_id': str(uom.id),
                        'is_optional': False,
                    }
                ],
            },
            headers=auth_headers,
        ).json()['id']

        plan_id = client.post(
            PLAN_URL, json=_plan_payload(), headers=auth_headers
        ).json()['id']
        client.post(
            f'{PLAN_URL}/{plan_id}/entries',
            json={
                'date': date.today().isoformat(),
                'slot': 'LUNCH',
                'recipe_id': recipe_id,
                'order': 0,
            },
            headers=auth_headers,
        )

        summary = client.get(f'{PLAN_URL}/{plan_id}', headers=auth_headers).json()[
            'daily_nutrition_summary'
        ]
        day = summary[0]
        assert day['calories_kcal'] is None
        assert day['fat_g'] is None
        assert day['protein_g'] is None
        assert day['carbs_g'] is None

    def test_a_partly_measured_day_reports_coverage_and_no_false_zero(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        db_session: Any,
    ) -> None:
        """Pasta nobody measured does not turn into "0 g carbs".

        The oil has a full profile whose carbohydrates really are 0, so the
        recipe sums to carbs 0; the pasta, the dinner's only carbohydrate
        source, has no values. The day says how much of it was measured and
        leaves the nutrient the missing ingredient would have supplied unknown.
        """
        oil = ProductTemplate(
            id=uuid.uuid4(),
            organization_id=test_user.organization_id,
            name='Fully Measured Oil',
            meta_data={
                'nutrition': {
                    'calories_kcal': 900.0,
                    'protein_g': 0.0,
                    'fat_g': 100.0,
                    'carbs_g': 0.0,
                }
            },
        )
        db_session.add(oil)
        db_session.flush()
        uom = db_session.scalar(select(Uom).where(Uom.symbol == 'g'))
        assert uom is not None
        db_session.commit()

        def line(name: str, template: ProductTemplate | None) -> dict[str, Any]:
            return {
                'name': name,
                'template_id': str(template.id) if template else None,
                'quantity': '100',
                'uom_id': str(uom.id),
                'is_optional': False,
            }

        recipe_id = client.post(
            '/api/v1/recipes',
            json={
                'name': 'Pasta With Oil',
                'servings': 1,
                'ingredients': [
                    line('Fully Measured Oil', oil),
                    line('Unmeasured Pasta', None),
                ],
            },
            headers=auth_headers,
        ).json()['id']
        plan_id = client.post(
            PLAN_URL, json=_plan_payload(), headers=auth_headers
        ).json()['id']
        client.post(
            f'{PLAN_URL}/{plan_id}/entries',
            json={
                'date': date.today().isoformat(),
                'slot': 'LUNCH',
                'recipe_id': recipe_id,
                'order': 0,
            },
            headers=auth_headers,
        )

        day = client.get(f'{PLAN_URL}/{plan_id}', headers=auth_headers).json()[
            'daily_nutrition_summary'
        ][0]
        assert day['coverage'] == 0.5
        assert day['carbs_g'] is None
        assert day['protein_g'] is None
        assert day['fat_g'] == pytest.approx(200.0, abs=2.0)

    def test_a_nearly_complete_day_is_not_rounded_up_to_complete(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        db_session: Any,
    ) -> None:
        """Coverage 200/201 is partial; rounding to two decimals must not say 1.0."""
        oil = ProductTemplate(
            id=uuid.uuid4(),
            organization_id=test_user.organization_id,
            name='Rounding Oil',
            meta_data={
                'nutrition': {
                    'calories_kcal': 900.0,
                    'protein_g': 0.0,
                    'fat_g': 100.0,
                    'carbs_g': 0.0,
                }
            },
        )
        db_session.add(oil)
        db_session.flush()
        uom = db_session.scalar(select(Uom).where(Uom.symbol == 'g'))
        assert uom is not None
        db_session.commit()

        def make_recipe(name: str, ingredients: list[dict[str, Any]]) -> str:
            response = client.post(
                '/api/v1/recipes',
                json={'name': name, 'servings': 1, 'ingredients': ingredients},
                headers=auth_headers,
            )
            return str(response.json()['id'])

        def line(name: str, tpl: ProductTemplate | None, qty: str) -> dict[str, Any]:
            return {
                'name': name,
                'template_id': str(tpl.id) if tpl else None,
                'quantity': qty,
                'uom_id': str(uom.id),
                'is_optional': False,
            }

        measured = make_recipe(
            'Fifty Measured Lines',
            [line(f'Oil {i}', oil, '10') for i in range(50)],
        )
        unmeasured = make_recipe('Unmeasured Dish', [line('Mystery', None, '200')])
        plan_id = client.post(
            PLAN_URL, json=_plan_payload(), headers=auth_headers
        ).json()['id']
        for order, recipe_id in enumerate([measured] * 4 + [unmeasured]):
            client.post(
                f'{PLAN_URL}/{plan_id}/entries',
                json={
                    'date': date.today().isoformat(),
                    'slot': 'LUNCH',
                    'recipe_id': recipe_id,
                    'order': order,
                },
                headers=auth_headers,
            )

        day = client.get(f'{PLAN_URL}/{plan_id}', headers=auth_headers).json()[
            'daily_nutrition_summary'
        ][0]
        assert day['carbs_g'] is None
        assert day['coverage'] < 1

    def test_an_ingredient_with_calories_only_does_not_vouch_for_carbs(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        db_session: Any,
    ) -> None:
        """A calorie figure is not a carbohydrate measurement.

        The pasta has calories and nothing else; the oil is fully measured
        with 0 carbohydrates. Every ingredient has *some* data, yet the
        day's carbs and protein come only from the oil, so they read unknown
        while the calories (which both measured) stay numbers. The nonzero fat
        is just as partial — the pasta's fat is unknown — so the day states
        its coverage by the least-measured nutrient: one ingredient in two.
        """

        def template(name: str, nutrition: dict[str, float]) -> ProductTemplate:
            return ProductTemplate(
                id=uuid.uuid4(),
                organization_id=test_user.organization_id,
                name=name,
                meta_data={'nutrition': nutrition},
            )

        oil = template(
            'Measured Oil',
            {'calories_kcal': 900.0, 'protein_g': 0.0, 'fat_g': 100.0, 'carbs_g': 0.0},
        )
        pasta = template('Calorie Only Pasta', {'calories_kcal': 350.0})
        db_session.add_all([oil, pasta])
        db_session.flush()
        uom = db_session.scalar(select(Uom).where(Uom.symbol == 'g'))
        assert uom is not None
        db_session.commit()

        def line(tpl: ProductTemplate) -> dict[str, Any]:
            return {
                'name': tpl.name,
                'template_id': str(tpl.id),
                'quantity': '100',
                'uom_id': str(uom.id),
                'is_optional': False,
            }

        recipe_id = client.post(
            '/api/v1/recipes',
            json={
                'name': 'Calorie Only Pasta With Oil',
                'servings': 1,
                'ingredients': [line(oil), line(pasta)],
            },
            headers=auth_headers,
        ).json()['id']
        plan_id = client.post(
            PLAN_URL, json=_plan_payload(), headers=auth_headers
        ).json()['id']
        client.post(
            f'{PLAN_URL}/{plan_id}/entries',
            json={
                'date': date.today().isoformat(),
                'slot': 'LUNCH',
                'recipe_id': recipe_id,
                'order': 0,
            },
            headers=auth_headers,
        )

        day = client.get(f'{PLAN_URL}/{plan_id}', headers=auth_headers).json()[
            'daily_nutrition_summary'
        ][0]
        assert day['carbs_g'] is None
        assert day['protein_g'] is None
        # The plan cooks two servings of the one-serving recipe.
        assert day['calories_kcal'] == pytest.approx(2500.0, abs=2.0)
        assert day['fat_g'] == pytest.approx(200.0, abs=2.0)
        assert day['coverage'] == 0.5

    def test_bulk_save_entries_replaces_all(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        plan_id, recipe_id = self._create_plan_and_recipe(client, auth_headers)
        today = date.today()
        # Add initial entry
        client.post(
            f'{PLAN_URL}/{plan_id}/entries',
            json={
                'date': today.isoformat(),
                'slot': 'LUNCH',
                'recipe_id': recipe_id,
                'order': 0,
            },
            headers=auth_headers,
        )
        # Bulk replace with 2 entries
        r = client.post(
            f'{PLAN_URL}/{plan_id}/entries/bulk',
            json={
                'entries': [
                    {
                        'date': today.isoformat(),
                        'slot': 'LUNCH',
                        'recipe_id': recipe_id,
                        'order': 0,
                    },
                    {
                        'date': today.isoformat(),
                        'slot': 'DINNER',
                        'recipe_id': recipe_id,
                        'order': 0,
                    },
                ]
            },
            headers=auth_headers,
        )
        assert r.status_code == 200
        plan = client.get(f'{PLAN_URL}/{plan_id}', headers=auth_headers).json()
        assert len(plan['entries']) == 2


@pytest.mark.integration
class TestMealPlanSlotConflict:
    """disabling a slot that still has entries must explain the
    conflict precisely (only the slots that actually collide, with counts)
    and offer an explicit removal escape hatch."""

    def _plan_with_entries(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> tuple[str, str]:
        plan_id = client.post(
            PLAN_URL,
            json=_plan_payload(enabled_slots=['LUNCH', 'DINNER', 'SNACK']),
            headers=auth_headers,
        ).json()['id']
        recipe_id = client.post(
            '/api/v1/recipes', json=_recipe_payload(), headers=auth_headers
        ).json()['id']
        today = date.today()
        for offset in (0, 1):
            client.post(
                f'{PLAN_URL}/{plan_id}/entries',
                json={
                    'date': (today + timedelta(days=offset)).isoformat(),
                    'slot': 'DINNER',
                    'recipe_id': recipe_id,
                    'order': 0,
                },
                headers=auth_headers,
            )
        client.post(
            f'{PLAN_URL}/{plan_id}/entries',
            json={
                'date': today.isoformat(),
                'slot': 'LUNCH',
                'recipe_id': recipe_id,
                'order': 0,
            },
            headers=auth_headers,
        )
        return plan_id, recipe_id

    def test_disable_slots_reports_only_conflicting_slots(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        plan_id, _ = self._plan_with_entries(client, auth_headers)
        # Disables DINNER (2 entries) and SNACK (0 entries).
        r = client.put(
            f'{PLAN_URL}/{plan_id}',
            json={'enabled_slots': ['LUNCH']},
            headers=auth_headers,
        )
        assert r.status_code == 409
        detail = r.json()['detail']
        assert detail['code'] == 'MEAL_PLAN_SLOT_CONFLICT'
        assert detail['conflicts'] == [{'slot': 'DINNER', 'count': 2}]
        # The empty SNACK slot must not be blamed.
        assert 'SNACK' not in detail['message']

        # The plan is untouched after the rejected update.
        plan = client.get(f'{PLAN_URL}/{plan_id}', headers=auth_headers).json()
        assert plan['enabled_slots'] == ['LUNCH', 'DINNER', 'SNACK']
        assert len(plan['entries']) == 3

    def test_disable_slots_with_remove_flag_deletes_only_conflicting_entries(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        plan_id, _ = self._plan_with_entries(client, auth_headers)
        r = client.put(
            f'{PLAN_URL}/{plan_id}',
            json={
                'enabled_slots': ['LUNCH'],
                'remove_conflicting_entries': True,
            },
            headers=auth_headers,
        )
        assert r.status_code == 200
        plan = r.json()
        assert plan['enabled_slots'] == ['LUNCH']
        # The 2 DINNER entries were removed, the LUNCH entry survived.
        assert len(plan['entries']) == 1
        assert plan['entries'][0]['slot'] == 'LUNCH'


@pytest.mark.integration
class TestServingsFallBackToTheRecipe:
    """A plan with no default of its own follows each recipe's own servings."""

    def _plan_without_default(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> str:
        payload = _plan_payload()
        payload.pop('default_servings')
        r = client.post(PLAN_URL, json=payload, headers=auth_headers)
        assert r.status_code == 201
        assert r.json()['default_servings'] is None
        return str(r.json()['id'])

    def _add_entry(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        plan_id: str,
        recipe_id: str,
    ) -> dict[str, Any]:
        r = client.post(
            f'{PLAN_URL}/{plan_id}/entries',
            json={
                'date': date.today().isoformat(),
                'slot': 'LUNCH',
                'recipe_id': recipe_id,
                'order': 0,
            },
            headers=auth_headers,
        )
        assert r.status_code == 201
        return dict(r.json())

    def test_entry_inherits_servings_from_the_recipe(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        plan_id = self._plan_without_default(client, auth_headers)
        recipe_id = client.post(
            '/api/v1/recipes',
            json=_recipe_payload(name='One Serving', servings=1),
            headers=auth_headers,
        ).json()['id']

        self._add_entry(client, auth_headers, plan_id, recipe_id)

        plan = client.get(f'{PLAN_URL}/{plan_id}', headers=auth_headers).json()
        assert plan['entries'][0]['servings'] == 1

    def test_the_plan_default_still_wins_over_the_recipe(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        plan_id = client.post(
            PLAN_URL, json=_plan_payload(default_servings=4), headers=auth_headers
        ).json()['id']
        recipe_id = client.post(
            '/api/v1/recipes',
            json=_recipe_payload(name='One Serving', servings=1),
            headers=auth_headers,
        ).json()['id']

        self._add_entry(client, auth_headers, plan_id, recipe_id)

        plan = client.get(f'{PLAN_URL}/{plan_id}', headers=auth_headers).json()
        assert plan['entries'][0]['servings'] == 4

    def test_the_plan_default_can_be_cleared(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        plan_id = client.post(
            PLAN_URL, json=_plan_payload(default_servings=4), headers=auth_headers
        ).json()['id']

        r = client.put(
            f'{PLAN_URL}/{plan_id}',
            json={'default_servings': None},
            headers=auth_headers,
        )
        assert r.status_code == 200
        assert r.json()['default_servings'] is None
