"""LLM batch parser for ingredient lines.

Two entry points:

* :func:`parse_ingredients_llm_async` — preferred. Resolves the LLM
  client through the Core AI registry (``recipes.text_parse`` purpose)
  and returns parsed ingredients. Caller must have a DB session and
  an organisation id.

* :func:`parse_ingredients_llm` — legacy. Still works with the
  ``llm_cfg`` dict shape for unit-test / backwards compatibility
  purposes; new code MUST use the async variant.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.public_api.llm import LlmContractError, extract_json

from ._llm_client import call_llm_async
from .ingredient_parser_basic import (
    _VALID_UNITS,
    ParsedIngredient,
    parse_ingredients_basic,
)

log = get_logger(__name__)

_LANG_NAMES: dict[str, str] = {
    'pl': 'Polish',
    'en': 'English',
    'de': 'German',
    'fr': 'French',
    'es': 'Spanish',
    'it': 'Italian',
}

_FALLBACK_CONVERSION_TABLE = """\
    1 cup:
      Flour (wheat) ≈ 125 g
      Sugar (granulated) ≈ 200 g
      Breadcrumbs ≈ 110 g
      Oats (rolled) ≈ 90 g
      Rice (raw) ≈ 185 g
      Water / Milk / Broth ≈ 250 ml
      Oil (cooking) ≈ 220 ml
    1 tablespoon:
      Flour / dry powder ≈ 10 g
      Sugar ≈ 13 g
      Liquid ≈ 15 ml
      Oil ≈ 14 ml
      Honey ≈ 21 g
      Butter ≈ 14 g
    1 teaspoon:
      Sugar ≈ 4 g
      Salt ≈ 6 g
      Dry spice ≈ 3 g
      Liquid ≈ 5 ml
    1 clove (garlic) ≈ 3 g
    1 pinch ≈ 1 g"""

_INGREDIENT_PROMPT = """\
Parse the following recipe ingredient lines into a JSON array.
Output language: {target_language}. Translate ingredient names from any source language into {target_language}.

For each ingredient line return an object with these fields:

- "name": descriptive display name in {target_language}, nominative form.
  Include useful qualifiers such as preparation style, fat content, or variety
  (e.g. "sweet ground paprika", "heavy cream 30%", "extra-virgin olive oil").
  Do NOT include quantity or unit here.

- "group_name": short canonical product name for inventory matching, 1-3 words,
  lowercase, nominative form in {target_language}.
  Keep it generic enough to match stock items
  (e.g. "beef", "onion", "bell pepper", "oil", "salt", "cream", "garlic").

- "quantity": the ORIGINAL numeric value from the recipe text, unchanged.
  Examples: "1 cup flour" → 1, "2 tbsp sugar" → 2, "200g butter" → 200.
  Default to 1 if no quantity is given.

- "unit_text": the ORIGINAL unit name from the recipe text, as-is, in the source
  language. Examples: "cup", "tablespoon", "teaspoon", "pinch", "g", "ml",
  "pcs", "pack". If no unit is given write null.

- "unit_display": the unit from "unit_text" translated into {target_language},
  using common short culinary forms (e.g. "tsp", "tbsp", "pinch", "cup",
  "clove", "pc", "slice", "pack"). If "unit_text" is null, return null.
  If the unit is already a standard metric/inventory unit (g, kg, ml, l,
  pcs, pack), return it unchanged.

- "metric_quantity": numeric decimal — the quantity converted to metric units
  for inventory stock matching. Use the CONVERSION TABLE below for known
  ingredient+unit combinations. For unlisted ingredients, estimate a
  reasonable metric equivalent.
  If the original unit is ALREADY metric (g, kg, ml, l) or countable (pcs, pack),
  set metric_quantity to the SAME value as quantity (no conversion needed).

CONVERSION TABLE (ingredient — 1 unit ≈ metric):
{conversion_table}

- "metric_unit": REQUIRED — one of [g, kg, ml, l, pcs, pack].
  Use "g" for solids/powders, "ml" for liquids, "pcs" for countable items.
  NEVER return null.

- "original": the exact original line text, unchanged.

SPLITTING RULE: If a single line contains multiple distinct ingredients separated
by ";" or "," (e.g. "marinade: 2 tbsp oil; 1 tsp salt; 2 cloves garlic"), output
each as a SEPARATE entry. Drop any group prefix ("marinade:", "sauce:", etc.).

ALTERNATIVE RULE: If a line describes alternatives with "or" / "lub" / "oder" / "ou"
(e.g. "1 red pepper OR ⅓ each of red, yellow and green pepper"), output ONLY ONE
entry for the first / most straightforward option. Set "is_optional" to false unless
the line explicitly says it can be omitted.

Ingredient lines:
{lines}

