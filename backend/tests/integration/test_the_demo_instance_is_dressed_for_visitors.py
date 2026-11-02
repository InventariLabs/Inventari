"""The public demo is the seed plus what a visitor needs that a developer does not.

The shared seed (``seed_demo_data``) is written for every stack: developers,
the QA fixture and the test suite run it, and ``--clean`` finds its rows again
by the ``SEED-`` marker they carry. The public demo is never cleaned — it is
dropped and rebuilt — and on it the marker was the first thing a visitor read:
on every shelf's code, on the stock take, in the notes of every purchase
order. Seven screens also opened on their empty state, because nothing in the
shared seed fills them: the approvals queue, the attestation campaigns, the
label pool, the putaway rules, the reorder rules, the supplier price list and
the administrator's own "My assets".

``seed_demo_showcase.dress_for_visitors`` is the step only ``demo reset``
runs. Each test here reads what the administrator of a freshly dressed demo
would see.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import JSON, String, Text, cast, func, select
from sqlalchemy.orm import Session

from app.database import Base
from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.user import User
from app.modules.warehouse.models import WmsPickLine, WmsPickSession
from app.services.token_service import create_access_token
from seed_demo_data import DEMO_RECIPES, SEED_PREFIX
from seed_demo_showcase import DEMO_ORGANIZATION_NAME, dress_for_visitors
from tests.integration._demo_world import ids, seeded_organization

pytestmark = pytest.mark.integration


@pytest.fixture
def dressed(demo_world) -> tuple[uuid.UUID, uuid.UUID]:
    """A demo organization seeded and dressed, as the demo reset leaves it."""
    payload = demo_world('org-60-dressed', seeded_organization(items=60, dress=True))
    return ids(payload)


def _as(admin_id: uuid.UUID) -> dict[str, str]:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(admin_id)})}'
    }


def _rows(body: Any) -> list[dict]:
    """A list endpoint answers a bare list or a page with its rows in ``items``."""
    return body['items'] if isinstance(body, dict) else body


class TestNoSeedMarkerReachesAVisitor:
    def test_no_text_the_organization_holds_carries_the_marker(
        self, db_session: Session, dressed
    ) -> None:
        org_id, _admin_id = dressed
        leaked = []
        for table in Base.metadata.sorted_tables:
            owner = table.c.get('organization_id')
            if owner is None:
                continue
            for column in table.columns:
                if not isinstance(column.type, String | Text | JSON):
                    continue
                hits = db_session.scalar(
                    select(func.count())
                    .select_from(table)
                    .where(
                        owner == org_id,
                        cast(column, Text).contains(SEED_PREFIX),
                    )
                )
                if hits:
                    leaked.append(f'{table.name}.{column.name} ({hits})')
        assert not leaked, f'the seed marker is on screen in: {leaked}'

    def test_the_organization_is_called_something_a_business_would_be(
        self, db_session: Session, dressed
    ) -> None:
        org_id, _admin_id = dressed
        assert db_session.get(Organization, org_id).name == DEMO_ORGANIZATION_NAME

    def test_the_row_a_picker_reads_carries_no_marker(
        self, db_session: Session, dressed
    ) -> None:
        """A picking line quotes its shelf's code as text, prefix and all.

        The shelf loses its ``SEED-`` prefix when the demo is dressed; the
        line was written before that and keeps quoting the old spelling —
        which is why the line follows its shelf to the new code.
        """
        org_id, _admin_id = dressed
        lines = (
            db_session.query(WmsPickLine)
            .join(WmsPickSession, WmsPickSession.id == WmsPickLine.session_id)
            .filter(WmsPickSession.organization_id == org_id)
            .all()
        )
        assert lines, 'the seed walked no picking session — nothing was checked'
        leaked = [
            line.bin_location
            for line in lines
            if line.bin_location and SEED_PREFIX in line.bin_location
        ]
        assert not leaked, f'the seed marker is on screen in: {leaked}'


class TestNoModuleOpensOnItsEmptyState:
    def test_a_purchase_order_waits_for_the_administrators_decision(
        self, client, dressed
    ) -> None:
        _org_id, admin_id = dressed
        response = client.get(
            '/api/v1/approvals/requests',
            params={'status': 'PENDING,IN_PROGRESS'},
            headers=_as(admin_id),
        )
        assert response.status_code == 200, response.text
        waiting = [row for row in _rows(response.json()) if row['viewer_can_decide']]
        assert waiting, 'nothing in the approvals queue the administrator can decide'

    def test_an_order_the_visitor_confirms_without_prices_can_be_finished(
        self, client, dressed, db_session: Session
    ) -> None:
        """The visitor is the only person who can sign in, and the one asking."""
        org_id, admin_id = dressed
        headers = _as(admin_id)
        supplier = db_session.scalar(
            select(Partner).where(
                Partner.organization_id == org_id, Partner.type == 'SUPPLIER'
            )
        )
        made = client.post(
            '/api/v1/purchase-orders',
            headers=headers,
            json={
                'partner_id': str(supplier.id),
                'lines': [{'name': 'Natural Yoghurt', 'quantity_ordered': 1}],
            },
        )
        assert made.status_code == 201, made.text
        url = f'/api/v1/purchase-orders/{made.json()["id"]}'

        told = client.get(f'{url}/approval-requirement', headers=headers).json()
        assert told['approval_required'] is True
        assert told['approval_solvable'] is True

        confirmed = client.post(f'{url}/confirm', headers=headers)
        assert confirmed.json()['status'] == 'PENDING_APPROVAL'
        # Both stages of the demo's workflow, and the visitor decides each.
        for _stage in range(2):
            approved = client.post(f'{url}/approve', headers=headers)
            assert approved.status_code == 200, approved.text
        assert client.get(url, headers=headers).json()['status'] == 'CONFIRMED'

    def test_an_attestation_campaign_is_running_with_answers_in(
        self, client, dressed
    ) -> None:
        _org_id, admin_id = dressed
        response = client.get('/api/v1/equipment/campaigns', headers=_as(admin_id))
        assert response.status_code == 200, response.text
        active = [row for row in _rows(response.json()) if row['status'] == 'ACTIVE']
        assert active, 'no attestation campaign is running'

    def test_labels_are_printed_and_some_are_on_assets(self, client, dressed) -> None:
        _org_id, admin_id = dressed
        response = client.get('/api/v1/labels/pool', headers=_as(admin_id))
        assert response.status_code == 200, response.text
        labels = _rows(response.json())
        assert labels, 'the label pool is empty'
        assert any(label['is_assigned'] for label in labels)
        assert any(not label['is_assigned'] for label in labels)

    def test_the_labels_on_assets_are_on_different_products(
        self, client, dressed
    ) -> None:
        """Six labels on six "APC Smart-UPS 3000VA" read as one row copied."""
        _org_id, admin_id = dressed
        response = client.get('/api/v1/labels/pool', headers=_as(admin_id))
        assert response.status_code == 200, response.text
        named = [
            label['assigned_item_name']
            for label in _rows(response.json())
            if label['is_assigned']
        ]
        assert len(named) >= 6, f'only {len(named)} labels are assigned'
        assert len(set(named)) == len(named), (
            f'labels repeat a product: {sorted(named)}'
        )

    def test_receipts_have_putaway_rules_to_follow(self, client, dressed) -> None:
        _org_id, admin_id = dressed
        response = client.get('/api/v1/warehouse/putaway-rules', headers=_as(admin_id))
        assert response.status_code == 200, response.text
        rules = _rows(response.json())
        assert rules, 'no putaway rule'
        assert all(rule['locations'] for rule in rules), 'a rule sends goods nowhere'

    def test_a_reorder_point_has_been_crossed(self, client, dressed) -> None:
        """Rules nobody has crossed leave the replenishment screen with nothing
        to suggest — the half of it worth showing."""
        _org_id, admin_id = dressed
        response = client.get(
            '/api/v1/purchase-orders/reorder-rules', headers=_as(admin_id)
        )
        assert response.status_code == 200, response.text
        assert _rows(response.json()), 'no reorder rule'
        alerts = client.get(
            '/api/v1/purchase-orders/replenishment/alerts', headers=_as(admin_id)
        )
        assert alerts.status_code == 200, alerts.text
        assert _rows(alerts.json()), 'no product is below its reorder point'

    def test_every_supplier_the_workshop_buys_from_has_a_price_list(
        self, client, db_session: Session, dressed
    ) -> None:
        """The price list is read per supplier, on the partner's page."""
        org_id, admin_id = dressed
        suppliers = db_session.scalars(
            select(Partner.id).where(
                Partner.organization_id == org_id,
                Partner.code.in_(['FFD-004', 'MCC-005']),
            )
        ).all()
        assert len(suppliers) == 2
        for partner_id in suppliers:
            response = client.get(
                f'/api/v1/purchase-orders/pricelist/by-partner/{partner_id}',
                headers=_as(admin_id),
            )
            assert response.status_code == 200, response.text
            assert _rows(response.json()), f'supplier {partner_id} has no prices'

    def test_the_administrator_has_assets_of_their_own(self, client, dressed) -> None:
        _org_id, admin_id = dressed
        response = client.get('/api/v1/equipment/my-assets', headers=_as(admin_id))
        assert response.status_code == 200, response.text
        assert _rows(response.json()), '"My assets" is empty for the administrator'

    def test_no_asset_is_created_after_something_happened_to_it(
        self, client, db_session: Session, dressed
    ) -> None:
        """A ThinkPad read "Asset created 10/07" above "Checked out 09/14"."""
        org_id, admin_id = dressed
        assets = db_session.scalars(
            select(Item.id).where(
                Item.organization_id == org_id, Item.module_name == 'equipment'
            )
        ).all()
        assert assets
        backwards = []
        for item_id in assets:
            response = client.get(
                f'/api/v1/equipment/assets/{item_id}/timeline', headers=_as(admin_id)
            )
            assert response.status_code == 200, response.text
            events = response.json()['events']
            created = next(e['date'] for e in events if e['kind'] == 'created')
            # Day against day: a repair is dated by the day, not the minute.
            earlier = [
                e['kind'] for e in events if str(e['date'])[:10] < str(created)[:10]
            ]
            if earlier:
                backwards.append((item_id, earlier))
        assert not backwards, f'created after its own events: {backwards}'


