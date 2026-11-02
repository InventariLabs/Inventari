"""LLM-assisted batch matching of parsed recipe ingredients to ProductTemplates.

Sends ONE LLM call per recipe with all ingredient group_names and the org's
product catalog, returning a mapping of ingredient-index -> template_id.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID

from app.core.llm.errors import LlmContractError, LlmPurposeUnboundError
from app.core.logging import get_logger
from app.core.public_api import core_api
from app.core.public_api.llm import extract_json

from ._llm_client import call_llm_async
from ._name_matching import match_key

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.contracts import ProductTemplateCandidateDTO

log = get_logger(__name__)

_MAX_TEMPLATES = 200

_MATCH_PROMPT = """\
You are a product matching assistant for a home inventory system.

Match each recipe ingredient to the most appropriate product from the inventory list.
Return a JSON object with a single "matches" key whose value is an array. Each array
entry is an object with two fields:
- "index": the 0-based integer index of the ingredient (from the list above)
- "template_id": the product ID (UUID string), or null if no suitable match exists

MATCHING RULES:
- Match by ingredient TYPE, not exact name. Declension and number don't matter.
- "onion" matches "White Onion 1kg" ✓
- "beef" matches "Minced Beef Class I 500g" ✓  
- "pickled cucumber" matches "Pickled Cucumbers Krakus 900g" ✓
- "red pepper" (fresh pepper) ≠ "Ground Sweet Paprika Kamis 20g" (spice) ✗
- "sweet paprika" (spice) matches "Ground Sweet Paprika Kamis 20g" ✓
- If the ingredient is a generic commodity (water, salt, oil) and multiple products match,
  pick the one that is most general or first in the list.
- If NO product fits, set "template_id" to null for that entry.

Recipe ingredients (index: group_name):
{ingredients_list}

Available inventory products (ID: name):
{products_list}

