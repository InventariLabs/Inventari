"""
Seeds realistic demo data for manual testing and performance verification.

Creates:
    - warehouse hierarchy for food + equipment, one branch four deep (ADR-018)
    - ~120 product templates with barcodes, prices, nutrition info, UoMs
    - ~600 items with categories, expiry dates, purchase prices
    - their stock opened in the register: opening movement, cost layer
    - 10 supplier partners
 - 8 warehouse documents (IN/OUT/INT) with priced lines, the completed
   ones' stock posted through the register, two of the dispatches picked
   in one session, one of them packed and shipped under a tracking number

Target org: organization of admin@example.com (resolved at runtime).
All data uses the "SEED-" prefix in short_codes for easy cleanup.

Usage:
    docker compose exec backend uv run python seed_demo_data.py
    docker compose exec backend uv run python seed_demo_data.py --items 1000
    docker compose exec backend uv run python seed_demo_data.py --clean
"""

import argparse
import hashlib
import itertools
import os
import random
import string
import sys
import uuid
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import or_

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.core.barcode import gtin_check_digit
from app.database import SessionLocal
from app.models.item import Item
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import LocationUsage, StorageLocation
from app.models.user import User
from app.modules.maker.models import BoMLine, MakerRecipe, ProductionOrder
from app.modules.purchase_orders.models import PurchaseOrder, PurchaseOrderLine
from app.modules.stock_takes.models import (
    StockTakeItem,  # noqa: F401 — resolve Item.stock_take_items
)
from app.modules.warehouse.country_tax_rules import get_country_rule
from app.modules.warehouse.document_value_service import recompute_document_values
from app.modules.warehouse.models import (
    Document,
    DocumentLine,
    DocumentStatus,
    DocumentType,
)
from app.seed_profiles.equipment_wms import seed_equipment_wms
from app.seed_profiles.food_home import seed_food_home
from app.services.items._module_owner import resolve_module_owner

SEED_PREFIX = 'SEED-'

ADMIN_EMAIL = 'admin@example.com'  # seed targets this user's organization

# UoM symbols used in the template data below. Real UUIDs are owned by the
# base seed and resolved at runtime — never hardcode them here.
UOM_PIECE = 'pcs'
UOM_GRAM = 'g'
UOM_KG = 'kg'
UOM_LITER = 'l'
UOM_ML = 'ml'
UOM_PACK = 'pack'

TODAY = date.today()


def _short_code(db, org_id) -> str:
    """A fresh shelf code: drawn again until the organization has no such location."""
    while True:
        code = SEED_PREFIX + ''.join(
            random.choices(string.ascii_uppercase + string.digits, k=4)
        )
        taken = (
            db.query(StorageLocation.id)
            .filter(
                StorageLocation.organization_id == org_id,
                StorageLocation.short_code == code,
            )
            .first()
        )
        if taken is None:
            return code


def _seeded_barcode(name: str, taken: set[str]) -> str:
    """A barcode for a product the catalogue names none for — and the same
    one in every sandbox the seed opens.

    A printed label is worth its paper only when the code on it answers
    wherever it is scanned, and the demo hands every visitor a sandbox of
    their own built from these rows: a barcode drawn at random here would
    put product codes on a printed sheet that resolve in the one sandbox
    that drew them. The first twelve digits come from the name, the
    thirteenth is the GS1 check digit over them, so a scanner reads the
    number as the EAN-13 it looks like. ``taken`` widens the draw and the
    salt keeps it a draw of the same shape — a name that meets an already
    taken code still lands on a code of its own: same name, same code,
    every time.
    """
    seed = int(hashlib.sha256(name.encode('utf-8')).hexdigest(), 16)
    for salt in itertools.count():
        body = f'{(seed + salt) % 10**12:012d}'
        code = body + gtin_check_digit(body)
        if code not in taken:
            return code


# ---------------------------------------------------------------------------
# The story the demo tells
# ---------------------------------------------------------------------------
# A demo instance is read before it is used, and the overview is the first
# screen a visitor sees. Until 2026-09-21 this seeder drew every expiry date
# independently, 15% of them in the past, which on ~580 items printed
# "100 EXPIRED" in red on the landing page of a product whose first promise is
# that you stop throwing food away. The counts below replace that coin flip:
# enough to show the alert machinery doing its job, few enough that the
# organization reads as one somebody actually keeps.
#
# They are exact, not approximate — the dates are handed out after the items
# exist, so the overview counters land on these numbers rather than near them.
DEMO_STORY_EXPIRED = 2
DEMO_STORY_EXPIRING_SOON = 9
#: Products sitting exactly on their reorder threshold — the sum of a
#: product's shelf quantities equal to its ``min_quantity``. Without this
#: the LOW STOCK tile is a permanent zero, and a permanent zero does not
#: tell the reader whether the counter works.
DEMO_STORY_LOW_STOCK = 3
#: The demo stock take's title and description. Named here so the language
#: gate sweeps them like every other seeded string a guest can read.
DEMO_STOCK_TAKE_TITLE = 'Dry Goods count'
DEMO_STOCK_TAKE_DESCRIPTION = 'Quarterly count of the dry goods shelves.'
#: The carrier the shipped demo dispatch goes out with, and the number to
#: follow it by. Named here so the language gate sweeps them like every
#: other seeded string a guest can read.
DEMO_SHIPMENT_CARRIER = 'InPost'
DEMO_SHIPMENT_TRACKING_NUMBER = '620012345678901234567890'


def _org_currency(db, org_id) -> str:
    """The currency this organization keeps its books in.

    Every seeded row used to be written as ``PLN`` while the organization the
    seed targets is created as ``USD``, so the demo showed zloty amounts inside
    a dollar organization — the valuation screens read the organization, the
    rows read themselves, and the two disagreed on every screen that showed
    both.
    """
    from app.models.organization import Organization

    currency = (
        db.query(Organization.currency).filter(Organization.id == org_id).scalar()
    )
    return currency or 'USD'


def _org_tax_rates(db, org_id) -> tuple[Decimal | None, Decimal | None]:
    """The standard and the reduced rate this organization's country charges.

    A country with no row, or none named, charges nothing here, the way a real
    document of that organization is left untaxed
    (``resolve_document_tax_rate``): a dollar organization with no country was
    otherwise shown 23% Polish VAT on every order. Food takes the reduced rate;
    a country with none charges its standard rate there too.
    """
    from app.models.organization import Organization

    country = db.query(Organization.country).filter(Organization.id == org_id).scalar()
    rule = get_country_rule(country)
    if rule is None:
        return None, None
    reduced = rule.reduced_tax_rates
    standard = rule.default_tax_rate
    return standard, reduced[0] if reduced else standard


def _apply_expiry_story(
    items_with_mode: list[tuple[Any, str]], *, chilled: list[Any] | None = None
) -> None:
    """Hand out expiry dates so the overview tiles tell the story above.

    The perishable rows are shuffled first, so *which* item is the expired one
    changes between runs while *how many* does not.

    *chilled* are the rows kept in the fridge. The expired and expiring-soon
    dates go to them first: the pantry shelves also run in expiry mode, and
    the overview leading with "Iodised Salt — expired" reads as a joke on the
    product's first promise, which is about food going off.
    """
    from app.services.items.expiry import DEFAULT_EXPIRING_SOON_DAYS

    perishable = [item for item, mode in items_with_mode if mode == 'EXPIRY']
    frozen = [item for item, mode in items_with_mode if mode == 'FREEZING']
    shelf_stable = [
        item for item, mode in items_with_mode if mode not in ('EXPIRY', 'FREEZING')
    ]

    random.shuffle(perishable)
    if chilled:
        # Stable sort: the fridge rows move to the front, each group keeps
        # the shuffled order.
        chilled_ids = {id(item) for item in chilled}
        perishable.sort(key=lambda item: id(item) not in chilled_ids)
    cut_expired = DEMO_STORY_EXPIRED
    cut_soon = cut_expired + DEMO_STORY_EXPIRING_SOON

    for item in perishable[:cut_expired]:
        # Days, not months: a demo showing food two months rotten tells the
        # reader that nobody looks at this instance.
        item.expiry_date = TODAY - timedelta(days=random.randint(1, 4))

    # The counters' window is inclusive at both ends and today itself counts as
    # expiring soon, so spread the batch across every day of it.
    window = DEFAULT_EXPIRING_SOON_DAYS + 1
    for offset, item in enumerate(perishable[cut_expired:cut_soon]):
        item.expiry_date = TODAY + timedelta(days=offset % window)

    for item in perishable[cut_soon:]:
        item.expiry_date = (
            None
            if random.random() < 0.25
            else TODAY + timedelta(days=random.randint(21, 365))
        )

    for item in frozen:
        item.expiry_date = (
            None
            if random.random() < 0.10
            else TODAY + timedelta(days=random.randint(60, 540))
        )

    for item in shelf_stable:
        item.expiry_date = None


def _apply_low_stock_story(items: list[Any], templates: list[tuple[Any, str]]) -> int:
    """Put a few products at their reorder threshold, and only a few.

    The LOW STOCK counter compares a product's **total shelf quantity**
    against its threshold — ``sum(quantity) <= min_quantity`` over the
    internal, not-deleted rows, one answer per product (see
    ``low_stock_template_ids``). The threshold is therefore set to that
    sum: the product sits exactly on its reorder point — "time to
    reorder", not "you have run out" — and the counter counts it, because
    the comparison is ``<=``.

    Setting the **lowest row's** quantity instead was written for an
    earlier, per-row comparison; once the counter moved to sums, a product
    holding more than one row crossed the line its own lowest row had set,
    and the tile read zero while this seed kept printing "below
    threshold" — measured five resets in a row by review 2026-09-22.

    Products are taken fewest-rows-first so the story stays small: a
    product with one row is one whose per-row and per-product answers
    cannot disagree.

    Returns how many *products* the tile will count — the same unit the
    LOW STOCK counter prints, not the number of rows under a threshold.
    """
    rows_by_template: dict[Any, list[Any]] = {}
    for item in items:
        rows_by_template.setdefault(item.template_id, []).append(item)
    if not rows_by_template:
        return 0

    by_id = {template.id: template for template, _cat_key in templates}
    candidates = sorted(rows_by_template.items(), key=lambda kv: len(kv[1]))[
        : DEMO_STORY_LOW_STOCK * 3
    ]
    random.shuffle(candidates)

    flagged = 0
    for template_id, rows in candidates:
        if flagged >= DEMO_STORY_LOW_STOCK:
            break
        template = by_id.get(template_id)
        if template is None:
            continue
        total = sum(row.quantity for row in rows)
        if total <= 0:
            # The counter requires a positive threshold; a product holding
            # nothing cannot carry the story.
            continue
        template.min_quantity = float(total)
        flagged += 1
    return flagged


