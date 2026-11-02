"""backfill recipe_ingredients.allergens from name inference

Existing recipes must aggregate allergens without manual configuration. The
implementation chose name-based inference (``infer_allergens``) suggested
at edit time, so pre-existing rows kept ``allergens=[]`` and aggregated
nothing until edited. This data-only migration closes that gap:

* Upgrade — fills ``allergens`` using the same name-based inference map,
  ONLY for rows where ``allergens`` is NULL or an empty JSONB array.
  Rows with explicitly set values (manual curation) are never touched.
  Idempotent: re-running updates nothing because backfilled rows no
  longer match the empty-array predicate (or, when inference yields no
  allergen, still yield no allergen and write nothing).
* Downgrade — no-op by design: the backfilled values are indistinguishable
  from user-entered ones, so a safe reversal is not possible.

The inference below is a frozen copy of the map and matching rules the
application used when this revision was cut. A revision imports no
application code, so a later change to the runtime inference (a keyword
added, the matching tightened) does not alter what this backfill writes on
a fresh install; it stays what it was when it first ran.

Revision ID: 003_backfill_allergens
Revises: 002_add_allergens
Create Date: 2026-08-02
"""

import json
import re
import unicodedata
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Revision id kept short: alembic_version_recipes.version_num is varchar(32).
revision: str = '003_backfill_allergens'
down_revision: str | None = '002_add_allergens'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

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

# Keyword → allergens. Substring match on the normalized (lowercase,
# diacritics-stripped) ingredient name. PL + EN keywords.
_ALLERGEN_NAME_MAP: dict[str, set[str]] = {
    # gluten: wheat, rye, barley, oats and their derivatives
    'maka': {'gluten'},
    'flour': {'gluten'},
    'pszen': {'gluten'},
    'wheat': {'gluten'},
    'orkisz': {'gluten'},
    'spelt': {'gluten'},
    'makaron': {'gluten'},
    'pasta': {'gluten'},
    'chleb': {'gluten'},
    'bread': {'gluten'},
    'bulka': {'gluten'},
    'roll': {'gluten'},
    'kaszka manna': {'gluten'},
    'semolina': {'gluten'},
    'jeczmien': {'gluten'},
    'barley': {'gluten'},
    'zyto': {'gluten'},
    'rye': {'gluten'},
    'owies': {'gluten'},
    'oats': {'gluten'},
    'kuskus': {'gluten'},
    'couscous': {'gluten'},
    'bulgur': {'gluten'},
    'seitan': {'gluten'},
    # crustaceans
    'krewetk': {'crustaceans'},
    'shrimp': {'crustaceans'},
    'prawn': {'crustaceans'},
    'krab': {'crustaceans'},
    'crab': {'crustaceans'},
    'homar': {'crustaceans'},
    'lobster': {'crustaceans'},
    'raki': {'crustaceans'},
    'langusta': {'crustaceans'},
    'skorupiaki': {'crustaceans'},
    # eggs
    'jajk': {'eggs'},
    'egg': {'eggs'},
    'jaja': {'eggs'},
    'majonez': {'eggs'},
    'mayonnaise': {'eggs'},
    # fish
    'ryba': {'fish'},
    'fish': {'fish'},
    'losos': {'fish'},
    'salmon': {'fish'},
    'dorsz': {'fish'},
    'cod': {'fish'},
    'tunczyk': {'fish'},
    'tuna': {'fish'},
    'sledz': {'fish'},
    'herring': {'fish'},
    'makrela': {'fish'},
    'mackerel': {'fish'},
    'sardynk': {'fish'},
    'sardine': {'fish'},
    'pstrąg': {'fish'},
    'trout': {'fish'},
    'anchois': {'fish'},
    'anchov': {'fish'},
    'kawior': {'fish'},
    'caviar': {'fish'},
    # peanuts
    'orzeszki ziemne': {'peanuts'},
    'peanut': {'peanuts'},
    'arachid': {'peanuts'},
    'maslo orzechowe': {'peanuts'},
    # soy
    'soj': {'soy'},
    'soy': {'soy'},
    'tofu': {'soy'},
    'edamame': {'soy'},
    'tempeh': {'soy'},
    'tamari': {'soy'},
    # milk
    'mleko': {'milk'},
    'milk': {'milk'},
    'smietan': {'milk'},
    'cream': {'milk'},
    'jogurt': {'milk'},
    'yogurt': {'milk'},
    'yoghurt': {'milk'},
    'twarog': {'milk'},
    'cottage': {'milk'},
    'ser': {'milk'},
    'cheese': {'milk'},
    'maslo': {'milk'},
    'butter': {'milk'},
    'kefir': {'milk'},
    'maslanka': {'milk'},
    'buttermilk': {'milk'},
    'mascarpone': {'milk'},
    'ricotta': {'milk'},
    'parmezan': {'milk'},
    'parmesan': {'milk'},
    'mozzarella': {'milk'},
    'gouda': {'milk'},
    'cheddar': {'milk'},
    'whey': {'milk'},
    'serwatka': {'milk'},
    'laktoza': {'milk'},
    'lactose': {'milk'},
    # nuts (tree nuts) — careful: bare 'nut' matches coconut/donut
    'orzech': {'nuts'},
    'walnut': {'nuts'},
    'orzech wloski': {'nuts'},
    'migdal': {'nuts'},
    'almond': {'nuts'},
    'nerkowc': {'nuts'},
    'cashew': {'nuts'},
    'pistac': {'nuts'},
    'pistachio': {'nuts'},
    'pecan': {'nuts'},
    'laskow': {'nuts'},
    'hazelnut': {'nuts'},
    'brazylijski': {'nuts'},
    'brazil nut': {'nuts'},
    'makadamia': {'nuts'},
    'macadamia': {'nuts'},
    # celery
    'seler': {'celery'},
    'celery': {'celery'},
    # mustard
    'musztarda': {'mustard'},
    'mustard': {'mustard'},
    'gorczyca': {'mustard'},
    # sesame
    'sezam': {'sesame'},
    'sesame': {'sesame'},
    'tahini': {'sesame'},
    'tahina': {'sesame'},
    # sulphites
    'siarczyn': {'sulphites'},
    'sulphite': {'sulphites'},
    'sulfite': {'sulphites'},
    'siarka': {'sulphites'},
    # lupin
    'lubin': {'lupin'},
    'lupin': {'lupin'},
    # molluscs
    'malze': {'molluscs'},
    'mussel': {'molluscs'},
    'ostryg': {'molluscs'},
    'oyster': {'molluscs'},
    'miezaki': {'molluscs'},
    'mollusc': {'molluscs'},
    'kalmar': {'molluscs'},
    'squid': {'molluscs'},
    'osmiornic': {'molluscs'},
    'octopus': {'molluscs'},
    'przegrzebk': {'molluscs'},
    'scallop': {'molluscs'},
    'conch': {'molluscs'},
}

