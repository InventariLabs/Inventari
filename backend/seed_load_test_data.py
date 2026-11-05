"""
Seeds realistic data for k6 load-test organizations.

PROBLEM: /api/items performance is very different on an empty database
vs. a database with hundreds of products plus filtering, sorting, and pagination.
This script fills each k6 organization with a realistic amount of data.

Usage:
    # Seed data for all k6 orgs (default: 300 items/org)
    docker compose exec backend uv run python seed_load_test_data.py

    # Change number of items per org
    docker compose exec backend uv run python seed_load_test_data.py --items-per-org 500

    # Only first 10 orgs (quick test)
    docker compose exec backend uv run python seed_load_test_data.py --limit-orgs 10

    # Clean test data and start from scratch
    docker compose exec backend uv run python seed_load_test_data.py --clean

Realistic data distribution per organization:
    - 4 locations (Cold Storage, Freezer, Shelf A, Shelf B) — created with no
      storage_type, so the seeder is vertical-agnostic and works on any deployment
      (food, IT equipment, warehouse, …) without depending on pre-seeded StorageType rows
    - 300 items by default: ~35% Cold Storage, ~20% Freezer, ~30% Shelf A, ~15% Shelf B
    - 30% of items expire within 90 days (endpoint /api/items/expiring)
    - 15% of items are already expired (expired filtering tests)
    - Diverse names, brands, and barcodes to exercise SELECT with WHERE LIKE
"""

import argparse
import os
import random
import sys
import uuid
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.core.module_registry import module_registry
from app.database import SessionLocal
from app.models.item import Item
from app.models.organization import Organization
from app.models.storage_location import LocationUsage, StorageLocation
from app.models.uom import Uom
from app.models.user import User

# Standalone seeders bypass app.main startup, so module models — which core
# models reference via SQLAlchemy relationships — are never imported. Discover
# modules now so the mapper can resolve every relationship before the first query
# (otherwise the first query raises a mapper-configuration error).
module_registry.discover_modules()

K6_USER_PREFIX = 'k6user'
K6_ORG_PREFIX = 'LoadTest Org'

# --------------------------------------------------------------------------- #
# Test data: invented grocery products
# --------------------------------------------------------------------------- #
# The brands are made up and the names are plain English. Every barcode is an
# EAN-13 from the GS1 restricted-circulation range (prefixes 200-299), which is
# kept for use inside one store and printed on no product in general retail —
# so a public repository names no real company's product. The k6 scenario
# load_tests/scenarios/browse_and_scan.js scans some of these codes and searches
# for words in these names.

FRIDGE_ITEMS = [
    ('UHT milk 3.2%', 'Vellacrest', '2001000000012'),
    ('Plain yogurt', 'Orrindale', '2001000000029'),
    ('Butter 82%', 'Quenby Farm', '2001000000036'),
    ('Gouda cheese', 'Tamsworth', '2001000000043'),
    ('Sour cream 18%', 'Tamsworth', '2001000000050'),
    ('Cottage cheese', 'Orrindale', '2001000000067'),
    ('Sliced chicken ham', 'Fernwick', '2001000000074'),
    ('Pork sausages', 'Larkholt', '2001000000081'),
    ('Smoked sausage', 'Larkholt', '2001000000098'),
    ('Smoked bacon', 'Fernwick', '2001000000104'),
    ('Chicken breast fillet', 'Fernwick', '2001000000111'),
    ('Smoked salmon', 'Corrowick', '2001000000128'),
    ('Eggs, size M', 'Hennaby', '2001000000135'),
    ('Mayonnaise', 'Pellmore', '2001000000142'),
    ('Tomato ketchup', 'Pellmore', '2001000000159'),
    ('Wholegrain mustard', 'Pellmore', '2001000000166'),
    ('Orange juice, not from concentrate', 'Grenhollow', '2001000000173'),
    ('Chocolate milk drink', 'Vellacrest', '2001000000180'),
    ('Low-fat quark', 'Tamsworth', '2001000000197'),
    ('Classic hummus', 'Altonby', '2001000000203'),
    ('Red pesto', 'Dunmarra', '2001000000210'),
    ('Carrots', 'Marrowfield', None),
    ('Broccoli', 'Marrowfield', None),
    ('Cherry tomatoes', 'Grenhollow', None),
    ('Cucumber', 'Marrowfield', None),
    ('Fuji apples', 'Grenhollow', None),
    ('Green grapes', 'Grenhollow', None),
    ('Strawberries', 'Marrowfield', None),
]

