"""Tests for the removal-strategy resolver.

The resolver picks FIFO vs FEFO for a given (template, lot) pair using
the priority chain:
  - explicit override (caller-supplied)
  - ProductTemplate.removal_strategy
  - default 'FIFO'

The chain is intentionally simple at this stage.  Future work may
extend it to Category and StorageLocation for org-wide policies like
'dairy uses FEFO globally'.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.core.exceptions import ContractViolationError
from app.services.stock_strategy import resolve_removal_strategy


def _make_template(removal_strategy: str | None) -> object:
    """Build a tiny stub with just the attribute the resolver reads."""

    class _Stub:
        pass

    s = _Stub()
    s.id = uuid4()
    s.removal_strategy = removal_strategy
    return s


class TestResolveRemovalStrategy:
    """Pure function: takes a template-like object + optional override."""

    def test_explicit_override_wins(self):
        template = _make_template('FEFO')
        # Caller passes 'FIFO' explicitly — that wins.
        assert resolve_removal_strategy(template, override='FIFO') == 'FIFO'

    def test_template_strategy_used_when_no_override(self):
        template = _make_template('FEFO')
        assert resolve_removal_strategy(template) == 'FEFO'

    def test_default_fifo_when_template_has_none(self):
        template = _make_template(None)
        assert resolve_removal_strategy(template) == 'FIFO'

    def test_default_fifo_when_template_attribute_missing(self):
        class _Bare:
            pass

        bare = _Bare()
        # No removal_strategy attribute at all — defaults to 'FIFO'.
        assert resolve_removal_strategy(bare) == 'FIFO'

    def test_empty_string_template_treated_as_unset(self):
        """An empty string is not a valid strategy; fall back to default."""
        template = _make_template('')
        assert resolve_removal_strategy(template) == 'FIFO'

    def test_override_with_empty_string_falls_back_to_template(self):
        template = _make_template('FEFO')
        # Override of '' is treated as "no override" → use template.
        assert resolve_removal_strategy(template, override='') == 'FEFO'

    @pytest.mark.parametrize('strategy', ['FIFO', 'FEFO'])
    def test_supported_strategies_pass_through(self, strategy):
        template = _make_template(strategy)
        assert resolve_removal_strategy(template) == strategy

    def test_unknown_strategy_raises(self):
        template = _make_template('LIFO')
        # A caller's mistake, not a refusal: a ValueError would reach a reader
        # as a 400 with this English sentence.
        with pytest.raises(ContractViolationError, match='Unknown removal strategy'):
            resolve_removal_strategy(template)
