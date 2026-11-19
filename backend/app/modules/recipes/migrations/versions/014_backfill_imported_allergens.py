"""backfill recipe_ingredients.allergens left empty by a recipe import

A recipe imported from JSON or from a web page saved its ingredients with the
allergens the source named, and a source that named none left every line
empty: the recipe page read "No allergens marked" for an omelette of eggs,
butter and cheddar. The import now gives a line what its name suggests, as the
recipe form's lookup does; this revision does the same for the lines saved
before.

* Upgrade — fills ``allergens`` from name inference ONLY for rows where it is
  NULL or an empty JSONB array; a row with values of its own is never touched.
  An empty list is what the recipe form also reads as "never looked at": it
  fills the inferred allergens of such a line whenever the recipe is opened
  for editing. A name that suggests nothing stays empty.
* The rows are walked in ``id`` order, a bounded page at a time, each write
  committed on its own: a row the inference leaves empty still matches the
  predicate, so the key, not the predicate, is what ends the walk. A replay
  finds nothing more to write.
* Downgrade — no-op by design: the backfilled values cannot be told apart
  from the ones a cook confirmed, so a safe reversal is not possible.

The inference below is a frozen copy of the map and matching rules the
application uses at this revision; a revision imports no application code, so
a later change to the runtime inference does not alter what this one writes.

Revision ID: 014_backfill_imported_allergens
Revises: 013_meal_plan_listed_meals
Create Date: 2026-11-19
"""

import json
import re
import unicodedata
import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '014_backfill_imported_allergens'
down_revision: str | None = '013_meal_plan_listed_meals'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BATCH = 1000

_ALLERGEN_KEYS: tuple[str, ...] = (
    'gluten',
    'crustaceans',
    'eggs',
    'fish',
    'peanuts',
    'soy',
    'milk',
    'nuts',
    'celery',
    'mustard',
    'sesame',
    'sulphites',
    'lupin',
    'molluscs',
)

# Allergen → keywords. Substring match on the normalized (lowercase,
# diacritics-stripped) ingredient name. PL + EN keywords.
_KEYWORDS: dict[str, tuple[str, ...]] = {
    'gluten': (
        'maka',
        'flour',
        'pszen',
        'wheat',
        'orkisz',
        'spelt',
        'makaron',
        'pasta',
        'spaghetti',
        'penne',
        'fusilli',
        'tagliatelle',
        'lasagne',
        'noodle',
        'chleb',
        'bread',
        'bulka',
        'roll',
        'kaszka manna',
        'semolina',
        'jeczmien',
        'barley',
        'zyto',
        'rye',
        'owies',
        'owsian',
        'oats',
        'kuskus',
        'couscous',
        'bulgur',
        'seitan',
    ),
    'crustaceans': (
        'krewetk',
        'shrimp',
        'prawn',
        'krab',
        'crab',
        'homar',
        'lobster',
        'raki',
        'langusta',
        'skorupiaki',
    ),
    'eggs': ('jajk', 'egg', 'jaja', 'majonez', 'mayonnaise'),
    'fish': (
        'ryba',
        'fish',
        'losos',
        'salmon',
        'dorsz',
        'cod',
        'tunczyk',
        'tuna',
        'sledz',
        'herring',
        'makrela',
        'mackerel',
        'sardynk',
        'sardine',
        'pstrąg',
        'trout',
        'anchois',
        'anchov',
        'kawior',
        'caviar',
    ),
    'peanuts': ('orzeszki ziemne', 'peanut', 'arachid', 'maslo orzechowe'),
    'soy': ('soj', 'soy', 'tofu', 'edamame', 'tempeh', 'tamari'),
    'milk': (
        'mleko',
        'mleczn',
        'milk',
        'smietan',
        'cream',
        'jogurt',
        'yogurt',
        'yoghurt',
        'twarog',
        'cottage',
        'ser',
        'cheese',
        'maslo',
        'butter',
        'kefir',
        'maslanka',
        'buttermilk',
        'mascarpone',
        'ricotta',
        'parmezan',
        'parmesan',
        'mozzarella',
        'gouda',
        'cheddar',
        'whey',
        'serwatka',
        'laktoza',
        'lactose',
    ),
    'nuts': (
        'orzech',
        'walnut',
        'orzech wloski',
        'migdal',
        'almond',
        'nerkowc',
        'cashew',
        'pistac',
        'pistachio',
        'pecan',
        'laskow',
        'hazelnut',
        'brazylijski',
        'brazil nut',
        'makadamia',
        'macadamia',
    ),
    'celery': ('seler', 'celery'),
    'mustard': ('musztarda', 'mustard', 'gorczyca'),
    'sesame': ('sezam', 'sesame', 'tahini', 'tahina'),
    'sulphites': ('siarczyn', 'sulphite', 'sulfite', 'siarka'),
    'lupin': ('lubin', 'lupin'),
    'molluscs': (
        'malze',
        'mussel',
        'ostryg',
        'oyster',
        'miezaki',
        'mollusc',
        'kalmar',
        'squid',
        'osmiornic',
        'octopus',
        'przegrzebk',
        'scallop',
        'conch',
    ),
}

# Longest-first so multi-word keywords win over single-word ones.
_SORTED_KEYWORDS: list[tuple[str, str]] = sorted(
    ((keyword, key) for key, words in _KEYWORDS.items() for keyword in words),
    key=lambda pair: len(pair[0]),
    reverse=True,
)