# ---------------------------------------------------------------------------
# Food product templates: (name, brand, barcode, cat_key, uom, weight_g, price, nutrition)
#
# Nutrition is per 100 g, under the keys the application itself stores on a
# card (app.services.items.nutrition) and the recipe pipeline reads. The seed
# used to write calories/protein/fat/carbs: the pipeline found the calories and
# the fat, never the protein or the carbs, and the meal plan's daily table —
# which counts a recipe only when all four are known — stayed all dashes.
# ---------------------------------------------------------------------------
FOOD_TEMPLATES = [
    (
        'UHT Milk 3.2%',
        'Meadowlane',
        '2000000000015',
        'dairy',
        UOM_PIECE,
        1000,
        Decimal('4.50'),
        {'calories_kcal': 62, 'protein_g': 3.2, 'fat_g': 3.2, 'carbs_g': 4.8},
    ),
    (
        'Natural Yoghurt 400g',
        'Meadowlane',
        '2000000000022',
        'dairy',
        UOM_PIECE,
        400,
        Decimal('5.20'),
        {'calories_kcal': 67, 'protein_g': 4.0, 'fat_g': 1.5, 'carbs_g': 7.5},
    ),
    (
        'Butter Extra 82%',
        'Meadowlane',
        '2000000000039',
        'dairy',
        UOM_PIECE,
        200,
        Decimal('8.90'),
        {'calories_kcal': 748, 'protein_g': 0.5, 'fat_g': 82.0, 'carbs_g': 0.8},
    ),
    (
        'Gouda Cheese',
        'Meadowlane',
        '2000000000046',
        'cheese',
        UOM_PIECE,
        300,
        Decimal('12.50'),
        {'calories_kcal': 356, 'protein_g': 24.0, 'fat_g': 27.0, 'carbs_g': 1.3},
    ),
    (
        'Sour Cream 18%',
        'Meadowlane',
        '2000000000053',
        'dairy',
        UOM_PIECE,
        300,
        Decimal('4.10'),
        {'calories_kcal': 182, 'protein_g': 2.5, 'fat_g': 18.0, 'carbs_g': 3.4},
    ),
    (
        'Cottage Cheese',
        'Meadowlane',
        '2000000000060',
        'dairy',
        UOM_PIECE,
        200,
        Decimal('3.80'),
        {'calories_kcal': 125, 'protein_g': 9.0, 'fat_g': 7.0, 'carbs_g': 5.0},
    ),
    (
        'Lean Quark',
        'Meadowlane',
        '2000000000077',
        'dairy',
        UOM_PIECE,
        250,
        Decimal('5.50'),
        {'calories_kcal': 85, 'protein_g': 18.0, 'fat_g': 0.5, 'carbs_g': 3.5},
    ),
    (
        'Eggs Medium 10pk',
        'Fellbrook Farms',
        '2000000000084',
        'eggs',
        UOM_PACK,
        600,
        Decimal('9.90'),
        {'calories_kcal': 155, 'protein_g': 13.0, 'fat_g': 11.0, 'carbs_g': 1.1},
    ),
    (
        'Chicken Ham',
        'Fellbrook Farms',
        '2000000000091',
        'deli',
        UOM_KG,
        500,
        Decimal('24.90'),
        {'calories_kcal': 110, 'protein_g': 16.0, 'fat_g': 4.5, 'carbs_g': 1.0},
    ),
    (
        'Pork Frankfurters',
        'Fellbrook Farms',
        '2000000000107',
        'deli',
        UOM_PACK,
        500,
        Decimal('11.50'),
        {'calories_kcal': 253, 'protein_g': 12.0, 'fat_g': 22.0, 'carbs_g': 2.0},
    ),
    (
        'Smoked Sausage',
        'Fellbrook Farms',
        '2000000000114',
        'deli',
        UOM_PIECE,
        400,
        Decimal('9.80'),
        {'calories_kcal': 301, 'protein_g': 12.0, 'fat_g': 27.0, 'carbs_g': 3.0},
    ),
    (
        'Smoked Bacon',
        'Fellbrook Farms',
        '2000000000121',
        'pork',
        UOM_KG,
        500,
        Decimal('19.90'),
        {'calories_kcal': 393, 'protein_g': 12.0, 'fat_g': 38.0, 'carbs_g': 1.0},
    ),
    (
        'Chicken Breast Fillet',
        'Fellbrook Farms',
        '2000000000138',
        'poultry',
        UOM_KG,
        600,
        Decimal('22.50'),
        {'calories_kcal': 110, 'protein_g': 23.0, 'fat_g': 1.2, 'carbs_g': 0.0},
    ),
    (
        'Smoked Salmon',
        'Bluewater',
        '2000000000145',
        'fish',
        UOM_PIECE,
        150,
        Decimal('18.90'),
        {'calories_kcal': 196, 'protein_g': 20.0, 'fat_g': 13.0, 'carbs_g': 0.0},
    ),
    (
        'Mayonnaise',
        'Harvest Row',
        '2000000000152',
        'sauces',
        UOM_PIECE,
        300,
        Decimal('6.50'),
        {'calories_kcal': 714, 'protein_g': 1.0, 'fat_g': 79.0, 'carbs_g': 1.0},
    ),
    (
        'Tomato Ketchup',
        'Harvest Row',
        '2000000000169',
        'sauces',
        UOM_PIECE,
        500,
        Decimal('8.90'),
        {'calories_kcal': 112, 'protein_g': 1.0, 'fat_g': 0.1, 'carbs_g': 26.0},
    ),
    (
        'Orange Juice NFC',
        'Orchard & Oak',
        '2000000000176',
        'drinks',
        UOM_PIECE,
        1000,
        Decimal('7.50'),
        {'calories_kcal': 45, 'protein_g': 0.7, 'fat_g': 0.2, 'carbs_g': 10.0},
    ),
    (
        'Chocolate Milk Drink',
        'Meadowlane',
        '2000000000183',
        'drinks',
        UOM_PIECE,
        500,
        Decimal('4.20'),
        {'calories_kcal': 84, 'protein_g': 3.2, 'fat_g': 1.5, 'carbs_g': 14.0},
    ),
    (
        'Classic Hummus',
        'Green Acre',
        '2000000000190',
        'sauces',
        UOM_PIECE,
        200,
        Decimal('6.80'),
        {'calories_kcal': 215, 'protein_g': 7.0, 'fat_g': 14.0, 'carbs_g': 14.0},
    ),
    (
        'Red Pesto',
        'Harvest Row',
        '2000000000206',
        'sauces',
        UOM_PIECE,
        190,
        Decimal('14.90'),
        {'calories_kcal': 267, 'protein_g': 3.0, 'fat_g': 25.0, 'carbs_g': 5.0},
    ),
    (
        'Carrots 1kg',
        'Green Acre',
        None,
        'fresh_vegetables',
        UOM_KG,
        1000,
        Decimal('3.50'),
        {'calories_kcal': 41, 'protein_g': 0.9, 'fat_g': 0.2, 'carbs_g': 10.0},
    ),
    (
        'Broccoli',
        'Green Acre',
        None,
        'fresh_vegetables',
        UOM_PIECE,
        400,
        Decimal('5.90'),
        {'calories_kcal': 34, 'protein_g': 2.8, 'fat_g': 0.4, 'carbs_g': 7.0},
    ),
    (
        'Cherry Tomatoes',
        'Green Acre',
        None,
        'fresh_vegetables',
        UOM_KG,
        500,
        Decimal('8.90'),
        {'calories_kcal': 18, 'protein_g': 0.9, 'fat_g': 0.2, 'carbs_g': 3.9},
    ),
    (
        'Cucumber',
        'Green Acre',
        None,
        'fresh_vegetables',
        UOM_PIECE,
        300,
        Decimal('3.20'),
        {'calories_kcal': 16, 'protein_g': 0.7, 'fat_g': 0.1, 'carbs_g': 3.6},
    ),
    (
        'Fuji Apples',
        'Green Acre',
        None,
        'fresh_fruits',
        UOM_KG,
        1000,
        Decimal('6.50'),
        {'calories_kcal': 52, 'protein_g': 0.3, 'fat_g': 0.2, 'carbs_g': 14.0},
    ),
    (
        'Green Grapes',
        'Green Acre',
        None,
        'fresh_fruits',
        UOM_KG,
        500,
        Decimal('9.90'),
        {'calories_kcal': 69, 'protein_g': 0.7, 'fat_g': 0.2, 'carbs_g': 18.0},
    ),
    (
        'Strawberries',
        'Green Acre',
        None,
        'fresh_fruits',
        UOM_KG,
        500,
        Decimal('14.90'),
        {'calories_kcal': 32, 'protein_g': 0.7, 'fat_g': 0.3, 'carbs_g': 7.7},
    ),
    (
        'Bananas',
        'Green Acre',
        None,
        'fresh_fruits',
        UOM_KG,
        1000,
        Decimal('5.90'),
        {'calories_kcal': 89, 'protein_g': 1.1, 'fat_g': 0.3, 'carbs_g': 23.0},
    ),
    (
        'Vanilla Ice Cream',
        'Northwind Frozen',
        '2000000000299',
        'ice_cream',
        UOM_PIECE,
        500,
        Decimal('11.90'),
        {'calories_kcal': 207, 'protein_g': 3.5, 'fat_g': 11.0, 'carbs_g': 24.0},
    ),
    (
        'Frozen Pepperoni Pizza',
        'Northwind Frozen',
        '2000000000305',
        'frozen_pizza',
        UOM_PIECE,
        350,
        Decimal('13.50'),
        {'calories_kcal': 266, 'protein_g': 11.0, 'fat_g': 12.0, 'carbs_g': 28.0},
    ),
    (
        'Potato and Cheese Dumplings',
        'Northwind Frozen',
        '2000000000312',
        'frozen_meals',
        UOM_PACK,
        600,
        Decimal('9.50'),
        {'calories_kcal': 196, 'protein_g': 5.0, 'fat_g': 7.0, 'carbs_g': 28.0},
    ),
    (
        'Fish Fingers',
        'Bluewater',
        '2000000000329',
        'frozen_meals',
        UOM_PACK,
        400,
        Decimal('12.90'),
        {'calories_kcal': 215, 'protein_g': 10.0, 'fat_g': 10.0, 'carbs_g': 22.0},
    ),
    (
        'Frozen Mixed Vegetables',
        'Northwind Frozen',
        '2000000000336',
        'frozen_vegetables',
        UOM_PACK,
        750,
        Decimal('5.90'),
        {'calories_kcal': 35, 'protein_g': 2.0, 'fat_g': 0.5, 'carbs_g': 5.0},
    ),
    (
        'Frozen Green Peas',
        'Northwind Frozen',
        '2000000000343',
        'frozen_vegetables',
        UOM_PACK,
        450,
        Decimal('4.80'),
        {'calories_kcal': 81, 'protein_g': 5.0, 'fat_g': 0.4, 'carbs_g': 14.0},
    ),
    (
        'Frozen Chips',
        'Northwind Frozen',
        '2000000000350',
        'frozen_vegetables',
        UOM_PACK,
        750,
        Decimal('8.90'),
        {'calories_kcal': 152, 'protein_g': 2.5, 'fat_g': 5.0, 'carbs_g': 24.0},
    ),
    (
        'Frozen Blueberries',
        'Northwind Frozen',
        '2000000000367',
        'frozen_fruits',
        UOM_PACK,
        400,
        Decimal('9.50'),
        {'calories_kcal': 57, 'protein_g': 0.7, 'fat_g': 0.3, 'carbs_g': 14.0},
    ),
    (
        'Frozen Sour Cherries',
        'Northwind Frozen',
        '2000000000374',
        'frozen_fruits',
        UOM_PACK,
        500,
        Decimal('7.90'),
        {'calories_kcal': 50, 'protein_g': 1.0, 'fat_g': 0.3, 'carbs_g': 12.0},
    ),
    (
        'Minced Pork',
        'Fellbrook Farms',
        '2000000000381',
        'pork',
        UOM_KG,
        500,
        Decimal('16.90'),
        {'calories_kcal': 242, 'protein_g': 15.0, 'fat_g': 19.0, 'carbs_g': 0.0},
    ),
    (
        'Spaghetti 500g',
        'Harvest Row',
        '2000000000398',
        'pasta',
        UOM_PIECE,
        500,
        Decimal('5.90'),
        {'calories_kcal': 371, 'protein_g': 13.0, 'fat_g': 1.5, 'carbs_g': 75.0},
    ),
    (
        'Penne Pasta',
        'Harvest Row',
        '2000000000404',
        'pasta',
        UOM_PIECE,
        500,
        Decimal('5.90'),
        {'calories_kcal': 371, 'protein_g': 13.0, 'fat_g': 1.5, 'carbs_g': 75.0},
    ),
    (
        'Fusilli Pasta',
        'Harvest Row',
        '2000000000411',
        'pasta',
        UOM_PIECE,
        500,
        Decimal('5.90'),
        {'calories_kcal': 371, 'protein_g': 13.0, 'fat_g': 1.5, 'carbs_g': 75.0},
    ),
    (
        'Jasmine Rice 1kg',
        'Harvest Row',
        '2000000000428',
        'rice_grains',
        UOM_PIECE,
        1000,
        Decimal('9.90'),
        {'calories_kcal': 348, 'protein_g': 7.0, 'fat_g': 0.5, 'carbs_g': 78.0},
    ),
    (
        'Buckwheat Groats',
        'Harvest Row',
        '2000000000435',
        'rice_grains',
        UOM_PIECE,
        500,
        Decimal('5.50'),
        {'calories_kcal': 343, 'protein_g': 12.0, 'fat_g': 3.0, 'carbs_g': 62.0},
    ),
    (
        'Rolled Oats',
        'Harvest Row',
        '2000000000442',
        'dry_products',
        UOM_PIECE,
        500,
        Decimal('4.50'),
        {'calories_kcal': 379, 'protein_g': 13.0, 'fat_g': 7.0, 'carbs_g': 68.0},
    ),
    (
        'Fruit Muesli',
        'Harvest Row',
        '2000000000459',
        'dry_products',
        UOM_PIECE,
        400,
        Decimal('8.90'),
        {'calories_kcal': 398, 'protein_g': 9.0, 'fat_g': 9.0, 'carbs_g': 67.0},
    ),
    (
        'Corn Flakes',
        'Harvest Row',
        '2000000000466',
        'dry_products',
        UOM_PIECE,
        375,
        Decimal('11.90'),
        {'calories_kcal': 361, 'protein_g': 6.0, 'fat_g': 1.0, 'carbs_g': 84.0},
    ),
    (
        'Wheat Flour Type 550',
        'Harvest Row',
        '2000000000473',
        'flours_sugars',
        UOM_PIECE,
        1000,
        Decimal('3.90'),
        {'calories_kcal': 341, 'protein_g': 10.0, 'fat_g': 1.0, 'carbs_g': 72.0},
    ),
    (
        'White Sugar 1kg',
        'Harvest Row',
        '2000000000480',
        'flours_sugars',
        UOM_PIECE,
        1000,
        Decimal('4.50'),
        {'calories_kcal': 387, 'protein_g': 0.0, 'fat_g': 0.0, 'carbs_g': 100.0},
    ),
    (
        'Iodised Salt',
        'Saltmill',
        '2000000000497',
        'spices_herbs',
        UOM_PIECE,
        1000,
        Decimal('2.50'),
        None,
    ),
    (
        'Ground Black Pepper',
        'Saltmill',
        '2000000000503',
        'spices_herbs',
        UOM_PIECE,
        40,
        Decimal('5.90'),
        None,
    ),
    (
        'Dried Oregano',
        'Saltmill',
        '2000000000510',
        'spices_herbs',
        UOM_PIECE,
        15,
        Decimal('4.50'),
        None,
    ),
    (
        'Dried Basil',
        'Saltmill',
        '2000000000527',
        'spices_herbs',
        UOM_PIECE,
        10,
        Decimal('3.90'),
        None,
    ),
    (
        'Granulated Garlic',
        'Saltmill',
        '2000000000534',
        'spices_herbs',
        UOM_PIECE,
        25,
        Decimal('4.20'),
        None,
    ),
    (
        'Extra Virgin Olive Oil',
        'Harvest Row',
        '2000000000541',
        'oils_vinegars',
        UOM_PIECE,
        750,
        Decimal('24.90'),
        {'calories_kcal': 884, 'protein_g': 0.0, 'fat_g': 100.0, 'carbs_g': 0.0},
    ),
    (
        'Sunflower Oil',
        'Harvest Row',
        '2000000000558',
        'oils_vinegars',
        UOM_PIECE,
        1000,
        Decimal('9.90'),
        {'calories_kcal': 884, 'protein_g': 0.0, 'fat_g': 100.0, 'carbs_g': 0.0},
    ),
    (
        'Tomato Passata',
        'Harvest Row',
        '2000000000565',
        'cans_jars',
        UOM_PIECE,
        700,
        Decimal('7.90'),
        {'calories_kcal': 32, 'protein_g': 1.5, 'fat_g': 0.2, 'carbs_g': 5.5},
    ),
    (
        'Peeled Tomatoes 400g',
        'Harvest Row',
        '2000000000572',
        'cans_jars',
        UOM_PIECE,
        400,
        Decimal('6.50'),
        {'calories_kcal': 26, 'protein_g': 1.2, 'fat_g': 0.2, 'carbs_g': 4.0},
    ),
    (
        'Canned Chickpeas',
        'Harvest Row',
        '2000000000589',
        'canned_goods',
        UOM_PIECE,
        400,
        Decimal('4.90'),
        {'calories_kcal': 164, 'protein_g': 9.0, 'fat_g': 2.6, 'carbs_g': 27.0},
    ),
    (
        'Canned White Beans',
        'Harvest Row',
        '2000000000596',
        'canned_goods',
        UOM_PIECE,
        400,
        Decimal('4.50'),
        {'calories_kcal': 139, 'protein_g': 9.0, 'fat_g': 0.5, 'carbs_g': 25.0},
    ),
    (
        'Canned Sweetcorn',
        'Harvest Row',
        '2000000000602',
        'canned_goods',
        UOM_PIECE,
        340,
        Decimal('3.90'),
        {'calories_kcal': 96, 'protein_g': 3.0, 'fat_g': 1.5, 'carbs_g': 19.0},
    ),
    (
        'Tuna in Oil',
        'Bluewater',
        '2000000000619',
        'canned_goods',
        UOM_PIECE,
        160,
        Decimal('8.50'),
        {'calories_kcal': 198, 'protein_g': 26.0, 'fat_g': 9.0, 'carbs_g': 0.0},
    ),
    (
        'Chicken Stock',
        'Harvest Row',
        '2000000000626',
        'dry_products',
        UOM_PIECE,
        120,
        Decimal('3.90'),
        None,
    ),
    (
        'Earl Grey Tea',
        'Orchard & Oak',
        '2000000000633',
        'tea_coffee',
        UOM_PIECE,
        50,
        Decimal('8.90'),
        None,
    ),
    (
        'Ground Coffee',
        'Orchard & Oak',
        '2000000000640',
        'tea_coffee',
        UOM_PIECE,
        250,
        Decimal('19.90'),
        None,
    ),
    (
        'Coffee Beans',
        'Orchard & Oak',
        '2000000000657',
        'tea_coffee',
        UOM_PIECE,
        1000,
        Decimal('39.90'),
        None,
    ),
    (
        'Strawberry Jam',
        'Orchard & Oak',
        '2000000000664',
        'sweets',
        UOM_PIECE,
        350,
        Decimal('6.50'),
        {'calories_kcal': 264, 'protein_g': 0.5, 'fat_g': 0.1, 'carbs_g': 65.0},
    ),
    (
        'Peanut Butter',
        'Orchard & Oak',
        '2000000000671',
        'sweets',
        UOM_PIECE,
        250,
        Decimal('12.90'),
        {'calories_kcal': 588, 'protein_g': 25.0, 'fat_g': 50.0, 'carbs_g': 20.0},
    ),
    (
        'Dark Chocolate 85%',
        'Orchard & Oak',
        '2000000000688',
        'sweets',
        UOM_PIECE,
        100,
        Decimal('9.90'),
        {'calories_kcal': 598, 'protein_g': 8.0, 'fat_g': 44.0, 'carbs_g': 39.0},
    ),
    (
        'Salted Potato Crisps',
        'Orchard & Oak',
        '2000000000695',
        'snacks',
        UOM_PIECE,
        165,
        Decimal('7.90'),
        {'calories_kcal': 536, 'protein_g': 4.0, 'fat_g': 35.0, 'carbs_g': 53.0},
    ),
    (
        'Rice Cakes',
        'Harvest Row',
        '2000000000701',
        'snacks',
        UOM_PACK,
        120,
        Decimal('4.50'),
        {'calories_kcal': 387, 'protein_g': 7.0, 'fat_g': 2.0, 'carbs_g': 82.0},
    ),
    (
        'Butter Biscuits',
        'Orchard & Oak',
        '2000000000718',
        'snacks',
        UOM_PACK,
        200,
        Decimal('5.90'),
        {'calories_kcal': 454, 'protein_g': 6.0, 'fat_g': 17.0, 'carbs_g': 71.0},
    ),
    (
        'Soy Sauce',
        'Harvest Row',
        '2000000000725',
        'oils_vinegars',
        UOM_PIECE,
        250,
        Decimal('11.50'),
        {'calories_kcal': 53, 'protein_g': 8.0, 'fat_g': 0.0, 'carbs_g': 5.0},
    ),
    (
        'Tomato Paste',
        'Harvest Row',
        '2000000000732',
        'cans_jars',
        UOM_PIECE,
        170,
        Decimal('3.20'),
        {'calories_kcal': 55, 'protein_g': 3.0, 'fat_g': 0.3, 'carbs_g': 9.0},
    ),
    (
        'Potato Starch',
        'Harvest Row',
        '2000000000749',
        'flours_sugars',
        UOM_PIECE,
        500,
        Decimal('3.20'),
        {'calories_kcal': 341, 'protein_g': 0.5, 'fat_g': 0.0, 'carbs_g': 85.0},
    ),
    (
        'Baking Powder',
        'Harvest Row',
        '2000000000756',
        'dry_products',
        UOM_PIECE,
        50,
        Decimal('2.90'),
        None,
    ),
    (
        'Dry Yeast',
        'Harvest Row',
        '2000000000763',
        'dry_products',
        UOM_PACK,
        14,
        Decimal('3.50'),
        None,
    ),
    (
        'Vanilla Sugar',
        'Harvest Row',
        '2000000000770',
        'flours_sugars',
        UOM_PACK,
        32,
        Decimal('3.20'),
        None,
    ),
    (
        'Ground Cinnamon',
        'Saltmill',
        '2000000000787',
        'spices_herbs',
        UOM_PIECE,
        20,
        Decimal('4.80'),
        None,
    ),
    (
        'Sweet Paprika',
        'Saltmill',
        '2000000000794',
        'spices_herbs',
        UOM_PIECE,
        30,
        Decimal('3.90'),
        None,
    ),
    (
        'Curry Powder',
        'Saltmill',
        '2000000000800',
        'spices_herbs',
        UOM_PIECE,
        25,
        Decimal('4.50'),
        None,
    ),
    (
        'Ground Ginger',
        'Saltmill',
        '2000000000817',
        'spices_herbs',
        UOM_PIECE,
        20,
        Decimal('5.20'),
        None,
    ),
    (
        'Wildflower Honey',
        'Orchard & Oak',
        '2000000000824',
        'sweets',
        UOM_PIECE,
        1000,
        Decimal('19.90'),
        {'calories_kcal': 304, 'protein_g': 0.3, 'fat_g': 0.0, 'carbs_g': 82.0},
    ),
    (
        'Walnuts',
        'Green Acre',
        '2000000000831',
        'snacks',
        UOM_PACK,
        200,
        Decimal('12.90'),
        {'calories_kcal': 654, 'protein_g': 15.0, 'fat_g': 65.0, 'carbs_g': 14.0},
    ),
    (
        'Almonds',
        'Green Acre',
        '2000000000848',
        'snacks',
        UOM_PACK,
        200,
        Decimal('18.90'),
        {'calories_kcal': 579, 'protein_g': 21.0, 'fat_g': 50.0, 'carbs_g': 22.0},
    ),
    (
        'Instant Tomato Soup',
        'Harvest Row',
        '2000000000855',
        'dry_products',
        UOM_PACK,
        85,
        Decimal('2.90'),
        None,
    ),
    (
        'Cocoa Powder',
        'Orchard & Oak',
        '2000000000862',
        'dry_products',
        UOM_PIECE,
        100,
        Decimal('6.90'),
        {'calories_kcal': 348, 'protein_g': 24.0, 'fat_g': 15.0, 'carbs_g': 36.0},
    ),
]

EQUIPMENT_TEMPLATES = [
    (
        'Dell Latitude 5540',
        'Dell',
        '5397184123456',
        'laptop',
        UOM_PIECE,
        Decimal('4200.00'),
        {'cpu': 'Intel i5-1345U', 'ram': '16GB', 'storage': '512GB SSD'},
    ),
    (
        'ThinkPad T14s Gen 4',
        'Lenovo',
        '0196881123456',
        'laptop',
        UOM_PIECE,
        Decimal('5800.00'),
        {'cpu': 'AMD Ryzen 7 PRO', 'ram': '32GB', 'storage': '1TB SSD'},
    ),
    (
        'MacBook Pro 14 M3',
        'Apple',
        '0194252123456',
        'laptop',
        UOM_PIECE,
        Decimal('9500.00'),
        {'cpu': 'Apple M3 Pro', 'ram': '18GB', 'storage': '512GB SSD'},
    ),
    (
        'HP EliteBook 840 G10',
        'HP',
        '0196882123456',
        'laptop',
        UOM_PIECE,
        Decimal('4600.00'),
        {'cpu': 'Intel i7-1365U', 'ram': '16GB', 'storage': '512GB SSD'},
    ),
    (
        'Dell OptiPlex 7010',
        'Dell',
        '5397184234567',
        'desktop',
        UOM_PIECE,
        Decimal('3200.00'),
        {'cpu': 'Intel i5-13500', 'ram': '16GB', 'storage': '512GB SSD'},
    ),
    (
        'HP ProDesk 400 G9',
        'HP',
        '0196883234567',
        'desktop',
        UOM_PIECE,
        Decimal('2800.00'),
        {'cpu': 'Intel i5-12500', 'ram': '8GB', 'storage': '256GB SSD'},
    ),
    (
        'Lenovo ThinkCentre M90q',
        'Lenovo',
        '0196884234567',
        'desktop',
        UOM_PIECE,
        Decimal('3600.00'),
        {'cpu': 'Intel i7-13700', 'ram': '16GB', 'storage': '1TB SSD'},
    ),
    (
        'Dell UltraSharp U2723QE',
        'Dell',
        '5397184345678',
        'monitor',
        UOM_PIECE,
        Decimal('2100.00'),
        {'size': '27"', 'resolution': '3840x2160', 'panel': 'IPS'},
    ),
    (
        'LG 27UK850-W',
        'LG',
        '8806097345678',
        'monitor',
        UOM_PIECE,
        Decimal('1600.00'),
        {'size': '27"', 'resolution': '3840x2160', 'panel': 'IPS'},
    ),
    (
        'Samsung Odyssey G5',
        'Samsung',
        '8806098345678',
        'monitor',
        UOM_PIECE,
        Decimal('1400.00'),
        {'size': '32"', 'resolution': '2560x1440', 'panel': 'VA'},
    ),
    (
        'iPhone 15 Pro',
        'Apple',
        '0194253456789',
        'phone',
        UOM_PIECE,
        Decimal('5200.00'),
        {'storage': '256GB', 'color': 'Natural Titanium'},
    ),
    (
        'Samsung Galaxy S24',
        'Samsung',
        '8806099456789',
        'phone',
        UOM_PIECE,
        Decimal('3800.00'),
        {'storage': '128GB', 'color': 'Phantom Black'},
    ),
    (
        'iPad Air M2',
        'Apple',
        '0194254456789',
        'phone',
        UOM_PIECE,
        Decimal('3400.00'),
        {'storage': '128GB', 'color': 'Space Gray'},
    ),
    (
        'Cisco Catalyst 9200L',
        'Cisco',
        '0882658567890',
        'network_device',
        UOM_PIECE,
        Decimal('8500.00'),
        {'ports': '24x 1GbE', 'management': 'DNA Center'},
    ),
    (
        'Ubiquiti UniFi USW-Pro-48',
        'Ubiquiti',
        '8100014567890',
        'network_device',
        UOM_PIECE,
        Decimal('3200.00'),
        {'ports': '48x 1GbE + 4x 10GbE'},
    ),
    (
        'TP-Link TL-SG3428',
        'TP-Link',
        '6935364567890',
        'network_device',
        UOM_PIECE,
        Decimal('950.00'),
        {'ports': '24x 1GbE + 4x SFP'},
    ),
    (
        'Cisco Meraki MR46',
        'Cisco',
        '0882659567890',
        'network_device',
        UOM_PIECE,
        Decimal('2800.00'),
        {'standard': 'Wi-Fi 6', 'speed': 'AX5400'},
    ),
    (
        'Logitech MX Keys S',
        'Logitech',
        '0978551678901',
        'peripheral',
        UOM_PIECE,
        Decimal('450.00'),
        {'type': 'Mechanical', 'layout': 'US'},
    ),
    (
        'Logitech MX Master 3S',
        'Logitech',
        '0978552678901',
        'peripheral',
        UOM_PIECE,
        Decimal('400.00'),
        {'dpi': 8000, 'buttons': 7},
    ),
    (
        'Logitech C920 HD Pro',
        'Logitech',
        '0978553678901',
        'peripheral',
        UOM_PIECE,
        Decimal('350.00'),
        {'resolution': '1080p', 'fps': 30},
    ),
    (
        'Jabra Evolve2 65',
        'Jabra',
        '5707054678901',
        'peripheral',
        UOM_PIECE,
        Decimal('650.00'),
        {'type': 'Headset', 'connection': 'Bluetooth'},
    ),
    (
        'Dell PowerEdge R750',
        'Dell',
        '5397185678901',
        'server',
        UOM_PIECE,
        Decimal('28000.00'),
        {'cpu': 'Intel Xeon Silver 4314', 'ram': '64GB', 'storage': '2x 480GB SSD'},
    ),
    (
        'HPE ProLiant DL380 Gen10',
        'HPE',
        '8881825678901',
        'server',
        UOM_PIECE,
        Decimal('32000.00'),
        {'cpu': 'Intel Xeon Gold 5318Y', 'ram': '128GB', 'storage': '4x 960GB SSD'},
    ),
    (
        'Supermicro SYS-1029U',
        'Supermicro',
        '1234565678901',
        'server',
        UOM_PIECE,
        Decimal('18000.00'),
        {'cpu': 'Intel Xeon Silver 4214', 'ram': '96GB', 'storage': '2x 1TB SSD'},
    ),
    (
        'APC Smart-UPS 3000VA',
        'APC',
        '0731303678901',
        'other_equipment',
        UOM_PIECE,
        Decimal('4200.00'),
        {'capacity': '3000VA/2700W', 'runtime': '~15min at full load'},
    ),
    (
        'Rack 42U Open Frame',
        'Rittal',
        '4017304678901',
        'other_equipment',
        UOM_PIECE,
        Decimal('2800.00'),
        {'size': '42U', 'width': '19 inch'},
    ),
]

