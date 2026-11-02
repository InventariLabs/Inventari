"""What the nutrition module wants read off a photographed package.

The fields themselves are in :mod:`app.modules.nutrition.schemas`; what is
here is the asking. Vision learns of them through its public API, so nothing
outside this module names a nutrient and nothing in Core ever did.
"""

from __future__ import annotations

from app.modules.vision.vision_api import PRODUCT_CONTEXT, vision_api

from .schemas import NutritionFacts

__all__ = ['register_vision_fields']

_INSTRUCTIONS = (
    'Fill the nutrition fields only when a nutrition table is clearly legible '
    'in the pictures. Values are per 100 g or 100 ml — if the table is given '
    'per serving and the serving size is visible, convert; if it is not '
    'visible, leave the values null rather than estimating. Use numbers only.'
)


def register_vision_fields() -> None:
    """Ask vision to read a nutrition table alongside a product label.

    Bound to the product intent alone: a label printed for assets gets no
    nutrition question, so the prompt sent for a rating plate does not mention
    food at all.
    """
    vision_api.register_label_fields(
        module='nutrition',
        schema=NutritionFacts,
        instructions=_INSTRUCTIONS,
        context_tags=frozenset({PRODUCT_CONTEXT}),
    )
