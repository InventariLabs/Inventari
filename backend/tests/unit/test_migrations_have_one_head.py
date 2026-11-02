"""Every migration chain, the Core's and each module's, ends in exactly one head.

Two branches that each add a migration on top of the same parent merge
without a textual conflict, yet leave two heads behind, and then
``alembic upgrade head`` refuses to run on every instance. Nothing else
in the suite notices: the test database is built from the models, not
from the migrations.
"""

from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from app.core.module_migrations import (
    discover_modules_with_migrations,
    module_migrations_dir,
)

_ALEMBIC_INI = Path(__file__).resolve().parents[2] / 'alembic.ini'


def test_the_core_migrations_have_a_single_head():
    config = Config(str(_ALEMBIC_INI))
    config.set_main_option('script_location', str(_ALEMBIC_INI.parent / 'migrations'))

    heads = ScriptDirectory.from_config(config).get_heads()

    assert len(heads) == 1, f'the Core migrations fork into {sorted(heads)}'


@pytest.mark.parametrize('module_name', discover_modules_with_migrations())
def test_each_module_migration_chain_has_a_single_head(module_name):
    config = Config()
    config.set_main_option('script_location', str(module_migrations_dir(module_name)))

    heads = ScriptDirectory.from_config(config).get_heads()

    assert len(heads) == 1, f'the {module_name} migrations fork into {sorted(heads)}'