# Every party the demo trades with — suppliers to receive from,
# manufacturers behind the equipment, customers to dispatch to.
DEMO_PARTNERS = [
    # Contact details use the domains and number ranges reserved for
    # documentation (RFC 2606, Ofcom drama range), so nothing here can reach a
    # real mailbox or a real telephone if the demo instance is ever public.
    (
        'Eurodata Systems',
        'SUPPLIER',
        'SUP-001',
        'orders@eurodata.example.com',
        '+44 20 7946 0101',
    ),
    (
        'Northgate IT Distribution',
        'SUPPLIER',
        'ITD-002',
        'sales@northgate-it.example.com',
        '+44 20 7946 0102',
    ),
    (
        'TechSupply Europe',
        'SUPPLIER',
        'TSE-003',
        'orders@techsupply.example.net',
        '+44 20 7946 0103',
    ),
    (
        'Freshfield Wholesale',
        'SUPPLIER',
        'FFD-004',
        'orders@freshfield.example.com',
        '+44 20 7946 0104',
    ),
    (
        'Bulkline Cash & Carry',
        'SUPPLIER',
        'MCC-005',
        'b2b@bulkline.example.com',
        '+44 20 7946 0105',
    ),
    (
        'Cornerstore Deliveries',
        'SUPPLIER',
        'ZAB-006',
        'deliveries@cornerstore.example.com',
        '+44 20 7946 0106',
    ),
    # The manufacturers are the firms that really make the seeded hardware, so
    # naming them is descriptive rather than a fabricated business
    # relationship — unlike a supplier or a customer, which is a claim about
    # who trades with this organization and is therefore invented here.
    (
        'Cisco Systems',
        'MANUFACTURER',
        'CSC-007',
        'enterprise@cisco.example.com',
        '+44 20 7946 0107',
    ),
    (
        'Dell Technologies',
        'MANUFACTURER',
        'DLL-008',
        'enterprise@dell.example.com',
        '+44 20 7946 0108',
    ),
    (
        'Hewlett Packard Enterprise',
        'MANUFACTURER',
        'HPE-009',
        'sales@hpe.example.com',
        '+44 20 7946 0109',
    ),
    (
        'Apple',
        'MANUFACTURER',
        'APL-010',
        'business@apple.example.com',
        '+44 20 7946 0110',
    ),
    # Somebody to dispatch to. Without a CUSTOMER the seeded catalogue can
    # receive goods and never send any: the partner picker on a delivery
    # document comes up empty, and the whole outbound half of the app is
    # unreachable from a fresh install.
    (
        'Harper Catering',
        'CUSTOMER',
        'CUS-011',
        'orders@harpercatering.example.com',
        '+44 20 7946 0111',
    ),
    (
        'Officeworks Services',
        'CUSTOMER',
        'CUS-012',
        'office@officeworks.example.net',
        '+44 20 7946 0112',
    ),
]


# ---------------------------------------------------------------------------
# Hierarchy definition
# ---------------------------------------------------------------------------
FOOD_HIERARCHY = [
    (
        'Main Warehouse',
        None,
        'STORAGE_ROOM',
        None,
        {
            'Cold Storage': (
                'FRIDGE',
                'EXPIRY',
                'food',
                [
                    ('Fridge A', ['Fridge A - Top Shelf', 'Fridge A - Door']),
                    'Fridge B',
                    'Fridge C',
                    'Walk-in Cooler',
                ],
            ),
            'Freezer Zone': (
                'FREEZER',
                'FREEZING',
                'food',
                [
                    'Freezer 1',
                    'Freezer 2',
                    'Chest Freezer',
                ],
            ),
        },
    ),
    (
        'Pantry Building',
        None,
        'STORAGE_ROOM',
        None,
        {
            'Dry Goods': (
                'PANTRY',
                'EXPIRY',
                'food',
                [
                    'Shelf A - Top',
                    'Shelf A - Middle',
                    'Shelf A - Bottom',
                    'Shelf B - Top',
                    'Shelf B - Middle',
                    'Shelf B - Bottom',
                ],
            ),
            'Beverages': (
                'PANTRY',
                'STOCK',
                'food',
                [
                    'Beverage Rack 1',
                    'Beverage Rack 2',
                ],
            ),
        },
    ),
]

EQUIPMENT_HIERARCHY = [
    (
        'Office Building',
        None,
        'STORAGE_ROOM',
        'equipment',
        {
            'Server Room': (
                'SERVER_ROOM',
                'STOCK',
                'equipment',
                [
                    'Server Rack A',
                    'Server Rack B',
                    'UPS Bay',
                    'Patch Panel',
                ],
            ),
            'IT Workshop': (
                'IT_STORAGE',
                'STOCK',
                'equipment',
                [
                    'Workshop Shelf 1',
                    'Workshop Shelf 2',
                    'Spare Parts Bin',
                ],
            ),
            'Workstations': (
                'IT_STORAGE',
                'STOCK',
                'equipment',
                [
                    'Floor 1 - Row A',
                    'Floor 1 - Row B',
                    'Floor 2 - Row A',
                    'Floor 2 - Row B',
                ],
            ),
        },
    ),
]


def _resolve_uom_ids(db):
    """Map UoM symbols to live IDs — the base seed owns the real UUIDs."""
    from app.models.uom import Uom

    symbols = {UOM_PIECE, UOM_GRAM, UOM_KG, UOM_LITER, UOM_ML, UOM_PACK}
    # The system units only: a visitor of the public demo may define a unit
    # of their own under the same symbol, and it is theirs, not the seed's.
    found = dict(
        db.query(Uom.symbol, Uom.id)
        .filter(Uom.symbol.in_(symbols), Uom.organization_id.is_(None))
        .all()
    )
    missing = symbols - found.keys()
    if missing:
        raise RuntimeError(f'UoMs not found: {sorted(missing)} — run base seed first')
    return found


# Storage types the demo hierarchy needs but no seed profile provides.
# Definitions mirror the pre-profile demo environment.
DEMO_STORAGE_TYPES = [
    (
        'SERVER_ROOM',
        'Server Room',
        'NONE',
        ['serial_number', 'manufacturer', 'model', 'ip_address', 'equipment_status'],
        'server',
    ),
    (
        'IT_STORAGE',
        'IT Storage / Warehouse',
        'NONE',
        ['serial_number', 'manufacturer', 'model', 'equipment_status'],
        'warehouse',
    ),
]


def _ensure_storage_types(db, org_id):
    """Create demo-only storage types if missing; return {type_code: id}.

    Read inside the organization (and the global types beside it): every
    organization has a SHELF of its own, and a map read across the instance
    resolved a shared code to whichever row came back last — on the public
    demo, where each visitor has an organization, another visitor's.
    """
    from sqlalchemy import or_

    from app.models.storage_type import StorageType

    visible = or_(
        StorageType.organization_id == org_id, StorageType.organization_id.is_(None)
    )
    for code, name, behavior, context_schema, icon in DEMO_STORAGE_TYPES:
        existing = (
            db.query(StorageType.id)
            .filter(StorageType.type_code == code, visible)
            .first()
        )
        if existing:
            continue
        db.add(
            StorageType(
                id=uuid.uuid4(),
                organization_id=org_id,
                name=name,
                type_code=code,
                behavior_mode=behavior,
                context_schema=context_schema,
                field_definitions=[],
                icon=icon,
                is_system=True,
            )
        )
    db.flush()
    # The organization's own type wins over a global one with the same code.
    rows = db.query(StorageType.type_code, StorageType.id, StorageType.organization_id)
    found = {}
    for code, type_id, owner in rows.filter(visible).all():
        if owner is not None or code not in found:
            found[code] = type_id
    return found


class SeedCategoriesMissingError(RuntimeError):
    """The shelf a template was going to be filed on does not exist.

    Raised instead of filing the record under ``None``: an item with no
    category and no module namespace is a record neither list owns, and the
    seeder used to produce 71 of them without a word.
    """


#: The tag the equipment module files its catalogue under. Everything else
#: is the food catalogue's, tagged or not: the food profile tags its
#: categories by storage context (``cold_storage``, ``dry_goods``), and only
#: one seeded category — the fallback "other" — has no tag at all. Asking for
#: an untagged category, as this seeder used to, therefore found exactly that
#: one and refused the other twenty-seven.
_EQUIPMENT_CATALOGUE_TAG = 'equipment'


def _resolve_category_ids(db, org_id, *, catalogue='food'):
    """Map category codes (lowercased) to live IDs, for one organization.

    Reads the organization's own categories as well as the global ones —
    module categories became per-organization rows in ``modcat01``, so a
    lookup over global rows alone came back empty on an installation that
    has no global catalogue at all. Where a code exists in both, the
    organization's row wins: it is the one every other write path uses.

    ``catalogue`` says which of the two to read. They share codes ('other'),
    so which catalogue a row belongs to has to be part of the question rather
    than a property checked afterwards. The equipment one is the tagged side;
    the food one is everything that is not equipment's.
    """
    from app.models.category import Category

    if catalogue == 'equipment':
        catalogue_filter = Category.context_tag == _EQUIPMENT_CATALOGUE_TAG
    else:
        catalogue_filter = or_(
            Category.context_tag.is_(None),
            Category.context_tag != _EQUIPMENT_CATALOGUE_TAG,
        )

    rows = (
        db.query(Category.code, Category.id, Category.organization_id)
        .filter(
            or_(
                Category.organization_id == org_id,
                Category.organization_id.is_(None),
            ),
            Category.code.isnot(None),
            catalogue_filter,
        )
        .all()
    )
    resolved: dict[str, uuid.UUID] = {}
    for code, cat_id, owner_id in rows:
        key = code.lower()
        if key not in resolved or owner_id is not None:
            resolved[key] = cat_id
    return resolved


def _ensure_module_catalogues(org_id):
    """Give the organization the start data the modules declare for it.

    The seed profiles cover what a *profile* owns — storage types and the food
    categories. The equipment catalogue (LAPTOP, SERVER, MONITOR, …) is owned
    by the equipment module instead: it is declared in the module's metadata
    and copied per organization by ``system_on_enable``, which runs when the
    module is enabled. On a fresh installation that happens during the
    onboarding walkthrough — a walkthrough nobody has been through when
    ``make dev-up && make db-seed-demo`` runs, which left this seeder asking
    for eight categories that had never been created.

    Only the system hook runs (``run_custom_hook=False``), the same half
    onboarding runs: it copies the declared catalogue and grants the module's
    default permissions, and does not go on to a module's own on-enable work.
    """
    import asyncio

    from app.core.module_registry import module_registry
    from app.services.module_lifecycle_service import enable_modules_async

    module_registry.discover_modules()
    modules = [m for m in (module_registry.get('equipment'),) if m is not None]
    if not modules:
        print('  No equipment module registered — skipping its catalogue.')
        return

    async def _seed():
        # The factory is a module global that ``init_async_engine`` assigns,
        # so it has to be read off the module after the call, not imported by
        # name before it — a plain script has had no lifespan startup.
        from app import database

        database.init_async_engine()
        async with database.AsyncSessionLocal() as adb:
            await enable_modules_async(
                modules, str(org_id), db=adb, run_custom_hook=False
            )
            await adb.commit()

    asyncio.run(_seed())
    print(f'  Module catalogues: {", ".join(m.metadata.name for m in modules)}')


def _require_categories(cat_ids, codes, *, what):
    """Every code the templates use has to name a live category.

    ``cat_ids.get(code)`` returning ``None`` is the failure this seeder is
    least able to notice and the user is least able to explain, so it stops
    the run instead.
    """
    missing = sorted({code for code in codes if not cat_ids.get(code)})
    if missing:
        raise SeedCategoriesMissingError(
            f'{what}: no category for {", ".join(missing)} in this '
            "organization's catalogue. This run has already applied the seed "
            "profiles and the modules' declared categories, so these codes "
            'are not declared anywhere — check the profile and the module '
            'metadata that are supposed to declare them, not the order of '
            'the setup commands.'
        )


def _create_hierarchy(db, org_id, created_by, hierarchy_def, type_ids):
    # Names belong to their parent: a root someone already named Cold Storage
    # is not the demo zone of the same name beneath Main Warehouse.
    existing = {
        (row[0], row[1]): row[2]
        for row in db.query(
            StorageLocation.name, StorageLocation.parent_id, StorageLocation.id
        )
        .filter(
            StorageLocation.organization_id == org_id,
        )
        .all()
    }
    locations = {}
    for site_name, _, site_type, site_tag, zones in hierarchy_def:
        if (site_name, None) in existing:
            site = db.get(StorageLocation, existing[site_name, None])
        else:
            site = StorageLocation(
                id=uuid.uuid4(),
                organization_id=org_id,
                name=site_name,
                storage_type_id=type_ids.get(site_type),
                usage=LocationUsage.INTERNAL,
                short_code=_short_code(db, org_id),
                context_tag=site_tag,
                created_by=created_by,
            )
            db.add(site)
            db.flush()
        locations[site_name] = site

        for zone_name, (zone_type, behavior, zone_tag, leaf_names) in zones.items():
            if (zone_name, site.id) in existing:
                zone = db.get(StorageLocation, existing[zone_name, site.id])
            else:
                zone = StorageLocation(
                    id=uuid.uuid4(),
                    organization_id=org_id,
                    parent_id=site.id,
                    name=zone_name,
                    storage_type_id=type_ids.get(zone_type),
                    behavior_mode=behavior,
                    usage=LocationUsage.INTERNAL,
                    short_code=_short_code(db, org_id),
                    context_tag=zone_tag,
                    created_by=created_by,
                )
                db.add(zone)
                db.flush()
            locations[f'{site_name}/{zone_name}'] = zone

            for leaf_entry in leaf_names:
                # A leaf may carry children of its own: the tree has no floor
                # (ADR-018), and the demo data says so rather than stopping at
                # the depth the old three levels allowed.
                leaf_name, children = (
                    leaf_entry if isinstance(leaf_entry, tuple) else (leaf_entry, ())
                )
                leaf = _get_or_create(
                    db,
                    existing,
                    org_id=org_id,
                    created_by=created_by,
                    name=leaf_name,
                    parent_id=zone.id,
                    storage_type_id=type_ids.get(zone_type),
                    behavior=behavior,
                    context_tag=zone_tag,
                )
                path = f'{site_name}/{zone_name}/{leaf_name}'
                locations[path] = leaf
                for child_name in children:
                    child = _get_or_create(
                        db,
                        existing,
                        org_id=org_id,
                        created_by=created_by,
                        name=child_name,
                        parent_id=leaf.id,
                        storage_type_id=type_ids.get(zone_type),
                        behavior=behavior,
                        context_tag=zone_tag,
                    )
                    locations[f'{path}/{child_name}'] = child

    return locations


def _get_or_create(
    db,
    existing,
    *,
    org_id,
    created_by,
    name,
    parent_id,
    storage_type_id,
    behavior,
    context_tag,
):
    """Return the location called *name*, creating it under *parent_id* if new."""
    if (name, parent_id) in existing:
        return db.get(StorageLocation, existing[name, parent_id])
    node = StorageLocation(
        id=uuid.uuid4(),
        organization_id=org_id,
        parent_id=parent_id,
        name=name,
        storage_type_id=storage_type_id,
        behavior_mode=behavior,
        usage=LocationUsage.INTERNAL,
        short_code=_short_code(db, org_id),
        context_tag=context_tag,
        created_by=created_by,
    )
    db.add(node)
    db.flush()
    return node


def _create_food_templates(db, org_id, uom_ids):
    existing_barcodes = {
        row[0]
        for row in db.query(ProductTemplate.barcode)
        .filter(
            ProductTemplate.organization_id == org_id,
            ProductTemplate.barcode.isnot(None),
        )
        .all()
    }
    templates = []
    for name, brand, barcode, cat_key, uom, weight, _price, nutrition in FOOD_TEMPLATES:
        bc = barcode or _seeded_barcode(name, existing_barcodes)
        if bc in existing_barcodes:
            t = (
                db.query(ProductTemplate)
                .filter(
                    ProductTemplate.organization_id == org_id,
                    ProductTemplate.barcode == bc,
                )
                .first()
            )
            if t:
                templates.append((t, cat_key))
            continue
        # Every code handed out joins the draw: a generated one must not land
        # on a fixed one a later row still needs.
        existing_barcodes.add(bc)
        t = ProductTemplate(
            id=uuid.uuid4(),
            organization_id=org_id,
            name=name,
            brand=brand,
            barcode=bc,
            uom_id=uom_ids.get(uom),
            weight_value=float(weight),
            weight_uom_id=uom_ids.get(UOM_GRAM),
            meta_data={'nutrition': nutrition} if nutrition else None,
        )
        db.add(t)
        templates.append((t, cat_key))
    db.flush()
    return templates


def _create_equipment_templates(db, org_id, uom_ids):
    existing_barcodes = {
        row[0]
        for row in db.query(ProductTemplate.barcode)
        .filter(
            ProductTemplate.organization_id == org_id,
            ProductTemplate.barcode.isnot(None),
        )
        .all()
    }
    templates = []
    for name, brand, barcode, cat_key, uom, _price, specs in EQUIPMENT_TEMPLATES:
        bc = barcode or _seeded_barcode(name, existing_barcodes)
        if bc in existing_barcodes:
            t = (
                db.query(ProductTemplate)
                .filter(
                    ProductTemplate.organization_id == org_id,
                    ProductTemplate.barcode == bc,
                )
                .first()
            )
            if t:
                templates.append((t, cat_key))
            continue
        # Every code handed out joins the draw: a generated one must not land
        # on a fixed one a later row still needs.
        existing_barcodes.add(bc)
        t = ProductTemplate(
            id=uuid.uuid4(),
            organization_id=org_id,
            name=name,
            brand=brand,
            barcode=bc,
            uom_id=uom_ids.get(uom),
            meta_data={'equipment': specs} if specs else None,
        )
        db.add(t)
        templates.append((t, cat_key))
    db.flush()
    return templates


def _create_partners(db, org_id, created_by):
    existing_codes = {
        row[0]
        for row in db.query(Partner.code)
        .filter(
            Partner.organization_id == org_id,
            Partner.code.isnot(None),
        )
        .all()
    }
    partners = []
    for name, ptype, code, email, phone in DEMO_PARTNERS:
        if code in existing_codes:
            continue
        p = Partner(
            id=uuid.uuid4(),
            organization_id=org_id,
            name=name,
            code=code,
            type=ptype,
            email=email,
            phone=phone,
            created_by=created_by,
        )
        db.add(p)
        partners.append(p)
    db.flush()
    return partners


