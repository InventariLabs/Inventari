"""The demo seed's rows have to survive being looked at, not only counted.

The README is photographed from this seed, so every row it writes ends up in
front of a reader who has no other evidence about the product. Five things read
wrong on the screens, although every count behind them was right:

* each seeded document printed ``SEED-DOC`` where a supplier's delivery note
  number belongs;
* products sat on a random shelf — chicken breast in dry goods, cinnamon in a
  fridge door — on the one screen whose job is to say where things are;
* the overview led with "Iodised Salt — expired", because the pantry runs in
  expiry mode too and the story drew from it;
* every asset carried a flat price and no purchase or warranty date, so the
  warranty column was blank and the fleet depreciated by nothing;
* every recipe was fully in stock, so "I can cook" had nothing to tell apart.

Two more came from photographing the warehouse half:

* the finished production run was a bare row with a hand-typed total — no
  ingredient on it, nothing taken off a shelf, nothing put on one — and two of
  its recipe's three ingredients had no price anywhere, so the recipe card
  said its cost could not be worked out;
* every record opened at the minute of seeding, so each product's history was
  one line dated today, and every document was created, confirmed and
  completed in the same second.

Each test below pins one of them against a freshly seeded organization.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.stock_move import StockMove, StockMoveReferenceType
from app.models.stock_valuation_layer import StockValuationLayer
from app.models.storage_location import StorageLocation
from app.modules.equipment.models import EquipmentMaintenanceLog
from app.modules.maker.models import (
    BoMLine,
    MakerRecipe,
    ProductionOrder,
    ProductionOrderLine,
)
from app.modules.recipes.models.meal_plan import MealPlan, MealPlanEntry
from app.modules.recipes.models.recipe import Recipe, RecipeIngredient
from app.modules.shopping_lists.models import ShoppingListItem
from app.modules.warehouse.models import Document
from seed_demo_data import (
    DEMO_STORY_EXPIRED,
    FOOD_TEMPLATES,
    FOOD_ZONE_BY_CATEGORY,
    SEED_PREFIX,
    TODAY,
    clean_seed_data,
)
from tests.integration._demo_world import ids, seeded_organization

pytestmark = pytest.mark.integration


@pytest.fixture
def seeded(demo_world) -> uuid.UUID:
    """An organization seeded with every module."""
    payload = demo_world('org-120', seeded_organization(items=120))
    return ids(payload)[0]


def _zone_of(db: Session, location_id: uuid.UUID) -> str:
    """The second level of the hierarchy a location sits under."""
    node = db.get(StorageLocation, location_id)
    while node.parent_id is not None:
        parent = db.get(StorageLocation, node.parent_id)
        if parent.parent_id is None:
            return node.name
        node = parent
    return node.name


class TestDocumentsCarryNoSeedMarkerOnScreen:
    def test_no_document_prints_the_marker_where_a_reference_belongs(
        self, db_session: Session, seeded: uuid.UUID
    ) -> None:
        references = [
            ref
            for (ref,) in db_session.query(Document.external_reference).filter(
                Document.organization_id == seeded
            )
        ]
        assert references, 'the seed wrote no documents — nothing was checked'
        leaked = [ref for ref in references if ref and ref.startswith(SEED_PREFIX)]
        assert not leaked, f'seed marker printed as a reference: {leaked}'

    def test_clean_still_finds_every_seeded_document(
        self, db_session: Session, seeded: uuid.UUID
    ) -> None:
        """Moving the marker must not strand the documents ``--clean`` removes."""
        clean_seed_data(db_session, seeded)
        db_session.commit()

        left = (
            db_session.query(Document)
            .filter(Document.organization_id == seeded)
            .count()
        )
        assert left == 0


class TestFoodSitsWhereItIsKept:
    def test_every_product_is_in_the_zone_its_category_belongs_to(
        self, db_session: Session, seeded: uuid.UUID
    ) -> None:
        zone_by_name = {
            row[0]: FOOD_ZONE_BY_CATEGORY.get(row[3], 'Dry Goods')
            for row in FOOD_TEMPLATES
        }
        misplaced = []
        rows = (
            db_session.query(Item.name, Item.storage_location_id)
            .filter(Item.organization_id == seeded, Item.module_name.is_(None))
            .all()
        )
        for name, location_id in rows:
            expected = zone_by_name.get(name)
            if expected is None:
                continue
            actual = _zone_of(db_session, location_id)
            if actual != expected:
                misplaced.append((name, actual, expected))
        assert rows
        assert not misplaced, f'{len(misplaced)} misplaced, e.g. {misplaced[:5]}'

    def test_what_has_gone_off_is_something_that_can(
        self, db_session: Session, seeded: uuid.UUID
    ) -> None:
        food = {row[0] for row in FOOD_TEMPLATES}
        expired = (
            db_session.query(Item.storage_location_id)
            .filter(
                Item.organization_id == seeded,
                Item.name.in_(food),
                Item.expiry_date < TODAY,
            )
            .all()
        )
        assert len(expired) == DEMO_STORY_EXPIRED
        zones = {_zone_of(db_session, location_id) for (location_id,) in expired}
        assert zones == {'Cold Storage'}


class TestTheFleetHasAHistory:
    def test_every_asset_has_a_purchase_and_a_warranty_date(
        self, db_session: Session, seeded: uuid.UUID
    ) -> None:
        assets = (
            db_session.query(Item)
            .filter(Item.organization_id == seeded, Item.module_name == 'equipment')
            .all()
        )
        assert assets
        undated = [
            item.name
            for item in assets
            if not item.meta_data['equipment'].get('purchase_date')
            or not item.meta_data['equipment'].get('warranty_until')
        ]
        assert not undated
        assert len({item.purchase_price for item in assets}) > 1, (
            'every asset still carries the same flat price'
        )

    def test_an_open_repair_puts_its_asset_in_maintenance(
        self, db_session: Session, seeded: uuid.UUID
    ) -> None:
        open_jobs = (
            db_session.query(EquipmentMaintenanceLog)
            .filter(
                EquipmentMaintenanceLog.organization_id == seeded,
                EquipmentMaintenanceLog.next_maintenance_at.is_(None),
            )
            .all()
        )
        assert open_jobs
        for job in open_jobs:
            item = db_session.get(Item, job.item_id)
            assert item.meta_data['equipment']['equipment_status'] == 'MAINTENANCE'


class TestTheKitchenHasSomethingToDecide:
    def test_some_recipes_are_near_misses(
        self, db_session: Session, seeded: uuid.UUID
    ) -> None:
        """An ingredient no template names is one the pantry cannot cover."""
        recipes = db_session.query(Recipe).filter(Recipe.organization_id == seeded)
        short = [
            recipe.name
            for recipe in recipes
            if db_session.query(RecipeIngredient)
            .filter(
                RecipeIngredient.recipe_id == recipe.id,
                RecipeIngredient.template_id.is_(None),
            )
            .count()
        ]
        assert short, 'every recipe is fully covered by the catalogue'
        assert len(short) < recipes.count(), 'no recipe is fully covered'

    def test_the_shared_seed_leaves_the_photographs_to_the_demo(
        self, db_session: Session, seeded: uuid.UUID
    ) -> None:
        """Every stack and the suite run this seed; only ``demo reset``
        stores photographs (``seed_demo_showcase``)."""
        photographed = (
            db_session.query(Recipe)
            .filter(Recipe.organization_id == seeded, Recipe.image_url.is_not(None))
            .count()
        )
        assert photographed == 0

    def test_this_weeks_plan_comes_with_its_shopping_list(
        self, db_session: Session, seeded: uuid.UUID
    ) -> None:
        plan = (
            db_session.query(MealPlan).filter(MealPlan.organization_id == seeded).one()
        )
        assert plan.start_date <= TODAY <= plan.end_date
        entries = (
            db_session.query(MealPlanEntry)
            .filter(MealPlanEntry.meal_plan_id == plan.id)
            .count()
        )
        assert entries >= 7
        assert plan.shopping_list_id is not None
        on_the_list = {
            name
            for (name,) in db_session.query(ShoppingListItem.name).filter(
                ShoppingListItem.shopping_list_id == plan.shopping_list_id
            )
        }
        missing = {
            name
            for (name,) in db_session.query(RecipeIngredient.name)
            .join(Recipe, Recipe.id == RecipeIngredient.recipe_id)
            .filter(
                Recipe.organization_id == seeded,
                RecipeIngredient.template_id.is_(None),
            )
        }
        assert missing <= on_the_list, (
            f'the plan is short of {sorted(missing - on_the_list)} and the '
            f'shopping list does not say so'
        )

    def test_every_kitchen_amount_names_its_unit(
        self, db_session: Session, seeded: uuid.UUID
    ) -> None:
        """No seeded amount reads "Onion 1" on a recipe or "1 —" on the list.

        Four names have no product to borrow a unit from; a count is what
        they are, and a count is stated in pieces.
        """
        unitless_lines = [
            name
            for (name,) in db_session.query(RecipeIngredient.name)
            .join(Recipe, Recipe.id == RecipeIngredient.recipe_id)
            .filter(
                Recipe.organization_id == seeded,
                RecipeIngredient.uom_id.is_(None),
            )
        ]
        plan = (
            db_session.query(MealPlan).filter(MealPlan.organization_id == seeded).one()
        )
        unitless_entries = [
            name
            for (name,) in db_session.query(ShoppingListItem.name).filter(
                ShoppingListItem.shopping_list_id == plan.shopping_list_id,
                ShoppingListItem.uom_id.is_(None),
            )
        ]
        assert unitless_lines == []
        assert unitless_entries == []


class TestTheWorkshopRanWhatItReports:
    def _finished_run(self, db: Session, org_id: uuid.UUID) -> ProductionOrder:
        return (
            db.query(ProductionOrder)
            .filter(
                ProductionOrder.organization_id == org_id,
                ProductionOrder.status == 'COMPLETED',
            )
            .one()
        )

    def test_the_finished_run_lists_every_ingredient_it_consumed(
        self, db_session: Session, seeded: uuid.UUID
    ) -> None:
        run = self._finished_run(db_session, seeded)
        lines = (
            db_session.query(ProductionOrderLine)
            .filter(ProductionOrderLine.production_order_id == run.id)
            .all()
        )
        recipe_children = {
            child
            for (child,) in db_session.query(BoMLine.child_template_id).filter(
                BoMLine.recipe_id == run.recipe_id
            )
        }
        assert recipe_children, 'the run names no recipe it was made by'
        assert {line.child_template_id for line in lines} == recipe_children
        unpriced = [
            line.child_template_id for line in lines if not line.unit_cost_snapshot
        ]
        assert not unpriced, f'consumed at no cost: {unpriced}'
        consumed = sum(
            (line.consumed_qty * line.unit_cost_snapshot for line in lines),
            Decimal('0'),
        )
        assert abs(consumed - run.total_cost) < Decimal('0.05'), (
            f'the lines add up to {consumed}, the run says {run.total_cost}'
        )

    def test_what_the_run_made_is_on_a_shelf(
        self, db_session: Session, seeded: uuid.UUID
    ) -> None:
        run = self._finished_run(db_session, seeded)
        assert run.produced_item_id is not None
        made = db_session.get(Item, run.produced_item_id)
        assert made.quantity == run.actual_qty
        assert not (run.number or '').startswith(SEED_PREFIX)

    def test_every_ingredient_of_the_recipe_still_has_a_price(
        self, db_session: Session, seeded: uuid.UUID
    ) -> None:
        """The recipe card costs a batch from the stock that is left."""
        recipe = (
            db_session.query(MakerRecipe)
            .filter(
                MakerRecipe.organization_id == seeded,
                MakerRecipe.is_default.is_(True),
            )
            .one()
        )
        children = [
            child
            for (child,) in db_session.query(BoMLine.child_template_id).filter(
                BoMLine.recipe_id == recipe.id
            )
        ]
        priced = {
            template_id
            for (template_id,) in db_session.query(
                StockValuationLayer.product_template_id
            ).filter(
                StockValuationLayer.organization_id == seeded,
                StockValuationLayer.direction == 'IN',
                StockValuationLayer.remaining_qty > 0,
                StockValuationLayer.cost_basis != 'unknown',
                StockValuationLayer.product_template_id.in_(children),
            )
        }
        assert set(children) == priced, (
            f'{len(set(children) - priced)} ingredient(s) have no stock with a price'
        )


class TestTheShelvesFilledOverTime:
    def test_records_opened_across_weeks_not_at_the_minute_of_seeding(
        self, db_session: Session, seeded: uuid.UUID
    ) -> None:
        moved_at = func.coalesce(StockMove.completed_at, StockMove.created_at)
        dates = [
            when
            for (when,) in db_session.query(moved_at).filter(
                StockMove.organization_id == seeded,
                StockMove.reference_type == StockMoveReferenceType.OPENING_BALANCE,
            )
        ]
        assert dates, 'nothing was opened — nothing was checked'
        today = datetime.combine(TODAY, time.min, UTC)
        assert max(dates) < today, 'a record opened on the day of seeding'
        assert min(dates) < today - timedelta(days=30)
        assert len({when.date() for when in dates}) >= 10

    def test_cost_layers_carry_the_day_their_stock_arrived(
        self, db_session: Session, seeded: uuid.UUID
    ) -> None:
        """The as-of report values stock by the layer's day, not its write time."""
        days = {
            day
            for (day,) in db_session.query(StockValuationLayer.document_date).filter(
                StockValuationLayer.organization_id == seeded,
                StockValuationLayer.direction == 'IN',
                StockValuationLayer.document_date.is_not(None),
            )
        }
        assert len(days) >= 10

    def test_a_document_is_confirmed_after_it_is_written_and_completed_after_that(
        self, db_session: Session, seeded: uuid.UUID
    ) -> None:
        documents = (
            db_session.query(Document).filter(Document.organization_id == seeded).all()
        )
        confirmed = [doc for doc in documents if doc.confirmed_at is not None]
        assert confirmed, 'no document was confirmed — nothing was checked'
        for doc in confirmed:
            assert doc.confirmed_at > doc.created_at, doc.number
            if doc.completed_at is not None:
                assert doc.completed_at > doc.confirmed_at, doc.number
