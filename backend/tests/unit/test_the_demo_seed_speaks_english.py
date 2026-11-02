"""Every name the demo seeder writes to the database is English.

The demo instance is the first thing a visitor sees and its interface is
English, but the names of products, partners and places do not come from the
translation files — they come from this seeder and land in the database as
written. Until 2026-09-21 they were Polish with the diacritics stripped
(``Dzem truskawkowy``, ``Herbatniki maslane``, ``Maka ziemniaczana``), so the
stock list read as misspelt Polish under an English header.

Two rules, and the second is the one that survives a refactor:

* a seeded name is plain ASCII and contains no word from the guard list, and
* the corpus this module collects is not allowed to be empty or to shrink.

Without the second rule the gate is theatre: renaming ``FOOD_TEMPLATES`` would
leave a green test collecting nothing. The counts below are the measured size
of the corpus, not a guess, and raising them is fine — lowering one means a
constant stopped being seen.
"""

from __future__ import annotations

import pytest

from seed_demo_data import (
    DEMO_MAINTENANCE,
    DEMO_MEAL_PLAN_NAME,
    DEMO_PARTNERS,
    DEMO_RECIPES,
    DEMO_SHIPMENT_CARRIER,
    DEMO_SHIPMENT_TRACKING_NUMBER,
    DEMO_SHOPPING_ITEMS,
    DEMO_SHOPPING_LIST_NAME,
    DEMO_STOCK_TAKE_DESCRIPTION,
    DEMO_STOCK_TAKE_TITLE,
    EQUIPMENT_HIERARCHY,
    EQUIPMENT_TEMPLATES,
    FOOD_HIERARCHY,
    FOOD_TEMPLATES,
    MAKER_BOM,
    MAKER_RUN_NOTES,
    MAKER_SKUS,
    MAKER_TEMPLATES,
    SEED_PREFIX,
)
from seed_demo_showcase import (
    DEMO_ADMIN_ASSET_NOTES,
    DEMO_APPROVAL_NOTES,
    DEMO_APPROVAL_STAGES,
    DEMO_APPROVAL_WORKFLOW,
    DEMO_CAMPAIGN_DESCRIPTION,
    DEMO_CAMPAIGN_NAME,
    DEMO_DISPUTE_REASON,
    DEMO_ORGANIZATION_NAME,
    DEMO_PO_NOTES,
    DEMO_TEAM,
)

#: Words that survived the last translation pass with their diacritics removed.
#: A plain ASCII check cannot see them, which is exactly why they are listed.
POLISH_GUARD_WORDS = frozenset(
    {
        'bialy',
        'borowki',
        'cukier',
        'cynamon',
        'czekoladowy',
        'dzem',
        'jajka',
        'kakao',
        'kielbasa',
        'losos',
        'maka',
        'maslane',
        'maslo',
        'mieso',
        'mleko',
        'mrozone',
        'mrozony',
        'musli',
        'ogorek',
        'platki',
        'powidla',
        'sliwki',
        'smietana',
        'twarog',
        'wisnie',
        'zolty',
    }
)


def _flatten_locations(hierarchy: list) -> list[str]:
    """Every location name in a seeder hierarchy, at any of its four depths."""
    names: list[str] = []
    for root_name, _parent, _type, _catalogue, children in hierarchy:
        names.append(root_name)
        for child_name, (_ctype, _behavior, _cat, leaves) in children.items():
            names.append(child_name)
            for leaf in leaves:
                if isinstance(leaf, tuple):
                    leaf_name, sub_leaves = leaf
                    names.append(leaf_name)
                    names.extend(sub_leaves)
                else:
                    names.append(leaf)
    return names