class TestNoAssetIsIssuedBeforeItExists:
    def test_equipment_that_arrived_lately_is_not_issued_in_the_past(
        self, db_session: Session, dressed
    ) -> None:
        """A delivered laptop is created on the day the receipt closed; the
        seed picked laptops and the administrator's phone by name alone, so
        which asset got a check-out dated weeks back depended on row order,
        and a delivered one read "Checked out" above "Asset created"."""
        from app.modules.equipment.models import EquipmentAssignment
        from seed_demo_data import _create_assignments_demo
        from seed_demo_showcase import DEMO_ADMIN_ASSET, _issue_the_administrator_a_kit

        org_id, admin_id = dressed
        db_session.query(EquipmentAssignment).filter(
            EquipmentAssignment.organization_id == org_id
        ).delete()
        issuable = (
            Item.name.ilike('%Latitude%')
            | Item.name.ilike('%ThinkPad%')
            | (Item.name == DEMO_ADMIN_ASSET)
        )
        recent = datetime.now(UTC) - timedelta(days=2)
        db_session.query(Item).filter(Item.organization_id == org_id, issuable).update(
            {Item.created_at: recent}, synchronize_session=False
        )
        # One old laptop among the new ones: the only one that may be issued.
        old = db_session.scalars(
            select(Item).where(Item.organization_id == org_id, issuable)
        ).first()
        assert old is not None
        old.created_at = datetime.now(UTC) - timedelta(days=400)
        db_session.flush()

        admin = db_session.get(User, admin_id)
        _create_assignments_demo(db_session, org_id, admin_id)
        _issue_the_administrator_a_kit(db_session, org_id, admin)

        rows = db_session.execute(
            select(EquipmentAssignment.checked_out_at, Item.created_at).join(
                Item, Item.id == EquipmentAssignment.item_id
            )
        ).all()
        backwards = [(out, born) for out, born in rows if out < born]
        assert not backwards, f'issued before it existed: {backwards}'


