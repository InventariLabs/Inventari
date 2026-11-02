"""Removal-strategy resolution.

Pure function: given a ProductTemplate-like object (anything with
``removal_strategy`` attribute) and an optional caller override,
return the strategy string ('FIFO' or 'FEFO').

Priority chain:
  1. ``override`` (caller-supplied; '' or None is treated as "no override")
  2. ``template.removal_strategy`` (if set and valid)
  3. 'FIFO' (default)

Future extension: category-level and
location-level fallback for org-wide policies like 'anything with an
expiry date uses FEFO'.
"""

from __future__ import annotations

from typing import Protocol

from app.core.exceptions import ContractViolationError

SUPPORTED_STRATEGIES: tuple[str, ...] = ('FIFO', 'FEFO')
DEFAULT_STRATEGY = 'FIFO'


class _TemplateLike(Protocol):
    removal_strategy: str | None


def resolve_removal_strategy(
    template: _TemplateLike | None,
    override: str | None = None,
) -> str:
    """Pick FIFO/FEFO for a (template, override) pair.

    Raises ``ContractViolationError`` (a caller's mistake, never shown to a reader) if the chosen value is not in
    :data:`SUPPORTED_STRATEGIES` — catches typos in caller code.
    """
    candidate = override if override else _read_template_strategy(template)
    if candidate not in SUPPORTED_STRATEGIES:
        raise ContractViolationError(
            f'Unknown removal strategy: {candidate!r}. '
            f'Supported: {", ".join(SUPPORTED_STRATEGIES)}'
        )
    return candidate


def _read_template_strategy(template: _TemplateLike | None) -> str:
    if template is None:
        return DEFAULT_STRATEGY
    value = getattr(template, 'removal_strategy', None)
    if not value:  # None or empty string
        return DEFAULT_STRATEGY
    return value
