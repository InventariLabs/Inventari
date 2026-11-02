"""The contract probe for ``recipes.text_parse``.

What the connection test sends to a text connection: a handful of ingredient
lines, in the prompt, schema and sampling the recipe import uses, judged by
the parser the import uses. A model that answers outside that shape is the
one whose import would quietly drop to the basic parser — no translation, no
original units — so this is where it should show.
"""

from __future__ import annotations

from app.core.public_api.llm import AiContractProbe, LlmRequest, extract_json

from ._llm_client import build_text_request
from .ingredient_parser_basic import ParsedIngredient
from .ingredient_parser_llm import (
    _FALLBACK_CONVERSION_TABLE,
    _INGREDIENT_PROMPT,
    _INGREDIENT_SCHEMA,
    _parse_ingredients_payload,
)

# Ordinary lines in the shapes the parser meets most: a metric weight, a
# bare count and a volume measure to convert.
_LINES = [
    '200 g wheat flour',
    '2 eggs',
    '1 cup milk',
]


def build_probe_request() -> LlmRequest:
    """The import's ingredient request, over the probe's lines."""
    prompt = _INGREDIENT_PROMPT.format(
        lines='\n'.join(_LINES),
        target_language='English',
        conversion_table=_FALLBACK_CONVERSION_TABLE,
    )
    return build_text_request(prompt, json_schema=_INGREDIENT_SCHEMA)


def validate(content: str) -> list[ParsedIngredient]:
    """The import's reading of the answer.

    An answer it gets no ingredient out of is one the import replaces with
    the basic parser's, so it fails the contract here. The code is never a
    refusal: the connection test catches it, asks once more, and reports
    the verdict with the model's answer beside it.
    """
    items = _parse_ingredients_payload(extract_json(content))
    if not items:
        raise ValueError('NO_INGREDIENTS')
    return items


probe = AiContractProbe(build_request=build_probe_request, validate=validate)