class TestTheMealPlanCountsWhatItServes:
    def test_every_day_with_a_meal_has_its_nutrition(self, client, dressed) -> None:
        """The daily table counts a recipe only when all four are known; the
        seed's protein and carbs sat under keys nothing reads, so every row
        was dashes."""
        _org_id, admin_id = dressed
        plans = client.get('/api/v1/recipes/meal-plans', headers=_as(admin_id))
        assert plans.status_code == 200, plans.text
        plan_id = _rows(plans.json())[0]['id']
        plan = client.get(
            f'/api/v1/recipes/meal-plans/{plan_id}', headers=_as(admin_id)
        )
        assert plan.status_code == 200, plan.text
        body = plan.json()
        days = {entry['date'] for entry in body['entries']}
        assert days
        keys = ('calories_kcal', 'protein_g', 'fat_g', 'carbs_g')
        summary = {row['date']: row for row in body['daily_nutrition_summary']}
        blank = [
            day
            for day in sorted(days)
            if any(summary.get(day, {}).get(key) is None for key in keys)
        ]
        assert not blank, f'days with meals and no nutrition: {blank}'


class TestTheKitchenHasPictures:
    def test_every_recipe_card_shows_a_photograph(self, client, dressed) -> None:
        """The grey "Add photo" band was the largest thing on a recipe."""
        _org_id, admin_id = dressed
        response = client.get(
            '/api/v1/recipes', params={'limit': 100}, headers=_as(admin_id)
        )
        assert response.status_code == 200, response.text
        recipes = _rows(response.json())
        assert len(recipes) == len(DEMO_RECIPES)
        bare = [recipe['name'] for recipe in recipes if not recipe['image_url']]
        assert not bare, f'recipes with no photograph: {bare}'

    def test_the_photograph_is_served_from_the_apps_own_storage(
        self, client, dressed
    ) -> None:
        _org_id, admin_id = dressed
        recipes = _rows(
            client.get(
                '/api/v1/recipes', params={'limit': 100}, headers=_as(admin_id)
            ).json()
        )
        url = recipes[0]['image_url']
        assert not url.startswith('http'), f'a photo hotlinked from {url}'
        image = client.get(url, headers=_as(admin_id))
        assert image.status_code == 200, url
        assert image.headers['content-type'].startswith('image/')