Return ONLY valid JSON, e.g.: {{"matches": [{{"index": 0, "template_id": "uuid-here"}}, {{"index": 1, "template_id": null}}]}}
No explanation."""

# Output shape for structured output, matching the list-of-entries contract
# described above. The open-keyed object shape is avoided because
# ``additionalProperties`` / ``patternProperties`` are outside Google's
# OpenAPI subset.
_MATCH_SCHEMA: dict[str, Any] = {
    'type': 'object',
    'properties': {
        'matches': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'index': {'type': 'integer'},
                    'template_id': {'type': ['string', 'null']},
                },
                'required': ['index', 'template_id'],
            },
        },
    },
    'required': ['matches'],
}


async def match_identical_names_async(
    db: AsyncSession, org_id: UUID, names: list[str]
) -> dict[str, ProductTemplateCandidateDTO]:
    """The products whose name *is* the ingredient's name, keyed by that name.

    "Rice" against a product called "Rice" is not a guess, and leaving it to
    the model — or to nobody, where no AI connection is set up — sent an
    import's four exact names to the review screen as "Not matched" and to
    the recipe as "Similar". Compared after folding case, diacritics and word
    order (:func:`match_key`), so "frozen peas" is "Frozen peas". A name two
    visible products share is ambiguous and stays unmatched: the reader picks.
    """
    wanted = [name for name in names if name and name.strip()]
    if not wanted:
        return {}
    candidates = await core_api.product_templates.search_fuzzy_many_async(
        db, org_id, wanted
    )
    found: dict[str, ProductTemplateCandidateDTO] = {}
    for name in wanted:
        key = match_key(name)
        same = {
            candidate.id: candidate
            for candidate in candidates.get(name.strip().lower(), [])
            if match_key(candidate.name) == key
        }
        if len(same) == 1:
            found[name] = next(iter(same.values()))
    return found


@dataclass
class TemplateMatchResult:
    """Result of template matching for a single ingredient."""

    ingredient_index: int
    template_id: UUID | None


async def match_templates(
    db: AsyncSession,
    org_id: UUID,
    group_names: list[str],
    usage_ctx: dict[str, Any] | None = None,
) -> list[TemplateMatchResult]:
    """Match *group_names* to ProductTemplate IDs using a single LLM call.

    Returns one :class:`TemplateMatchResult` per input name (same order).
    Any LLM failure results in all template_ids being None — import still succeeds
    through the ILIKE fuzzy fallback set in ``ingredient_group_name``. The one
    exception is :class:`LlmPurposeUnboundError`: an organization with no AI
    connection configured gets that refusal by name, not an empty match.

    Args:
        db: SQLAlchemy session (read-only usage).
        org_id: Organization to scope template lookup.
        group_names: List of short ingredient names from :class:`ParsedIngredient.group_name`.
        usage_ctx: Optional AI usage tracking context.

    Returns:
        List of TemplateMatchResult in the same order as *group_names*.
    """
    null_result = [TemplateMatchResult(i, None) for i in range(len(group_names))]

    if not group_names:
        return null_result

    templates = await core_api.product_templates.list_for_org_with_recipe_usage_async(
        db, org_id, limit=_MAX_TEMPLATES
    )
    if not templates:
        log.info('template_matcher: no templates found for org %s — skipping', org_id)
        return null_result

    template_pairs: list[tuple[UUID, str]] = [(t.id, t.name) for t in templates]
    ingredients_list = '\n'.join(f'{i}: {name}' for i, name in enumerate(group_names))
    products_list = '\n'.join(f'{tid}: {tname}' for tid, tname in template_pairs)

    prompt = _MATCH_PROMPT.format(
        ingredients_list=ingredients_list,
        products_list=products_list,
    )

    try:
        raw = await call_llm_async(
            db,
            org_id,
            prompt,
            usage_ctx=usage_ctx,
            action_type='recipe_import',
            json_schema=_MATCH_SCHEMA,
        )
        data: Any = extract_json(raw)

        entries: list[Any] = []
        if isinstance(data, dict):
            matches = data.get('matches')
            if isinstance(matches, list):
                entries = matches
        elif isinstance(data, list):
            # Prompt-only clients may drop the wrapper and answer with a bare
            # list; tolerate it so graceful degradation still matches.
            entries = data
        else:
            raise LlmContractError(f'Expected JSON object, got {type(data).__name__}')

        valid_ids: set[str] = {str(tid) for tid, _ in template_pairs}

        by_index: dict[int, UUID | None] = {}
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            raw_index = entry.get('index')
            if type(raw_index) is not int or not 0 <= raw_index < len(group_names):
                continue
            raw_val = entry.get('template_id')
            tid: UUID | None = None
            if raw_val and isinstance(raw_val, str):
                raw_val = raw_val.strip()
                if raw_val in valid_ids:
                    try:
                        tid = uuid.UUID(raw_val)
                    except ValueError:
                        log.warning(
                            'template_matcher: invalid UUID from LLM: %r', raw_val
                        )
            by_index[raw_index] = tid

        results = [
            TemplateMatchResult(ingredient_index=i, template_id=by_index.get(i))
            for i in range(len(group_names))
        ]

        matched = sum(1 for r in results if r.template_id is not None)
        log.info(
            'template_matcher: matched %d/%d ingredients for org %s',
            matched,
            len(group_names),
            org_id,
        )
        return results

    except LlmPurposeUnboundError:
        # A configuration gap, not a matching failure: "nothing bound for
        # recipes.text_parse" must not read as "the model found no product".
        # It travels on to the 503 the exception mapper has for it — the
        # callers that have already parsed (import) never reach this line
        # unbound, and the mass-matching screen needs to say "set it up".
        raise
    except (
        json.JSONDecodeError,
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        RuntimeError,
    ) as exc:
        log.warning(
            'template_matcher: LLM matching failed, falling back to ILIKE: %s', exc
        )
        return null_result
