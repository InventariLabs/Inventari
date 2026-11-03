"""Search and read-with-relations helpers for ProductTemplate.

Extracted from ``product_template_service.py`` — search operations and the
``get_with_uom`` helper that eager-loads a related UoM record. These are
kept separate from the basic read/write operations because they are
distinct user-facing concerns:

- Reads: list / get / exists / lookup-by-barcode (catalog browsing).
- Writes: create / update / delete / clone / create-stub (CRUD).
- Searches (here): ranked + fuzzy + batch-fuzzy + get-with-uom (LLM and
  import-pipeline helpers, called by the recipes module).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from anyascii import anyascii
from sqlalchemy import case, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.contracts import ProductTemplateCandidateDTO
from app.core.db_utils import escape_ilike, typed_fragment_pattern
from app.models.product_template import ProductTemplate
from app.models.uom import Uom

_MIN_FALLBACK_WORD_LENGTH = 3
"""Below this a word is a preposition or a unit abbreviation; requiring it
only ever removes real matches."""

_FALLBACK_STEM_LENGTH = 4
"""Words are compared by their opening characters so an inflected ending
does not break the match — "puszki" still finds "puszce". Short enough to
survive most endings, long enough not to collapse unrelated words."""


async def search_ranked_async(
    db: AsyncSession,
    org_id: UUID,
    query: str,
    limit: int = 10,
) -> list[ProductTemplate]:
    """Search templates with priority ranking: exact barcode > exact SKU > ILIKE name.

    Returns results ordered by relevance rather than creation date. A
    fragment shorter than ``db_utils.SUBSTRING_MIN_LENGTH`` matches the start of the
    SKU and the name; a longer one matches anywhere in them.
    """
    q = query.strip()
    if not q:
        return []

    pattern = typed_fragment_pattern(q)
    rank = case(
        (ProductTemplate.barcode == q, 0),
        (ProductTemplate.sku.ilike(pattern), 1),
        (ProductTemplate.name.ilike(pattern), 2),
        else_=3,
    )

    result = await db.scalars(
        select(ProductTemplate)
        .where(
            ProductTemplate.organization_id == org_id,
            or_(
                ProductTemplate.barcode == q,
                ProductTemplate.sku.ilike(pattern),
                ProductTemplate.name.ilike(pattern),
            ),
        )
        .order_by(rank, ProductTemplate.name)
        .limit(limit)
    )
    return list(result.all())


async def search_fuzzy_async(
    db: AsyncSession,
    org_id: UUID,
    query: str,
    limit: int = 10,
) -> list[ProductTemplate]:
    """Fuzzy ILIKE search across org + global templates, name-only.

    Tier 2 CoreAPI extension for ingredient-to-template matching in
    recipes import. Distinct from ``search_ranked_async`` (which scores
    barcode/SKU/name priority) — this method treats name-match as the
    sole criterion and includes global (org_id IS NULL) templates.

    A phrase that matches nothing as one substring is retried word by word,
    requiring every word to appear somewhere in the name. That is what lets
    typing "Ciecierzyca z puszki" into an ingredient field offer
    "Ciecierzyca w puszce": the preposition and the ending differ, so the
    whole phrase is a substring of nothing.

    The fallback stays deliberately language-neutral — split on whitespace,
    compare each word by its opening characters, require them all. Knowing
    that a word *after* a preposition qualifies the goods rather than names
    them is Polish grammar, and grammar belongs to the module that owns the
    domain, not to a core serving every vertical in every language.

    Args:
        org_id: Calling organization scope.
        query: Free-text name fragment.
        limit: Safety cap (default 10).

    Returns:
        Templates whose name matches the query, scoped to org or global,
        ordered alphabetically by name. Substring hits are returned in
        exactly the order they always were; the word-wise pass runs only
        when there are none.
    """
    q = query.strip()
    if not q:
        return []

    visible = or_(
        ProductTemplate.organization_id == org_id,
        ProductTemplate.organization_id.is_(None),
    )

    async def _matching(*conditions: Any) -> list[ProductTemplate]:
        result = await db.scalars(
            select(ProductTemplate)
            .where(*conditions, visible)
            .order_by(ProductTemplate.name)
            .limit(limit)
        )
        return list(result.all())

    found = await _matching(ProductTemplate.name.ilike(f'%{escape_ilike(q)}%'))
    if found:
        return found

    words = [word for word in q.split() if len(word) >= _MIN_FALLBACK_WORD_LENGTH]
    if not words:
        return []
    return await _matching(*[_word_condition(word) for word in words])


def _word_condition(word: str) -> Any:
    """Match one word by its opening characters, either spelling of them."""
    stem = word[:_FALLBACK_STEM_LENGTH]
    spellings = {stem.lower(), anyascii(stem).lower()}
    return or_(*[ProductTemplate.name.ilike(f'%{escape_ilike(s)}%') for s in spellings])


def _build_accent_variants() -> dict[str, str]:
    """Each plain Latin letter, with the accented letters that fold to it.

    The database cannot compare "ryz" with "Ryż" by itself (``ilike`` is
    case-insensitive, not accent-insensitive) and the ``unaccent`` extension
    is not part of every deployment. The classes are built from the same
    ``anyascii`` the caller folds with, so no language is hard-coded; only
    the single-letter folds are listed, the rest is the raw spelling's job.
    """
    variants: dict[str, set[str]] = {}
    for code_point in range(0xC0, 0x250):
        letter = chr(code_point).lower()
        plain = anyascii(letter)
        if len(letter) == 1 and letter != plain and len(plain) == 1 and plain.isalpha():
            # Both cases are listed: a database in the "C" locale folds the
            # case of ASCII letters only.
            variants.setdefault(plain, set()).update({letter, letter.upper()})
    return {plain: ''.join(sorted(letters)) for plain, letters in variants.items()}


_ACCENT_VARIANTS = _build_accent_variants()


def _accent_tolerant_regex(folded: str) -> str | None:
    """A regex matching *folded* in a name that kept its accents.

    ``None`` when no letter of *folded* has an accented spelling: the raw
    pattern already finds it.
    """
    parts = []
    tolerant = False
    for char in folded:
        letters = _ACCENT_VARIANTS.get(char)
        if letters:
            tolerant = True
            parts.append(f'[{char}{letters}]')
        else:
            parts.append(char if char.isalnum() else f'\\{char}')
    return ''.join(parts) if tolerant else None


def _names_containing(fragments: list[str]) -> Any:
    """``name`` contains one of *fragments* in its own spelling, or folded.

    The raw pattern per fragment covers every script and the multi-letter
    folds ("ß" for "ss"). The accent-tolerant regex covers a fragment the
    caller already folded ("ryz") against a name that kept its letters
    ("Ryż 1 kg"); all of them go into ONE regex, because PostgreSQL keeps 32
    compiled regexes per session and a query naming more recompiles on every
    row (a recipes page names about sixty fragments).

    Both read the name as stored. The raw patterns alone stay on the trigram
    index; the regex does not, so the query scans the catalogue whenever a
    fragment has an accented spelling.
    """
    conditions = [
        ProductTemplate.name.ilike(f'%{escape_ilike(fragment)}%')
        for fragment in fragments
    ]
    folded = {anyascii(fragment).lower() for fragment in fragments}
    regexes = sorted(
        {regex for fragment in folded if (regex := _accent_tolerant_regex(fragment))}
    )
    if regexes:
        conditions.append(ProductTemplate.name.op('~*')('|'.join(regexes)))
    return or_(*conditions)


async def search_fuzzy_many_async(
    db: AsyncSession,
    org_id: UUID,
    queries: list[str],
) -> dict[str, list[ProductTemplateCandidateDTO]]:
    """Batch name-fragment search: each fragment → the templates containing it.

    Tier 2 CoreAPI extension used by recipes availability checks. Runs one
    SQL query with ``OR``-combined ILIKE patterns instead of N round-trips.

    This returns *candidates*, not a verdict. Deciding which of them is
    actually the ingredient the caller asked about needs to know what an
    ingredient is, and that knowledge is domain- and language-specific
    (AGENTS.md, Core Neutrality) — so it stays with the caller, and the
    names travel back alongside the ids to make that possible.

    Matching is diacritic-insensitive: both the fragment and the template
    name are folded to ASCII for the verdict, so a catalogue stored as
    "Maslo" answers a query spelled "Masło" and the other way round. The
    database narrows by the fragment as given (any script, "ß", "œ") and by
    its ASCII fold against the accented Latin letters of a name ("ryz" finds
    "Ryż"); a name whose letters fold to several ("Weißbrot" for "weissbrot")
    is reached by the fragment spelled with them, not by the folded one.

    Args:
        org_id: Calling organization scope.
        queries: Name fragments — one per thing being looked up.

    Returns:
        Dict mapping the original (lowered, stripped) fragment → the
        candidates whose name contains it. Fragments with no candidate
        map to ``[]``.
    """
    cleaned = [q.strip().lower() for q in queries if q and q.strip()]
    if not cleaned:
        return {}

    # A fragment and a name can disagree on diacritics in either direction,
    # so narrow tolerantly and settle the exact verdict in Python below,
    # where the same fold is available on both sides.
    result = await db.execute(
        select(ProductTemplate.id, ProductTemplate.name).where(
            _names_containing(cleaned),
            or_(
                ProductTemplate.organization_id == org_id,
                ProductTemplate.organization_id.is_(None),
            ),
        )
    )
    rows = result.all()

    folded_queries = [(q, anyascii(q).lower()) for q in cleaned]
    matched: dict[str, list[ProductTemplateCandidateDTO]] = {q: [] for q in cleaned}
    for template_id, template_name in rows:
        if template_name is None:
            continue
        folded_name = anyascii(template_name).lower()
        for query, folded_query in folded_queries:
            if folded_query in folded_name:
                matched[query].append(
                    ProductTemplateCandidateDTO(id=template_id, name=template_name)
                )

    return matched


async def get_with_uom_async(
    db: AsyncSession,
    org_id: UUID,
    template_id: UUID,
) -> ProductTemplate | None:
    """Return a template with ``weight_uom`` eagerly loaded.

    Tier 2 CoreAPI extension for recipes nutrition/cost reads that need
    the weight UOM symbol without an additional query.
    """
    result = await db.scalars(
        select(ProductTemplate)
        .options(selectinload(ProductTemplate.weight_uom))
        .where(
            ProductTemplate.id == template_id,
            or_(
                ProductTemplate.organization_id == org_id,
                ProductTemplate.organization_id.is_(None),
            ),
        )
    )
    template = result.first()
    if template is None:
        return None
    if template.weight_uom_id is not None and template.weight_uom is None:
        weight_uom = await db.get(Uom, template.weight_uom_id)
        template.weight_uom = weight_uom
    return template
