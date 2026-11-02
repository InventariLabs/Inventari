"""Match a recipe ingredient onto the product names in the catalogue.

The catalogue says "Ciecierzyca w puszce", the recipe says "Ciecierzyca
z puszki" — the same goods, a different preposition and a different
inflection. A substring search finds nothing, so the ingredient looks
unmatched even though seven cans sit on the shelf. This module compares
token *stems* instead, which absorbs the inflection, and treats whatever
follows the first preposition in a catalogue name as a qualifier rather
than as the goods themselves, which is what keeps "Olej" away from
"Tunczyk w oleju".

The rules are linguistic and therefore stay here. ``app/services`` serves
every vertical in every language and must not grow a list of Polish
prepositions (AGENTS.md, Core Neutrality); it narrows candidates by a
language-neutral fragment and leaves the verdict to this module.

Nothing here is persisted. The key is derived from the ingredient row on
every read, so a product added to the catalogue today is visible to a
recipe written last year without anyone re-saving it.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from anyascii import anyascii

DEFAULT_CATALOG_LANGUAGE = 'pl'
"""Language the product catalogue is assumed to be written in.

Deciding where this really comes from — an organization setting or the
request language — is a separate question; today the only filled-in entry
in :data:`_QUALIFIER_PREPOSITIONS` is Polish.
"""

MIN_STEM_LENGTH = 4
"""Leading characters two different tokens must share to count as one word.

Four is the shortest prefix that separates "puszki"/"puszce" (accept) from
"wloszczyzna"/"wloskie" (reject) on the catalogue this was measured on.
"""

_STEM_SLACK = 2
"""How much of the shorter token may differ — one inflected ending."""

_MIN_TOKEN_LENGTH = 3
"""Below this a token carries no goods identity: units, prepositions, sizes."""

_QUALIFIER_PREPOSITIONS: dict[str, frozenset[str]] = {
    'pl': frozenset({'w', 'we', 'z', 'ze', 'na', 'do', 'bez', 'od', 'po'}),
}
"""Words after which a catalogue name stops naming the goods.