def _get_food_leaf_locations(locations):
    leaf_locs = []
    for _key, loc in locations.items():
        if loc.parent_id is not None and loc.context_tag == 'food':
            parent = None
            for _k2, l2 in locations.items():
                if l2.id == loc.parent_id:
                    parent = l2
                    break
            if parent and parent.parent_id is not None:
                leaf_locs.append(loc)
    return leaf_locs


def _get_equip_leaf_locations(locations):
    leaf_locs = []
    for _key, loc in locations.items():
        if loc.parent_id is not None and loc.context_tag == 'equipment':
            parent = None
            for _k2, l2 in locations.items():
                if l2.id == loc.parent_id:
                    parent = l2
                    break
            if parent and parent.parent_id is not None:
                leaf_locs.append(loc)
    return leaf_locs


def _uom_rounding_map(db) -> dict:
    """UoM id -> rounding, so seeded quantities honour the precision the API enforces."""
    from app.models.uom import Uom

    return dict(db.query(Uom.id, Uom.rounding).all())


def _anchor_records(db, org_id, records) -> None:
    """Give every group the seeded records stand in its anchor, before they are written.

    A record with a card names its group's anchor by a foreign key, and in
    the application the anchor comes from the lock a write takes first
    (``core_api.stock.lock_async``). The seeder writes records in bulk in a
    session of its own, on an organization nobody else is writing to, so it
    creates the anchors directly — the same insert the lock makes. The
    records' stock is opened later through the core movement call, which
    locks those anchors the way every write does.
    """
    from sqlalchemy.dialects.postgresql import insert

    from app.models.stock_anchor import StockAnchor

    groups = sorted({(r.template_id, r.storage_location_id) for r in records}, key=str)
    if not groups:
        return
    db.execute(
        insert(StockAnchor)
        .values(
            [
                {
                    'organization_id': org_id,
                    'product_template_id': template_id,
                    'storage_location_id': location_id,
                }
                for template_id, location_id in groups
            ]
        )
        .on_conflict_do_nothing(
            index_elements=[
                'organization_id',
                'product_template_id',
                'storage_location_id',
            ]
        )
    )


def _random_quantity(rounding: float | None) -> Decimal:
    """Random stock quantity valid for the UoM.

    A unit that rounds to 1 (pieces, packs, cans) only ever holds whole numbers --
    seeding 2.2 pcs produced demo data the API itself would reject.
    """
    if rounding is not None and rounding >= 1:
        return Decimal(random.randint(1, 10))
    return Decimal(str(round(random.uniform(1, 10), 1)))


#: Which zone of the food hierarchy a category is kept in. Items used to land
#: on a random shelf, so the overview — whose whole point is saying where a
#: thing is — told the reader that the chicken breast sat on a dry-goods shelf
#: and the cinnamon in a fridge door. Categories not listed go to Dry Goods.
FOOD_ZONE_BY_CATEGORY = {
    **dict.fromkeys(
        (
            'dairy',
            'cheese',
            'eggs',
            'deli',
            'pork',
            'poultry',
            'fish',
            'sauces',
            'fresh_vegetables',
            'fresh_fruits',
        ),
        'Cold Storage',
    ),
    **dict.fromkeys(
        (
            'ice_cream',
            'frozen_pizza',
            'frozen_meals',
            'frozen_vegetables',
            'frozen_fruits',
        ),
        'Freezer Zone',
    ),
    'drinks': 'Beverages',
}


def _food_leaves_by_zone(locations, leaf_locs) -> dict[str, list]:
    """Group food leaves under the zone they belong to (Cold Storage, ...).

    A zone is the second level of the hierarchy — the child of a building —
    however deep the leaf sits below it (``Fridge A - Door`` is Cold Storage).
    """
    by_id = {loc.id: loc for loc in locations.values()}
    zones: dict[str, list] = {}
    for leaf in leaf_locs:
        node = leaf
        while (
            node.parent_id is not None and by_id[node.parent_id].parent_id is not None
        ):
            node = by_id[node.parent_id]
        zones.setdefault(node.name, []).append(leaf)
    return zones


def _create_food_items(
    db, org_id, created_by, templates, locations, target_count, cat_ids
):
    _require_categories(
        cat_ids, {cat_key for _t, cat_key in templates}, what='food items'
    )
    leaf_locs = _get_food_leaf_locations(locations)
    if not leaf_locs:
        return 0

    currency = _org_currency(db, org_id)

    items_created = 0
    roundings = _uom_rounding_map(db)
    # (item, behaviour of the place it sits in) — the expiry story is handed
    # out once all the rows exist, so its counts are exact rather than the
    # outcome of a per-row coin flip.
    story_rows: list[tuple[Any, str]] = []
    chilled: list[Any] = []
    leaves_by_zone = _food_leaves_by_zone(locations, leaf_locs)

    for _ in range(target_count):
        template, cat_key = random.choice(templates)
        zone = FOOD_ZONE_BY_CATEGORY.get(cat_key, 'Dry Goods')
        loc = random.choice(leaves_by_zone.get(zone) or leaf_locs)
        cat_id = cat_ids.get(cat_key)

        qty = _random_quantity(roundings.get(template.uom_id))
        price = Decimal('5.00')
        variance = random.uniform(0.85, 1.15)
        purchase_price = round(Decimal(str(price)) * Decimal(str(variance)), 2)

        item = Item(
            id=uuid.uuid4(),
            organization_id=org_id,
            storage_location_id=loc.id,
            category_id=cat_id,
            template_id=template.id,
            name=template.name,
            brand=template.brand,
            barcode=None,  # template owns the barcode; uq_items_org_barcode_active
            uom_id=template.uom_id,
            quantity=qty,
            purchase_price=purchase_price,
            currency=currency,
            expiry_date=None,  # handed out by _apply_expiry_story below
            is_deleted=False,
        )
        _anchor_records(db, org_id, [item])
        db.add(item)
        story_rows.append((item, loc.behavior_mode))
        if zone == 'Cold Storage':
            chilled.append(item)

        items_created += 1

    _apply_expiry_story(story_rows, chilled=chilled)
    _date_the_arrivals([item for item, _mode in story_rows], chilled)
    low_stock = _apply_low_stock_story([item for item, _mode in story_rows], templates)
    print(
        f'  Story: {DEMO_STORY_EXPIRED} expired, '
        f'{DEMO_STORY_EXPIRING_SOON} expiring soon, {low_stock} below threshold'
    )
    db.flush()
    return items_created


def _date_the_arrivals(items: list[Any], chilled: list[Any]) -> None:
    """Spread the day each record arrived over the last ten weeks.

    Chilled food is days old, the pantry weeks; nothing arrived today, so a
    record's history never opens at the minute of seeding. The stride walks
    the days evenly without a random draw. A record that has already gone off
    arrived before it did.
    """
    fresh = {id(item) for item in chilled}
    for index, item in enumerate(items):
        if id(item) in fresh:
            arrived = TODAY - timedelta(days=1 + index % 6)
        else:
            arrived = TODAY - timedelta(days=7 + index * 11 % 64)
        if item.expiry_date is not None:
            arrived = min(arrived, item.expiry_date - timedelta(days=3))
        item.added_date = arrived


def _create_equipment_items(
    db, org_id, created_by, templates, locations, uom_ids, cat_ids
):
    _require_categories(
        cat_ids, {cat_key for _t, cat_key in templates}, what='equipment items'
    )
    leaf_locs = _get_equip_leaf_locations(locations)
    if not leaf_locs:
        return 0

    currency = _org_currency(db, org_id)

    items_created = 0
    # Serials come off a counter, not out of random.randint. Six random digits
    # over ~84 assets is a birthday collision in roughly one run in 250, and
    # ``uq_items_org_serial`` turns that into an IntegrityError halfway through
    # the seed. A nightly rebuild that fails twice a year and leaves the demo
    # half-built is worse than the odds suggest, because nobody is watching it
    # at three in the morning. The offset keeps the numbers looking like
    # inventory tags rather than like a loop index.
    next_serial = 100000
    # Catalogue price per template, and a purchase date walked across the
    # last three years. A flat price and no date left the fleet valuation
    # with nothing to depreciate and the warranty column blank on every row.
    # The stride spreads the dates evenly without a random draw; against a
    # three-year warranty the window puts a handful past it and a few inside
    # the thirty-day alert. A wider window buried the equipment overview
    # under a page of expired warranties.
    catalogue_price = {row[0]: row[5] for row in EQUIPMENT_TEMPLATES}
    asset_index = 0

    for template, cat_key in templates:
        cat_id = cat_ids.get(cat_key)
        count = random.randint(1, 5)

        for _ in range(count):
            loc = random.choice(leaf_locs)
            serial = f'SN-{next_serial}'
            next_serial += 1

            # What the module's own form and importer write, written here too:
            # the namespace says which module owns the record, and
            # ``module_name`` is that answer resolved once (AGENTS.md §4,
            # app.services.items._module_owner). The seeder bypasses the
            # service layer, so nothing else would fill either in — and a
            # record carrying neither is one the core inventory offers to
            # decrement while the equipment list cannot find it at all.
            purchased = TODAY - timedelta(days=45 + (asset_index * 97) % 1100)
            asset_index += 1
            meta_data = {
                'equipment': {
                    'equipment_status': 'AVAILABLE',
                    'purchase_date': purchased.isoformat(),
                    'warranty_until': (purchased + timedelta(days=3 * 365)).isoformat(),
                }
            }

            item = Item(
                id=uuid.uuid4(),
                organization_id=org_id,
                storage_location_id=loc.id,
                category_id=cat_id,
                template_id=template.id,
                name=template.name,
                brand=template.brand,
                barcode=None,  # template owns the barcode; uq_items_org_barcode_active
                # The template's own unit, as the food seeder writes it: a
                # record contradicting its catalogue row about the unit is
                # what the item guard refuses at every door, and the demo
                # data must not be the one place that ships the contradiction.
                # Pieces stand in only for a template with no unit of its own.
                uom_id=template.uom_id or uom_ids.get(UOM_PIECE),
                quantity=Decimal('1'),
                serial_number=serial,
                purchase_price=catalogue_price.get(template.name, Decimal('500.00')),
                currency=currency,
                added_date=purchased,
                # The asset timeline opens on ``created_at``; left at the
                # reset, "Asset created" landed after the check-outs and
                # repairs seeded weeks back (all within 41 days; the newest
                # purchase is 45 days old).
                created_at=datetime.combine(purchased, time(9), tzinfo=UTC),
                meta_data=meta_data,
                module_name=resolve_module_owner(meta_data),
                is_deleted=False,
            )
            _anchor_records(db, org_id, [item])
            db.add(item)

            items_created += 1

    db.flush()
    return items_created


def highest_document_seq(db, org_id, doc_type: str, year: int) -> int:
    """The highest sequence this organization already uses for a type and year.

    The seeder writes its own numbers instead of asking
    ``document_numbering_service``: that service is async and takes an advisory
    lock to promise numbering without gaps, which demo data does not need. What
    demo data does need is numbers nobody else holds — an organization already
    carrying ``IN/<year>/001``, from ordinary use or from a seed run whose
    documents ``clean_seed_data`` does not own, made the whole seeder a
    UniqueViolation on ``uq_document_org_number``.

    Returns 0 when the pattern is free, so callers add their own 1-based
    sequence to it.
    """
    prefix = f'{doc_type}/{year}/'
    taken = [
        int(number[len(prefix) :])
        for (number,) in db.query(Document.number)
        .filter(
            Document.organization_id == org_id,
            Document.number.like(f'{prefix}%'),
        )
        .all()
        if number[len(prefix) :].isdigit()
    ]
    return max(taken, default=0)


#: Where a seeded document says it is seeded: on its lines' product snapshot,
#: which no screen reads. It used to be ``external_reference``, and that field
#: is printed on the register and on the document itself — every demo document
#: carried "SEED-DOC" where a supplier's delivery note number belongs.
DOC_SEED_MARKER = f'{SEED_PREFIX}DOC'


def _seeded_document_ids(db, org_id) -> list:
    """Ids of the documents this seeder wrote for the organization.

    Documents seeded before the marker moved still carry it in
    ``external_reference``; ``--clean`` has to find those too.
    """
    by_line = (
        db.query(DocumentLine.document_id)
        .join(Document, Document.id == DocumentLine.document_id)
        .filter(
            Document.organization_id == org_id,
            DocumentLine.product_snapshot['seed'].astext == DOC_SEED_MARKER,
        )
    )
    by_reference = db.query(Document.id).filter(
        Document.organization_id == org_id,
        Document.external_reference == DOC_SEED_MARKER,
    )
    return [row[0] for row in by_line.union(by_reference).all()]


def _beside_the_first_shelf(locations, leaves):
    """The shelf beside the first one: a second stand the walk can reach.

    The pick path compares the numbers along a line's shelf one level at a
    time, and a level the line's chain does not reach reads as having no
    number at all, so a child of the first shelf would be walked before its
    own parent. A sibling keeps the two stands one level apart, and the seed
    numbers them both.
    """
    cold = _food_leaves_by_zone(locations, leaves).get('Cold Storage') or leaves
    first = leaves[0]
    return next(
        (loc for loc in cold if loc.id != first.id and loc.parent_id != first.id),
        first,
    )


def _add_the_demo_dispatches(add_doc, food, tax, locations, leaves, customers) -> list:
    """The five dispatches the demo register shows, drawn from two stands.

    The first stands finished behind what the receipts landed, two stay
    confirmed for a visitor to pick (two, so Pick N selected can be tried
    without writing a delivery from scratch), and the pair in the middle is
    the pair ``_walk_the_demo_dispatches`` walks: written CONFIRMED and
    finished afterwards, because their lines take what the receipts land and
    the receipts have not run yet. Every one names a customer, taken in turn
    from ``customers``: Duplicate and Create Return refuse a delivery with
    no partner. Returns the ids of the walked pair.
    """
    customer = itertools.cycle(customers)
    first = leaves[0]
    beside = _beside_the_first_shelf(locations, leaves)
    add_doc(
        DocumentType.OUT,
        1,
        DocumentStatus.COMPLETED,
        4,
        # Both dispatch lines name food the receipts above land on this
        # shelf: the finished dispatch draws on what they brought in, so it
        # has stock behind it whatever the random placement did.
        [(food[0], 12, tax), (food[2], 8, tax)],
        source=first,
        partner=next(customer),
    )
    # The dispatch a visitor may take: confirmed, not yet picked, and drawn
    # from the shelf the second delivery stocked, so a visitor who picks it
    # can complete it as well.
    add_doc(
        DocumentType.OUT,
        2,
        DocumentStatus.CONFIRMED,
        2,
        [(food[3], 10, tax)],
        source=beside,
        partner=next(customer),
    )
    packed = add_doc(
        DocumentType.OUT,
        3,
        DocumentStatus.CONFIRMED,
        1,
        [(food[1], 6, tax), (food[2], 4, tax)],
        source=first,
        partner=next(customer),
    )
    walked_with_packed = add_doc(
        DocumentType.OUT,
        4,
        DocumentStatus.CONFIRMED,
        1,
        [(food[3], 10, tax), (food[4], 5, tax)],
        source=beside,
        partner=next(customer),
    )
    add_doc(
        DocumentType.OUT,
        5,
        DocumentStatus.CONFIRMED,
        1,
        [(food[3], 8, tax), (food[4], 4, tax)],
        source=beside,
        partner=next(customer),
    )
    return [packed.id, walked_with_packed.id]


#: Clock times (UTC) a seeded document may be written at: a working morning
#: and early afternoon. The seed used to stamp every document with the moment
#: it ran, so a register read as one burst at the hour of seeding.
_WORKDAY_SLOTS = [
    time(8, 10),
    time(9, 35),
    time(10, 50),
    time(11, 20),
    time(12, 5),
    time(13, 15),
    time(14, 5),
    time(14, 40),
]

#: A document is confirmed within the hour it was written and put away before
#: the day is out; the longest span still ends before evening.
_CONFIRMED_AFTER = timedelta(hours=1, minutes=10)
_COMPLETED_AFTER = timedelta(hours=2, minutes=40)


def _written_at(day: datetime, seq: int = 1) -> datetime:
    """The time of ``day`` the seeded document number ``seq`` of its type was written.

    The slot a day starts from moves with the date, so two days do not open
    at the same minute, and the documents of one type written on one day
    climb through the slots in the order they are numbered (a type has at
    most five seeded documents).
    """
    first = day.toordinal() % (len(_WORKDAY_SLOTS) - 5)
    return datetime.combine(day.date(), _WORKDAY_SLOTS[first + seq - 1], tzinfo=UTC)