class TestTheRecipesShowTheirAllergens:
    """The seeder writes ingredients straight to the table, so the suggestion
    the form makes from a name never ran and every card reached the visitor
    bare, shakshuka included."""

    #: Words that put one of the four allergens a visitor looks for on a plate.
    #: Written out here on purpose: the test must not ask the inference it checks.
    PROBES = {
        'eggs': ('egg',),
        'milk': ('milk', 'butter', 'yoghurt', 'parmesan'),
        'gluten': ('flour', 'pasta', 'spaghetti', 'penne', 'oats'),
        'nuts': ('walnut',),
    }

    @staticmethod
    def _shown(client, admin_id) -> dict[str, set[str]]:
        """The allergens each recipe's own page shows, by recipe name."""
        listed = _rows(
            client.get(
                '/api/v1/recipes', params={'limit': 100}, headers=_as(admin_id)
            ).json()
        )
        shown = {}
        for row in listed:
            page = client.get(f'/api/v1/recipes/{row["id"]}', headers=_as(admin_id))
            assert page.status_code == 200, page.text
            shown[row['name']] = set(page.json()['allergens'])
        return shown

    def test_a_recipe_with_eggs_milk_gluten_or_nuts_shows_it(
        self, client, dressed
    ) -> None:
        _org_id, admin_id = dressed
        shown = self._shown(client, admin_id)
        missing = []
        for name, _description, _servings, _minutes, _tags, lines, _how in DEMO_RECIPES:
            for allergen, words in self.PROBES.items():
                has = any(w in line[0].lower() for line in lines for w in words)
                if has and allergen not in shown[name]:
                    missing.append(f'{name}: {allergen}')
        assert not missing, f'recipes that hide an allergen: {missing}'

    def test_shakshuka_says_eggs(self, client, dressed) -> None:
        _org_id, admin_id = dressed
        assert 'eggs' in self._shown(client, admin_id)['Shakshuka']