Adding a language must stay the addition of one entry here, never a rewrite
of the matcher. A language with no entry simply loses the qualifier rule and
the matcher gets more eager — which is why an unlisted language is a gap
worth filling rather than a silent default.
"""

_NOISE_TOKENS = frozenset({'szt', 'opak', 'kpl', 'typ', 'dag'})
"""Packaging and grading filler that survives the length cut but means nothing."""

_NON_LETTER = re.compile(r'[^a-z]+')


class NamedTemplate(Protocol):
    """Anything carrying a template id and a name — DTO or ORM row alike.

    Read-only on purpose: matching never writes, and declaring the members
    as settable attributes would exclude frozen carriers for no reason.
    """

    @property
    def id(self) -> UUID: ...

    @property
    def name(self) -> str: ...


@dataclass(frozen=True)
class IngredientMatch:
    """One catalogue product a given ingredient can be served from."""

    template_id: UUID
    template_name: str
    head_match: bool
    """True when the ingredient names what the product *is*, rather than one
    of its attributes — "Ciecierzyca" against "Ciecierzyca w puszce" rather
    than "Spaghetti" against "Makaron spaghetti 500g"."""


def _tokenize(text: str) -> list[str]:
    """Fold to ASCII, lowercase and split into letter-only tokens.

    Digits vanish with the punctuation, so "Smietana 18%" and "Pomidory
    pelati 400g" reduce to the words that name the goods.
    """
    return [token for token in _NON_LETTER.split(anyascii(text).lower()) if token]


def _content_tokens(tokens: list[str]) -> list[str]:
    return [
        token
        for token in tokens
        if len(token) >= _MIN_TOKEN_LENGTH and token not in _NOISE_TOKENS
    ]


def _goods_tokens(tokens: list[str], language: str) -> list[str]:
    """Return the leading tokens that name the goods, dropping the qualifier."""
    prepositions = _QUALIFIER_PREPOSITIONS.get(language, frozenset())
    for index, token in enumerate(tokens):
        if token in prepositions:
            return tokens[:index]
    return tokens


def _common_prefix_length(left: str, right: str) -> int:
    length = 0
    for left_char, right_char in zip(left, right, strict=False):
        if left_char != right_char:
            break
        length += 1
    return length


def _stems_match(left: str, right: str) -> bool:
    """True when two tokens are the same word under a different ending."""
    if left == right:
        return True
    common = _common_prefix_length(left, right)
    if common < MIN_STEM_LENGTH:
        return False
    return common >= min(len(left), len(right)) - _STEM_SLACK


def head_token(name: str) -> str | None:
    """Return the token naming the goods, or None when *name* names nothing.

    A name made only of digits, units and prepositions has no head — that is
    the honest meaning of an unknown ingredient.
    """
    tokens = _content_tokens(_tokenize(name))
    return tokens[0] if tokens else None


class KeyedIngredient(Protocol):
    """The ingredient fields a lookup key can be derived from."""

    @property
    def ingredient_group_name(self) -> str | None: ...

    @property
    def name(self) -> str: ...


def matching_key(ingredient: KeyedIngredient) -> str | None:
    """Return the name to look this ingredient's goods up by.

    ``ingredient_group_name`` when something set it — the URL import does,
    deliberately, and an explicit key has to win. Otherwise the ingredient's
    own name, which sits in the same row and which nothing was reading: an
    ingredient typed by hand carries neither a template nor a group name,
    and that is the ordinary case rather than the exception.

    ``None`` only when the text identifies nothing at all — empty, digits,
    bare prepositions. That, and nothing else, is an unknown ingredient;
    having no stock is a different answer and belongs to a different status.
    """
    for candidate in (ingredient.ingredient_group_name, ingredient.name):
        if candidate and head_token(candidate):
            return candidate
    return None


def narrowing_fragment(name: str) -> str | None:
    """Return the fragment every catalogue match for *name* must contain.

    :func:`_stems_match` accepts two tokens only when they share
    :data:`MIN_STEM_LENGTH` leading characters (or are equal, which for a
    shorter token means the same thing), so this prefix is the weakest
    necessary condition — narrowing the SQL query by it can never drop a
    candidate the rules below would have accepted.
    """
    head = head_token(name)
    if head is None:
        return None
    return head[:MIN_STEM_LENGTH]


def _grade_candidate(
    head: str,
    qualifiers: list[str],
    template_name: str,
    language: str,
) -> tuple[bool, int] | None:
    """Return (head_match, token count) for a candidate, or None to reject it."""
    tokens = _tokenize(template_name)
    goods = _content_tokens(_goods_tokens(tokens, language))
    if not goods:
        return None

    if _stems_match(head, goods[0]):
        head_match = True
    elif any(_stems_match(head, token) for token in goods[1:]):
        head_match = False
    else:
        return None

    all_tokens = _content_tokens(tokens)
    for qualifier in qualifiers:
        if not any(_stems_match(qualifier, token) for token in all_tokens):
            return None
    return head_match, len(all_tokens)


def match_templates(
    ingredient_name: str,
    templates: Iterable[NamedTemplate],
    language: str = DEFAULT_CATALOG_LANGUAGE,
) -> list[IngredientMatch]:
    """Return the catalogue products *ingredient_name* can be served from.

    Best first: products the ingredient names outright come before products
    that merely mention it, then the least-qualified name wins — "Pomidory
    cherry" before "Pomidory pelati 400g". Once any outright match exists
    the mentions are dropped entirely, so "Spaghetti" only falls back to
    "Makaron spaghetti 500g" when nothing is actually called spaghetti.
    """
    tokens = _content_tokens(_tokenize(ingredient_name))
    if not tokens:
        return []
    head, qualifiers = tokens[0], tokens[1:]

    graded: list[tuple[bool, int, str, IngredientMatch]] = []
    for template in templates:
        grade = _grade_candidate(head, qualifiers, template.name or '', language)
        if grade is None:
            continue
        head_match, token_count = grade
        folded = anyascii(template.name or '').lower()
        graded.append(
            (
                head_match,
                token_count,
                folded,
                IngredientMatch(
                    template_id=template.id,
                    template_name=template.name,
                    head_match=head_match,
                ),
            )
        )

    if any(head_match for head_match, _, _, _ in graded):
        graded = [entry for entry in graded if entry[0]]

    graded.sort(key=lambda entry: (not entry[0], entry[1], entry[2]))
    return [match for _, _, _, match in graded]