def _create_documents_demo(
    db, org_id, created_by, food_templates, equip_templates, locations
):
    """Demo warehouse documents with priced lines.

    Without unit prices on document lines the register, VAT totals and the
    approval queue all render empty on demo data. Documents are created
    directly, without stock execution — the seeded records' stock is
    already in the register, opened by ``_open_the_shelves``. What the
    completed documents claim to have moved is posted by
    ``_execute_the_seeded_documents`` afterwards: a finished document whose
    register says it moved nothing contradicts itself on one screen.

    Returns ``(how many, the two dispatches still to walk)``: the counts
    the report prints, and the ids of the pair picked together, packed and
    shipped once the receipts have landed. An organization that already
    carries the seed's documents answers ``(0, [])`` — there is nothing
    left to write and the walk has already happened.
    """
    currency = _org_currency(db, org_id)
    if _seeded_document_ids(db, org_id):
        return 0, []

    partners = (
        db.query(Partner)
        .filter(
            Partner.organization_id == org_id,
            Partner.code.in_([p[2] for p in DEMO_PARTNERS]),
        )
        .all()
    )

    food_price = {t[0]: t[6] for t in FOOD_TEMPLATES}
    equip_price = {t[0]: t[5] for t in EQUIPMENT_TEMPLATES}
    food = [t for t, _cat in food_templates][:8]
    equip = [t for t, _cat in equip_templates][:2]
    leaves = _get_food_leaf_locations(locations)
    equip_leaves = _get_equip_leaf_locations(locations)
    if len(leaves) < 2 or not food or not equip or not partners:
        return 0, []

    by_code = {p.code: p for p in partners}
    now = datetime.now(UTC)
    year = now.year

    highest_seq: dict[str, int] = {}

    def _seq_offset(doc_type) -> int:
        if doc_type.value not in highest_seq:
            highest_seq[doc_type.value] = highest_document_seq(
                db, org_id, doc_type.value, year
            )
        return highest_seq[doc_type.value]

    def transfer_source(qty, target):
        """A seeded food record holding ``qty``, off the target shelf, or None.

        The draft is written around a record that exists instead of a product
        picked first: where random placement left stock decides the product.
        A seed too small to hold one gets no transfer rather than one that
        Confirm refuses.
        """
        record = (
            db.query(Item)
            .filter(
                Item.organization_id == org_id,
                Item.template_id.in_([t.id for t, _cat in food_templates]),
                Item.is_deleted.is_(False),
                Item.quantity >= qty,
                Item.storage_location_id != target.id,
            )
            .order_by(Item.quantity.desc(), Item.id)
            .first()
        )
        return record

    def add_doc(
        doc_type,
        seq,
        status,
        days_ago,
        lines_spec,
        partner=None,
        source=None,
        target=None,
    ):
        created = _written_at(now - timedelta(days=days_ago), seq)
        doc = Document(
            id=uuid.uuid4(),
            organization_id=org_id,
            type=doc_type.value,
            number=f'{doc_type.value}/{year}/{_seq_offset(doc_type) + seq:03d}',
            status=status.value,
            partner_id=partner.id if partner else None,
            partner_snapshot={'name': partner.name, 'code': partner.code}
            if partner
            else None,
            source_location_id=source.id if source else None,
            target_location_id=target.id if target else None,
            scheduled_date=created.date(),
            currency=currency,
            # What a receipt really carries here: the supplier's own number.
            external_reference=(
                f'Delivery note {7310 + seq}'
                if partner and doc_type == DocumentType.IN
                else None
            ),
            created_by=created_by,
            created_at=created,
        )
        # Written in the morning, confirmed within the hour, put away after
        # lunch — one second for all three read as a row nobody worked on.
        if status in (DocumentStatus.CONFIRMED, DocumentStatus.COMPLETED):
            doc.confirmed_by = created_by
            doc.confirmed_at = created + _CONFIRMED_AFTER
        finished = status == DocumentStatus.COMPLETED
        if finished:
            doc.completed_by = created_by
            doc.completed_at = created + _COMPLETED_AFTER
        for n, (template, qty, tax) in enumerate(lines_spec, start=1):
            record = None
            if doc_type == DocumentType.INT:
                record = transfer_source(qty, target)
                template = db.get(ProductTemplate, record.template_id)
                doc.source_location_id = record.storage_location_id
            price = (
                food_price.get(template.name)
                or equip_price.get(template.name)
                or Decimal('9.99')
            )
            doc.lines.append(
                DocumentLine(
                    id=uuid.uuid4(),
                    document_id=doc.id,
                    product_template_id=template.id,
                    item_id=record.id if record is not None else None,
                    name=template.name,
                    brand=template.brand,
                    barcode=template.barcode,
                    quantity=Decimal(qty),
                    expected_quantity=Decimal(qty),
                    # Only a finished document has done anything: an open
                    # one written done reads "ready to close" beside a scan
                    # window that says nothing was picked.
                    done_quantity=Decimal(qty if finished else 0),
                    uom_id=template.uom_id,
                    unit_price=price,
                    tax_rate=tax,
                    currency=currency,
                    line_number=n,
                    product_snapshot={
                        'name': template.name,
                        'brand': template.brand,
                        'seed': DOC_SEED_MARKER,
                    },
                )
            )
        recompute_document_values(doc)
        db.add(doc)
        return doc

    equip_tax, food_tax = _org_tax_rates(db, org_id)
    add_doc(
        DocumentType.IN,
        1,
        DocumentStatus.COMPLETED,
        9,
        [(food[0], 48, food_tax), (food[1], 24, food_tax), (food[2], 36, food_tax)],
        partner=by_code.get('FFD-004'),
        target=leaves[0],
    )
    add_doc(
        DocumentType.IN,
        2,
        DocumentStatus.COMPLETED,
        7,
        [(food[3], 60, food_tax), (food[4], 20, food_tax)],
        partner=by_code.get('MCC-005'),
        # Beside the first shelf, so the demo's second dispatch has stock of
        # its own standing on a shelf of its own: one walk, two stands.
        target=_beside_the_first_shelf(locations, leaves),
    )
    add_doc(
        DocumentType.IN,
        3,
        DocumentStatus.COMPLETED,
        2,
        [(equip[0], 5, equip_tax), (equip[1], 3, equip_tax)],
        partner=by_code.get('SUP-001'),
        target=equip_leaves[0] if equip_leaves else leaves[0],
    )
    # The four dispatches, drawn from the two stands the receipts stock —
    # including the pair one picking session walks together afterwards.
    walked_pair = _add_the_demo_dispatches(
        add_doc,
        food,
        food_tax,
        locations,
        leaves,
        [by_code[code] for code in ('CUS-011', 'CUS-012') if code in by_code],
    )
    transfer = transfer_source(5, leaves[1]) is not None
    if transfer:
        add_doc(
            DocumentType.INT,
            1,
            DocumentStatus.DRAFT,
            1,
            [(food[7], 5, food_tax)],
            source=leaves[0],
            target=leaves[1],
        )
    db.flush()
    return 8 + transfer, walked_pair


async def _name_the_stock_the_dispatch_takes(adb, doc) -> None:
    """Settle every dispatch line onto a record standing where it draws.

    A dispatch document's lines have to name the stock they take from —
    ``requires_stock_row`` refuses one that names a product alone, on
    confirmation as on execution. The seed writes its dispatches' lines
    without a record because at that moment the stock the receipts land
    does not exist yet; this runs right after them and picks, for each
    line, a record of the line's product standing on the document's source
    shelf and holding what the line takes.
    """
    from sqlalchemy import select

    for line in doc.lines:
        if line.item_id is not None:
            continue
        record = await adb.scalar(
            select(Item.id)
            .where(
                Item.organization_id == doc.organization_id,
                Item.template_id == line.product_template_id,
                Item.storage_location_id == doc.source_location_id,
                Item.is_deleted.is_(False),
                Item.quantity >= line.quantity,
            )
            .order_by(Item.quantity.desc(), Item.id)
            .limit(1)
        )
        if record is None:
            raise RuntimeError(
                f'{doc.number}: no record of line {line.line_number} on its '
                f'source shelf holds the dispatched quantity'
            )
        line.item_id = record


def _wire_the_equipment_interceptor() -> None:
    """Let a delivery open assets the way a running server does.

    The server wires every module's interceptors at startup; this plain
    script never starts the modules, so the pipeline is empty here and a
    receipt would open an equipment-category record with no equipment
    namespace, listed as an Unknown asset.
    """
    from app.core.interceptors import interceptor_pipeline
    from app.core.module_registry import module_registry

    module_registry.discover_modules()
    if module_registry.get('equipment') is None:
        return
    from app.modules.equipment.interceptors import EquipmentItemInterceptor

    interceptor_pipeline.register_item_interceptor(EquipmentItemInterceptor())


def _execute_the_seeded_documents(org_id, created_by) -> int:
    """Post the stock the finished demo documents say they moved.

    The seed writes a document's whole life in one pass — status,
    timestamps, done quantities — and used to leave it at that: a receipt
    whose execution summary reads 8/8 had no movement behind it, so the
    register's own view of the document ("What this document moved") said
    it moved nothing. The executor every completion runs is what keeps the
    two accounts of the same goods together, so it runs here once per
    completed document, on the documents this seeder wrote.

    Order matters: the receipts go first, because the finished dispatch
    draws on what they land (and names those records). The movements are
    dated the day their document closed, the way an opening balance is
    dated the day its record arrived, so a shelf's history reads like one.
    Documents that already moved are left alone, so a run that tops the
    volume up moves nothing a second time.

    The confirmed dispatches are named their stock here too, once the
    receipts have landed: they are what a visitor picks and completes, and
    a completion refuses a dispatch line that names a product alone.
    """
    from sqlalchemy import select, update
    from sqlalchemy.orm import selectinload

    from app.core.contracts import ItemAction
    from app.models.item_history import ItemHistory
    from app.models.stock_move import StockMove, StockMoveReferenceType
    from app.models.stock_reservation import StockReservation
    from app.modules.warehouse import document_types as dt
    from app.modules.warehouse._document_workflow_crud import _reserve_quants_for_doc
    from app.modules.warehouse.document_stock_executor import execute_stock_operations
    from app.modules.warehouse.models import Document, DocumentStatus

    already_moved = select(StockMove.reference_id).where(
        StockMove.organization_id == org_id,
        StockMove.reference_type == StockMoveReferenceType.DOCUMENT,
        StockMove.reference_id.is_not(None),
    )
    seeded_lines = (
        select(DocumentLine.document_id)
        .join(Document, Document.id == DocumentLine.document_id)
        .where(
            Document.organization_id == org_id,
            DocumentLine.product_snapshot['seed'].astext == DOC_SEED_MARKER,
        )
    )
    finished = (
        select(Document)
        .options(selectinload(Document.lines))
        .where(
            Document.organization_id == org_id,
            Document.status == DocumentStatus.COMPLETED.value,
            Document.id.in_(seeded_lines),
            Document.id.not_in(already_moved),
        )
        # Receipts before dispatches — the dispatch draws on what they land.
        .order_by(Document.type, Document.number)
    )
    waiting = (
        select(Document)
        .options(selectinload(Document.lines))
        .where(
            Document.organization_id == org_id,
            Document.status == DocumentStatus.CONFIRMED.value,
            Document.id.in_(seeded_lines),
        )
    )

    async def _execute(adb) -> int:
        documents = list((await adb.execute(finished)).scalars().all())
        if documents:
            _wire_the_equipment_interceptor()
        for doc in documents:
            if not dt.is_receipt(doc.type):
                await _name_the_stock_the_dispatch_takes(adb, doc)
            await execute_stock_operations(adb, doc, created_by)
            closed = doc.completed_at
            await adb.execute(
                update(StockMove)
                .where(
                    StockMove.organization_id == org_id,
                    StockMove.reference_type == StockMoveReferenceType.DOCUMENT,
                    StockMove.reference_id == doc.id,
                )
                .values(created_at=closed, completed_at=closed)
            )
            if dt.is_receipt(doc.type):
                # A record the delivery opened arrived with it, not on the
                # day the seed ran: its own dates read the same as the
                # movement the delivery wrote, so it does not open at the
                # minute of seeding and does not lead a "newest first" list.
                opened_by_the_document = select(ItemHistory.item_id).where(
                    ItemHistory.organization_id == org_id,
                    ItemHistory.source_document_id == doc.id,
                    ItemHistory.action == ItemAction.CREATED.value,
                )
                await adb.execute(
                    update(Item)
                    .where(
                        Item.organization_id == org_id,
                        Item.id.in_(opened_by_the_document),
                    )
                    .values(added_date=closed.date(), created_at=closed)
                )
                # Delivered equipment is an asset from the day it arrives:
                # the purchase is the receipt, and the warranty runs from it
                # like the fleet the seeder wrote directly.
                for opened in (
                    await adb.scalars(
                        select(Item).where(
                            Item.organization_id == org_id,
                            Item.id.in_(opened_by_the_document),
                            Item.module_name == 'equipment',
                        )
                    )
                ).all():
                    opened.meta_data = {
                        **opened.meta_data,
                        'equipment': {
                            **opened.meta_data['equipment'],
                            'purchase_date': closed.date().isoformat(),
                            'warranty_until': (
                                closed.date() + timedelta(days=3 * 365)
                            ).isoformat(),
                        },
                    }
        for doc in (await adb.execute(waiting)).scalars().all():
            if dt.requires_stock_row(doc.type):
                await _name_the_stock_the_dispatch_takes(adb, doc)
            if dt.needs_quant_reservation(doc.type) and not await adb.scalar(
                select(StockReservation.id)
                .where(StockReservation.document_id == doc.id)
                .limit(1)
            ):
                # Confirm holds the stock a document will take; written
                # confirmed, a dispatch held nothing and Available read
                # On hand for goods it was about to take.
                await _reserve_quants_for_doc(adb, doc)
        await adb.commit()
        return len(documents)

    return _run_on_own_engine(_execute)


def _walk_the_demo_dispatches(org_id, created_by, packed_id, walked_id) -> dict:
    """Pick the two dispatches in one session, pack and ship one of them.

    The seed writes a document's whole life in one pass — status, timestamps,
    done quantities — and these states are the ones that pass cannot make: a
    session plans its lines from the shelves and orders them by the walk (the
    numbers ``_number_the_walk`` gave them), a package is bounded by what was
    picked, and a completion posts the stock the lines took in the same
    transaction it closes the document in — carrying the dispatch's hand-over
    to its carrier with it. Written out as rows, each state would be a copy of
    the rule that produces it; walked through the application's own doors it
    holds whatever those doors hold.

    Runs after ``_execute_the_seeded_documents``: the receipts have landed
    and the dispatches' lines name the records they take from on the shelves
    they draw from. Returns what the walk did, for the report the reset
    prints.
    """
    from sqlalchemy import select, update
    from sqlalchemy.orm import selectinload

    async def _walk(adb) -> dict:
        from app.modules.warehouse._document_workflow_transitions import (
            complete_document,
        )
        from app.modules.warehouse.document_profile_service import (
            get_or_create_profile,
        )
        from app.modules.warehouse.packing_service import (
            create_package_async,
            set_line_async,
        )
        from app.modules.warehouse.schemas import DocumentComplete
        from app.modules.warehouse.shipment_schemas import ShipmentCreate
        from app.modules.warehouse.wms_picking_service import (
            confirm_short_pick_async,
            start_pick_session_over_documents_async,
        )

        # The approval gate the pick start goes through builds this
        # organization's document profile on first use — the profile the
        # warehouse module leaves behind when it is switched on — and commits
        # it, which expires every document this walk has loaded. Give the
        # organization its profile first, while nothing is loaded yet, and
        # the walk keeps its objects live to the end.
        await get_or_create_profile(adb, org_id)

        docs = list(
            (
                await adb.scalars(
                    select(Document)
                    .where(
                        Document.id.in_([packed_id, walked_id]),
                        Document.organization_id == org_id,
                    )
                    .options(selectinload(Document.lines))
                )
            ).all()
        )
        if len(docs) != 2:
            raise RuntimeError('the dispatches to walk are not both in the register')
        written = {doc.id: doc.created_at for doc in docs}

        session = await start_pick_session_over_documents_async(
            adb, [packed_id, walked_id], org_id, created_by
        )
        # Nothing commits between loading the documents and here, so the
        # plan and the objects it names are still live below: the last line
        # closes the session, and the boxes are filled from the quantities
        # those lines just wrote.
        plan = [(line.id, line.expected_quantity) for line in session.lines]
        session_id = session.id
        for line_id, expected in plan:
            await confirm_short_pick_async(adb, session_id, org_id, line_id, expected)

        packed = next(doc for doc in docs if doc.id == packed_id)
        boxes = []
        for line in sorted(packed.lines, key=lambda ln: ln.line_number):
            # One box per line: the demo's dispatch is two boxes of two
            # different goods, which is what the slip prints and the register
            # counts when the carrier is told about it.
            box = await create_package_async(adb, org_id, packed_id, created_by)
            await set_line_async(
                adb, org_id, packed_id, box.id, line.id, line.done_quantity, created_by
            )
            boxes.append(box)
        await adb.commit()

        # The packed dispatch is the one that leaves the building: it goes
        # out under a carrier with a number to follow it, and the shipment
        # rides the completion — same transaction, ahead of the stock the
        # lines take. Its pair simply closes.
        await complete_document(
            adb,
            org_id,
            packed_id,
            created_by,
            execution_data=DocumentComplete(
                shipment=ShipmentCreate(
                    carrier=DEMO_SHIPMENT_CARRIER,
                    tracking_number=DEMO_SHIPMENT_TRACKING_NUMBER,
                )
            ),
        )
        await complete_document(adb, org_id, walked_id, created_by)

        # The completion stamps the minute the seed ran. The register dates
        # the pair like every other finished document: the day it was
        # written, put away after lunch.
        from app.models.stock_move import StockMove, StockMoveReferenceType

        for document_id, created in written.items():
            closed = created + _COMPLETED_AFTER
            await adb.execute(
                update(Document)
                .where(Document.id == document_id)
                .values(completed_at=closed)
            )
            await adb.execute(
                update(StockMove)
                .where(
                    StockMove.organization_id == org_id,
                    StockMove.reference_type == StockMoveReferenceType.DOCUMENT,
                    StockMove.reference_id == document_id,
                )
                .values(created_at=closed, completed_at=closed)
            )
        await adb.commit()
        return {'picked': len(plan), 'packages': len(boxes)}

    return _run_on_own_engine(_walk)


def _seed_documents_demo(
    db, org_id, created_by, food_templates, equip_templates, locations, say
) -> int:
    """The documents one step: write them, post what they moved, walk two of them."""
    say('Creating demo documents with priced lines...')
    documents, to_walk = _create_documents_demo(
        db, org_id, created_by, food_templates, equip_templates, locations
    )
    db.commit()
    say(f'  Created: {documents} documents')
    moved = _execute_the_seeded_documents(org_id, created_by)
    if moved:
        say(f'  Executed: {moved} completed documents, their stock posted')
    if to_walk:
        walked = _walk_the_demo_dispatches(org_id, created_by, *to_walk)
        say(
            f'  Walked: {walked["picked"]} lines picked in one session, '
            f'{walked["packages"]} packages'
        )
    return documents


def _number_the_seeded_documents_by_date(db, org_id) -> int:
    """Renumber what the seed wrote so each type's numbers climb with its dates.

    The documents and the purchase order's receipt are written by two steps
    that each take the next free number, and the receipt — dated weeks before
    the delivery notes — came second: ``IN/…/004`` dated the 10th sat under
    ``IN/…/001`` dated the 18th. A warehouse numbers its documents in the
    order they happen, so once everything is written they are numbered again
    by the day each was written. Returns how many numbers changed.
    """
    ids = _seeded_document_ids(db, org_id)
    if not ids:
        return 0
    docs = db.query(Document).filter(Document.id.in_(ids)).all()
    was = {doc.id: doc.number for doc in docs}
    # ``uq_document_org_number`` forbids two holders of a number, even for
    # the length of one statement: park them all, then hand them back.
    for doc in docs:
        doc.number = f'PARKED-{doc.id}'
    db.flush()

    by_series: dict[str, list[Document]] = {}
    for doc in docs:
        series = was[doc.id].rpartition('/')[0]
        by_series.setdefault(series, []).append(doc)

    changed = 0
    for series, members in by_series.items():
        doc_type, _, year = series.partition('/')
        next_seq = highest_document_seq(db, org_id, doc_type, int(year)) + 1
        for doc in sorted(members, key=lambda d: (d.created_at, was[d.id])):
            doc.number = f'{series}/{next_seq:03d}'
            changed += doc.number != was[doc.id]
            next_seq += 1
    db.flush()
    return changed


def highest_po_seq(db, org_id, year: int) -> int:
    """The highest sequence this organization already uses for an order.

    Same reason as ``highest_document_seq``: the numbering service is async
    and takes an advisory lock that demo data does not need, but the unique
    index on (organization, number) is very much real.
    """
    prefix = f'PO/{year}/'
    taken = [
        int(number[len(prefix) :])
        for (number,) in db.query(PurchaseOrder.number)
        .filter(
            PurchaseOrder.organization_id == org_id,
            PurchaseOrder.number.like(f'{prefix}%'),
        )
        .all()
        if number[len(prefix) :].isdigit()
    ]
    return max(taken, default=0)


#: The partners equipment is bought from (codes in ``DEMO_PARTNERS``).
EQUIPMENT_SUPPLIERS = ('SUP-001', 'ITD-002', 'TSE-003')


def _create_purchase_orders_demo(db, org_id, created_by, equip_templates, locations=()):
    """Orders in the three states the module's screens are written for.

    A warehouse profile without a single order shows an empty list where its
    whole procurement half begins — the reorder suggestions, the receiving
    queue and the approval threshold all read from here. One order waiting to
    be sent, one sent, one half delivered.

    Written straight to the tables, like the documents above: the service is
    async and holds the numbering lock, which demo data does not need. The
    half delivered order is written with the receipt behind its received
    count (``_receive_the_part_delivered_line``), because that count is only
    ever what completed receipts brought; the receipt's stock is posted by
    ``_execute_the_seeded_documents`` afterwards.
    """
    marker = f'{SEED_PREFIX}PO'
    currency = _org_currency(db, org_id)
    existing = (
        db.query(PurchaseOrder.id)
        .filter(
            PurchaseOrder.organization_id == org_id,
            PurchaseOrder.notes == marker,
        )
        .first()
    )
    if existing:
        return 0

    # The orders buy equipment, so they go to the IT distributors first; the
    # first supplier the query happened to return was a food wholesaler,
    # and the demo's approval queue showed laptops from a cash and carry.
    suppliers = sorted(
        db.query(Partner)
        .filter(
            Partner.organization_id == org_id,
            Partner.type.in_(['SUPPLIER', 'BOTH']),
        )
        .all(),
        key=lambda partner: (
            partner.code not in EQUIPMENT_SUPPLIERS,
            partner.code or '',
        ),
    )
    products = [t for t, _cat in equip_templates][:3]
    if not suppliers or len(products) < 2:
        return 0

    equip_price = {t[0]: t[5] for t in EQUIPMENT_TEMPLATES}
    standard_tax = _org_tax_rates(db, org_id)[0]
    now = datetime.now(UTC)
    year = now.year
    offset = highest_po_seq(db, org_id, year)

    def add_order(seq, status, days_ago, supplier, lines_spec):
        created = now - timedelta(days=days_ago)
        po = PurchaseOrder(
            id=uuid.uuid4(),
            organization_id=org_id,
            number=f'PO/{year}/{offset + seq:03d}',
            status=status,
            partner_id=supplier.id,
            scheduled_date=(created + timedelta(days=7)).date(),
            notes=marker,
            currency=currency,
            created_by=created_by,
            created_at=created,
        )
        if status in ('CONFIRMED', 'COMPLETED'):
            po.confirmed_by = created_by
            po.confirmed_at = created
        for n, (template, ordered, received) in enumerate(lines_spec, start=1):
            po.lines.append(
                PurchaseOrderLine(
                    id=uuid.uuid4(),
                    purchase_order_id=po.id,
                    product_template_id=template.id,
                    name=template.name,
                    quantity_ordered=Decimal(ordered),
                    quantity_received=Decimal(received),
                    unit_price=equip_price.get(template.name, Decimal('9.99')),
                    uom_id=template.uom_id,
                    tax_rate=standard_tax,
                    line_number=n,
                )
            )
        db.add(po)
        return po

    add_order(1, 'DRAFT', 3, suppliers[0], [(products[0], 4, 0)])
    add_order(
        2,
        'CONFIRMED',
        10,
        suppliers[0],
        [(products[0], 6, 0), (products[1], 2, 0)],
    )
    part_delivered = add_order(
        3,
        'CONFIRMED',
        20,
        suppliers[min(1, len(suppliers) - 1)],
        [(products[1], 5, 3)],
    )
    db.flush()
    _receive_the_part_delivered_line(
        db, org_id, created_by, part_delivered, _get_equip_leaf_locations(locations)
    )
    db.flush()
    return 3