def _corpus() -> dict[str, list[str]]:
    """Seeded names, grouped by the constant they came from."""
    return {
        'FOOD_TEMPLATES': [row[0] for row in FOOD_TEMPLATES]
        + [row[1] for row in FOOD_TEMPLATES if row[1]],
        'EQUIPMENT_TEMPLATES': [row[0] for row in EQUIPMENT_TEMPLATES]
        + [row[1] for row in EQUIPMENT_TEMPLATES if row[1]],
        'DEMO_PARTNERS': [row[0] for row in DEMO_PARTNERS],
        'FOOD_HIERARCHY': _flatten_locations(FOOD_HIERARCHY),
        'EQUIPMENT_HIERARCHY': _flatten_locations(EQUIPMENT_HIERARCHY),
        'MAKER_TEMPLATES': [row[0] for row in MAKER_TEMPLATES]
        + [row[1] for row in MAKER_TEMPLATES]
        + [row[2] for row in MAKER_TEMPLATES],
        'MAKER_SKUS': list(MAKER_SKUS) + list(MAKER_SKUS.values()),
        'MAKER_BOM': [row[0] for row in MAKER_BOM] + [row[4] for row in MAKER_BOM],
        # Criteria classes the first corpus missed (review 2026-09-22):
        # recipes the visitor can open, the category codes the templates
        # are filed under, and the stock take a guest reads on the
        # inventory screen. Document numbers are generated as
        # <TYPE>/<year>/<seq> from ASCII type codes and carry no seed text
        # of their own — everything wordsy on a document (line names,
        # partner snapshots) arrives via the constants above.
        'DEMO_RECIPES': [row[0] for row in DEMO_RECIPES]
        + [row[1] for row in DEMO_RECIPES]
        + [row[6] for row in DEMO_RECIPES]
        + [line[0] for row in DEMO_RECIPES for line in row[5]],
        # The kitchen week and the workshop added 2026-09-23: what the meal
        # planner, the shopping list and an asset's timeline print.
        'DEMO_KITCHEN_WEEK': [DEMO_MEAL_PLAN_NAME, DEMO_SHOPPING_LIST_NAME]
        + [row[0] for row in DEMO_SHOPPING_ITEMS]
        + [row[2] for row in DEMO_SHOPPING_ITEMS if row[2]],
        'DEMO_MAINTENANCE': [row[2] for row in DEMO_MAINTENANCE]
        + [row[3] for row in DEMO_MAINTENANCE],
        'CATEGORIES': [row[3] for row in FOOD_TEMPLATES]
        + [row[3] for row in EQUIPMENT_TEMPLATES],
        'DEMO_SHIPMENT': [DEMO_SHIPMENT_CARRIER] + [DEMO_SHIPMENT_TRACKING_NUMBER],
        'DEMO_STOCK_TAKE': [f'{SEED_PREFIX}{DEMO_STOCK_TAKE_TITLE}']
        + [DEMO_STOCK_TAKE_DESCRIPTION],
        'MAKER_RUN': [MAKER_RUN_NOTES],
        # What only the public demo writes (``seed_demo_showcase``): the
        # organization's name on every page and PDF, the colleagues on the
        # approvals, the notes on the orders and the attestation campaign.
        'DEMO_SHOWCASE': [DEMO_ORGANIZATION_NAME, DEMO_APPROVAL_WORKFLOW]
        + [name for name, _email in DEMO_TEAM]
        + list(DEMO_PO_NOTES)
        + [stage['label'] for stage in DEMO_APPROVAL_STAGES]
        + [DEMO_APPROVAL_NOTES, DEMO_ADMIN_ASSET_NOTES]
        + [DEMO_CAMPAIGN_NAME, DEMO_CAMPAIGN_DESCRIPTION, DEMO_DISPUTE_REASON],
    }


