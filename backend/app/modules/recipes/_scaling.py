"""The one definition of a recipe multiplier.

A recipe is written for a number of servings and cooked for another, and
everything the kitchen asks for scales by the ratio between them. That ratio
was computed wherever it was needed — four spellings across four files, two of
them on ``float`` and only one of them refusing to divide by a recipe of zero
servings — so the same request could read 1.4 here and 1.3999999 there, and
one shopping list out of four could divide by zero.

``scale`` is the caller that already knows the ratio (a picking session held
across a recipe edit, a request that says "one and a half times"). It wins
over ``servings`` because it is the more specific answer: the servings are a
hint at what was wanted, the scale is what was decided.
"""

from decimal import ROUND_HALF_UP, Decimal


def resolve_multiplier(
    recipe_servings: int,
    servings_requested: int | Decimal | None,
    scale: Decimal | None,
) -> Decimal:
    """One definition of the multiplier. ``scale`` wins over ``servings``.

    A recipe of zero servings divides by one rather than raising: the number
    is nonsense, and nonsense should cost a wrong multiplier rather than a
    500. ``servings`` of zero or ``None`` means "as written", which is a
    multiplier of one for any recipe that has servings at all. A fractional
    count is legal — a caller that folded a stated scale into servings
    upstream (``resolve_servings_request``) hands one over, and the math
    carries it exactly.
    """
    if scale is not None:
        return Decimal(str(scale))
    effective = servings_requested if servings_requested else recipe_servings
    return Decimal(str(effective)) / Decimal(str(max(int(recipe_servings), 1)))


def serving_equivalent(recipe_servings: int, multiplier: Decimal) -> Decimal:
    """How many servings this cook is for: the recipe's, times the multiplier.

    Exact, and never rounded. The response shows a rounded count because
    ``servings`` is an ``int`` and every client already renders it; kcal per
    serving divides by this instead. One and a half times a four-portion
    recipe is 5.6 servings of food, and dividing by the 6 shown instead would
    report every per-serving figure against the wrong number of mouths.
    """
    return Decimal(str(recipe_servings)) * multiplier


def rounded_servings(exact: Decimal) -> int:
    """The count the response shows: the nearest whole serving, halves up."""
    return int(exact.to_integral_value(rounding=ROUND_HALF_UP))