Return ONLY a valid JSON array. No explanation, no markdown fences."""

# Output shape for structured output. Mirrors the field names the prompt
# asks for and :func:`_parse_ingredients_payload` reads. Kept flat (no
# ``anyOf`` / ``additionalProperties``) so Google's OpenAPI subset accepts it.
_INGREDIENT_SCHEMA: dict[str, Any] = {
    'type': 'object',
    'properties': {
        'ingredients': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'name': {'type': 'string'},
                    'group_name': {'type': ['string', 'null']},
                    'quantity': {'type': 'number'},
                    'unit_text': {'type': ['string', 'null']},
                    'unit_display': {'type': ['string', 'null']},
                    'metric_quantity': {'type': 'number'},
                    'metric_unit': {'type': 'string'},
                    'original': {'type': 'string'},
                },
            },
        },
    },
    'required': ['ingredients'],
}


def _parse_ingredients_payload(parsed: Any) -> list[ParsedIngredient]:
    """Convert the LLM's JSON payload into ParsedIngredient rows.

    Pure function on the parsed JSON shape — no LLM / network involved.
    """
    if isinstance(parsed, dict):
        for key in ('ingredients', 'items', 'data'):
            if isinstance(parsed.get(key), list):
                parsed = parsed[key]
                break
        else:
            for v in parsed.values():
                if isinstance(v, list):
                    parsed = v
                    break

    if not isinstance(parsed, list):
        raise LlmContractError(f'Expected JSON array, got {type(parsed).__name__}')

    result: list[ParsedIngredient] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        metric_unit = item.get('metric_unit') or item.get('unit')
        unit_symbol = (
            metric_unit
            if isinstance(metric_unit, str) and metric_unit in _VALID_UNITS
            else None
        )
        try:
            metric_qty = Decimal(
                str(item.get('metric_quantity') or item.get('quantity') or 1)
            )
        except InvalidOperation:
            metric_qty = Decimal('1')
        try:
            orig_qty = Decimal(str(item.get('quantity') or 1))
        except InvalidOperation:
            orig_qty = Decimal('1')
        raw_unit_text = item.get('unit_text')
        orig_unit_text = str(raw_unit_text).strip() if raw_unit_text else None
        raw_unit_display = item.get('unit_display')
        unit_display = str(raw_unit_display).strip() if raw_unit_display else None
        if orig_qty == metric_qty and (
            orig_unit_text is None or orig_unit_text in _VALID_UNITS
        ):
            orig_qty_final = None
            orig_unit_text = None
            unit_display = None
        else:
            orig_qty_final = orig_qty

        name = str(item.get('name') or item.get('original') or '').strip()
        if not name:
            continue
        raw_group = item.get('group_name')
        group_name = str(raw_group).strip().lower() if raw_group else None
        original_text = str(item.get('original', '')).strip() or None
        result.append(
            ParsedIngredient(
                name=name,
                quantity=metric_qty,
                unit_symbol=unit_symbol,
                group_name=group_name,
                original_text=original_text,
                original_quantity=orig_qty_final,
                original_unit_text=orig_unit_text,
                unit_display=unit_display,
            )
        )

    return result


@dataclass
class IngredientParseOutcome:
    """Result of the LLM ingredient parse, including fallback diagnostics."""

    items: list[ParsedIngredient] = field(default_factory=list)
    used_fallback: bool = False
    fallback_reason: str | None = None


async def parse_ingredients_llm_with_status_async(
    db: AsyncSession,
    org_id: UUID,
    lines: list[str],
    usage_ctx: dict[str, Any] | None = None,
    conversion_table: str | None = None,
) -> IngredientParseOutcome:
    """Like :func:`parse_ingredients_llm_async` but reports whether the
    basic regex fallback was used, so callers can warn the user that the
    import preview is degraded (no translation, no original units)."""
    if not lines:
        return IngredientParseOutcome()

    from app.i18n.service import get_current_lang

    lang_code = str(get_current_lang())
    target_language = _LANG_NAMES.get(lang_code, 'English')
    log.info(
        'Ingredient parsing → target_language=%s (lang=%s)',
        target_language,
        lang_code,
    )
    ct = conversion_table or _FALLBACK_CONVERSION_TABLE
    prompt = _INGREDIENT_PROMPT.format(
        lines='\n'.join(lines),
        target_language=target_language,
        conversion_table=ct,
    )
    try:
        raw_content = await call_llm_async(
            db,
            org_id,
            prompt,
            usage_ctx=usage_ctx,
            action_type='recipe_import',
            json_schema=_INGREDIENT_SCHEMA,
        )
        parsed = extract_json(raw_content)
        result = _parse_ingredients_payload(parsed)
        if result:
            return IngredientParseOutcome(items=result)
        log.warning(
            'LLM ingredient parsing returned no ingredients, falling back to basic'
        )
        return IngredientParseOutcome(
            items=parse_ingredients_basic(lines),
            used_fallback=True,
            fallback_reason='empty_result',
        )
    except (
        httpx.HTTPError,
        json.JSONDecodeError,
        ValueError,
        KeyError,
        TypeError,
        InvalidOperation,
        RuntimeError,
    ) as exc:
        log.warning('LLM ingredient parsing failed, falling back to basic: %s', exc)
        return IngredientParseOutcome(
            items=parse_ingredients_basic(lines),
            used_fallback=True,
            fallback_reason=str(exc),
        )


async def parse_ingredients_llm_async(
    db: AsyncSession,
    org_id: UUID,
    lines: list[str],
    usage_ctx: dict[str, Any] | None = None,
    conversion_table: str | None = None,
) -> list[ParsedIngredient]:
    """Async, registry-backed ingredient parser.

    Resolves the LLM through :func:`app.core.llm.registry.get_client_for_purpose`
    with the ``recipes.text_parse`` purpose. On any failure (no binding,
    provider error, malformed JSON) falls back to
    :func:`parse_ingredients_basic`.

    Args:
        db: Async SQLAlchemy session.
        org_id: Organization that owns the bound AI connection.
        lines: Raw ingredient lines from the imported recipe.
        usage_ctx: Optional AI-usage tracking context (``user_id``,
            ``organization_id`` keys).
        conversion_table: Optional pre-rendered metric conversion table.
            If omitted, the built-in English conversion table is used.

    Returns:
        List of parsed ingredients. Empty input returns ``[]``.
    """
    outcome = await parse_ingredients_llm_with_status_async(
        db,
        org_id,
        lines,
        usage_ctx=usage_ctx,
        conversion_table=conversion_table,
    )
    return outcome.items