# Longest-first so multi-word keywords win over single-word ones.
_SORTED_KEYWORDS: list[str] = sorted(_ALLERGEN_NAME_MAP, key=len, reverse=True)

_WS_RE = re.compile(r'\s+')


def _normalize_name(name: str) -> str:
    """Lowercase, strip diacritics and collapse whitespace."""
    decomposed = unicodedata.normalize('NFD', name.lower())
    no_diacritics = ''.join(c for c in decomposed if not unicodedata.combining(c))
    return _WS_RE.sub(' ', no_diacritics).strip()


def _infer_allergens(name: str) -> list[str]:
    """Allergens for an ingredient name, ordered by ``_ALLERGEN_KEYS``."""
    normalized = _normalize_name(name)
    if not normalized:
        return []
    found: set[str] = set()
    for keyword in _SORTED_KEYWORDS:
        if keyword in normalized:
            found |= _ALLERGEN_NAME_MAP[keyword]
    return [key for key in _ALLERGEN_KEYS if key in found]


def upgrade() -> None:
    """Backfill empty ``allergens`` from ingredient-name inference."""
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            """
            SELECT id, name
            FROM recipe_ingredients
            WHERE allergens IS NULL
               OR allergens = '[]'::jsonb
            """
        )
    )
    update = sa.text(
        'UPDATE recipe_ingredients '
        'SET allergens = CAST(:allergens AS jsonb) '
        'WHERE id = :id'
    )
    for row in rows:
        inferred = _infer_allergens(row.name)
        if inferred:
            bind.execute(update, {'allergens': json.dumps(inferred), 'id': row.id})


def downgrade() -> None:
    """No-op: backfilled values cannot be told apart from curated ones."""
