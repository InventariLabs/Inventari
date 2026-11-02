"""EU Regulation 1169/2011 allergens — keys, inference, validation.

The 14 allergens list is closed by law; keys are stable identifiers used
in the model, API, UI and exports.
"""

from __future__ import annotations

import re
import unicodedata

ALLERGEN_KEYS: tuple[str, ...] = (
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

ALLERGEN_SET: frozenset[str] = frozenset(ALLERGEN_KEYS)

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
    'spaghetti': {'gluten'},
    'penne': {'gluten'},
    'fusilli': {'gluten'},
    'tagliatelle': {'gluten'},
    'lasagne': {'gluten'},
    'noodle': {'gluten'},
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


def normalize_name(name: str) -> str:
    """Lowercase, strip diacritics and collapse whitespace."""
    decomposed = unicodedata.normalize('NFD', name.lower())
    no_diacritics = ''.join(c for c in decomposed if not unicodedata.combining(c))
    return _WS_RE.sub(' ', no_diacritics).strip()


def infer_allergens(name: str) -> list[str]:
    """Infer EU allergens for an ingredient from its name (PL/EN).

    Returns keys ordered by :data:`ALLERGEN_KEYS`. Empty list when nothing
    matches — the user can still set allergens manually.
    """
    normalized = normalize_name(name)
    if not normalized:
        return []
    found: set[str] = set()
    for keyword in _SORTED_KEYWORDS:
        if keyword in normalized:
            found |= _ALLERGEN_NAME_MAP[keyword]
    return [key for key in ALLERGEN_KEYS if key in found]