FREEZER_ITEMS = [
    ('Vanilla ice cream', 'Frostmere', '2002000000019'),
    ('Frozen pepperoni pizza', 'Frostmere', '2002000000026'),
    ('Potato and cheese dumplings', 'Ivelbrook', '2002000000033'),
    ('Fish fingers', 'Corrowick', '2002000000040'),
    ('Whole frozen chicken', 'Fernwick', '2002000000057'),
    ('Frozen cod fillet', 'Corrowick', '2002000000064'),
    ('Frozen mixed vegetables', 'Ivelbrook', '2002000000071'),
    ('Frozen peas', 'Ivelbrook', '2002000000088'),
    ('Frozen fries', 'Frostmere', '2002000000095'),
    ('Minced pork', 'Larkholt', '2002000000101'),
    ('Frozen sweet buns', 'Cobbleworth', '2002000000118'),
    ('Frozen shakshuka', 'Altonby', None),
    ('Blanched spinach', 'Ivelbrook', '2002000000125'),
    ('Frozen blueberries', 'Frostmere', '2002000000132'),
    ('Frozen sour cherries', 'Frostmere', '2002000000149'),
]

PANTRY_ITEMS = [
    ('Sandwich bread', 'Cobbleworth', '2003000000016'),
    ('Wheat rolls', 'Cobbleworth', '2003000000023'),
    ('Spaghetti pasta 500g', 'Dunmarra', '2003000000030'),
    ('Penne pasta', 'Dunmarra', '2003000000047'),
    ('Jasmine rice 1kg', 'Selbrook Mills', '2003000000054'),
    ('Buckwheat groats', 'Selbrook Mills', '2003000000061'),
    ('Rolled oats', 'Selbrook Mills', '2003000000078'),
    ('Fruit muesli', 'Wenlow', '2003000000085'),
    ('Corn flakes', 'Wenlow', '2003000000092'),
    ('Wheat flour type 550', 'Selbrook Mills', '2003000000108'),
    ('White sugar 1kg', 'Altonby', '2003000000115'),
    ('Iodised salt', 'Altonby', '2003000000122'),
    ('Ground black pepper', 'Halvern', '2003000000139'),
    ('Extra virgin olive oil', 'Morvane', '2003000000146'),
    ('Sunflower oil', 'Morvane', '2003000000153'),
    ('Tomato passata', 'Halvern', '2003000000160'),
    ('Peeled tomatoes 400g', 'Halvern', '2003000000177'),
    ('Canned chickpeas', 'Halvern', '2003000000184'),
    ('Canned white beans', 'Halvern', '2003000000191'),
    ('Sweetcorn', 'Halvern', '2003000000207'),
    ('Tuna in oil', 'Corrowick', '2003000000214'),
    ('Sardines in tomato sauce', 'Corrowick', '2003000000221'),
    ('Chicken stock granules', 'Altonby', '2003000000238'),
    ('Instant tomato soup', 'Altonby', '2003000000245'),
    ('Earl Grey tea', 'Rosswade', '2003000000252'),
    ('Ground coffee', 'Rosswade', '2003000000269'),
    ('Coffee beans', 'Rosswade', '2003000000276'),
    ('Cocoa powder', 'Rosswade', '2003000000283'),
    ('Strawberry jam', 'Thistlecombe', '2003000000290'),
    ('Wildflower honey', 'Thistlecombe', '2003000000306'),
    ('Peanut butter', 'Wenlow', '2003000000313'),
    ('Apple cider vinegar', 'Morvane', '2003000000320'),
    ('Soy sauce', 'Pellmore', '2003000000337'),
    ('Tomato paste', 'Halvern', '2003000000344'),
    ('Salted potato crisps', 'Wenlow', '2003000000351'),
    ('Rice cakes', 'Wenlow', '2003000000368'),
    ('Butter biscuits', 'Cobbleworth', '2003000000375'),
    ('Dark chocolate 85%', 'Thistlecombe', '2003000000382'),
    ('Gelatine', 'Altonby', '2003000000399'),
    ('Baking powder', 'Altonby', '2003000000405'),
]

# --------------------------------------------------------------------------- #
# Location profiles (vertical-agnostic)
# --------------------------------------------------------------------------- #
# Each k6 organisation gets one location per profile. Profiles do NOT depend on
# any pre-seeded system StorageType rows — storage_type_id is left NULL so the
# seeder works on any vertical (food, IT equipment, warehouse, …). Each profile
# carries its own product pool, expiry-date distribution kind, and the share of
# items placed in it.
#
# 'expiry_kind' drives _random_expiry():
#   - 'frozen':     long shelf life (3–18 months)
#   - 'perishable': short shelf life, ~15% already expired
#   - 'dry':        ambient, same spread as 'perishable'
LOCATIONS = [
    # (name, location_details, expiry_kind, product_pool, weight)
    ('Cold Storage', 'Zone A', 'perishable', FRIDGE_ITEMS, 0.35),
    ('Freezer', 'Zone A', 'frozen', FREEZER_ITEMS, 0.20),
    ('Shelf A', 'Room', 'dry', PANTRY_ITEMS, 0.30),
    ('Shelf B', 'Room', 'dry', PANTRY_ITEMS, 0.15),
]