class TestTheRecipesScaleWithServings:
    """A visitor steps the servings and expects the amounts to follow.

    The recipes were seeded as fractions of the product's unit (0.1 of a jar
    of garlic), the unit's step rounded each of them up to a whole jar, and
    every ingredient read "1 pcs." at two, three and four servings alike.
    """

    UNCATALOGUED = {'Coconut Milk', 'Parmesan', 'Onion', 'Fresh Basil'}

    @staticmethod
    def _availability(client, admin_id, recipe_id, servings):
        response = client.get(
            f'/api/v1/recipes/{recipe_id}/availability',
            params={'servings': servings},
            headers=_as(admin_id),
        )
        assert response.status_code == 200, response.text
        return {line['name']: line for line in response.json()['ingredients']}

    @staticmethod
    def _recipes(client, admin_id):
        rows = _rows(
            client.get(
                '/api/v1/recipes', params={'limit': 100}, headers=_as(admin_id)
            ).json()
        )
        return {row['name']: row['id'] for row in rows}

    def test_a_weighed_line_grows_with_the_servings_and_says_nothing_of_rounding(
        self, client, dressed
    ) -> None:
        _org_id, admin_id = dressed
        ids = self._recipes(client, admin_id)
        flat = []
        for name, _description, servings, _minutes, _tags, lines, _how in DEMO_RECIPES:
            weighed = [line[0] for line in lines if len(line) == 3]
            by_servings = [
                self._availability(client, admin_id, ids[name], servings * factor)
                for factor in (1, 2, 3)
            ]
            for ingredient in weighed:
                amounts = [
                    answer[ingredient]['required_quantity'] for answer in by_servings
                ]
                notes = [
                    answer[ingredient]['required_quantity_unrounded']
                    for answer in by_servings
                ]
                if amounts != sorted(set(amounts)) or any(n is not None for n in notes):
                    flat.append((name, ingredient, amounts, notes))
        assert not flat, f'lines that do not follow the servings: {flat}'

    def test_the_spaghetti_supper_changes_at_two_three_and_four_servings(
        self, client, dressed
    ) -> None:
        _org_id, admin_id = dressed
        recipe_id = self._recipes(client, admin_id)['Spaghetti with Garlic and Oil']
        answers = [
            self._availability(client, admin_id, recipe_id, servings)
            for servings in (2, 3, 4)
        ]
        for ingredient in (
            'Spaghetti 500g',
            'Extra Virgin Olive Oil',
            'Granulated Garlic',
            'Iodised Salt',
        ):
            amounts = [answer[ingredient]['required_quantity'] for answer in answers]
            assert amounts == sorted(set(amounts)), (ingredient, amounts)

    def test_what_is_counted_whole_stays_a_whole_number_of_its_own_unit(self) -> None:
        """A can, a pack of eggs, an onion: restating one as a weight reads wrong."""
        fractions = [
            (name, line[0], line[1])
            for name, _description, _servings, _minutes, _tags, lines, _how in DEMO_RECIPES
            for line in lines
            if len(line) == 2 and line[1] != int(line[1])
        ]
        assert not fractions, f'counted lines that are not whole: {fractions}'

    def test_a_line_in_grams_still_meets_the_stock_kept_in_jars(
        self, client, dressed
    ) -> None:
        """Restating a line in g or ml must not turn "in stock" into "cannot compare"."""
        _org_id, admin_id = dressed
        ids = self._recipes(client, admin_id)
        incomparable = []
        compared = 0
        gone = set()
        for name, *_rest in DEMO_RECIPES:
            for ingredient, line in self._availability(
                client, admin_id, ids[name], 0
            ).items():
                if line['status'] == 'incomparable':
                    incomparable.append((name, ingredient))
                elif line['status'] in (
                    'available',
                    'available_approx',
                    'insufficient',
                ):
                    compared += 1
                elif line['status'] == 'missing':
                    gone.add(ingredient)
        assert not incomparable, (
            f'lines the stock cannot be compared with: {incomparable}'
        )
        assert compared, 'no line was compared with any stock'
        assert self.UNCATALOGUED <= gone, 'a near miss stopped missing its ingredient'

    def test_a_serving_is_a_plausible_plate_and_a_recipe_has_a_plausible_price(
        self, client, dressed
    ) -> None:
        """A whole bottle of oil once put 3,800 kcal on one serving of shakshuka."""
        _org_id, admin_id = dressed
        ids = self._recipes(client, admin_id)
        off = {}
        for name, *_rest in DEMO_RECIPES:
            nutrition = client.get(
                f'/api/v1/recipes/{ids[name]}/nutrition', headers=_as(admin_id)
            ).json()
            cost = client.get(
                f'/api/v1/recipes/{ids[name]}/cost', headers=_as(admin_id)
            ).json()
            kcal = nutrition['per_serving']['calories_kcal']
            # The price is read from stock, and this fixture stocks a random
            # sixty items, so a recipe whose products were not drawn is priced
            # on part of its lines or none: only a full estimate is judged.
            price = cost['estimated_cost'] if cost['cost_coverage'] == 1 else None
            if (
                kcal is None
                or not 50 <= kcal <= 1500
                or (price is not None and not 0.5 <= price <= 60)
            ):
                off[name] = (kcal, price)
        assert not off, f'recipes with an implausible plate or price: {off}'