def _receive_the_part_delivered_line(db, org_id, created_by, po, equip_leaves) -> None:
    """Write the completed receipt behind the half delivered order's count.

    A line's received quantity is recounted from the completed receipts that
    name it every time one completes. Written without a receipt, the demo's
    3 of 5 became whatever the first real receipt brought. The receipt lands
    on the first equipment shelf three days after the order was written, and
    its stock is posted with the other seeded documents.
    """
    line = po.lines[0]
    year = po.created_at.year
    seq = highest_document_seq(db, org_id, DocumentType.IN.value, year) + 1
    received_at = _written_at(po.created_at + timedelta(days=3))
    supplier = db.get(Partner, po.partner_id)
    receipt = Document(
        id=uuid.uuid4(),
        organization_id=org_id,
        type=DocumentType.IN.value,
        number=f'IN/{year}/{seq:03d}',
        status=DocumentStatus.COMPLETED.value,
        partner_id=po.partner_id,
        partner_snapshot={'name': supplier.name, 'code': supplier.code},
        target_location_id=equip_leaves[0].id if equip_leaves else None,
        scheduled_date=received_at.date(),
        currency=po.currency,
        # What Create Receipt writes: the order's number in the reference row.
        external_reference=po.number,
        created_by=created_by,
        created_at=received_at,
        confirmed_by=created_by,
        confirmed_at=received_at + _CONFIRMED_AFTER,
        completed_by=created_by,
        completed_at=received_at + _COMPLETED_AFTER,
    )
    receipt.lines.append(
        DocumentLine(
            id=uuid.uuid4(),
            document_id=receipt.id,
            product_template_id=line.product_template_id,
            name=line.name,
            quantity=line.quantity_received,
            expected_quantity=line.quantity_received,
            done_quantity=line.quantity_received,
            uom_id=line.uom_id,
            unit_price=line.unit_price,
            tax_rate=line.tax_rate,
            currency=po.currency,
            line_number=1,
            source_po_line_id=line.id,
            product_snapshot={'name': line.name, 'seed': DOC_SEED_MARKER},
        )
    )
    recompute_document_values(receipt)
    db.add(receipt)


# ---------------------------------------------------------------------------
# Maker demo: one bill of materials, lifted out of the seeder so the corpus
# gate in tests/unit/test_the_demo_seed_speaks_english.py can read it. A name
# that only exists inside a function body is a name no gate can check.
# ---------------------------------------------------------------------------
#: (name, brand, sku-seed-token). The cinnamon is the workshop's own bulk
#: sack, counted in kilograms: named "Ground Cinnamon" it matched the 20 g
#: kitchen jar of the food catalogue, and a recipe line of 50 g came out as
#: two and a half jars a batch — thirty jars on one run of plum butter.
MAKER_TEMPLATES: list[tuple[str, str, str]] = [
    ('Plum Butter', 'Hollow Lane Orchard', 'PLUMBUTTER'),
    ('Damson Plums', 'Green Acre', 'PLUMS'),
    ('White Sugar', 'Harvest Row', 'SUGAR'),
    ('Cassia Cinnamon', 'Saltmill', 'CINNAMON'),
]

#: In-store EAN-13s, the range the food catalogue's own codes come from. The
#: templates used to carry ``SEED-<token>`` here, and the product card printed
#: it where a barcode belongs.
MAKER_BARCODES = {
    'PLUMBUTTER': '2000000009018',
    'PLUMS': '2000000009025',
    'SUGAR': '2000000009032',
    'CINNAMON': '2000000009049',
}

MAKER_SKUS = {
    'PLUMBUTTER': 'PLB-001',
    'PLUMS': 'PLM-001',
    'SUGAR': 'SUG-001',
    'CINNAMON': 'CIN-001',
}

#: (ingredient, quantity, uom symbol, scrap %, note)
MAKER_BOM = [
    ('Damson Plums', Decimal('2.0'), 'kg', Decimal('10'), 'stone fruit'),
    ('White Sugar', Decimal('0.3'), 'kg', Decimal('5'), 'sweetener'),
    ('Cassia Cinnamon', Decimal('0.005'), 'kg', Decimal('0'), 'spice'),
]

#: What the workshop holds before its first run: (ingredient, kg, price per kg,
#: zone, days since it arrived). A recipe is costed from the stock its
#: ingredients have, and two of the three used to have none — the recipe card
#: said it could not work out what a batch costs, and the run that was
#: supposed to show the module working had consumed nothing.
MAKER_STOCK = [
    ('Damson Plums', Decimal('40'), Decimal('3.40'), 'Cold Storage', 3),
    ('White Sugar', Decimal('25'), Decimal('1.10'), 'Dry Goods', 20),
    ('Cassia Cinnamon', Decimal('0.5'), Decimal('24.00'), 'Dry Goods', 34),
]

#: The finished run: planned, actually made, and where the jars went.
MAKER_RUN_PLANNED = Decimal('12')
MAKER_RUN_MADE = Decimal('11.4')
MAKER_RUN_NOTES = 'Autumn batch, first of the season.'


def _seed_line_measure(
    db, child_id: uuid.UUID, qty: Decimal, symbol: str
) -> tuple[uuid.UUID, Decimal, str]:
    """A seeded recipe line's unit, stated — never left for a reader to guess.

    A line that names no unit is counted in its ingredient's, so a line seeded
    as "0.05 kg" with no unit consumed 0.05 of whatever the product is kept
    in. The line keeps the recipe's unit when it converts to the product's;
    against a product kept in pieces it is restated in pieces through the
    piece's recorded weight (0.05 kg of 20 g jars is 2.5 jars). Neither
    available is a seed defect and stops the seed.
    """
    from app.models.uom import Uom
    from app.services.uom_service import convert_quantity

    declared = (
        db.query(Uom)
        .filter(Uom.symbol == symbol, Uom.organization_id.is_(None))
        .first()
    )
    template = db.get(ProductTemplate, child_id)
    stock = db.get(Uom, template.uom_id) if template and template.uom_id else None
    if declared is None:
        raise RuntimeError(f'UoM "{symbol}" not found — run base seed first')
    if stock is None or convert_quantity(qty, declared, stock)[1]:
        return declared.id, qty, declared.symbol
    weight_uom = db.get(Uom, template.weight_uom_id) if template.weight_uom_id else None
    if template.weight_value and weight_uom is not None:
        per_piece, ok = convert_quantity(
            Decimal(str(template.weight_value)), weight_uom, declared
        )
        if ok and per_piece > 0:
            return stock.id, (qty / per_piece).normalize(), stock.symbol
    raise RuntimeError(
        f'Seeded line of {qty} {symbol} cannot be stated in {stock.symbol}'
    )


def _create_maker_demo(db, org_id) -> dict[str, uuid.UUID]:
    """Seed a sample Bill of Materials — 'Plum Butter' recipe.

    Creates 4 product templates and 3 BoM lines mapping the parent
    (Plum Butter) to its three ingredients. Idempotent: re-running
    the seed will skip anything already present. Templates carry a
    ``meta_data['maker_demo'] = True`` marker so ``clean_seed_data``
    can target them precisely.

    Returns a dict of template names → ids for downstream seeders.
    """
    from app.models.uom import Uom

    def _uom(symbol: str) -> uuid.UUID:
        row = (
            db.query(Uom)
            .filter(Uom.symbol == symbol, Uom.organization_id.is_(None))
            .first()
        )
        if row is None:
            raise RuntimeError(f'UoM "{symbol}" not found — run base seed first')
        return row.id

    uom_kg = _uom('kg')
    uom_gram = _uom('g')

    demo_templates = MAKER_TEMPLATES

    # Lookup existing by name (idempotent).
    existing_by_name = {
        row[0]: row[1]
        for row in db.query(ProductTemplate.name, ProductTemplate.id)
        .filter(
            ProductTemplate.organization_id == org_id,
            ProductTemplate.name.in_([n for n, _, _ in demo_templates]),
        )
        .all()
    }

    sku_counter = MAKER_SKUS

    ids: dict[str, uuid.UUID] = {}
    for name, brand, _token in demo_templates:
        if name in existing_by_name:
            ids[name] = existing_by_name[name]
            continue

        template = ProductTemplate(
            id=uuid.uuid4(),
            organization_id=org_id,
            name=name,
            brand=brand,
            sku=sku_counter[_token],
            barcode=MAKER_BARCODES[_token],
            uom_id=uom_kg,
            weight_value=1000.0,
            weight_uom_id=uom_gram,
            removal_strategy='FIFO',
            meta_data={'maker_demo': True},
        )
        db.add(template)
        ids[name] = template.id

    db.flush()

    # BoM lines: Plum Butter <- {Damson Plums 2.0 kg, White Sugar 0.3 kg, Cassia Cinnamon 5 g},
    # each with its unit stated (see _seed_line_measure).
    parent_id = ids['Plum Butter']
    bom_recipe = MAKER_BOM
    # Ensure a default recipe exists for the parent template.
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
            name='Plum Butter',
            batch_yield_qty=Decimal('1'),
            # Store reference price (per kg jar) — powers the
            # savings/margin result on the catalog card and dashboard.
            reference_price=Decimal('18.00'),
            is_default=True,
        )
        db.add(recipe)
        db.flush()

    bom_count = 0
    for child_name, qty, unit, yield_loss, note in bom_recipe:
        child_id = ids[child_name]
        existing_line = (
            db.query(BoMLine)
            .filter(
                BoMLine.organization_id == org_id,
                BoMLine.parent_template_id == parent_id,
                BoMLine.child_template_id == child_id,
            )
            .first()
        )
        if existing_line:
            continue
        line_uom_id, line_qty, line_unit = _seed_line_measure(db, child_id, qty, unit)
        line = BoMLine(
            organization_id=org_id,
            recipe_id=recipe.id,
            parent_template_id=parent_id,
            child_template_id=child_id,
            qty_per_batch=line_qty,
            uom_id=line_uom_id,
            unit=line_unit,
            yield_loss_pct=yield_loss,
            notes=note,
        )
        db.add(line)
        bom_count += 1

    db.flush()
    print(
        f'  Maker demo: 4 templates (4 ingredient/output) + {bom_count} new BoM lines for "Plum Butter"'
    )
    return ids


# ---------------------------------------------------------------------------
# Modules that used to seed nothing
# ---------------------------------------------------------------------------
# Four modules shipped a demo that showed their empty state: production, stock
# takes, recipes and the equipment check-out desk. An empty list does not tell
# a reader whether the feature is unfinished or merely unused, and on a public
# instance the second reading is unavailable to them. Each of the four gets
# the smallest amount of work that makes its own screen legible.

#: Equipment goes out to people, and the people are invented — the addresses
#: sit in the domain reserved for documentation so a public demo cannot mail a
#: stranger.
DEMO_ASSIGNEES = [
    ('Ava Brennan', 'ava.brennan@example.com'),
    ('Marcus Webb', 'marcus.webb@example.com'),
    ('Priya Raman', 'priya.raman@example.com'),
]


def _create_assignments_demo(db, org_id, created_by) -> int:
    """Check a few assets out to named people.

    The equipment overview leads with "Checked Out" and an assignment panel.
    With nothing assigned both read zero, and the fleet looks like hardware
    nobody has ever issued.
    """
    from app.modules.equipment.models import EquipmentAssignment

    already = (
        db.query(EquipmentAssignment)
        .filter(
            EquipmentAssignment.organization_id == org_id,
            EquipmentAssignment.checked_in_at.is_(None),
        )
        .count()
    )
    if already:
        return 0

    # Only an asset that already existed on the day it is issued: equipment a
    # delivery opened is created when the receipt closed, and an unordered
    # pick made which asset read "Checked out" above "Asset created" depend
    # on row order.
    oldest_checkout = 14 + (len(DEMO_ASSIGNEES) - 1) * 9
    laptops = (
        db.query(Item)
        .filter(
            Item.organization_id == org_id,
            Item.is_deleted.is_(False),
            Item.name.ilike('%Latitude%') | Item.name.ilike('%ThinkPad%'),
            Item.created_at <= datetime.now(UTC) - timedelta(days=oldest_checkout),
        )
        .order_by(Item.created_at, Item.id)
        .limit(len(DEMO_ASSIGNEES))
        .all()
    )
    if not laptops:
        return 0

    created = 0
    for item, (name, email) in zip(laptops, DEMO_ASSIGNEES, strict=False):
        db.add(
            EquipmentAssignment(
                id=uuid.uuid4(),
                organization_id=org_id,
                item_id=item.id,
                assigned_to_name=name,
                assigned_to_email=email,
                checkout_location_id=item.storage_location_id,
                checked_out_at=datetime.now(UTC) - timedelta(days=14 + created * 9),
                expected_return_at=datetime.now(UTC) + timedelta(days=180),
                checked_out_by=created_by,
                checkout_notes='Issued with the standard laptop kit.',
            )
        )
        # The check-out service writes this too; the seeder bypasses it, and an
        # asset assigned to somebody while still reading AVAILABLE is the kind
        # of contradiction a demo cannot explain away.
        meta = dict(item.meta_data or {})
        equipment_ns = dict(meta.get('equipment') or {})
        equipment_ns['equipment_status'] = 'DEPLOYED'
        meta['equipment'] = equipment_ns
        item.meta_data = meta
        created += 1

    db.flush()
    return created


#: (asset name fragment, type, title, description, days ago, open?)
#: An open job puts the asset in MAINTENANCE, as logging one through the
#: module does; a closed one is history with the next service date on it.
DEMO_MAINTENANCE = [
    (
        'PowerEdge',
        'REPAIR',
        'Replace failed PSU',
        'Redundant power supply 2 reported a fault; unit sent to the vendor.',
        3,
        True,
    ),
    (
        'Smart-UPS',
        'INSPECTION',
        'Battery self-test and runtime check',
        'Runtime at full load 11 min, within spec. Batteries due next year.',
        40,
        False,
    ),
]


def _create_maintenance_demo(db, org_id, created_by) -> int:
    """One asset in the workshop, one with a service history.

    "In Maintenance" is a counter on the equipment overview and a status on
    the asset list; with no job ever logged both read zero and the module
    looks like a register of things that never break.
    """
    from app.modules.equipment.models import EquipmentMaintenanceLog

    if (
        db.query(EquipmentMaintenanceLog)
        .filter(EquipmentMaintenanceLog.organization_id == org_id)
        .count()
    ):
        return 0

    currency = _org_currency(db, org_id)
    created = 0
    for fragment, kind, title, description, days_ago, still_open in DEMO_MAINTENANCE:
        item = (
            db.query(Item)
            .filter(
                Item.organization_id == org_id,
                Item.is_deleted.is_(False),
                Item.name.ilike(f'%{fragment}%'),
            )
            .order_by(Item.serial_number)
            .first()
        )
        if item is None:
            continue
        performed = TODAY - timedelta(days=days_ago)
        db.add(
            EquipmentMaintenanceLog(
                id=uuid.uuid4(),
                organization_id=org_id,
                item_id=item.id,
                maintenance_type=kind,
                title=title,
                description=description,
                cost=None if still_open else Decimal('120.00'),
                currency=currency,
                performed_at=performed,
                performed_by='Northgate IT Distribution',
                next_maintenance_at=None
                if still_open
                else performed + timedelta(days=365),
                created_by=created_by,
            )
        )
        if still_open:
            meta = dict(item.meta_data or {})
            equipment_ns = dict(meta.get('equipment') or {})
            equipment_ns['equipment_status'] = 'MAINTENANCE'
            meta['equipment'] = equipment_ns
            item.meta_data = meta
        created += 1

    db.flush()
    return created


def _create_production_demo(db, org_id, created_by, maker_ids) -> int:
    """One finished production run, so the module reports a result.

    "Monthly result" on the overview reads from completed runs, and a demo
    with none said "No completed runs with a result yet" on an instance whose
    whole point is to show the feature working.

    The run used to be one row written here with a total typed in by hand: no
    ingredient on it ("No ingredients were recorded for this run"), nothing
    taken off a shelf and nothing put on one. It is now made the way the
    application makes one — a draft order, then the completion that draws the
    ingredients ``_stock_the_workshop`` put on the shelves, prices them off
    their cost layers and puts the jars on a shelf.
    """
    parent_id = maker_ids.get('Plum Butter') if maker_ids else None
    if parent_id is None:
        return 0

    existing = (
        db.query(ProductionOrder)
        .filter(
            ProductionOrder.organization_id == org_id,
            ProductionOrder.output_template_id == parent_id,
        )
        .count()
    )
    if existing:
        return 0

    shelf = _workshop_shelf(db, org_id, 'Dry Goods')
    if shelf is None:
        return 0
    # The completion runs on a connection of its own and has to see the rows
    # this session wrote.
    db.commit()

    async def _produce(adb) -> int:
        from app.core.contracts import UserContextDTO
        from app.modules.maker import production_service
        from app.modules.maker._schemas_production import ProductionOrderCreate

        user = await adb.get(User, created_by)
        context = UserContextDTO(
            id=user.id,
            email=user.email,
            role=user.role,
            organization_id=org_id,
        )
        order = await production_service.create_order(
            adb,
            org_id,
            ProductionOrderCreate(
                output_template_id=parent_id,
                planned_qty=MAKER_RUN_PLANNED,
                output_location_id=shelf.id,
                notes=MAKER_RUN_NOTES,
            ),
            context,
        )
        await production_service.complete_production(
            adb, org_id, order.id, context, actual_qty=MAKER_RUN_MADE
        )
        await adb.commit()
        return 1

    return _run_on_own_engine(_produce)


def _workshop_shelf(db, org_id, zone: str):
    """The first shelf of a food zone (Cold Storage, Dry Goods, ...)."""
    hierarchy = {
        loc.id: loc
        for loc in db.query(StorageLocation).filter(
            StorageLocation.organization_id == org_id
        )
    }
    leaves = sorted(_get_food_leaf_locations(hierarchy), key=lambda loc: loc.name)
    shelves = _food_leaves_by_zone(hierarchy, leaves).get(zone) or []
    return shelves[0] if shelves else None