TODAY = date.today()


def _ean13(body: str) -> str:
    """Appends the EAN-13 check digit to a 12-digit body."""
    total = sum(int(digit) * (3 if i % 2 else 1) for i, digit in enumerate(body))
    return body + str(-total % 10)


def _random_restricted_ean() -> str:
    """A barcode for a product with none of its own (loose produce).

    Random, but inside the restricted-circulation range like the pooled codes:
    any 13 digits could be a real product's EAN.
    """
    return _ean13(f'29{random.randint(0, 10**10 - 1):010d}')


def _random_expiry(expiry_kind: str) -> date | None:
    """Returns a realistic expiry date for the given location profile kind."""
    r = random.random()
    if expiry_kind == 'frozen':
        # Freezer — long shelf life (3–18 months)
        if r < 0.10:
            return None  # no date
        return TODAY + timedelta(days=random.randint(30, 540))
    # Perishable / dry — shorter shelf life
    if r < 0.15:
        return TODAY - timedelta(days=random.randint(1, 60))  # 15% already expired
    if r < 0.45:
        return TODAY + timedelta(days=random.randint(1, 90))  # 30% expiring soon
    if r < 0.70:
        return TODAY + timedelta(days=random.randint(91, 365))  # 25% OK
    return None  # 30% no expiry date


def seed_org_data(db, org_id, items_per_org: int) -> int:
    """Creates locations + items for one organisation. Returns number of items created."""

    # Fetch the org's user (needed for created_by — StorageLocation.created_by is NOT NULL)
    org_user = db.query(User).filter(User.organization_id == org_id).first()
    created_by_id = org_user.id if org_user else None

    profile_by_name = {
        p[0]: (p[2], p[3]) for p in LOCATIONS
    }  # name -> (expiry_kind, pool)

    # Reuse locations created on a previous run (idempotent)
    existing_by_name = {
        loc.name: loc
        for loc in db.query(StorageLocation)
        .filter(
            StorageLocation.organization_id == org_id,
            StorageLocation.name.in_(profile_by_name),
        )
        .all()
    }

    # Build one (location, expiry_kind, pool) entry per profile
    loc_profiles: list[tuple[StorageLocation, str, list]] = []
    for name, location_details, expiry_kind, pool, _weight in LOCATIONS:
        loc = existing_by_name.get(name)
        if loc is None:
            loc = StorageLocation(
                id=uuid.uuid4(),
                organization_id=org_id,
                name=name,
                location_details=location_details,
                usage=LocationUsage.INTERNAL,
                created_by=created_by_id,
            )
            db.add(loc)
        loc_profiles.append((loc, expiry_kind, pool))

    db.flush()

    if not loc_profiles:
        return 0

    # Every product in the pools is counted in pieces, and 'pcs' rounds to 1 --
    # the API rejects fractional quantities for it.
    piece_uom_id = db.query(Uom.id).filter(Uom.symbol == 'pcs').scalar()
    if piece_uom_id is None:
        raise RuntimeError("UoM 'pcs' not found -- run the base seed first")

    # Count existing items (idempotent on re-run)
    existing_count = (
        db.query(Item)
        .filter(
            Item.organization_id == org_id,
            Item.is_deleted == False,  # noqa: E712
        )
        .count()
    )

    to_create = items_per_org - existing_count
    if to_create <= 0:
        return 0

    # Distribute items across locations (proportional to profile weights)
    weights = [p[4] for p in LOCATIONS]
    counts = []
    remaining = to_create
    for i, w in enumerate(weights):
        if i == len(weights) - 1:
            counts.append(remaining)
        else:
            n = max(0, round(to_create * w))
            counts.append(min(n, remaining))
            remaining -= n

    # An organization holds one active item per barcode
    # (uq_items_org_barcode_active), and products are drawn with replacement:
    # the first item of a product carries its EAN, a repeat carries none, and
    # loose produce gets an in-store code of its own. Codes from an earlier run
    # count as taken.
    taken_barcodes = {
        barcode
        for (barcode,) in db.query(Item.barcode).filter(
            Item.organization_id == org_id,
            Item.is_deleted.is_(False),
            Item.barcode.isnot(None),
        )
    }

    items_created = 0
    for (loc, expiry_kind, pool), n in zip(loc_profiles, counts, strict=True):
        for _ in range(n):
            product = random.choice(pool)
            name, brand, barcode = product
            if barcode is None:
                # Ten random digits collide now and then, and more often as
                # an organization fills up: draw again until the code is free.
                barcode = _random_restricted_ean()
                while barcode in taken_barcodes:
                    barcode = _random_restricted_ean()
            elif barcode in taken_barcodes:
                barcode = None
            if barcode is not None:
                taken_barcodes.add(barcode)

            # Small name variation to avoid exact duplicates
            if random.random() < 0.3:
                name = f'{name} {random.choice(["", "large", "Bio", "Organic", "light"]).strip()}'.strip()

            item = Item(
                id=uuid.uuid4(),
                organization_id=org_id,
                storage_location_id=loc.id,
                name=name,
                brand=brand,
                barcode=barcode,
                quantity=random.randint(1, 5),
                uom_id=piece_uom_id,
                expiry_date=_random_expiry(expiry_kind),
                is_deleted=False,
            )
            db.add(item)
            items_created += 1

    return items_created