def test_dressing_twice_leaves_the_same_demo(db_session: Session, dressed) -> None:
    """``demo reset`` runs on a timer; a step it repeats must not pile up."""
    from app.modules.approvals.models import ApprovalRequest
    from app.modules.purchase_orders.models import PartnerPricelist

    org_id, admin_id = dressed

    def counts() -> tuple[int, ...]:
        return tuple(
            db_session.scalar(
                select(func.count())
                .select_from(model)
                .where(model.organization_id == org_id)
            )
            for model in (ApprovalRequest, PartnerPricelist, User)
        )

    before = counts()
    dress_for_visitors(db_session, org_id, admin_id)
    assert counts() == before


class _Borrowed:
    """The test's session, lent to code that closes what it opens."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def __getattr__(self, name: str) -> Any:
        return getattr(self._session, name)

    def close(self) -> None:
        """The fixture still needs it, to tear the organization down."""


def test_the_reset_opens_the_file_storage_it_writes_to(
    db_session: Session, dressed, monkeypatch, tmp_path
) -> None:
    """The API opens the file storage at start-up, and a CLI never starts it.

    The first real ``demo reset`` with photographs died on "FileStorageService
    not initialized" while every test here passed: the suite opens a storage
    of its own before any test runs. This one takes it away again and goes in
    through the door the reset uses.
    """
    import seed_demo_showcase
    from app.config import settings
    from app.core.file_storage.service import FileStorageService
    from app.modules.recipes.models.recipe import Recipe

    org_id, admin_id = dressed
    db_session.query(Recipe).filter(Recipe.organization_id == org_id).update(
        {'image_url': None}
    )
    db_session.commit()
    monkeypatch.setattr(FileStorageService(), '_provider', None)
    monkeypatch.setattr(settings, 'FILE_STORAGE_BACKEND', 'local')
    monkeypatch.setattr(settings, 'FILE_STORAGE_LOCAL_PATH', str(tmp_path))
    monkeypatch.setattr(
        seed_demo_showcase, 'SessionLocal', lambda: _Borrowed(db_session)
    )

    summary = seed_demo_showcase.dress_from_cli(
        admin_email=db_session.get(User, admin_id).email, report=lambda _m: None
    )

    assert summary['recipe_photos'] == len(DEMO_RECIPES)
    assert len(list(tmp_path.rglob('cover.*'))) == len(DEMO_RECIPES)


class TestTheProductsListHidesNothingFromAVisitor:
    """Items a module creates stay off the general lists unless the organization says otherwise.

    The seed fills the demo with module-made rows, so with the switch off the
    Products list opened on "N products are hidden" — the first thing the
    README's picture and every visitor read.
    """

    def test_module_data_is_switched_on_for_the_demo_organization(
        self, db_session: Session, dressed
    ) -> None:
        org_id, _admin_id = dressed
        db_session.expire_all()
        org = db_session.get(Organization, org_id)
        assert org.settings.get('show_module_data') is True

    def test_dressing_keeps_the_settings_it_found(
        self, db_session: Session, dressed
    ) -> None:
        org_id, admin_id = dressed
        org = db_session.get(Organization, org_id)
        org.settings = {**(org.settings or {}), 'kept': 'yes'}
        db_session.commit()

        dress_for_visitors(db_session, org_id, admin_id)

        db_session.expire_all()
        settings = db_session.get(Organization, org_id).settings
        assert settings['kept'] == 'yes'
        assert settings['show_module_data'] is True
