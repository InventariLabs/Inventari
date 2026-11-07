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

# "Coconut milk" is no dairy: the plant word stays (so almond milk still reads
# as nuts, soy milk as soy), the milk or cream word it qualifies goes. Only an
# unambiguous phrase is rewritten: "cream" only after a plant whose cream is a
# plant product (hazelnut or almond cream, rice cream may well be dairy), and
# nothing when a further noun follows ("almond milk chocolate", "pea cream
# soup") - a missed milk is the unsafe error, a false one the safe error.
_PLANT_MILK_EN_RE = re.compile(
    r'\b(?:(coconut|almond|soy|soya|oats?|rice|cashew|hazelnut|hemp|pea|plant)[ -]milk'
    r'|(coconut|soy|soya|oats?|cashew|plant)[ -]cream)\b(?!\s+[a-z])'
)
_PL_MILK_PLANT = (
    r'(kokosow\w*|sojow\w*|migdalow\w*|owsian\w*|ryzow\w*|orzechow\w*|roslinn\w*)'
)
_PL_CREAM_PLANT = r'(kokosow\w*|sojow\w*|owsian\w*|roslinn\w*)'
_PLANT_MILK_PL_RE = re.compile(
    rf'\b(?:mleko\s+{_PL_MILK_PLANT}|{_PL_MILK_PLANT}\s+mleko'
    rf'|smietan[ak]a?\s+{_PL_CREAM_PLANT}|{_PL_CREAM_PLANT}\s+smietan[ak]a?)\b(?!\s+[a-z])'
)


def normalize_name(name: str) -> str:
    """Lowercase, strip diacritics and collapse whitespace."""
    decomposed = unicodedata.normalize('NFD', name.lower().replace('ł', 'l'))
    no_diacritics = ''.join(c for c in decomposed if not unicodedata.combining(c))
    return _WS_RE.sub(' ', no_diacritics).strip()


def _without_plant_milk(normalized: str) -> str:
    """Drop the dairy word from a plant milk, keeping its plant."""

    def plant(m: re.Match[str]) -> str:
        word = next(g for g in m.groups() if g)
        return 'oats' if word.startswith('oat') else word

    return _PLANT_MILK_PL_RE.sub(plant, _PLANT_MILK_EN_RE.sub(plant, normalized))


def infer_allergens(name: str) -> list[str]:
    """Infer EU allergens for an ingredient from its name (PL/EN).

    Returns keys ordered by :data:`ALLERGEN_KEYS`. Empty list when nothing
    matches — the user can still set allergens manually.
    """
    normalized = normalize_name(name)
    if not normalized:
        return []
    normalized = _without_plant_milk(normalized)
    found: set[str] = set()
    for keyword in _SORTED_KEYWORDS:
        if keyword in normalized:
            found |= _ALLERGEN_NAME_MAP[keyword]
    return [key for key in ALLERGEN_KEYS if key in found]