def _stock_the_workshop(db, org_id, maker_ids) -> int:
    """Put the recipe's ingredients on the shelves, each at a price.

    Written as records like every other seeded one, so ``_open_the_shelves``
    opens them with a movement and a cost layer; the run in
    ``_create_production_demo`` then has something to draw and the recipe
    card something to cost. A run that tops the volume up adds nothing here.
    """
    currency = _org_currency(db, org_id)
    created = 0
    for name, kilos, price, zone, days_ago in MAKER_STOCK:
        template_id = maker_ids.get(name)
        shelf = _workshop_shelf(db, org_id, zone)
        if template_id is None or shelf is None:
            continue
        if db.query(Item).filter(Item.template_id == template_id).count():
            continue
        template = db.get(ProductTemplate, template_id)
        item = Item(
            id=uuid.uuid4(),
            organization_id=org_id,
            storage_location_id=shelf.id,
            template_id=template_id,
            name=name,
            brand=template.brand,
            uom_id=template.uom_id,
            quantity=kilos,
            purchase_price=price,
            currency=currency,
            added_date=TODAY - timedelta(days=days_ago),
            is_deleted=False,
        )
        _anchor_records(db, org_id, [item])
        db.add(item)
        created += 1
    db.flush()
    return created


def _create_stock_take_demo(db, org_id, created_by) -> int:
    """One closed count that found something, because a clean count proves nothing.

    A stock take whose lines all agree exercises none of the machinery the
    module exists for — the discrepancy column, the reason code, the tolerance
    gate. This one is short on two lines and over on one.
    """
    from app.modules.stock_takes.models import (
        StockTake,
        StockTakeDiscrepancyCode,
        StockTakeStatus,
    )

    if (
        db.query(StockTake)
        .filter(
            StockTake.organization_id == org_id,
            StockTake.name.like(f'{SEED_PREFIX}%'),
        )
        .count()
    ):
        return 0

    location = (
        db.query(StorageLocation)
        .filter(
            StorageLocation.organization_id == org_id,
            StorageLocation.name == 'Dry Goods',
        )
        .first()
    )
    if location is None:
        return 0

    rows = (
        db.query(Item)
        .filter(
            Item.organization_id == org_id,
            Item.is_deleted.is_(False),
            Item.storage_location_id.in_(
                db.query(StorageLocation.id).filter(
                    StorageLocation.parent_id == location.id
                )
            ),
        )
        .limit(8)
        .all()
    )
    if not rows:
        return 0

    take = StockTake(
        id=uuid.uuid4(),
        organization_id=org_id,
        storage_location_id=location.id,
        user_id=created_by,
        name=f'{SEED_PREFIX}{DEMO_STOCK_TAKE_TITLE}',
        description=DEMO_STOCK_TAKE_DESCRIPTION,
        status=StockTakeStatus.COMPLETED,
        started_at=datetime.now(UTC) - timedelta(days=3, hours=2),
        completed_at=datetime.now(UTC) - timedelta(days=3),
        blind_mode=False,
        require_full_count=True,
        tolerance_percent=Decimal('2.00'),
    )
    db.add(take)
    db.flush()

    #: (index into rows, what the counter found relative to the system)
    differences = {0: Decimal('-1'), 3: Decimal('-2'), 5: Decimal('1')}
    reasons = {
        0: StockTakeDiscrepancyCode.MISCOUNT,
        3: StockTakeDiscrepancyCode.DAMAGE,
        5: StockTakeDiscrepancyCode.WRONG_LOCATION,
    }
    for index, item in enumerate(rows):
        delta = differences.get(index, Decimal('0'))
        counted = item.quantity + delta
        db.add(
            StockTakeItem(
                id=uuid.uuid4(),
                stock_take_id=take.id,
                item_id=item.id,
                item_name=item.name,
                item_brand=item.brand,
                uom_id=item.uom_id,
                system_quantity=item.quantity,
                counted_quantity=counted,
                is_discrepancy=1 if delta else 0,
                discrepancy_reason_code=reasons.get(index).value if delta else None,
            )
        )

    db.flush()
    return 1


#: (name, description, servings, prep minutes, tags, ingredient names)
#: The ingredients name products the food catalogue above really seeds, so the
#: "I can cook" filter has something true to answer with.
DEMO_RECIPES = [
    # (name, description, servings, minutes, tags, ingredients, instructions)
    #
    # An ingredient is (catalogue name, quantity) or (catalogue name, quantity,
    # unit symbol). Ingredient names are catalogue names, so each one resolves
    # to a template the food seed stocks. A line without a symbol is counted in
    # the template's own unit, which is right only for what is counted whole —
    # a can of chickpeas, a pack of eggs, an onion. Everything a cook weighs or pours is
    # stated the way a cook writes it: 200 g of spaghetti, 3 g of garlic, 40 g
    # of oil. Those were once fractions of the product's unit (0.1 of a 25 g
    # jar), and a recipe asks for whole units at their step, so every such
    # line read "1 pcs. - rounded up from 0.1" however many servings the
    # visitor chose and scaling looked broken. A line in grams still meets the
    # stock, which is kept in jars and bottles, through the weight the
    # template records for one of them. Liquids are in grams too: the template
    # records a bottle's weight, not its volume.
    #
    # Four names are deliberately not in the catalogue — Coconut Milk,
    # Parmesan, Onion, Fresh Basil — so four recipes come out as near misses
    # ("4 of 5 in stock") rather than every card reading 100%: "I can cook"
    # only means something next to a recipe it does not cover.
    (
        'Tomato and Chickpea Stew',
        'One pot, thirty minutes, everything from the pantry shelf.',
        4,
        30,
        ['quick', 'vegetarian'],
        [
            ('Canned Chickpeas', Decimal('2')),
            ('Tomato Passata', Decimal('500'), UOM_GRAM),
            ('Extra Virgin Olive Oil', Decimal('25'), UOM_GRAM),
            ('Sweet Paprika', Decimal('3'), UOM_GRAM),
        ],
        '1. Warm the oil and toast the paprika for thirty seconds.\n'
        '2. Add the passata and the drained chickpeas.\n'
        '3. Simmer for twenty minutes, season and serve with bread.',
    ),
    (
        'Spaghetti with Garlic and Oil',
        'The five-ingredient supper worth knowing by heart.',
        2,
        20,
        ['quick', 'pasta'],
        [
            ('Spaghetti 500g', Decimal('200'), UOM_GRAM),
            ('Extra Virgin Olive Oil', Decimal('40'), UOM_GRAM),
            ('Granulated Garlic', Decimal('3'), UOM_GRAM),
            ('Iodised Salt', Decimal('10'), UOM_GRAM),
        ],
        '1. Cook the spaghetti in well-salted water.\n'
        '2. Warm the oil gently with the garlic; do not let it brown.\n'
        '3. Toss the drained pasta in the oil with a splash of cooking water.',
    ),
    (
        'Chicken Curry with Jasmine Rice',
        'A weeknight curry from the freezer and the spice drawer.',
        4,
        40,
        ['dinner'],
        [
            ('Chicken Breast Fillet', Decimal('600'), UOM_GRAM),
            ('Jasmine Rice 1kg', Decimal('300'), UOM_GRAM),
            ('Curry Powder', Decimal('10'), UOM_GRAM),
            ('Peeled Tomatoes 400g', Decimal('1')),
            ('Coconut Milk', Decimal('400'), UOM_ML),
        ],
        '1. Brown the diced chicken, then stir in the curry powder.\n'
        '2. Add the tomatoes and coconut milk; simmer for twenty minutes.\n'
        '3. Serve over the rice.',
    ),
    (
        'Penne with Red Pesto',
        'Fifteen minutes, one pan, no chopping board.',
        2,
        15,
        ['quick', 'pasta', 'vegetarian'],
        [
            ('Penne Pasta', Decimal('200'), UOM_GRAM),
            ('Red Pesto', Decimal('90'), UOM_GRAM),
            ('Cherry Tomatoes', Decimal('250'), UOM_GRAM),
            ('Parmesan', Decimal('40'), UOM_GRAM),
        ],
        '1. Cook the penne.\n'
        '2. Halve the tomatoes and warm them in the pesto.\n'
        '3. Toss with the pasta and finish with grated parmesan.',
    ),
    (
        'Overnight Oats with Blueberries',
        'Made the evening before, eaten on the way out.',
        2,
        10,
        ['breakfast', 'vegetarian'],
        [
            ('Rolled Oats', Decimal('100'), UOM_GRAM),
            ('Natural Yoghurt 400g', Decimal('300'), UOM_GRAM),
            ('Frozen Blueberries', Decimal('120'), UOM_GRAM),
            ('Wildflower Honey', Decimal('20'), UOM_GRAM),
        ],
        '1. Stir the oats into the yoghurt with a spoon of honey.\n'
        '2. Fold in the blueberries straight from the freezer.\n'
        '3. Cover and leave in the fridge overnight.',
    ),
    (
        'Banana Bread',
        'What the bananas going brown on the counter are for.',
        8,
        70,
        ['baking'],
        [
            ('Bananas', Decimal('500'), UOM_GRAM),
            ('Wheat Flour Type 550', Decimal('250'), UOM_GRAM),
            ('White Sugar 1kg', Decimal('150'), UOM_GRAM),
            ('Eggs Medium 10pk', Decimal('1')),
            ('Butter Extra 82%', Decimal('100'), UOM_GRAM),
            ('Baking Powder', Decimal('8'), UOM_GRAM),
            ('Walnuts', Decimal('100'), UOM_GRAM),
        ],
        '1. Mash the bananas and beat in the melted butter, sugar and eggs.\n'
        '2. Fold in the flour, baking powder and chopped walnuts.\n'
        '3. Bake in a lined loaf tin at 175 C for about an hour.',
    ),
    (
        'Shakshuka',
        'Eggs poached in a spiced tomato sauce, straight from the pan.',
        2,
        25,
        ['breakfast', 'vegetarian'],
        [
            ('Eggs Medium 10pk', Decimal('1')),
            ('Peeled Tomatoes 400g', Decimal('1')),
            ('Sweet Paprika', Decimal('3'), UOM_GRAM),
            ('Extra Virgin Olive Oil', Decimal('25'), UOM_GRAM),
            ('Onion', Decimal('1')),
        ],
        '1. Soften the sliced onion in the oil with the paprika.\n'
        '2. Add the tomatoes and simmer until thick.\n'
        '3. Make four wells, crack in the eggs, cover and cook until set.',
    ),
    (
        'Pancakes with Strawberries',
        'Saturday breakfast, twelve thin pancakes.',
        4,
        30,
        ['breakfast'],
        [
            ('Wheat Flour Type 550', Decimal('250'), UOM_GRAM),
            ('UHT Milk 3.2%', Decimal('500'), UOM_GRAM),
            ('Eggs Medium 10pk', Decimal('1')),
            ('Strawberries', Decimal('300'), UOM_GRAM),
            ('Sunflower Oil', Decimal('25'), UOM_GRAM),
        ],
        '1. Whisk the flour, milk and eggs into a thin batter; rest it ten minutes.\n'
        '2. Fry in a lightly oiled pan, a ladle at a time.\n'
        '3. Serve with sliced strawberries.',
    ),
    (
        'Tuna Pasta Salad',
        'A lunchbox that keeps until Wednesday.',
        3,
        20,
        ['quick', 'pasta'],
        [
            ('Fusilli Pasta', Decimal('300'), UOM_GRAM),
            ('Tuna in Oil', Decimal('1')),
            ('Canned Sweetcorn', Decimal('1')),
            ('Mayonnaise', Decimal('75'), UOM_GRAM),
            ('Cucumber', Decimal('1')),
            ('Fresh Basil', Decimal('10'), UOM_GRAM),
        ],
        '1. Cook the fusilli and cool it under running water.\n'
        '2. Mix with the tuna, sweetcorn, diced cucumber and mayonnaise.\n'
        '3. Tear the basil over the top before serving.',
    ),
]


def _create_recipes_demo(db, org_id, created_by) -> int:
    """Recipes cooked from the shelf this seed just filled, and a few near misses.

    The recipes module leads with an "I can cook" filter that reads stock. On
    an instance with no recipes at all the filter has nothing to be right or
    wrong about, and the module's whole idea goes unshown.
    """
    from app.modules.recipes._allergens import infer_allergens
    from app.modules.recipes.models.recipe import Recipe, RecipeIngredient

    if (
        db.query(Recipe)
        .filter(Recipe.organization_id == org_id)
        .filter(Recipe.name.in_([name for name, *_rest in DEMO_RECIPES]))
        .count()
    ):
        return 0

    templates = {
        row[0]: (row[1], row[2])
        for row in db.query(
            ProductTemplate.name, ProductTemplate.id, ProductTemplate.uom_id
        )
        .filter(ProductTemplate.organization_id == org_id)
        .all()
    }

    uom_ids = _resolve_uom_ids(db)

    created = 0
    for (
        name,
        description,
        servings,
        minutes,
        tags,
        ingredients,
        instructions,
    ) in DEMO_RECIPES:
        recipe = Recipe(
            id=uuid.uuid4(),
            organization_id=org_id,
            name=name,
            description=description,
            instructions=instructions,
            servings=servings,
            prep_time_minutes=minutes,
            tags=tags,
            created_by=created_by,
        )
        db.add(recipe)
        db.flush()

        for sort_order, (ingredient_name, quantity, *symbol) in enumerate(ingredients):
            template_id, uom_id = templates.get(ingredient_name, (None, None))
            if symbol:
                uom_id = uom_ids[symbol[0]]
            # A line named only by a count is counted in pieces: with no
            # unit it read "Onion 1" on the recipe and "1 —" on the list.
            uom_id = uom_id or uom_ids[UOM_PIECE]
            db.add(
                RecipeIngredient(
                    id=uuid.uuid4(),
                    recipe_id=recipe.id,
                    template_id=template_id,
                    uom_id=uom_id,
                    name=ingredient_name,
                    quantity=quantity,
                    sort_order=sort_order,
                    # Written straight to the table, so the form's suggestion
                    # never ran: ask the same inference the form asks.
                    allergens=infer_allergens(ingredient_name),
                )
            )
        created += 1

    db.flush()
    return created


DEMO_MEAL_PLAN_NAME = 'This week'
DEMO_SHOPPING_LIST_NAME = 'Weekly shop'

#: (weekday offset from Monday, slot, recipe name). Breakfast and dinner only —
#: a plan with every slot filled reads as a template nobody lives by.
DEMO_MEAL_PLAN = [
    (0, 'BREAKFAST', 'Overnight Oats with Blueberries'),
    (0, 'DINNER', 'Tomato and Chickpea Stew'),
    (1, 'DINNER', 'Spaghetti with Garlic and Oil'),
    (2, 'BREAKFAST', 'Overnight Oats with Blueberries'),
    (2, 'DINNER', 'Chicken Curry with Jasmine Rice'),
    (3, 'DINNER', 'Tuna Pasta Salad'),
    (4, 'DINNER', 'Penne with Red Pesto'),
    (5, 'BREAKFAST', 'Pancakes with Strawberries'),
    (5, 'DINNER', 'Shakshuka'),
    (6, 'BREAKFAST', 'Banana Bread'),
]

#: What the plan above is short of — the ingredients no shelf holds — plus two
#: staples, so the list reads as a real week's shop rather than a diff.
#: (name, quantity, note)
DEMO_SHOPPING_ITEMS = [
    ('Coconut Milk', Decimal('1'), 'For the curry on Wednesday'),
    ('Parmesan', Decimal('1'), 'For the penne on Friday'),
    ('Onion', Decimal('3'), 'Shakshuka on Saturday'),
    ('Fresh Basil', Decimal('1'), 'Tuna pasta salad'),
    ('UHT Milk 3.2%', Decimal('2'), None),
    ('Bananas', Decimal('1'), None),
]


def _create_meal_plan_demo(db, org_id, created_by, *, with_list=True) -> int:
    """This week's plan, cooked from the seeded recipes, and the shop it needs.

    The meal planner opens on the current week. Empty, it shows a grid of
    blank slots and says nothing about what the module does with them; the
    shopping list beside it is where the planner meets the pantry, so the two
    are seeded together and linked the way the planner links them.
    """
    from app.modules.recipes.models.meal_plan import MealPlan, MealPlanEntry
    from app.modules.recipes.models.recipe import Recipe
    from app.modules.shopping_lists.models import ShoppingList, ShoppingListItem

    if (
        db.query(MealPlan)
        .filter(
            MealPlan.organization_id == org_id,
            MealPlan.name == DEMO_MEAL_PLAN_NAME,
        )
        .count()
    ):
        return 0

    recipes = dict(
        db.query(Recipe.name, Recipe.id).filter(Recipe.organization_id == org_id).all()
    )
    if not recipes:
        return 0

    templates = {
        name: (template_id, uom_id)
        for name, template_id, uom_id in db.query(
            ProductTemplate.name, ProductTemplate.id, ProductTemplate.uom_id
        )
        .filter(ProductTemplate.organization_id == org_id)
        .all()
    }

    shopping_list = None
    if with_list:
        shopping_list = ShoppingList(
            id=uuid.uuid4(),
            organization_id=org_id,
            name=DEMO_SHOPPING_LIST_NAME,
            created_by=created_by,
        )
        db.add(shopping_list)
        db.flush()
    piece = _resolve_uom_ids(db)[UOM_PIECE] if shopping_list else None
    for name, quantity, note in DEMO_SHOPPING_ITEMS if shopping_list else ():
        template_id, uom_id = templates.get(name, (None, None))
        # The four names no shelf holds have no product to take a unit from;
        # a count is what they are, so they say "1 pcs", never "1 —".
        uom_id = uom_id or piece
        db.add(
            ShoppingListItem(
                id=uuid.uuid4(),
                shopping_list_id=shopping_list.id,
                template_id=template_id,
                uom_id=uom_id,
                name=name,
                quantity=quantity,
                notes=note,
                source='manual',
            )
        )

    monday = TODAY - timedelta(days=TODAY.weekday())
    plan = MealPlan(
        id=uuid.uuid4(),
        organization_id=org_id,
        name=DEMO_MEAL_PLAN_NAME,
        start_date=monday,
        end_date=monday + timedelta(days=6),
        enabled_slots=['BREAKFAST', 'DINNER'],
        shopping_list_id=shopping_list.id if shopping_list else None,
        created_by=created_by,
    )
    db.add(plan)
    db.flush()
    for offset, slot, recipe_name in DEMO_MEAL_PLAN:
        recipe_id = recipes.get(recipe_name)
        if recipe_id is None:
            continue
        db.add(
            MealPlanEntry(
                id=uuid.uuid4(),
                meal_plan_id=plan.id,
                date=monday + timedelta(days=offset),
                slot=slot,
                recipe_id=recipe_id,
                order=0,
            )
        )
    db.flush()
    return 1


def _clean_module_extras(db, org_id) -> None:
    """Remove the records the module seeders above wrote.

    Equipment assignments go with the items they point at (the foreign key
    cascades) and production orders are already deleted further down, before
    the template they output. Stock takes and recipes have neither, so a
    ``--clean`` that skipped them left the seeder's own idempotence guards
    satisfied on an organization that no longer held the rows — the next run
    reported success and seeded neither. The meal plan and its shopping list
    are the same case; maintenance logs cascade with their items.
    """
    from app.modules.recipes.models.meal_plan import MealPlan
    from app.modules.recipes.models.recipe import Recipe, RecipeIngredient
    from app.modules.shopping_lists.models import ShoppingList
    from app.modules.stock_takes.models import StockTake

    # Entries cascade with the plan, items with the list.
    db.query(MealPlan).filter(
        MealPlan.organization_id == org_id,
        MealPlan.name == DEMO_MEAL_PLAN_NAME,
    ).delete(synchronize_session=False)
    db.query(ShoppingList).filter(
        ShoppingList.organization_id == org_id,
        ShoppingList.name == DEMO_SHOPPING_LIST_NAME,
    ).delete(synchronize_session=False)

    take_ids = [
        row[0]
        for row in db.query(StockTake.id)
        .filter(
            StockTake.organization_id == org_id,
            StockTake.name.like(f'{SEED_PREFIX}%'),
        )
        .all()
    ]
    if take_ids:
        db.query(StockTakeItem).filter(
            StockTakeItem.stock_take_id.in_(take_ids)
        ).delete(synchronize_session=False)
        db.query(StockTake).filter(StockTake.id.in_(take_ids)).delete(
            synchronize_session=False
        )

    recipe_ids = [
        row[0]
        for row in db.query(Recipe.id)
        .filter(
            Recipe.organization_id == org_id,
            Recipe.name.in_([name for name, *_rest in DEMO_RECIPES]),
        )
        .all()
    ]
    if recipe_ids:
        db.query(RecipeIngredient).filter(
            RecipeIngredient.recipe_id.in_(recipe_ids)
        ).delete(synchronize_session=False)
        db.query(Recipe).filter(Recipe.id.in_(recipe_ids)).delete(
            synchronize_session=False
        )


