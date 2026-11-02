"""A module made by ``make new-module`` is accepted by the gate its author commits through.

The generator copies the reference module, so a pattern the lint only
tolerates there because a baseline line names it — a bare-list route, an
import from outside the module SDK — reaches the copy under a new name the
baseline does not hold. The pre-commit hook runs ``manage.py arch lint``, and
it refused the author's very first commit before a line of their own existed.

The lint reads the tree it lives in, so the ``lint_of_a_scaffolded_copy``
fixture copies ``app/``, generates a module into the copy and
runs the copy's lint there, in a process of its own. Findings about the copy
itself (no ``tests/`` or ``scripts/`` beside it, the baseline entries of the
modules it left out) are not this test's business; a finding that names the
new module is.
"""

from __future__ import annotations

import pytest

from ._scaffolded_lint_copy import SCAFFOLDED_MODULE, LintRun

pytestmark = pytest.mark.unit


def test_the_lint_finds_nothing_in_the_new_module(
    lint_of_a_scaffolded_copy: LintRun,
) -> None:
    about_the_module = [
        line for line in lint_of_a_scaffolded_copy.errors if SCAFFOLDED_MODULE in line
    ]
    assert about_the_module == []
