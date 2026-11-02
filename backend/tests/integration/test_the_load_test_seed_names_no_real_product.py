"""The load-test seed names no real product.

The k6 seed filled each load-test organization from real grocery brands, with
the EAN codes printed on their packs, and gave loose produce any 13 random
digits. In a public repository that reads as an endorsement or as scraped
catalogue data, and an EAN identifies a third party's product. The seed now
uses invented brands, English names, and EANs from the GS1 restricted-
circulation range (prefixes 200-299), which no product in general retail
carries. The k6 browse-and-scan scenario scans some of those codes and searches
for words in those names, so it is held to the seed here as well.

The seed also never ran past the second item of one product: it gave both the
same barcode, and an organization holds one active item per barcode.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

import seed_load_test_data as seed
from app.models.item import Item
from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.models.user import User

_BACKEND_DIR = Path(__file__).resolve().parents[2]  # backend/
# The container mounts the checkout read-only and names it here; on the host
# the checkout is the backend's parent.
_PROJECT_ROOT = Path(os.environ.get('INVENTARI_REPO_ROOT') or _BACKEND_DIR.parent)
_SCENARIO = _PROJECT_ROOT / 'load_tests' / 'scenarios' / 'browse_and_scan.js'

_POOLED = seed.FRIDGE_ITEMS + seed.FREEZER_ITEMS + seed.PANTRY_ITEMS


def _check_digit(body: str) -> str:
    # Computed here rather than taken from the seed, so a wrong rule there
    # cannot agree with itself.
    total = sum(int(digit) * (3 if i % 2 else 1) for i, digit in enumerate(body))
    return str(-total % 10)


def _is_valid_ean13(code: str) -> bool:
    return bool(re.fullmatch(r'\d{13}', code)) and _check_digit(code[:12]) == code[12]


def _is_restricted_circulation(code: str) -> bool:
    return _is_valid_ean13(code) and code.startswith('2')


def _scenario_list(name: str) -> list[str]:
    source = _SCENARIO.read_text(encoding='utf-8')
    block = re.search(rf'const {name} = \[(.*?)\];', source, re.DOTALL)
    assert block, f'{_SCENARIO} has no {name} list'
    return re.findall(r"'([^']+)'", block.group(1))


def test_every_pooled_barcode_is_a_restricted_circulation_ean() -> None:
    not_restricted = [
        (name, code)
        for name, _brand, code in _POOLED
        if code is not None and not _is_restricted_circulation(code)
    ]
    assert not_restricted == []


def test_names_and_brands_are_plain_english_text() -> None:
    # The pools used to be Polish product names; English names are what the
    # k6 searches look for.
    not_plain = [
        (name, brand)
        for name, brand, _code in _POOLED
        if not (name.isascii() and brand.isascii())
    ]
    assert not_plain == []


def test_a_product_without_a_barcode_gets_a_restricted_one() -> None:
    codes = {seed._random_restricted_ean() for _ in range(500)}
    assert all(_is_restricted_circulation(code) for code in codes)


def test_the_seed_fills_an_organization_with_these_products_only(
    db_session: Session, test_household: Organization, test_user: User
) -> None:
    # 120 items from 83 products repeat some of them, and an organization
    # holds one active item per barcode: this seed used to stop there.
    created = seed.seed_org_data(db_session, test_household.id, 120)
    db_session.flush()

    items = db_session.scalars(
        select(Item).where(Item.organization_id == test_household.id)
    ).all()
    locations = db_session.scalars(
        select(StorageLocation.name).where(
            StorageLocation.organization_id == test_household.id
        )
    ).all()

    assert created == 120
    assert len(items) == 120
    assert {'Cold Storage', 'Freezer', 'Shelf A', 'Shelf B'} <= set(locations)
    pooled_brands = {brand for _name, brand, _code in _POOLED}
    assert {item.brand for item in items} <= pooled_brands
    barcodes = [item.barcode for item in items if item.barcode is not None]
    assert barcodes, 'the seed gave no item a barcode'
    assert [code for code in barcodes if not _is_restricted_circulation(code)] == []


def test_a_second_run_tops_up_without_reusing_a_barcode(
    db_session: Session, test_household: Organization, test_user: User
) -> None:
    seed.seed_org_data(db_session, test_household.id, 120)
    db_session.flush()

    created = seed.seed_org_data(db_session, test_household.id, 240)
    db_session.flush()

    barcodes = db_session.scalars(
        select(Item.barcode).where(
            Item.organization_id == test_household.id, Item.barcode.isnot(None)
        )
    ).all()
    assert created == 120
    assert len(barcodes) == len(set(barcodes))


def test_the_scenario_scans_seeded_codes_or_codes_no_product_has() -> None:
    pooled_codes = {code for _name, _brand, code in _POOLED if code}
    scanned = _scenario_list('BARCODES')

    assert set(scanned) & pooled_codes, 'the scenario scans no seeded product'
    stray = [
        code for code in scanned if code not in pooled_codes and _is_valid_ean13(code)
    ]
    assert stray == []


def test_every_scenario_search_finds_a_seeded_name() -> None:
    names = [name.lower() for name, _brand, _code in _POOLED]
    unmatched = [
        query
        for query in _scenario_list('SEARCH_QUERIES')
        if not any(query.lower() in name for name in names)
    ]
    assert unmatched == []