_WS_RE = re.compile(r'\s+')

# A plant milk or cream is no dairy; the plant word stays.
_PLANT_MILK_EN_RE = re.compile(
    r'\b(?:(coconut|almond|soy|soya|oats?|rice|cashew|hazelnut|hemp|pea|plant'
    r'|walnut|pistachio|macadamia|peanut)[ -]milk'
    r'|(coconut|soy|soya|oats?|cashew|plant)[ -]cream'
    r'|cream of (coconut))\b(?!\s+[a-z])'
)
# A nut or fat butter is no dairy; the nut or fat stays.
_NON_DAIRY_BUTTER_EN_RE = re.compile(
    r'\b(peanut|almond|cashew|hazelnut|walnut|pistachio|macadamia|sesame|coconut'
    r'|sunflower|apple|cocoa|cacao|shea|nut)(?:[ -]seed)?[ -]butter\b(?!\s+[a-z])'
)
_NON_DAIRY_BUTTER_PL_RE = re.compile(
    r'\bmaslo (orzechowe|kakaowe|shea|migdalowe|sezamowe|kokosowe'
    r'|z orzechow \w+|z orzeszki ziemne)\b(?!\s+[a-z])'
)
# Both Polish spellings of a peanut are one keyword.
_PL_PEANUT_RE = re.compile(r'\b(?:orzech|orzesz)\w* ziemn(?:e|a|y|ego|ej|ych|ym|ymi)\b')
# "Groundnut" and "ground nuts" are peanuts.
_GROUNDNUT_RE = re.compile(r'\bground[ -]?nuts?\b')
# Bare "nut"/"nuts" as a word, not inside coconut, donut, nutmeg or peanuts.
_NUT_WORD_RE = re.compile(r'\bnuts?\b')
_PL_MILK_PLANT = (
    r'(kokosow\w*|sojow\w*|migdalow\w*|owsian\w*|ryzow\w*|orzechow\w*|roslinn\w*)'
)
_PL_CREAM_PLANT = r'(kokosow\w*|sojow\w*|owsian\w*|roslinn\w*)'
_PLANT_MILK_PL_RE = re.compile(
    rf'\b(?:mleko\s+{_PL_MILK_PLANT}|{_PL_MILK_PLANT}\s+mleko'
    rf'|smietan[ak]a?\s+{_PL_CREAM_PLANT}|{_PL_CREAM_PLANT}\s+smietan[ak]a?)\b(?!\s+[a-z])'
)


def _normalize_name(name: str) -> str:
    """Lowercase, strip diacritics and collapse whitespace."""
    decomposed = unicodedata.normalize('NFD', name.lower().replace('ł', 'l'))
    no_diacritics = ''.join(c for c in decomposed if not unicodedata.combining(c))
    return _WS_RE.sub(' ', no_diacritics).strip()


def _without_plant_milk(normalized: str) -> str:
    """Drop the dairy word from a plant milk or a nut butter, keeping its plant."""

    def plant(m: re.Match[str]) -> str:
        word = next(g for g in m.groups() if g)
        return 'oats' if word.startswith('oat') else word

    def butter_pl(m: re.Match[str]) -> str:
        return 'orzeszki ziemne' if m.group(1).startswith('orzech') else m.group(1)

    normalized = _NON_DAIRY_BUTTER_EN_RE.sub(lambda m: m.group(1), normalized)
    normalized = _NON_DAIRY_BUTTER_PL_RE.sub(butter_pl, normalized)
    return _PLANT_MILK_PL_RE.sub(plant, _PLANT_MILK_EN_RE.sub(plant, normalized))


def _infer_allergens(name: str) -> list[str]:
    """Allergens for an ingredient name, ordered by ``_ALLERGEN_KEYS``."""
    normalized = _normalize_name(name)
    if not normalized:
        return []
    normalized = _GROUNDNUT_RE.sub('peanut', normalized)
    normalized = _without_plant_milk(_PL_PEANUT_RE.sub('orzeszki ziemne', normalized))
    found: set[str] = {'nuts'} if _NUT_WORD_RE.search(normalized) else set()
    for keyword, key in _SORTED_KEYWORDS:
        if keyword in normalized:
            found.add(key)
    return [key for key in _ALLERGEN_KEYS if key in found]


_PAGE = sa.text(
    'SELECT id, name FROM recipe_ingredients '
    "WHERE (allergens IS NULL OR allergens = '[]'::jsonb) AND id > :after "
    'ORDER BY id LIMIT :limit'
)

_FILL = sa.text(
    'UPDATE recipe_ingredients SET allergens = CAST(:allergens AS jsonb) '
    "WHERE id = :id AND (allergens IS NULL OR allergens = '[]'::jsonb)"
)


def upgrade() -> None:
    """Fill empty ``allergens`` from ingredient-name inference, page by page."""
    with op.get_context().autocommit_block():
        conn = op.get_bind()
        after = uuid.UUID(int=0)
        while True:
            rows = conn.execute(_PAGE, {'after': after, 'limit': _BATCH}).all()
            if not rows:
                break
            fills = [
                {'id': row.id, 'allergens': json.dumps(inferred)}
                for row in rows
                if (inferred := _infer_allergens(row.name or ''))
            ]
            if fills:
                conn.execute(_FILL, fills)
            after = rows[-1].id


def downgrade() -> None:
    """No-op: backfilled values cannot be told apart from confirmed ones."""
