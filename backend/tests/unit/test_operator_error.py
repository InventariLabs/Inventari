"""Refusals meant for the operator are ``OperatorError``, not reader-facing.

Boot, ``manage.py`` and manifest or seed-profile validation refuse in sentences
for a terminal. They stay ``ValueError`` for every caller that already catches
one, and say they are not for a reader, so the 400 handler never shows them.
"""

from typing import Any, cast

import pytest

from app.core.define_module import define_module
from app.core.exceptions import is_reader_facing_value_error
from app.core.module_migrations import run_module_migrations
from app.core.operator_error import OperatorError
from app.seed_data import _get_seeder


def test_an_operator_error_is_a_value_error_a_reader_never_sees() -> None:
    error = OperatorError('set DATABASE_URL')

    assert isinstance(error, ValueError)
    assert is_reader_facing_value_error(error) is False
    assert is_reader_facing_value_error(ValueError('a refusal')) is True


def test_an_unknown_seed_profile_names_the_ones_there_are() -> None:
    with pytest.raises(OperatorError, match='Unknown seed profile') as raised:
        _get_seeder('no_such_profile')

    assert 'clean_core' in str(raised.value)


def test_an_unknown_migration_action_is_refused_to_the_operator() -> None:
    with pytest.raises(OperatorError, match='Unknown action: sideways'):
        run_module_migrations(
            'maker',
            action=cast(Any, 'sideways'),
            db_url='postgresql://x@localhost/none',
        )


def test_a_module_without_a_router_is_refused_to_the_developer() -> None:
    with pytest.raises(OperatorError, match='router or router_factory'):
        define_module()
