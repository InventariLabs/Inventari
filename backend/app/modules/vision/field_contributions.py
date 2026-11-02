"""What other modules want read off the same photograph.

Vision knows how to look at a label. It does not know that anyone cares about
grams of salt — the nutrition module does, and says so here. The alternative
was the shape this file replaces: one schema carrying both ``expiry_date`` and
``energy_kcal``, so every reading of an equipment nameplate came back with six
empty nutrition fields and a prompt paragraph explaining when to leave them
empty.

A contribution is only folded in when its module is enabled *and* the scan's
intent matches — the ``context_tag`` the label was printed with. A sticker
printed for assets never sends a nutrition table question to the model, which
is the difference between a prompt that is merely tolerant of other verticals
and one that does not mention them.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel

__all__ = [
    'LabelFieldContribution',
    'clear_label_fields',
    'register_label_fields',
    'registered_label_fields',
]

# The intent of an untagged label — the plain product context. Spelled out
# because a bare '' in a set of tags reads like an oversight.
PRODUCT_CONTEXT = ''


@dataclass(frozen=True)
class LabelFieldContribution:
    """One module's addition to the label-extraction request."""

    module: str
    """Owning module. Gates the contribution, and names its key in ``extra``."""

    schema: type[BaseModel]
    """The fields to read. Descriptions on them become the prompt."""

    instructions: str
    """A sentence added to the request saying when these fields apply."""

    context_tags: frozenset[str] | None = field(default=None)
    """Intents this applies to; ``None`` means every intent."""

    def applies_to(self, context_tag: str | None) -> bool:
        if self.context_tags is None:
            return True
        return (context_tag or PRODUCT_CONTEXT) in self.context_tags


_contributions: dict[str, LabelFieldContribution] = {}


def register_label_fields(contribution: LabelFieldContribution) -> None:
    """Register (or replace) a module's contribution. Idempotent per module."""
    _contributions[contribution.module] = contribution


def registered_label_fields() -> list[LabelFieldContribution]:
    """Every registered contribution, in registration order."""
    return list(_contributions.values())


def clear_label_fields() -> None:
    """Drop all registrations — for tests that install their own."""
    _contributions.clear()