def clean_data(db):
    """Deletes all items and locations for k6 organisations."""
    orgs = (
        db.query(Organization).filter(Organization.name.like(f'{K6_ORG_PREFIX}%')).all()
    )
    org_ids = [o.id for o in orgs]
    if not org_ids:
        print('No k6 orgs found — run seed_load_test_users.py first')
        return

    items_deleted = (
        db.query(Item)
        .filter(Item.organization_id.in_(org_ids))
        .delete(synchronize_session=False)
    )
    locs_deleted = (
        db.query(StorageLocation)
        .filter(StorageLocation.organization_id.in_(org_ids))
        .delete(synchronize_session=False)
    )
    db.commit()
    print(
        f'Deleted {items_deleted} items and {locs_deleted} locations for {len(org_ids)} orgs.'
    )


def main():
    parser = argparse.ArgumentParser(
        description='Seed k6 load test data (items + locations)'
    )
    parser.add_argument(
        '--items-per-org',
        type=int,
        default=300,
        help='Number of items per organisation (default: 300)',
    )
    parser.add_argument(
        '--limit-orgs',
        type=int,
        default=None,
        help='Limit to N orgs (default: all k6 orgs)',
    )
    parser.add_argument(
        '--clean', action='store_true', help='Clear existing test data before seeding'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be created without saving',
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        if args.clean and not args.dry_run:
            clean_data(db)

        # Fetch k6 organisations
        orgs = (
            db.query(Organization)
            .filter(Organization.name.like(f'{K6_ORG_PREFIX}%'))
            .order_by(Organization.name)
            .all()
        )

        if not orgs:
            print('❌ No k6 organisations found! Run first:')
            print(
                '   docker compose exec backend uv run python seed_load_test_users.py --count 100'
            )
            sys.exit(1)

        if args.limit_orgs:
            orgs = orgs[: args.limit_orgs]

        print(f'Found {len(orgs)} k6 orgs. Target: {args.items_per_org} items/org.')
        if args.dry_run:
            print(
                f'[DRY RUN] Would create ~{len(orgs) * args.items_per_org} items '
                f'and {len(orgs) * len(LOCATIONS)} locations.'
            )
            return

        total_items = 0
        batch_size = 10
        for i, org in enumerate(orgs):
            created = seed_org_data(db, org.id, args.items_per_org)
            total_items += created

            if (i + 1) % batch_size == 0:
                db.commit()
                print(f'  [{i + 1}/{len(orgs)}] ~ {total_items} items...', end='\r')

        db.commit()
        print('\n✅ Seeding complete.')
        print(f'   Organisations: {len(orgs)}')
        print(f'   New items: {total_items}')
        print(
            f'   Locations per org: {len(LOCATIONS)} (Cold Storage, Freezer, Shelf A, Shelf B)'
        )
        print('\n   Expiry date distribution:')
        print('   - ~15% already expired')
        print('   - ~30% expiring within 90 days (endpoint /expiring)')
        print('   - ~25% OK (91–365 days)')
        print('   - ~30% no expiry date')

    except Exception as e:  # noqa: BLE001 — top-level script handler; prints the traceback
        db.rollback()
        print(f'\n❌ Error: {e}')
        import traceback

        traceback.print_exc()
        sys.exit(1)
    finally:
        db.close()


if __name__ == '__main__':
    main()