#: Measured 2026-09-21. A constant that stops being collected shows up here as
#: a shortfall rather than as a test that quietly checks nothing.
MINIMUM_NAMES = {
    'FOOD_TEMPLATES': 172,
    'EQUIPMENT_TEMPLATES': 52,
    'DEMO_PARTNERS': 12,
    'FOOD_HIERARCHY': 21,
    'EQUIPMENT_HIERARCHY': 15,
    'MAKER_TEMPLATES': 12,
    'MAKER_SKUS': 8,
    'MAKER_BOM': 6,
    'DEMO_RECIPES': 71,
    'DEMO_KITCHEN_WEEK': 12,
    'DEMO_MAINTENANCE': 4,
    'CATEGORIES': 10,
    'DEMO_SHIPMENT': 2,
    'DEMO_STOCK_TAKE': 2,
    'MAKER_RUN': 1,
    'DEMO_SHOWCASE': 14,
}


def _all_names() -> list[tuple[str, str]]:
    return [(source, name) for source, names in _corpus().items() for name in names]


class TestTheCorpusIsActuallyRead:
    """The gate's own reach, measured before it is trusted."""

    def test_every_source_still_yields_the_names_it_used_to(self):
        collected = {source: len(names) for source, names in _corpus().items()}
        short = {
            source: (count, MINIMUM_NAMES[source])
            for source, count in collected.items()
            if count < MINIMUM_NAMES[source]
        }
        assert not short, (
            f'the corpus shrank — {short} (got, expected at least). A constant '
            f'was renamed or emptied, so the English gate below now checks less '
            f'than it did.'
        )

    def test_every_declared_source_is_collected(self):
        assert set(_corpus()) == set(MINIMUM_NAMES)


class TestTheSeededNamesAreEnglish:
    def test_no_seeded_name_leaves_ascii(self):
        offenders = [
            (source, name) for source, name in _all_names() if not name.isascii()
        ]
        assert not offenders, (
            f'{len(offenders)} seeded name(s) are not plain ASCII: {offenders[:10]}. '
            f'The demo corpus is English; a name with an accent in it is either a '
            f'leftover translation or typography that belongs in the i18n files.'
        )

    def test_no_seeded_name_is_polish_with_the_accents_filed_off(self):
        offenders = []
        for source, name in _all_names():
            words = {
                word.strip('.,-()%').lower() for word in name.replace('-', ' ').split()
            }
            hits = words & POLISH_GUARD_WORDS
            if hits:
                offenders.append((source, name, sorted(hits)))
        assert not offenders, (
            f'{len(offenders)} seeded name(s) are Polish with the diacritics '
            f'stripped: {offenders[:10]}. ASCII alone cannot catch these, which '
            f'is why the guard list exists.'
        )


class TestTheGuardListItselfHasTeeth:
    """A planted violation must turn each half of the gate red.

    A gate nobody has seen fail is a gate nobody knows the reach of. These two
    run the same predicates the tests above run, over a corpus that is wrong on
    purpose, and assert that each one objects.
    """

    @pytest.mark.parametrize(
        ('planted', 'why'),
        [
            ('Dżem truskawkowy', 'accented Polish'),
            ('Dzem truskawkowy', 'Polish with the accents filed off'),
        ],
    )
    def test_a_planted_polish_name_is_rejected_by_one_of_the_two_checks(
        self, planted: str, why: str
    ):
        words = {
            word.strip('.,-()%').lower() for word in planted.replace('-', ' ').split()
        }
        caught_by_ascii = not planted.isascii()
        caught_by_guard = bool(words & POLISH_GUARD_WORDS)
        assert caught_by_ascii or caught_by_guard, (
            f'{planted!r} ({why}) passes both halves of the gate — the guard list '
            f'needs the word that carries it.'
        )

    def test_an_english_name_is_not_rejected(self):
        """The gate must not be so wide that it refuses the corpus it guards."""
        for name in ('Strawberry Jam', 'Fridge A - Top Shelf', 'Cisco Catalyst 9200L'):
            words = {
                word.strip('.,-()%').lower() for word in name.replace('-', ' ').split()
            }
            assert name.isascii()
            assert not (words & POLISH_GUARD_WORDS), name