def clean_seed_data(db, org_id):
    prefix_pattern = f'{SEED_PREFIX}%'

    _clean_module_extras(db, org_id)

    doc_ids = _seeded_document_ids(db, org_id)
    if doc_ids:
        db.query(DocumentLine).filter(DocumentLine.document_id.in_(doc_ids)).delete(
            synchronize_session=False
        )
        db.query(Document).filter(Document.id.in_(doc_ids)).delete(
            synchronize_session=False
        )

    # Deleted records too: they still point at the templates removed below,
    # and the guard that sends the reader here counts them.
    items_count = (
        db.query(Item)
        .filter(Item.organization_id == org_id)
        .delete(synchronize_session=False)
    )

    # Production orders point at the template they output, so they have to go
    # before it. The comment that used to stand further down named
    # ``output_storage_location_id`` as the dependency and left these alone —
    # the constraint that actually fires is ``output_template_id``, which made
    # --clean an unrecoverable ForeignKeyViolation on any org that had ever run
    # a production order.
    order_count = (
        db.query(ProductionOrder)
        .filter(ProductionOrder.organization_id == org_id)
        .delete(synchronize_session=False)
    )

    pt_count = (
        db.query(ProductTemplate)
        .filter(
            ProductTemplate.organization_id == org_id,
        )
        .delete(synchronize_session=False)
    )

    loc_ids = [
        row[0]
        for row in db.query(StorageLocation.id)
        .filter(
            StorageLocation.organization_id == org_id,
            StorageLocation.short_code.like(prefix_pattern),
        )
        .all()
    ]

    partner_count = (
        db.query(Partner)
        .filter(
            Partner.organization_id == org_id,
            or_(*[Partner.code == p[2] for p in DEMO_PARTNERS]),
        )
        .delete(synchronize_session=False)
    )

    loc_count = 0
    for loc_id in loc_ids:
        db.query(StorageLocation).filter(StorageLocation.id == loc_id).delete(
            synchronize_session=False
        )
        loc_count += 1

    # BoM lines cascade from the templates, so they need no pass of their own.
    db.commit()
    print(
        f'Cleaned: {len(doc_ids)} documents, {items_count} items, '
        f'{order_count} production orders, '
        f'{pt_count} templates, {loc_count} locations, {partner_count} partners'
    )


#: What a full run can hand an organization, by the module that owns it.
#: A run narrowed to a profile's modules seeds the rest of the list not at all,
#: rather than seeding rows into a module the organization does not run.
SEEDED_MODULES = frozenset(
    {
        'maker',
        'partners',
        'equipment',
        'warehouse',
        'purchase_orders',
        'stock_takes',
        'recipes',
        'shopping_lists',
    }
)


def _seed_starting_catalogues(db, org_id, enabled, say):
    """Categories, storage types and units this organization files things under.

    Both starter profiles are applied whatever the organization runs on: a
    product is filed under a category, the templates below name both kinds,
    and a profile that declares only one of the two used to stop the run dead
    rather than seed less. They are additive — categories, storage types and
    units — and switch no module on.
    """
    say('Ensuring seed profiles (food_home, equipment_wms)...')
    # Both profiles seed categories and storage types that belong to one
    # tenant, so they need the org this run targets — the parameter became
    # required when seeding moved per organization, and these two calls
    # were left behind, which made `make db-seed-demo` a TypeError.
    seed_food_home(db, organization_id=org_id, insert_only=True, commit=False)
    seed_equipment_wms(db, organization_id=org_id, insert_only=True, commit=False)
    db.commit()
    # This one is not additive — it runs the module's system on-enable hook —
    # so it is asked for only where the module is already part of the org.
    if 'equipment' in enabled:
        _ensure_module_catalogues(org_id)

    uom_ids = _resolve_uom_ids(db)
    type_ids = _ensure_storage_types(db, org_id)
    # Two catalogues, asked for separately: the equipment module files its
    # records under categories tagged 'equipment', the food profile under
    # everything else, and both use the code 'other'.
    cat_ids = _resolve_category_ids(db, org_id)
    equip_cat_ids = _resolve_category_ids(db, org_id, catalogue='equipment')
    say(
        f'  Types: {len(type_ids)} storage types, categories: '
        f'{len(cat_ids)} general + {len(equip_cat_ids)} equipment'
    )
    return uom_ids, type_ids, cat_ids, equip_cat_ids


def _number_the_walk(db, org_id, locations) -> None:
    """Give every shelf of the organization its place in the walk.

    Picking orders its lines by the sequence path of each line's shelf —
    the site's number, then the zone's, then the shelf's — so a demo whose
    locations carry no number is walked in the order its shelf codes happen
    to spell, and those codes are drawn at random. Numbered in the order the
    seed builds them, the pick order of a session over several dispatches is
    the walk of this warehouse, and the Spaces list shows the same order.

    What the seed did not build — the roots a profile put down before it, in
    an organization that onboarded first — takes the numbers after the walk:
    a location a visitor opens should not be the one place with no number.
    """
    for position, location in enumerate(locations.values(), start=1):
        location.sequence = position
    db.flush()
    elsewhere = (
        db.query(StorageLocation)
        .filter(
            StorageLocation.organization_id == org_id,
            StorageLocation.sequence.is_(None),
        )
        .order_by(StorageLocation.name, StorageLocation.id)
        .all()
    )
    for position, location in enumerate(elsewhere, start=len(locations) + 1):
        location.sequence = position
    db.flush()


def _seed_structure(db, org_id, created_by, uom_ids, type_ids, say):
    """The shelves and the catalogue entries — what every later step names."""
    say('Creating storage hierarchy...')
    locations = {}
    locations.update(
        _create_hierarchy(db, org_id, created_by, FOOD_HIERARCHY, type_ids)
    )
    locations.update(
        _create_hierarchy(db, org_id, created_by, EQUIPMENT_HIERARCHY, type_ids)
    )
    _number_the_walk(db, org_id, locations)
    db.commit()
    say(f'  Created: {len(locations)} locations')

    say('Creating product templates...')
    food_templates = _create_food_templates(db, org_id, uom_ids)
    equip_templates = _create_equipment_templates(db, org_id, uom_ids)
    db.commit()
    say(
        f'  Created: {len(food_templates)} food + '
        f'{len(equip_templates)} equipment templates'
    )
    return locations, food_templates, equip_templates


def _ensure_seedable(db, org_id, *, clean: bool) -> None:
    """Refuse to seed on top of an organization that already carries items.

    A second run used to die halfway through a uniqueness constraint —
    the organization left half populated, every later
    measurement on it unreproducible, and nothing in the final state
    saying so. A seed that cannot run says so before it writes anything,
    and names the way out.
    """
    if clean:
        return
    existing = db.query(Item).filter(Item.organization_id == org_id).count()
    if existing:
        # Deleted records live only in the Archived tab; a count that
        # includes them without saying so reads as a number from nowhere.
        archived = (
            db.query(Item)
            .filter(Item.organization_id == org_id, Item.is_deleted.is_(True))
            .count()
        )
        held = f'{existing} item(s)'
        if archived:
            held += f', {archived} of them archived (Products → Archived)'
        print(
            f'ERROR: the organization already holds {held}. '
            'Refusing to seed demo data on top of them. '
            'Use --clean to remove the seed data first.'
        )
        sys.exit(1)


def _seed_module_extras(db, org_id, created_by, enabled, maker_ids, say) -> dict:
    """The records that only make sense once the rest of the seed exists.

    Each of these reads rows the earlier steps wrote — assets to issue, a
    template to produce, shelves to count, a catalogue to cook from — so they
    run last, and each is skipped when its module is off rather than writing
    rows into a module the organization does not run.
    """
    steps = (
        (
            'equipment',
            'equipment_assignments',
            'equipment assignments',
            lambda: _create_assignments_demo(db, org_id, created_by),
        ),
        (
            'maker',
            'production_runs',
            'completed production run(s)',
            lambda: _create_production_demo(db, org_id, created_by, maker_ids),
        ),
        (
            'stock_takes',
            'stock_takes',
            'closed stock take(s)',
            lambda: _create_stock_take_demo(db, org_id, created_by),
        ),
        (
            'recipes',
            'recipes',
            'recipes',
            lambda: _create_recipes_demo(db, org_id, created_by),
        ),
        (
            'recipes',
            'meal_plans',
            'meal plan(s) with a shopping list',
            lambda: _create_meal_plan_demo(
                db, org_id, created_by, with_list='shopping_lists' in enabled
            ),
        ),
        (
            'equipment',
            'maintenance_logs',
            'maintenance log(s)',
            lambda: _create_maintenance_demo(db, org_id, created_by),
        ),
    )

    result = {}
    for module, key, label, seed in steps:
        count = 0
        if module in enabled:
            count = seed()
            db.commit()
            say(f'  Created: {count} {label}')
        result[key] = count
    return result


def _run_on_own_engine(work):
    """Run *work(async_session)* to completion on an engine of its own.

    The core calls are async and this script is not. Not
    ``init_async_engine``, which rebinds the application's session factory
    for whatever else runs in the process.
    """
    import asyncio

    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )
    from sqlalchemy.pool import NullPool

    from app.config import settings
    from app.database import _build_async_url

    async def _run():
        engine = create_async_engine(
            _build_async_url(settings.DATABASE_URL), poolclass=NullPool
        )
        try:
            async with async_sessionmaker(engine, class_=AsyncSession)() as adb:
                return await work(adb)
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def _opened_at(day: date, index: int) -> datetime:
    """A working-hours moment on *day*, so a shelf's history reads like one."""
    return datetime.combine(day, time(hour=7 + index % 10, minute=index * 7 % 60), UTC)


def _open_the_shelves(org_id, created_by) -> int:
    """Put every seeded record's stock in the register, the way the app does.

    This seed used to write a quant per shelf itself: the records and the
    quants agreed, and nothing else did — no movement said where the stock
    came from and no cost layer stood behind it, so the reconciliation
    report on the demo's Statistics page named hundreds of groups in its
    second and third pairs, a drift no path of the application had made.

    A record's stock is opened the way the application opens stock it did
    not receive: through the core movement call, one ``opening_balance``
    movement per record pointing at it, and a cost layer at the record's
    purchase price (unpriced, and so valued at the organization's rate,
    where there is none). Records that already opened are left alone, so a
    run that tops the volume up opens only what it added.

    Both are dated the day the record arrived (``added_date``). Opened at the
    minute of seeding, every product's history was one line dated today, and
    the stock-as-of report found an empty warehouse a day earlier.
    """
    from sqlalchemy import select, update

    from app.core.public_api import core_api
    from app.models.stock_move import StockMove, StockMoveReferenceType

    opened_already = select(StockMove.reference_id).where(
        StockMove.organization_id == org_id,
        StockMove.reference_type == StockMoveReferenceType.OPENING_BALANCE,
        StockMove.reference_id.is_not(None),
    )
    unopened = (
        select(
            Item.id,
            Item.template_id,
            Item.storage_location_id,
            Item.quantity,
            Item.purchase_price,
            Item.added_date,
        )
        .where(
            Item.organization_id == org_id,
            Item.is_deleted.is_(False),
            Item.template_id.is_not(None),
            Item.storage_location_id.is_not(None),
            Item.quantity > 0,
            Item.id.not_in(opened_already),
        )
        .order_by(Item.created_at, Item.id)
    )

    async def _open(adb) -> int:
        records = (await adb.execute(unopened)).all()
        for index, record in enumerate(records):
            await core_api.stock.post_movement_async(
                adb,
                org_id,
                record.template_id,
                record.quantity,
                to_location_id=record.storage_location_id,
                reference_type=StockMoveReferenceType.OPENING_BALANCE,
                reference_id=record.id,
                created_by=created_by,
            )
            arrived = record.added_date or TODAY
            moved_at = _opened_at(arrived, index)
            await adb.execute(
                update(StockMove)
                .where(
                    StockMove.organization_id == org_id,
                    StockMove.reference_type == StockMoveReferenceType.OPENING_BALANCE,
                    StockMove.reference_id == record.id,
                )
                .values(created_at=moved_at, completed_at=moved_at)
            )
            if record.purchase_price:
                await core_api.valuation.record_receipt_async(
                    adb,
                    org_id,
                    record.template_id,
                    record.quantity,
                    record.purchase_price,
                    document_date=arrived,
                )
            else:
                await core_api.valuation.record_unpriced_receipt_async(
                    adb, org_id, record.template_id, record.quantity
                )
        await adb.commit()
        return len(records)

    return _run_on_own_engine(_open)


def seed_organization(db, org_id, created_by, *, items, modules=None, report=None):
    """Seed one organization to the demo state, as far as its modules go.

    This is the whole sequence — catalogues, hierarchy, templates, records,
    documents, orders — and it has two callers: this script's ``main`` and the
    QA fixture's ``many`` variant. They used to carry a copy each, and the
    copies were not the same one: the fixture's stopped at food products, so
    ``--variant many`` under a warehouse profile crashed on food categories
    that profile never declares, and under the food profile produced volume
    with no document behind it.

    ``modules`` is the set of module ids the organization actually runs;
    ``None`` asks for everything. Records belonging to a module that is off
    are not written: they would be invisible in the product and would still
    have to be explained by whoever reads the database.

    Both starter catalogues are seeded whatever the profile, because a product
    is filed under a category and the templates here name both kinds. That is
    additive — categories, storage types and units, no module is switched on
    by it.

    Volume is topped up to *items*, not added to it, so a second run leaves
    the same organization rather than twice the one it found.

    The refusal to seed on top of existing items lives in ``main``, not here,
    on purpose: this function is a re-runnable top-up, and the fixture's
    ``many`` variant wipes the organization itself before calling it, so a
    guard on the operation would refuse exactly the runs that are meant to
    succeed. ``main`` is where an operator can run it by mistake.
    """
    say = report if report is not None else (lambda _message: None)
    enabled = SEEDED_MODULES if modules is None else set(modules)

    uom_ids, type_ids, cat_ids, equip_cat_ids = _seed_starting_catalogues(
        db, org_id, enabled, say
    )
    locations, food_templates, equip_templates = _seed_structure(
        db, org_id, created_by, uom_ids, type_ids, say
    )

    maker_ids: dict[str, uuid.UUID] = {}
    if 'maker' in enabled:
        say('Creating maker demo recipe...')
        maker_ids = _create_maker_demo(db, org_id)
        db.commit()

    partners = []
    if 'partners' in enabled:
        say('Creating supplier partners...')
        partners = _create_partners(db, org_id, created_by)
        db.commit()
        say(f'  Created: {len(partners)} partners')

    existing = db.query(Item).filter(Item.organization_id == org_id).count()
    missing = max(0, items - existing)
    food_items = 0
    if missing:
        say(f'Creating {missing} food items...')
        food_items = _create_food_items(
            db, org_id, created_by, food_templates, locations, missing, cat_ids
        )
        db.commit()
        say(f'  Created: {food_items} food items')

    equip_items = 0
    if 'equipment' in enabled:
        say('Creating equipment items...')
        equip_items = _create_equipment_items(
            db, org_id, created_by, equip_templates, locations, uom_ids, equip_cat_ids
        )
        db.commit()
        say(f'  Created: {equip_items} equipment items')

    workshop_items = 0
    if maker_ids:
        workshop_items = _stock_the_workshop(db, org_id, maker_ids)
        db.commit()
        say(f'  Stocked: {workshop_items} ingredient(s) for the workshop')

    opened = _open_the_shelves(org_id, created_by)
    say(f'  Opened: {opened} records on the shelves, movement and cost layer each')

    documents = 0
    if 'warehouse' in enabled:
        documents = _seed_documents_demo(
            db, org_id, created_by, food_templates, equip_templates, locations, say
        )

    orders = 0
    if 'purchase_orders' in enabled:
        say('Creating demo purchase orders...')
        orders = _create_purchase_orders_demo(
            db, org_id, created_by, equip_templates, locations
        )
        db.commit()
        # The order's receipt is a completed document like the others: post
        # the stock it says it brought.
        _execute_the_seeded_documents(org_id, created_by)
        say(f'  Created: {orders} purchase orders')

    # Both the documents and the order's receipt are down: number them in the
    # order they happened.
    if _number_the_seeded_documents_by_date(db, org_id):
        db.commit()

    extras = _seed_module_extras(db, org_id, created_by, enabled, maker_ids, say)

    return {
        'storage_locations': len(locations),
        'product_templates': len(food_templates) + len(equip_templates),
        'partners': len(partners),
        'items_added': food_items + equip_items + workshop_items,
        'items_total': existing + food_items + equip_items + workshop_items,
        'documents': documents,
        'purchase_orders': orders,
        **extras,
    }


def seed_from_cli(*, items: int, admin_email: str = ADMIN_EMAIL, report=print) -> dict:
    """Seed the admin's organization and return the summary, for ``manage.py``.

    ``main`` below is the argparse entry point this script has always had; the
    demo reset needs the same sequence without the argument parsing or the
    ``sys.exit`` on failure, and duplicating it is how the QA fixture and this
    script drifted apart the last time. The email is the account the caller
    created — the demo now chooses its own administrator, so seeding targets
    that account rather than the address this script was written around.
    """
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == admin_email).first()
        if not user or not user.organization_id:
            raise RuntimeError(
                f'{admin_email} not found — create the account before seeding.'
            )
        summary = seed_organization(
            db, user.organization_id, user.id, items=items, report=report
        )
        db.commit()
        return summary
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description='Seed demo data for manual testing')
    parser.add_argument(
        '--items',
        type=int,
        default=500,
        help='Number of food items to create (default: 500)',
    )
    parser.add_argument(
        '--clean', action='store_true', help='Remove all seed data before seeding'
    )
    parser.add_argument(
        '--dry-run', action='store_true', help='Show plan without creating data'
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == ADMIN_EMAIL).first()
        if not user or not user.organization_id:
            print(f'ERROR: {ADMIN_EMAIL} not found. Run: make create-admin first.')
            sys.exit(1)
        org_id = user.organization_id
        created_by = user.id

        # Before anything is written: demo data on top of existing items is
        # a refusal, not a crash halfway through.
        _ensure_seedable(db, org_id, clean=args.clean)

        if args.clean:
            print('Cleaning existing seed data...')
            clean_seed_data(db, org_id)

        print('\n=== Demo Data Seed Plan ===')
        print(f'Org: {org_id}')
        print(f'User: {user.email} (created_by)')
        print(f'Food items target: {args.items}')
        print('Storage hierarchy: 2 food sites, 1 equipment site')
        print(
            f'Product templates: ~{len(FOOD_TEMPLATES)} food + {len(EQUIPMENT_TEMPLATES)} equipment'
        )
        print(f'Partners: {len(DEMO_PARTNERS)}')
        print()

        if args.dry_run:
            print('[DRY RUN] No data created.')
            return

        summary = seed_organization(
            db, org_id, created_by, items=args.items, report=print
        )

        print(f'\n{"=" * 40}')
        print('SEED COMPLETE')
        print(f'  Locations:         {summary["storage_locations"]}')
        print(f'  Product templates: {summary["product_templates"]}')
        print(f'  Partners:          {summary["partners"]}')
        print(f'  Items:             {summary["items_total"]}')
        print(f'  Documents:         {summary["documents"]}')
        print(f'  Purchase orders:   {summary["purchase_orders"]}')
        print(f'{"=" * 40}')
        # The account itself is created by `make dev-up` / `make create-admin`
        # from DEV_ADMIN_PASSWORD; repeating the literal here is how the two
        # drifted apart in the first place.
        print('\nLogin: the credentials `make dev-up` printed (make print-dev-admin)')
        print(
            'Clean: docker compose exec backend uv run python seed_demo_data.py --clean'
        )

    except Exception as e:  # noqa: BLE001 — top-level script handler; prints the traceback
        db.rollback()
        print(f'\nERROR: {e}')
        import traceback

        traceback.print_exc()
        sys.exit(1)
    finally:
        db.close()


if __name__ == '__main__':
    main()
